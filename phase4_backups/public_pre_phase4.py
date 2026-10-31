"""Unauthenticated endpoints. By design they never return visitor records, phone numbers or e-mails."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_optional_current_user
from app.core.errors import AppError
from app.core.rate_limit import rate_limit_lookup
from app.models import FAQ, Department, OrganizationInfo
from app.models.user import User
from app.schemas.appointment import BookingRequest, LookupRequest, PublicBookingResult, SlotItem, SlotsOut
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.directory import DepartmentPublic, FAQPublic
from app.schemas.visitor import WalkInRegistration, WalkInResult
from app.services import appointment_service as appts
from app.services import visitor_service
from app.services.chat_service import ChatService, RuleBasedResponder

router = APIRouter(prefix="/api/public", tags=["Public (visitor)"])


def get_chat_service() -> ChatService:
    # Swap RuleBasedResponder for an LLM/retrieval provider here when one is actually implemented.
    return ChatService(RuleBasedResponder())


def _result(appt) -> PublicBookingResult:
    notif = getattr(appt, "notification_result", None)
    base_msg = appts.PUBLIC_STATUS_MESSAGES.get(appt.status, "")
    if notif and notif.message:
        msg = f"{base_msg} {notif.message}".strip()
    else:
        msg = base_msg
    return PublicBookingResult(
        reference_code=appt.reference_code,
        status=appt.status,
        start_at=appt.start_at,
        end_at=appt.end_at,
        staff_name=appt.staff.full_name,
        department_name=appt.department.name,
        message=msg,
    )


@router.get("/organization")
def organization(db: Session = Depends(get_db)):
    rows = db.execute(select(OrganizationInfo)).scalars().all()
    return {r.key: r.value for r in rows}


@router.get("/departments", response_model=list[DepartmentPublic])
def departments(db: Session = Depends(get_db)):
    rows = db.execute(select(Department).where(Department.is_active.is_(True)).options(selectinload(Department.staff)).order_by(Department.name)).scalars().all()
    for d in rows:
        d.staff = [s for s in d.staff if s.is_active]
    db.expunge_all()  # the filtered collection must never be flushed back
    return rows


@router.get("/faqs", response_model=list[FAQPublic])
def faqs(category: str | None = None, db: Session = Depends(get_db)):
    stmt = select(FAQ).where(FAQ.is_active.is_(True)).order_by(FAQ.category, FAQ.id)
    if category:
        stmt = stmt.where(FAQ.category == category)
    return db.execute(stmt).scalars().all()


@router.get("/slots", response_model=SlotsOut)
def slots(
    date: date = Query(...),
    staff_id: int | None = Query(None, gt=0),
    department_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
):
    if not staff_id and not department_id:
        raise AppError(400, "staff_id or department_id must be provided.")

    if staff_id:
        staff = appts._get_bookable_staff(db, staff_id)
        if department_id and staff.department_id != department_id:
            raise AppError(400, "The selected staff member does not belong to this department.")
        available_slots, all_items = appts.get_staff_slot_grid(db, staff, date)
        dept_id = staff.department_id
    else:
        dept = db.get(Department, department_id)
        if not dept or not dept.is_active:
            raise AppError(404, "The selected department is not available for booking.")
        available_slots, all_items = appts.get_department_slot_grid(db, department_id, date)
        dept_id = department_id

    return SlotsOut(
        staff_id=staff_id,
        department_id=dept_id,
        date=date,
        slot_minutes=get_settings().slot_minutes,
        slots=available_slots,
        all_slots=[SlotItem(**item) for item in all_items],
    )


@router.post("/appointments", response_model=PublicBookingResult, status_code=201)
def book(payload: BookingRequest, db: Session = Depends(get_db), current_user: User | None = Depends(get_optional_current_user)):
    user_id = current_user.id if current_user else None
    appt = appts.create_appointment(
        db,
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        staff_id=payload.staff_id,
        department_id=payload.department_id,
        start_at=payload.start_at,
        purpose=payload.purpose,
        user_id=user_id,
    )
    return _result(appt)


@router.post("/appointments/lookup", response_model=PublicBookingResult, dependencies=[Depends(rate_limit_lookup)])
def lookup(payload: LookupRequest, db: Session = Depends(get_db)):
    return _result(appts.lookup_public(db, payload.reference_code, payload.phone))


@router.post("/visitors/register", response_model=WalkInResult, status_code=201)
def register_visitor(payload: WalkInRegistration, db: Session = Depends(get_db)):
    visit = visitor_service.register_walk_in(db, full_name=payload.full_name, phone=payload.phone, email=payload.email,
                                             purpose=payload.purpose, staff_id=payload.staff_id)
    return WalkInResult(reference_code=visit.reference_code,
                        message="You are registered. Please let the reception desk know - they will check you in.")


@router.get("/chat", response_model=ChatResponse)
def get_chat(
    session_token: str = Query(..., min_length=8, max_length=64),
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
    current_user: User | None = Depends(get_optional_current_user),
):
    token, reply = service.get_session_state(db, session_token, current_user=current_user)
    return ChatResponse(
        session_token=token,
        reply=reply.text,
        intent=reply.intent,
        answered_from_records=reply.answered_from_records,
        suggestions=reply.suggestions,
        action=reply.action,
        booking_flow=reply.booking_flow,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
    current_user: User | None = Depends(get_optional_current_user),
):
    token, reply = service.handle(db, payload.message, payload.session_token, current_user=current_user)
    return ChatResponse(
        session_token=token,
        reply=reply.text,
        intent=reply.intent,
        answered_from_records=reply.answered_from_records,
        suggestions=reply.suggestions,
        action=reply.action,
        booking_flow=reply.booking_flow,
    )
