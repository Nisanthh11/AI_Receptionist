import secrets

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.timeutils import now_local
from app.models import Appointment, Notification, Staff, User, Visitor, VisitLog

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_reference(prefix: str) -> str:
    return f"{prefix}-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def get_or_create_visitor(db: Session, full_name: str, phone: str, email: str | None) -> Visitor:
    """Re-use a record only when BOTH phone and name match, and never overwrite its stored details
    from a public request (so one person cannot alter another person's record)."""
    existing = db.execute(
        select(Visitor).where(Visitor.phone == phone, func.lower(Visitor.full_name) == full_name.lower())
    ).scalars().first()
    if existing:
        return existing
    visitor = Visitor(full_name=full_name, phone=phone, email=email.lower() if email else None)
    db.add(visitor)
    db.flush()
    return visitor


def _active_staff(db: Session, staff_id: int | None) -> Staff | None:
    if staff_id is None:
        return None
    staff = db.get(Staff, staff_id)
    if staff is None or not staff.is_active:
        raise AppError(404, "The selected staff member was not found.")
    return staff


def register_walk_in(db: Session, *, full_name: str, phone: str, email: str | None, purpose: str,
                     staff_id: int | None) -> VisitLog:
    """Visitor self-registration. Creates a visit that reception must check in; nothing is claimed beyond that."""
    try:
        _active_staff(db, staff_id)
        visitor = get_or_create_visitor(db, full_name, phone, email)
        visit = VisitLog(reference_code=generate_reference("VIS"), visitor_id=visitor.id, staff_id=staff_id, purpose=purpose)
        db.add(visit)
        db.flush()
        db.add(Notification(type="visitor_registered", message=f"Visitor {visit.reference_code} registered and waiting at reception."))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return visit


def create_visit_by_staff(db: Session, user: User, *, full_name: str, phone: str, email: str | None, purpose: str,
                          staff_id: int | None, appointment_id: int | None, check_in_now: bool) -> VisitLog:
    try:
        _active_staff(db, staff_id)
        if appointment_id is not None and db.get(Appointment, appointment_id) is None:
            raise AppError(404, "Appointment not found.")
        visitor = get_or_create_visitor(db, full_name, phone, email)
        visit = VisitLog(reference_code=generate_reference("VIS"), visitor_id=visitor.id, staff_id=staff_id,
                         appointment_id=appointment_id, purpose=purpose)
        if check_in_now:
            visit.check_in_at = now_local()
            visit.checked_in_by = user.id
        db.add(visit)
        db.flush()
        if check_in_now:
            db.add(Notification(type="visitor_checked_in", message=f"Visit {visit.reference_code} checked in."))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return visit


def _get_visit(db: Session, visit_id: int) -> VisitLog:
    visit = db.get(VisitLog, visit_id)
    if visit is None:
        raise AppError(404, "Visit not found.")
    return visit


def check_in(db: Session, user: User, visit_id: int) -> VisitLog:
    visit = _get_visit(db, visit_id)
    if visit.check_in_at:
        raise AppError(409, "This visitor is already checked in.")
    visit.check_in_at = now_local()
    visit.checked_in_by = user.id
    db.add(Notification(type="visitor_checked_in", message=f"Visit {visit.reference_code} checked in."))
    db.commit()
    return visit


def check_out(db: Session, user: User, visit_id: int) -> VisitLog:
    visit = _get_visit(db, visit_id)
    if not visit.check_in_at:
        raise AppError(409, "Visitor has not been checked in yet.")
    if visit.check_out_at:
        raise AppError(409, "This visitor is already checked out.")
    visit.check_out_at = now_local()
    visit.checked_out_by = user.id
    db.add(Notification(type="visitor_checked_out", message=f"Visit {visit.reference_code} checked out."))
    db.commit()
    return visit


def list_visits(db: Session, *, status: str | None, q: str | None, page: int, page_size: int) -> tuple[list[VisitLog], int]:
    stmt = select(VisitLog).join(Visitor, VisitLog.visitor_id == Visitor.id)
    if status == "registered":
        stmt = stmt.where(VisitLog.check_in_at.is_(None))
    elif status == "checked_in":
        stmt = stmt.where(VisitLog.check_in_at.is_not(None), VisitLog.check_out_at.is_(None))
    elif status == "checked_out":
        stmt = stmt.where(VisitLog.check_out_at.is_not(None))
    elif status:
        raise AppError(422, "status must be registered, checked_in or checked_out.")
    if q:
        stmt = stmt.where(or_(Visitor.full_name.icontains(q, autoescape=True), Visitor.phone.icontains(q, autoescape=True),
                              VisitLog.reference_code.icontains(q, autoescape=True), VisitLog.purpose.icontains(q, autoescape=True)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(VisitLog.registered_at.desc(), VisitLog.id.desc())
                      .limit(page_size).offset((page - 1) * page_size)).unique().scalars().all()
    return rows, total


def list_visitors(db: Session, *, q: str | None, page: int, page_size: int) -> tuple[list[Visitor], int]:
    stmt = select(Visitor)
    if q:
        stmt = stmt.where(or_(Visitor.full_name.icontains(q, autoescape=True), Visitor.phone.icontains(q, autoescape=True),
                              Visitor.email.icontains(q, autoescape=True)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Visitor.created_at.desc(), Visitor.id.desc())
                      .limit(page_size).offset((page - 1) * page_size)).scalars().all()
    return rows, total


def visitor_detail(db: Session, visitor_id: int):
    visitor = db.get(Visitor, visitor_id)
    if visitor is None:
        raise AppError(404, "Visitor not found.")
    visits = db.execute(select(VisitLog).where(VisitLog.visitor_id == visitor_id)
                        .order_by(VisitLog.registered_at.desc())).unique().scalars().all()
    appts = db.execute(select(Appointment).where(Appointment.visitor_id == visitor_id)
                       .order_by(Appointment.start_at.desc())).unique().scalars().all()
    return visitor, visits, appts
