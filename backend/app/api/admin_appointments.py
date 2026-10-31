from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_staff
from app.core.errors import AppError
from app.models import Appointment
from app.schemas.appointment import AppointmentList, AppointmentOut, CancelRequest, RescheduleRequest, StatusUpdate
from app.services import appointment_service as svc

router = APIRouter(prefix="/api/admin/appointments", tags=["Admin: appointments"], dependencies=[Depends(require_staff)])


@router.get("", response_model=AppointmentList)
def list_appointments(q: str | None = Query(None, max_length=100), status: str | None = None, department_id: int | None = None,
                      staff_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
                      booking_source: str | None = None,
                      page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    rows, total = svc.search(db, q=q, status=status, department_id=department_id, staff_id=staff_id,
                             date_from=date_from, date_to=date_to, booking_source=booking_source,
                             page=page, page_size=page_size)
    return AppointmentList(items=rows, total=total, page=page, page_size=page_size)


@router.post("/reminders/process")
def trigger_reminders(db: Session = Depends(get_db)):
    """Manually process due appointment reminders."""
    from app.services.reminder_service import process_due_reminders
    count = process_due_reminders(db)
    return {"status": "ok", "processed": count}



@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(appointment_id: int, db: Session = Depends(get_db)):
    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise AppError(404, "Appointment not found.")
    return appt


@router.patch("/{appointment_id}/status", response_model=AppointmentOut)
def set_status(appointment_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    return svc.update_status(db, appointment_id, payload.status, notes=payload.notes, reason=payload.reason)


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule(appointment_id: int, payload: RescheduleRequest, db: Session = Depends(get_db)):
    return svc.reschedule(db, appointment_id, payload.start_at, payload.staff_id)


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(appointment_id: int, payload: CancelRequest, db: Session = Depends(get_db)):
    return svc.update_status(db, appointment_id, "cancelled", reason=payload.reason)
