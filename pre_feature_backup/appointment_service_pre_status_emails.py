"""Appointment business rules. Everything that decides whether a booking is allowed lives here,
on the server - the frontend only displays what this module allows."""
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.timeutils import now_local, to_local_naive
from app.models import Appointment, Notification, Staff, StaffAvailability, Visitor
from app.models.appointment import (ACTIVE_STATUSES, ALL_STATUSES, STATUS_CANCELLED, STATUS_COMPLETED,
                                    STATUS_CONFIRMED, STATUS_PENDING)
from app.services.notification_service import send_booking_notifications
from app.services.visitor_service import get_or_create_visitor

TRANSITIONS = {
    STATUS_PENDING: {STATUS_CONFIRMED, STATUS_CANCELLED},
    STATUS_CONFIRMED: {STATUS_COMPLETED, STATUS_CANCELLED},
    STATUS_COMPLETED: set(),
    STATUS_CANCELLED: set(),
}
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

PUBLIC_STATUS_MESSAGES = {
    STATUS_PENDING: "Your request has been received and is waiting for confirmation by the reception team.",
    STATUS_CONFIRMED: "Your appointment is confirmed. Please arrive a few minutes early and quote your reference code.",
    STATUS_COMPLETED: "This appointment has been completed.",
    STATUS_CANCELLED: "This appointment was cancelled. You can book a new slot at any time.",
}


def _slot() -> timedelta:
    return timedelta(minutes=get_settings().slot_minutes)


def make_slot_key(staff_id: int, start_at: datetime) -> str:
    return f"{staff_id}|{start_at:%Y%m%d%H%M}"


def _reference() -> str:
    return "APT-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def _get_bookable_staff(db: Session, staff_id: int, lock: bool = False) -> Staff:
    stmt = select(Staff).where(Staff.id == staff_id)
    if lock:
        stmt = stmt.with_for_update()  # serialises concurrent bookings for this staff member on MySQL/InnoDB
    staff = db.execute(stmt).scalar_one_or_none()
    if staff is None or not staff.is_active or not staff.department.is_active:
        raise AppError(404, "The selected staff member is not available for booking.")
    return staff


def _windows(db: Session, staff_id: int, day: date) -> list[StaffAvailability]:
    return list(db.execute(
        select(StaffAvailability).where(StaffAvailability.staff_id == staff_id, StaffAvailability.weekday == day.weekday())
        .order_by(StaffAvailability.start_time)).scalars())


def _grid(windows: list[StaffAvailability], day: date):
    delta = _slot()
    for w in windows:
        cur, end = datetime.combine(day, w.start_time), datetime.combine(day, w.end_time)
        while cur + delta <= end:
            yield cur
            cur += delta


def _check_time_rules(start_at: datetime) -> None:
    s, now = get_settings(), now_local()
    if start_at < now + timedelta(minutes=s.min_booking_lead_minutes):
        raise AppError(400, f"Appointments must be booked at least {s.min_booking_lead_minutes} minutes in advance and cannot be in the past.")
    if start_at.date() > now.date() + timedelta(days=s.max_booking_days_ahead):
        raise AppError(400, f"Appointments can only be booked up to {s.max_booking_days_ahead} days ahead.")


def _check_on_grid(db: Session, staff: Staff, start_at: datetime) -> None:
    if start_at not in set(_grid(_windows(db, staff.id, start_at.date()), start_at.date())):
        raise AppError(400, "That time is outside this staff member's available appointment slots.")


def _staff_conflict(db: Session, staff_id: int, start: datetime, end: datetime, exclude_id: int | None = None) -> bool:
    stmt = select(func.count()).select_from(Appointment).where(
        Appointment.staff_id == staff_id, Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_at < end, Appointment.end_at > start)
    if exclude_id:
        stmt = stmt.where(Appointment.id != exclude_id)
    return db.execute(stmt).scalar_one() > 0


def _visitor_conflict(db: Session, visitor_id: int, start: datetime, end: datetime, exclude_id: int | None = None) -> bool:
    stmt = select(func.count()).select_from(Appointment).where(
        Appointment.visitor_id == visitor_id, Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_at < end, Appointment.end_at > start)
    if exclude_id:
        stmt = stmt.where(Appointment.id != exclude_id)
    return db.execute(stmt).scalar_one() > 0


def list_available_slots(db: Session, staff_id: int, day: date) -> list[datetime]:
    staff = _get_bookable_staff(db, staff_id)
    s, now = get_settings(), now_local()
    if day < now.date() or day > now.date() + timedelta(days=s.max_booking_days_ahead):
        return []
    day_start = datetime.combine(day, datetime.min.time())
    booked = db.execute(select(Appointment).where(
        Appointment.staff_id == staff.id, Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_at >= day_start, Appointment.start_at < day_start + timedelta(days=1))).unique().scalars().all()
    earliest = now + timedelta(minutes=s.min_booking_lead_minutes)
    out = []
    for start in _grid(_windows(db, staff.id, day), day):
        end = start + _slot()
        if start < earliest or any(a.start_at < end and a.end_at > start for a in booked):
            continue
        out.append(start)
    return out


def create_appointment(db: Session, *, full_name: str, phone: str, email: str | None, staff_id: int,
                       start_at: datetime, purpose: str, user_id: int | None = None) -> Appointment:
    """Validate -> lock -> check conflicts -> insert -> commit. The caller only learns about success after COMMIT."""
    start_at = to_local_naive(start_at)
    end_at = start_at + _slot()
    try:
        staff = _get_bookable_staff(db, staff_id, lock=True)
        _check_time_rules(start_at)
        _check_on_grid(db, staff, start_at)
        if _staff_conflict(db, staff.id, start_at, end_at):
            raise AppError(409, "That time slot has just been taken. Please choose another slot.")
        visitor = get_or_create_visitor(db, full_name, phone, email)
        if _visitor_conflict(db, visitor.id, start_at, end_at):
            raise AppError(409, "You already have an appointment at an overlapping time.")
        appt = Appointment(reference_code=_reference(), visitor_id=visitor.id, staff_id=staff.id,
                           department_id=staff.department_id, start_at=start_at, end_at=end_at, purpose=purpose,
                           status=STATUS_PENDING, slot_key=make_slot_key(staff.id, start_at), user_id=user_id)
        db.add(appt)
        db.flush()
        db.add(Notification(type="appointment_requested", appointment_id=appt.id,
                            message=f"New appointment request {appt.reference_code} with {staff.full_name} on {start_at:%d %b %Y, %H:%M}."))
        db.commit()
    except AppError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise AppError(409, "That time slot has just been taken. Please choose another slot.")
    except Exception:
        db.rollback()
        raise

    # Send notifications after database save succeeds (failure does not delete the appointment)
    try:
        appt.notification_result = send_booking_notifications(db, appt)
    except Exception:
        pass
    return appt


def get_user_appointments(db: Session, user_id: int) -> tuple[list[Appointment], list[Appointment], int]:
    stmt = (
        select(Appointment)
        .where(Appointment.user_id == user_id)
        .order_by(Appointment.start_at.desc(), Appointment.id.desc())
    )
    all_appts = list(db.execute(stmt).scalars().all())
    now = now_local()
    upcoming = [a for a in all_appts if a.start_at >= now and a.status in ACTIVE_STATUSES]
    previous = [a for a in all_appts if a not in upcoming]
    return upcoming, previous, len(all_appts)


def get_user_appointment_by_id(db: Session, user_id: int, appt_id: int) -> Appointment:
    stmt = select(Appointment).where(Appointment.id == appt_id, Appointment.user_id == user_id)
    appt = db.execute(stmt).scalar_one_or_none()
    if appt is None:
        raise AppError(404, "Appointment not found.")
    return appt


def lookup_public(db: Session, reference_code: str, phone: str) -> Appointment:
    """Reference code AND phone must match; a mismatch is indistinguishable from 'not found'."""
    appt = db.execute(select(Appointment).where(Appointment.reference_code == reference_code.strip().upper())).unique().scalar_one_or_none()
    if appt is None or appt.visitor.phone != phone:
        raise AppError(404, "No appointment found for that reference code and phone number.")
    return appt


def _get_for_update(db: Session, appt_id: int) -> Appointment:
    # Lock the bare row first (no joins -> portable FOR UPDATE), then load the full object.
    locked = db.execute(select(Appointment.id).where(Appointment.id == appt_id).with_for_update()).scalar_one_or_none()
    if locked is None:
        raise AppError(404, "Appointment not found.")
    return db.execute(select(Appointment).where(Appointment.id == appt_id)).unique().scalar_one()


def update_status(db: Session, appt_id: int, new_status: str, *, notes: str | None = None, reason: str | None = None) -> Appointment:
    if new_status not in ALL_STATUSES:
        raise AppError(422, f"Status must be one of: {', '.join(ALL_STATUSES)}.")
    try:
        appt = _get_for_update(db, appt_id)
        if new_status not in TRANSITIONS[appt.status]:
            raise AppError(409, f"Cannot change an appointment from '{appt.status}' to '{new_status}'.")
        if new_status == STATUS_COMPLETED and appt.start_at > now_local():
            raise AppError(409, "An appointment in the future cannot be marked completed.")
        appt.status = new_status
        if new_status in (STATUS_COMPLETED, STATUS_CANCELLED):
            appt.slot_key = None  # frees the slot
        if new_status == STATUS_CANCELLED:
            appt.cancelled_reason = reason
        if notes is not None:
            appt.notes = notes
        db.add(Notification(type=f"appointment_{new_status}", appointment_id=appt.id, message=f"Appointment {appt.reference_code} marked {new_status}."))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return appt


def reschedule(db: Session, appt_id: int, start_at: datetime, staff_id: int | None = None) -> Appointment:
    start_at = to_local_naive(start_at)
    end_at = start_at + _slot()
    try:
        appt = _get_for_update(db, appt_id)
        if appt.status not in ACTIVE_STATUSES:
            raise AppError(409, f"A {appt.status} appointment cannot be rescheduled.")
        staff = _get_bookable_staff(db, staff_id or appt.staff_id, lock=True)
        _check_time_rules(start_at)
        _check_on_grid(db, staff, start_at)
        if _staff_conflict(db, staff.id, start_at, end_at, exclude_id=appt.id):
            raise AppError(409, "That time slot is already booked for this staff member.")
        if _visitor_conflict(db, appt.visitor_id, start_at, end_at, exclude_id=appt.id):
            raise AppError(409, "The visitor already has another appointment at that time.")
        appt.staff_id, appt.department_id = staff.id, staff.department_id
        appt.start_at, appt.end_at = start_at, end_at
        appt.slot_key = make_slot_key(staff.id, start_at)
        db.flush()
        db.add(Notification(type="appointment_rescheduled", appointment_id=appt.id,
                            message=f"Appointment {appt.reference_code} rescheduled to {start_at:%d %b %Y, %H:%M}."))
        db.commit()
        db.refresh(appt)
    except AppError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise AppError(409, "That time slot is already booked for this staff member.")
    except Exception:
        db.rollback()
        raise
    return appt


def search(db: Session, *, q: str | None, status: str | None, department_id: int | None, staff_id: int | None,
           date_from: date | None, date_to: date | None, page: int, page_size: int) -> tuple[list[Appointment], int]:
    stmt = select(Appointment).join(Visitor, Appointment.visitor_id == Visitor.id).join(Staff, Appointment.staff_id == Staff.id)
    if status:
        if status not in ALL_STATUSES:
            raise AppError(422, f"Status must be one of: {', '.join(ALL_STATUSES)}.")
        stmt = stmt.where(Appointment.status == status)
    if department_id:
        stmt = stmt.where(Appointment.department_id == department_id)
    if staff_id:
        stmt = stmt.where(Appointment.staff_id == staff_id)
    if date_from:
        stmt = stmt.where(Appointment.start_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        stmt = stmt.where(Appointment.start_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if q:
        stmt = stmt.where(or_(Appointment.reference_code.icontains(q, autoescape=True), Visitor.full_name.icontains(q, autoescape=True),
                              Visitor.phone.icontains(q, autoescape=True), Staff.full_name.icontains(q, autoescape=True),
                              Appointment.purpose.icontains(q, autoescape=True)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Appointment.start_at.desc(), Appointment.id.desc())
                      .limit(page_size).offset((page - 1) * page_size)).unique().scalars().all()
    return rows, total
