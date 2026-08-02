from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.agent.product_approval import (
    AUTO_EQUIVALENCE_SET_NAME,
    auto_configure_owner_supplies_background,
    auto_configure_supply_background,
    catalog_pack,
    significant_terms,
)
from app.auth import get_current_user
from app.database import get_db_session
from app.integrations.ucp import UcpAdapter, UcpConfigurationError, UcpMerchantError
from app.inventory import rebase_inventory, record_stock_count
from app.models import (
    ApprovedVariant,
    Beneficiary,
    LedgerEvent,
    MerchantAuthorization,
    ProductEquivalenceSet,
    StockMovement,
    Supply,
    User,
)
from app.schemas import (
    ApprovedVariantCreate,
    ApprovedVariantOut,
    BeneficiaryCreate,
    BeneficiaryDashboard,
    BeneficiaryOut,
    BeneficiaryUpdate,
    EquivalenceSetCreate,
    EquivalenceSetOut,
    MerchantAuthorizationCreate,
    MerchantAuthorizationOut,
    MerchantAuthorizationUpdate,
    ProductSuggestionOut,
    SetupDashboard,
    StockCountRequest,
    StockMovementOut,
    SupplyCreate,
    SupplyDashboard,
    SupplyOut,
    SupplyUpdate,
)

router = APIRouter(prefix="/setup", tags=["care setup"])

MERCHANTS: dict[str, tuple[str, str, str]] = {
    "himalaya": ("Himalaya Wellness", "himalayawellness.in", "https://himalayawellness.in"),
    "oziva": ("Oziva", "oziva.in", "https://www.oziva.in"),
    "zandu": ("Zandu Care", "zanducare.com", "https://zanducare.com"),
}


def owned_beneficiary(db: Session, owner_id: UUID, beneficiary_id: UUID) -> Beneficiary:
    beneficiary = db.scalar(
        select(Beneficiary).where(
            Beneficiary.id == beneficiary_id, Beneficiary.owner_id == owner_id
        )
    )
    if beneficiary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beneficiary not found")
    return beneficiary


def owned_supply(
    db: Session, owner_id: UUID, supply_id: UUID, *, for_update: bool = False
) -> Supply:
    statement = (
        select(Supply)
        .join(Supply.beneficiary)
        .where(
            Supply.id == supply_id,
            Beneficiary.owner_id == owner_id,
            Supply.deleted_at.is_(None),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    supply = db.scalar(statement)
    if supply is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supply not found")
    return supply


def owned_equivalence_set(
    db: Session, owner_id: UUID, equivalence_set_id: UUID
) -> ProductEquivalenceSet:
    equivalence_set = db.scalar(
        select(ProductEquivalenceSet)
        .join(ProductEquivalenceSet.supply)
        .join(Supply.beneficiary)
        .where(
            ProductEquivalenceSet.id == equivalence_set_id,
            Beneficiary.owner_id == owner_id,
            Supply.deleted_at.is_(None),
        )
    )
    if equivalence_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Equivalence set not found"
        )
    return equivalence_set


def owned_merchant_authorization(
    db: Session, owner_id: UUID, merchant_authorization_id: UUID
) -> MerchantAuthorization:
    authorization = db.scalar(
        select(MerchantAuthorization).where(
            MerchantAuthorization.id == merchant_authorization_id,
            MerchantAuthorization.owner_id == owner_id,
        )
    )
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Merchant authorization not found"
        )
    return authorization


def supply_has_eligible_variant(db: Session, owner_id: UUID, supply_id: UUID) -> bool:
    variant_id = db.scalar(
        select(ApprovedVariant.id)
        .join(ApprovedVariant.equivalence_set)
        .join(ProductEquivalenceSet.supply)
        .join(
            MerchantAuthorization,
            ApprovedVariant.merchant_authorization_id == MerchantAuthorization.id,
        )
        .where(
            Supply.id == supply_id,
            MerchantAuthorization.owner_id == owner_id,
            MerchantAuthorization.is_enabled.is_(True),
        )
        .limit(1)
    )
    return variant_id is not None


def suggestion_matches(*, query: str, catalog_evidence: str, merchant_label: str) -> bool:
    """Allow useful type-ahead prefixes without weakening final product approval rules."""
    required_terms = significant_terms(query) - significant_terms(merchant_label)
    evidence_terms = significant_terms(catalog_evidence)
    return bool(required_terms) and all(
        any(
            evidence == required
            or (len(required) >= 3 and evidence.startswith(required))
            for evidence in evidence_terms
        )
        for required in required_terms
    )


@router.get("/product-suggestions", response_model=list[ProductSuggestionOut])
def product_suggestions(
    query: str = Query(min_length=3, max_length=160),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> list[ProductSuggestionOut]:
    """Search the user's enabled merchant catalogs for human-readable type-ahead results."""
    authorizations = list(
        db.execute(
            select(
                MerchantAuthorization.merchant_key,
                MerchantAuthorization.merchant_name,
                MerchantAuthorization.preference_rank,
            )
            .where(
                MerchantAuthorization.owner_id == user.id,
                MerchantAuthorization.is_enabled.is_(True),
            )
            .order_by(MerchantAuthorization.preference_rank)
        ).all()
    )
    if not authorizations:
        return []

    adapter = UcpAdapter()

    def search_merchant(
        merchant_key: str, merchant_name: str, preference_rank: int
    ) -> list[tuple[int, ProductSuggestionOut]]:
        variants = adapter.search(merchant_key=merchant_key, query=query.strip())
        matches: list[tuple[int, ProductSuggestionOut]] = []
        merchant_label = f"{merchant_key} {merchant_name}"
        for variant in variants:
            if not variant.available or not suggestion_matches(
                query=query,
                catalog_evidence=variant.catalog_evidence,
                merchant_label=merchant_label,
            ):
                continue
            pack = catalog_pack(variant.catalog_evidence)
            if pack is None:
                continue
            matches.append(
                (
                    preference_rank,
                    ProductSuggestionOut(
                        merchant_key=merchant_key,
                        merchant_name=merchant_name,
                        product_id=variant.product_id,
                        variant_id=variant.variant_id,
                        product_title=variant.product_title,
                        variant_title=variant.variant_title,
                        pack_quantity=pack[0],
                        pack_unit=pack[1],
                        available=variant.available,
                        unit_price=variant.unit_price,
                        currency=variant.currency,
                    ),
                )
            )
        return matches

    ranked: list[tuple[int, ProductSuggestionOut]] = []
    with ThreadPoolExecutor(max_workers=min(3, len(authorizations))) as executor:
        futures = [executor.submit(search_merchant, *authorization) for authorization in authorizations]
        for future in as_completed(futures):
            try:
                ranked.extend(future.result())
            except (UcpConfigurationError, UcpMerchantError):
                continue

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].unit_price / item[1].pack_quantity,
            item[1].unit_price,
            item[1].product_title.casefold(),
            item[1].variant_id,
        )
    )
    seen: set[tuple[str, str, str]] = set()
    suggestions: list[ProductSuggestionOut] = []
    for _, suggestion in ranked:
        identity = (suggestion.merchant_key, suggestion.product_id, suggestion.variant_id)
        if identity in seen:
            continue
        seen.add(identity)
        suggestions.append(suggestion)
        if len(suggestions) == 8:
            break
    return suggestions


@router.get("/dashboard", response_model=SetupDashboard)
def dashboard(
    user: User = Depends(get_current_user), db: Session = Depends(get_db_session)
) -> SetupDashboard:
    beneficiaries = list(
        db.scalars(
            select(Beneficiary)
            .where(Beneficiary.owner_id == user.id)
            .options(
                selectinload(Beneficiary.supplies)
                .selectinload(Supply.equivalence_sets)
                .selectinload(ProductEquivalenceSet.approved_variants),
                selectinload(Beneficiary.supplies).selectinload(Supply.stock_movements),
            )
            .order_by(Beneficiary.created_at)
        )
    )
    authorizations = list(
        db.scalars(
            select(MerchantAuthorization)
            .where(MerchantAuthorization.owner_id == user.id)
            .order_by(MerchantAuthorization.preference_rank, MerchantAuthorization.merchant_name)
        )
    )
    return SetupDashboard(
        beneficiaries=[
            # Derived from the ORM row rather than field-by-field, so adding a beneficiary column
            # cannot silently leave this endpoint constructing an incomplete model.
            BeneficiaryDashboard(
                **BeneficiaryOut.model_validate(item).model_dump(),
                supplies=[
                    SupplyDashboard.model_validate(supply)
                    for supply in item.supplies
                    if supply.deleted_at is None
                ],
            )
            for item in beneficiaries
        ],
        merchant_authorizations=[
            MerchantAuthorizationOut.model_validate(item) for item in authorizations
        ],
    )


@router.post("/beneficiaries", response_model=BeneficiaryOut, status_code=status.HTTP_201_CREATED)
def create_beneficiary(
    payload: BeneficiaryCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> BeneficiaryOut:
    values = payload.model_dump(exclude_unset=True, exclude_none=True)
    values.pop("name", None)
    values.pop("relationship_label", None)
    beneficiary = Beneficiary(
        owner_id=user.id,
        name=payload.name.strip(),
        relationship_label=payload.relationship_label.strip(),
        **{key: value.strip() if isinstance(value, str) else value for key, value in values.items()},
    )
    db.add(beneficiary)
    db.commit()
    db.refresh(beneficiary)
    return BeneficiaryOut.model_validate(beneficiary)


@router.patch("/beneficiaries/{beneficiary_id}", response_model=BeneficiaryOut)
def update_beneficiary(
    beneficiary_id: UUID,
    payload: BeneficiaryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> BeneficiaryOut:
    beneficiary = owned_beneficiary(db, user.id, beneficiary_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "delivery_country" and value is None:
            continue  # NOT NULL with a default; clearing it is never meaningful
        setattr(beneficiary, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(beneficiary)
    return BeneficiaryOut.model_validate(beneficiary)


@router.post(
    "/beneficiaries/{beneficiary_id}/supplies",
    response_model=SupplyOut,
    status_code=status.HTTP_201_CREATED,
)
def create_supply(
    beneficiary_id: UUID,
    payload: SupplyCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SupplyOut:
    owned_beneficiary(db, user.id, beneficiary_id)
    values = payload.model_dump()
    values["name"] = payload.name.strip()
    values["unit"] = payload.unit.strip()
    values["product_requirements"] = (
        payload.product_requirements.strip() if payload.product_requirements else None
    )
    supply = Supply(beneficiary_id=beneficiary_id, **values)
    db.add(supply)
    db.flush()
    db.add(
        StockMovement(
            supply_id=supply.id,
            movement_type="initial_balance",
            quantity_delta=supply.quantity_on_hand,
            balance_after=supply.quantity_on_hand,
            unit=supply.unit,
            note="Initial stock recorded when the recurring supply was created.",
            occurred_at=supply.inventory_observed_at or datetime.now(UTC),
        )
    )
    db.commit()
    db.refresh(supply)
    background_tasks.add_task(auto_configure_supply_background, user.id, supply.id)
    return SupplyOut.model_validate(supply)


@router.patch("/supplies/{supply_id}", response_model=SupplyOut)
def update_supply(
    supply_id: UUID,
    payload: SupplyUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SupplyOut:
    supply = owned_supply(db, user.id, supply_id, for_update=True)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("is_enabled") is True and (
        supply.setup_status != "ready"
        or not supply_has_eligible_variant(db, user.id, supply.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Health Guard must verify an exact merchant product before automatic ordering can be enabled",
        )
    matching_fields = {"name", "unit", "product_requirements", "preferred_pack_quantity"}
    needs_reconfiguration = bool(matching_fields.intersection(updates))
    if needs_reconfiguration:
        next_requirements = updates.get("product_requirements", supply.product_requirements)
        has_specific_preference = bool(
            isinstance(next_requirements, str) and next_requirements.strip()
        )
        auto_set = db.scalar(
            select(ProductEquivalenceSet)
            .where(
                ProductEquivalenceSet.supply_id == supply.id,
                ProductEquivalenceSet.name == AUTO_EQUIVALENCE_SET_NAME,
            )
            .options(selectinload(ProductEquivalenceSet.approved_variants))
        )
        if auto_set is not None:
            for variant in list(auto_set.approved_variants):
                db.delete(variant)
        supply.setup_status = "discovering"
        supply.setup_message = (
            "Rechecking your specific product after the update…"
            if has_specific_preference
            else "Choosing a matching product after the update…"
        )
        supply.agent_summary = None
        supply.configured_at = None
        supply.is_enabled = False
    if {"quantity_on_hand", "daily_consumption", "safety_buffer_quantity"}.intersection(
        updates
    ):
        if "quantity_on_hand" in updates:
            record_stock_count(
                db,
                supply=supply,
                quantity_on_hand=updates["quantity_on_hand"],
                note="Stock count updated from the recurring supply settings.",
            )
        else:
            rebase_inventory(supply)
    for field, value in updates.items():
        setattr(supply, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(supply)
    if needs_reconfiguration:
        background_tasks.add_task(auto_configure_supply_background, user.id, supply.id)
    return SupplyOut.model_validate(supply)


@router.post("/supplies/{supply_id}/stock-count", response_model=StockMovementOut)
def update_stock_count(
    supply_id: UUID,
    payload: StockCountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> StockMovementOut:
    supply = owned_supply(db, user.id, supply_id, for_update=True)
    movement = record_stock_count(
        db,
        supply=supply,
        quantity_on_hand=payload.quantity_on_hand,
        note="Current stock confirmed by the user.",
    )
    db.add(
        LedgerEvent(
            owner_id=user.id,
            event_type="stock_count_updated",
            title=f"{supply.name} stock updated",
            detail=f"Current stock was set to {movement.balance_after} {supply.unit}(s).",
            severity="info",
            supply_id=supply.id,
            metadata_safe={
                "balance_after": str(movement.balance_after),
                "unit": supply.unit,
            },
        )
    )
    db.commit()
    db.refresh(movement)
    return StockMovementOut.model_validate(movement)


@router.delete("/supplies/{supply_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supply(
    supply_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> Response:
    supply = owned_supply(db, user.id, supply_id, for_update=True)
    supply.deleted_at = datetime.now(UTC)
    supply.is_enabled = False
    db.add(
        LedgerEvent(
            owner_id=user.id,
            event_type="supply_deleted",
            title="Recurring supply removed",
            detail=f"{supply.name} was removed from automatic ordering.",
            severity="info",
            supply_id=supply.id,
            metadata_safe={"supply_name": supply.name},
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/merchant-authorizations",
    response_model=MerchantAuthorizationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_merchant_authorization(
    payload: MerchantAuthorizationCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MerchantAuthorizationOut:
    merchant_name, merchant_domain, _ = MERCHANTS[payload.merchant_key]
    authorization = MerchantAuthorization(
        owner_id=user.id,
        merchant_key=payload.merchant_key,
        merchant_name=merchant_name,
        merchant_domain=merchant_domain,
        preference_rank=payload.preference_rank,
    )
    db.add(authorization)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This merchant is already approved"
        ) from error
    db.refresh(authorization)
    background_tasks.add_task(auto_configure_owner_supplies_background, user.id)
    return MerchantAuthorizationOut.model_validate(authorization)


@router.patch(
    "/merchant-authorizations/{merchant_authorization_id}", response_model=MerchantAuthorizationOut
)
def update_merchant_authorization(
    merchant_authorization_id: UUID,
    payload: MerchantAuthorizationUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MerchantAuthorizationOut:
    authorization = owned_merchant_authorization(db, user.id, merchant_authorization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(authorization, field, value)
    db.commit()
    db.refresh(authorization)
    if payload.is_enabled is True:
        background_tasks.add_task(auto_configure_owner_supplies_background, user.id)
    return MerchantAuthorizationOut.model_validate(authorization)


@router.post(
    "/supplies/{supply_id}/auto-configure",
    response_model=SupplyOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_automatic_product_setup(
    supply_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SupplyOut:
    supply = owned_supply(db, user.id, supply_id, for_update=True)
    supply.setup_status = "discovering"
    supply.setup_message = (
        "Checking approved merchants for your specific product…"
        if supply.product_requirements
        else "Checking approved merchants for a matching product…"
    )
    supply.is_enabled = False
    db.commit()
    db.refresh(supply)
    background_tasks.add_task(auto_configure_supply_background, user.id, supply.id)
    return SupplyOut.model_validate(supply)


@router.post(
    "/supplies/{supply_id}/equivalence-sets",
    response_model=EquivalenceSetOut,
    status_code=status.HTTP_201_CREATED,
)
def create_equivalence_set(
    supply_id: UUID,
    payload: EquivalenceSetCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> EquivalenceSetOut:
    owned_supply(db, user.id, supply_id)
    equivalence_set = ProductEquivalenceSet(supply_id=supply_id, **payload.model_dump())
    db.add(equivalence_set)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An equivalence set with that name already exists for this supply",
        ) from error
    db.refresh(equivalence_set)
    return EquivalenceSetOut.model_validate(equivalence_set)


@router.post(
    "/equivalence-sets/{equivalence_set_id}/approved-variants",
    response_model=ApprovedVariantOut,
    status_code=status.HTTP_201_CREATED,
)
def create_approved_variant(
    equivalence_set_id: UUID,
    payload: ApprovedVariantCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> ApprovedVariantOut:
    owned_equivalence_set(db, user.id, equivalence_set_id)
    owned_merchant_authorization(db, user.id, payload.merchant_authorization_id)
    variant = ApprovedVariant(equivalence_set_id=equivalence_set_id, **payload.model_dump())
    db.add(variant)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This exact variant is already approved"
        ) from error
    db.refresh(variant)
    return ApprovedVariantOut.model_validate(variant)
