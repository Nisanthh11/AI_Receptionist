"""Unauthenticated endpoints. By design they never return visitor records, phone numbers or e-mails."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.models import FAQ, Department, OrganizationInfo
from app.schemas.appointment import BookingRequest, LookupRequest, PublicBookingResult, SlotsOut
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
    return PublicBookingResult(
        reference_code=appt.reference_code, status=appt.status, start_at=appt.start_at, end_at=appt.end_at,
        staff_name=appt.staff.full_name, department_name=appt.department.name,
        message=appts.PUBLIC_STATUS_MESSAGES[appt.status])


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
def slots(staff_id: int = Query(gt=0), date: date = Query(...), db: Session = Depends(get_db)):
    return SlotsOut(staff_id=staff_id, date=date, slot_minutes=get_settings().slot_minutes,
                    slots=appts.list_available_slots(db, staff_id, date))


@router.post("/appointments", response_model=PublicBookingResult, status_code=201)
def book(payload: BookingRequest, db: Session = Depends(get_db)):
    appt = appts.create_appointment(db, full_name=payload.full_name, phone=payload.phone, email=payload.email,
                                    staff_id=payload.staff_id, start_at=payload.start_at, purpose=payload.purpose)
    return _result(appt)


@router.post("/appointments/lookup", response_model=PublicBookingResult)
def lookup(payload: LookupRequest, db: Session = Depends(get_db)):
    return _result(appts.lookup_public(db, payload.reference_code, payload.phone))


@router.post("/visitors/register", response_model=WalkInResult, status_code=201)
def register_visitor(payload: WalkInRegistration, db: Session = Depends(get_db)):
    visit = visitor_service.register_walk_in(db, full_name=payload.full_name, phone=payload.phone, email=payload.email,
                                             purpose=payload.purpose, staff_id=payload.staff_id)
    return WalkInResult(reference_code=visit.reference_code,
                        message="You are registered. Please let the reception desk know - they will check you in.")


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db), service: ChatService = Depends(get_chat_service)):
    token, reply = service.handle(db, payload.message, payload.session_token)
    return ChatResponse(session_token=token, reply=reply.text, intent=reply.intent,
                        answered_from_records=reply.answered_from_records, suggestions=reply.suggestions, action=reply.action)
