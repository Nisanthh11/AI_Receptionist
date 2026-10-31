"""Authenticated user endpoints for viewing own appointment history."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.appointment import UserAppointmentList, UserAppointmentOut
from app.services import appointment_service as appts

router = APIRouter(prefix="/api/user", tags=["User Appointments"])


def _to_user_appt(a) -> UserAppointmentOut:
    return UserAppointmentOut(
        id=a.id,
        reference_code=a.reference_code,
        status=a.status,
        start_at=a.start_at,
        end_at=a.end_at,
        purpose=a.purpose,
        staff_name=a.staff.full_name,
        department_name=a.department.name,
        notes=a.notes,
        cancelled_reason=a.cancelled_reason,
        created_at=a.created_at,
        sms_status=a.sms_status,
        email_status=a.email_status,
        booking_source=getattr(a, "booking_source", "website"),
    )


@router.get("/appointments", response_model=UserAppointmentList)
def my_appointments(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns the authenticated user's own appointment history (upcoming and previous)."""
    upcoming, previous, total = appts.get_user_appointments(db, current_user.id)
    return UserAppointmentList(
        upcoming=[_to_user_appt(a) for a in upcoming],
        previous=[_to_user_appt(a) for a in previous],
        total=total,
    )


@router.get("/appointments/{appt_id}", response_model=UserAppointmentOut)
def my_appointment_detail(appt_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns details of an appointment belonging strictly to the authenticated user."""
    appt = appts.get_user_appointment_by_id(db, current_user.id, appt_id)
    return _to_user_appt(appt)
