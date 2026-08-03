from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db_session
from app.models import MedicationReminder, Supply, User
from app.routers.setup import owned_supply
from app.schemas import MedicationReminderCreate, MedicationReminderOut, MedicationReminderUpdate

router = APIRouter(prefix="/reminders", tags=["medicine reminders"])


def owned_reminder(db: Session, owner_id: UUID, reminder_id: UUID) -> MedicationReminder:
    reminder = db.scalar(select(MedicationReminder).where(MedicationReminder.id == reminder_id, MedicationReminder.owner_id == owner_id))
    if reminder is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicine reminder not found")
    return reminder


@router.get("", response_model=list[MedicationReminderOut])
def list_reminders(user: User = Depends(get_current_user), db: Session = Depends(get_db_session)) -> list[MedicationReminderOut]:
    reminders = db.scalars(select(MedicationReminder).join(Supply).where(MedicationReminder.owner_id == user.id, Supply.deleted_at.is_(None)).order_by(MedicationReminder.time_of_day, MedicationReminder.created_at))
    return [MedicationReminderOut.model_validate(item) for item in reminders]


@router.post("", response_model=MedicationReminderOut, status_code=status.HTTP_201_CREATED)
def create_reminder(payload: MedicationReminderCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db_session)) -> MedicationReminderOut:
    owned_supply(db, user.id, payload.supply_id)
    reminder = MedicationReminder(owner_id=user.id, **payload.model_dump())
    db.add(reminder)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This supply already has a daily medicine reminder. Update it instead.") from error
    db.refresh(reminder)
    return MedicationReminderOut.model_validate(reminder)


@router.patch("/{reminder_id}", response_model=MedicationReminderOut)
def update_reminder(reminder_id: UUID, payload: MedicationReminderUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db_session)) -> MedicationReminderOut:
    reminder = owned_reminder(db, user.id, reminder_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(reminder, field, value)
    db.commit()
    db.refresh(reminder)
    return MedicationReminderOut.model_validate(reminder)


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(reminder_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db_session)) -> Response:
    db.delete(owned_reminder(db, user.id, reminder_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
