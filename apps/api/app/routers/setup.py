from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.database import get_db_session
from app.models import (
    ApprovedVariant,
    Beneficiary,
    MerchantAuthorization,
    ProductEquivalenceSet,
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
    SetupDashboard,
    SupplyCreate,
    SupplyOut,
    SupplyUpdate,
)

router = APIRouter(prefix="/setup", tags=["care setup"])

MERCHANTS: dict[str, tuple[str, str]] = {
    "himalaya": ("Himalaya Wellness", "himalayawellness.in"),
    "oziva": ("Oziva", "oziva.in"),
    "zandu": ("Zandu Care", "zanducare.com"),
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


def owned_supply(db: Session, owner_id: UUID, supply_id: UUID) -> Supply:
    supply = db.scalar(
        select(Supply)
        .join(Supply.beneficiary)
        .where(Supply.id == supply_id, Beneficiary.owner_id == owner_id)
    )
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
        .where(ProductEquivalenceSet.id == equivalence_set_id, Beneficiary.owner_id == owner_id)
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
                .selectinload(ProductEquivalenceSet.approved_variants)
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
        beneficiaries=[BeneficiaryDashboard.model_validate(item) for item in beneficiaries],
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
    beneficiary = Beneficiary(
        owner_id=user.id,
        name=payload.name.strip(),
        relationship_label=payload.relationship_label.strip(),
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SupplyOut:
    owned_beneficiary(db, user.id, beneficiary_id)
    supply = Supply(beneficiary_id=beneficiary_id, **payload.model_dump())
    db.add(supply)
    db.commit()
    db.refresh(supply)
    return SupplyOut.model_validate(supply)


@router.patch("/supplies/{supply_id}", response_model=SupplyOut)
def update_supply(
    supply_id: UUID,
    payload: SupplyUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> SupplyOut:
    supply = owned_supply(db, user.id, supply_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("is_enabled") is True and not supply_has_eligible_variant(
        db, user.id, supply.id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Approve at least one exact variant on an enabled merchant before enabling a supply",
        )
    for field, value in updates.items():
        setattr(supply, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(supply)
    return SupplyOut.model_validate(supply)


@router.post(
    "/merchant-authorizations",
    response_model=MerchantAuthorizationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_merchant_authorization(
    payload: MerchantAuthorizationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MerchantAuthorizationOut:
    merchant_name, merchant_domain = MERCHANTS[payload.merchant_key]
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
    return MerchantAuthorizationOut.model_validate(authorization)


@router.patch(
    "/merchant-authorizations/{merchant_authorization_id}", response_model=MerchantAuthorizationOut
)
def update_merchant_authorization(
    merchant_authorization_id: UUID,
    payload: MerchantAuthorizationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> MerchantAuthorizationOut:
    authorization = owned_merchant_authorization(db, user.id, merchant_authorization_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(authorization, field, value)
    db.commit()
    db.refresh(authorization)
    return MerchantAuthorizationOut.model_validate(authorization)


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
