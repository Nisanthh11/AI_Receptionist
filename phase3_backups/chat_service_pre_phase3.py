"""Receptionist chat service.
Supports rule-based FAQ answering, directory inquiries, and full conversational appointment booking.
"""
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.timeutils import now_local
from app.models import FAQ, Conversation, Department, Message, OrganizationInfo, Staff
from app.services import appointment_service as appts
from app.services.date_parser import parse_natural_date

MAX_MESSAGES_PER_CONVERSATION = 200
NOT_FOUND_REPLY = (
    "I'm sorry, I couldn't find that information in the records I have access to. "
    "Please ask at the reception desk, or try asking about our departments, working hours or appointments."
)
_STOP = set(
    "a an the is are am was were be to of in on at for and or do does did can could would should i you we me my your our "
    "it this that with what whats which who where when how please tell about any there have has need want like".split()
)


@dataclass
class ChatTurn:
    sender: str
    content: str


@dataclass
class ChatReply:
    text: str
    intent: str
    answered_from_records: bool = True
    suggestions: list[str] = field(default_factory=list)
    action: str | None = None
    booking_flow: dict | None = None


class ResponderProvider(ABC):
    """Extension point for LLM / retrieval-based responders."""

    name: str

    @abstractmethod
    def respond(
        self,
        db: Session,
        message: str,
        history: list[ChatTurn],
        session_token: str | None = None,
        current_user=None,
    ) -> ChatReply: ...


def _stem(w: str) -> str:
    for suf in ("ing", "es", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def fmt_slot_range(start: datetime, end: datetime) -> str:
    return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"


_GREETING = re.compile(r"\b(hi|hello|hey|namaste|vanakkam|good\s+(morning|afternoon|evening))\b", re.I)
_THANKS = re.compile(r"\b(thanks|thank you|thankyou)\b", re.I)
_BYE = re.compile(r"\b(bye|goodbye|see you)\b", re.I)
_HOURS = re.compile(r"\b(hours|timings?|opening|closing|open|close|working time|office time)\b", re.I)
_APPT = re.compile(r"\b(appointments?|book(ing)?|schedule|meeting|meet)\b", re.I)
_DEPT = re.compile(r"\b(departments?|dept|directory|offices?)\b", re.I)
_CANCEL_WORDS = {"cancel", "stop", "nevermind", "never mind", "restart", "start over", "abort", "quit", "exit"}
SUGGESTIONS = ["What are your working hours?", "Which departments do you have?", "I want to book an appointment"]


@dataclass
class BookingSession:
    session_token: str
    step: str = "idle"  # "department", "staff", "date", "slot", "visitor_name", "visitor_phone", "visitor_email", "visitor_purpose", "confirmation", "completed"
    department_id: int | None = None
    department_name: str | None = None
    staff_id: int | None = None
    staff_name: str | None = None
    date: date | None = None
    slot_start: datetime | None = None
    slot_end: datetime | None = None
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    purpose: str | None = None
    reference_code: str | None = None
    appointment_id: int | None = None
    available_slots: list[dict] = field(default_factory=list)
    user_id: int | None = None
    updated_at: datetime = field(default_factory=now_local)

    def to_flow_dict(self) -> dict | None:
        if self.step in ("idle", "completed") and not self.reference_code:
            return None
        return {
            "step": self.step,
            "department_id": self.department_id,
            "department_name": self.department_name,
            "staff_id": self.staff_id,
            "staff_name": self.staff_name,
            "date_str": self.date.isoformat() if self.date else None,
            "slot_start": self.slot_start.isoformat() if self.slot_start else None,
            "slot_end": self.slot_end.isoformat() if self.slot_end else None,
            "full_name": self.full_name,
            "phone": self.phone,
            "email": self.email,
            "purpose": self.purpose,
            "reference_code": self.reference_code,
            "options": [],
        }


# In-memory store mapping session_token -> BookingSession
_booking_sessions: dict[str, BookingSession] = {}


def _is_booking_intent(message: str) -> bool:
    m = message.lower().strip()
    booking_patterns = [
        r"\b(book|booking|schedule|request|make|fix|set up)\s+(an?\s+)?(appointment|meeting|consultation|visit)\b",
        r"\b(i\s+want|i\s+need|i'd\s+like|can\s+i|could\s+i|how\s+to|how\s+can\s+i)\s+(to\s+)?(book|schedule|meet|see|visit)\b",
        r"\b(want|need)\s+(an?\s+)?appointment\b",
        r"\bmeet\s+(with\s+)?(someone|dr\b|mr\b|ms\b|a\s+doctor|staff|officer)\b",
        r"\bbook\s+me\s+(a\s+)?(meeting|appointment)\b",
        r"\bbook\s+an?\s+appointment\b",
    ]
    for p in booking_patterns:
        if re.search(p, m):
            return True
    tokens_set = set(re.findall(r"[a-z0-9]+", m))
    if {"book", "appointment"} <= tokens_set or {"schedule", "appointment"} <= tokens_set:
        return True
    if m in ("book", "booking", "book appointment", "appointment booking", "schedule meeting"):
        return True
    return False


def _is_ambiguous_appointment_query(message: str) -> bool:
    m = message.lower().strip()
    return m in ("appointment", "appointments", "appointment?", "appointments?", "about appointment", "appointment details")


class RuleBasedResponder(ResponderProvider):
    name = "rule-based-faq"

    def respond(
        self,
        db: Session,
        message: str,
        history: list[ChatTurn],
        session_token: str | None = None,
        current_user=None,
    ) -> ChatReply:
        words = tokens(message)
        short = len(message.split()) <= 6
        msg_lower = message.lower().strip()

        # Check existing active booking flow for this session
        session: BookingSession | None = _booking_sessions.get(session_token) if session_token else None

        # Check if booking is already completed and visitor repeats confirmation
        if session and session.step == "completed":
            if any(w in msg_lower for w in ("confirm", "yes", "proceed", "book", "submit")) or session.reference_code:
                if not (_is_booking_intent(message) and any(w in msg_lower for w in ("another", "new", "different", "more"))):
                    return ChatReply(
                        text=(
                            f"Your appointment request is already recorded!\n\n"
                            f"📋 Reference Code: {session.reference_code}\n"
                            f"⏳ Status: Pending Staff Approval"
                        ),
                        intent="appointment_confirmed",
                        action="booking_completed",
                        suggestions=["Check Status", "Book another appointment"],
                        booking_flow=session.to_flow_dict(),
                    )

        # 1. Visitor asks to cancel or restart during an active flow
        if session and session.step not in ("idle", "completed"):
            if any(cw in msg_lower for cw in _CANCEL_WORDS) or msg_lower in ("cancel", "no", "nevermind", "restart"):
                _booking_sessions.pop(session_token, None)
                return ChatReply(
                    "I've cancelled the appointment booking. How else can I assist you today?",
                    "booking_cancelled",
                    suggestions=SUGGESTIONS,
                )

            # Change commands in active flow
            if "change department" in msg_lower or "different department" in msg_lower:
                session.step = "department"
                session.department_id = None
                session.department_name = None
                session.staff_id = None
                session.staff_name = None
                session.slot_start = None
                session.slot_end = None
                return self._prompt_department(db, session)

            if "change staff" in msg_lower or "different staff" in msg_lower or "different person" in msg_lower:
                if session.department_id:
                    session.step = "staff"
                    session.staff_id = None
                    session.staff_name = None
                    session.slot_start = None
                    session.slot_end = None
                    return self._prompt_staff(db, session)

            if "change date" in msg_lower or "different date" in msg_lower or "another day" in msg_lower:
                session.step = "date"
                session.date = None
                session.slot_start = None
                session.slot_end = None
                return self._prompt_date(session)

            if "change slot" in msg_lower or "different time" in msg_lower or "change time" in msg_lower or "another time" in msg_lower:
                session.step = "slot"
                session.slot_start = None
                session.slot_end = None
                return self._prompt_slot(db, session)

            # Handle active booking steps
            return self._handle_booking_step(db, message, session, current_user)

        # 2. Greeting, thanks, goodbye (outside active booking flow)
        if short and _GREETING.search(message):
            return ChatReply(
                "Hello! Welcome to our reception. I can help with departments, working hours, "
                "frequently asked questions and booking appointments. What would you like to know?",
                "greeting",
                suggestions=SUGGESTIONS,
            )
        if short and _THANKS.search(message):
            return ChatReply("You're welcome! Let me know if there is anything else I can help with.", "thanks")
        if short and _BYE.search(message):
            return ChatReply("Goodbye! Have a great day.", "goodbye")

        # 3. Check FAQ matches first if visitor is asking a question rather than booking
        best_faq, best_score = None, 0.0
        if words and not _is_booking_intent(message):
            for faq in db.execute(select(FAQ).where(FAQ.is_active.is_(True))).scalars():
                ftokens = tokens(faq.question) | tokens(faq.keywords or "")
                overlap = len(words & ftokens)
                score = overlap / len(words)
                if overlap >= 1 and score > best_score:
                    best_faq, best_score = faq, score
            if best_faq is not None and best_score >= 0.5:
                return ChatReply(best_faq.answer, "faq", suggestions=[])

        # 4. Working hours
        if _HOURS.search(message):
            info = db.get(OrganizationInfo, "working_hours")
            if info and info.value.strip():
                return ChatReply(f"Our working hours: {info.value}", "working_hours")

        # 5. Department enquiry by name
        departments = db.execute(select(Department).where(Department.is_active.is_(True)).order_by(Department.name)).scalars().all()
        for d in departments:
            dtokens = tokens(d.name)
            if dtokens and dtokens <= words and not _is_booking_intent(message):
                parts = [f"{d.name}: {d.description}" if d.description else d.name]
                if d.location:
                    parts.append(f"Location: {d.location}.")
                if d.working_hours:
                    parts.append(f"Hours: {d.working_hours}.")
                if d.phone:
                    parts.append(f"Phone: {d.phone}.")
                return ChatReply(
                    " ".join(parts),
                    "department_enquiry",
                    suggestions=["I want to book an appointment"],
                    action="book_appointment",
                )

        # 6. Ambiguous appointment mention
        if _is_ambiguous_appointment_query(message):
            return ChatReply(
                "Are you looking to book an appointment with our reception or staff, or do you have a question about an existing appointment?",
                "clarification",
                suggestions=["I want to book an appointment", "Check appointment status", "What are your working hours?"],
            )

        # 7. Explicit appointment booking intent -> start guided conversational booking!
        if _is_booking_intent(message) or _APPT.search(message):
            return self._start_booking_flow(db, message, session_token, current_user)

        # 8. Department directory listing
        if _DEPT.search(message):
            if departments:
                listing = "; ".join(f"{d.name}" + (f" ({d.location})" if d.location else "") for d in departments)
                return ChatReply(f"We have these departments: {listing}. Ask about any of them for more details.", "department_list")

        # 9. Fallback FAQ search if not checked earlier
        if words and best_faq is None:
            for faq in db.execute(select(FAQ).where(FAQ.is_active.is_(True))).scalars():
                ftokens = tokens(faq.question) | tokens(faq.keywords or "")
                overlap = len(words & ftokens)
                score = overlap / len(words)
                if overlap >= 1 and score > best_score:
                    best_faq, best_score = faq, score
            if best_faq is not None and best_score >= 0.5:
                return ChatReply(best_faq.answer, "faq", suggestions=[])

        return ChatReply(NOT_FOUND_REPLY, "unknown", answered_from_records=False, suggestions=SUGGESTIONS)

    def _start_booking_flow(self, db: Session, message: str, session_token: str | None, current_user=None) -> ChatReply:
        tok = session_token or uuid.uuid4().hex
        session = BookingSession(session_token=tok, step="department")
        if current_user:
            session.user_id = current_user.id
            session.full_name = getattr(current_user, "full_name", None) or getattr(current_user, "name", None)
            session.email = getattr(current_user, "email", None)
            session.phone = getattr(current_user, "phone", None)
        _booking_sessions[tok] = session

        msg_lower = message.lower()
        active_depts = db.execute(select(Department).where(Department.is_active.is_(True)).order_by(Department.name)).scalars().all()

        # Check if department mentioned in initial message
        for d in active_depts:
            if d.name.lower() in msg_lower:
                session.department_id = d.id
                session.department_name = d.name
                break

        # Check if staff mentioned in initial message
        active_staff = db.execute(select(Staff).where(Staff.is_active.is_(True))).scalars().all()
        for s in active_staff:
            if s.full_name.lower() in msg_lower:
                session.staff_id = s.id
                session.staff_name = s.full_name
                if not session.department_id:
                    session.department_id = s.department_id
                    session.department_name = s.department.name
                break

        # Check if date mentioned in initial message (e.g. "tomorrow", "next monday")
        parsed_dt = parse_natural_date(message)
        if parsed_dt:
            today = now_local().date()
            max_date = today + timedelta(days=get_settings().max_booking_days_ahead)
            if today <= parsed_dt <= max_date:
                session.date = parsed_dt

        # Advance to first missing step
        if not session.department_id:
            return self._prompt_department(db, session)
        if not session.staff_id and "anyone" not in msg_lower and "any" not in msg_lower:
            return self._prompt_staff(db, session)
        if not session.date:
            return self._prompt_date(session)

        # All 3 known from initial message! Prompt for slot
        return self._prompt_slot(db, session)

    def _prompt_department(self, db: Session, session: BookingSession) -> ChatReply:
        session.step = "department"
        depts = db.execute(select(Department).where(Department.is_active.is_(True)).order_by(Department.name)).scalars().all()
        dept_names = [d.name for d in depts]
        return ChatReply(
            text="I'd be glad to help you book an appointment! Which department would you like to visit?",
            intent="appointment_request",
            action="book_appointment",
            suggestions=dept_names + ["Cancel"],
            booking_flow=session.to_flow_dict(),
        )

    def _prompt_staff(self, db: Session, session: BookingSession) -> ChatReply:
        session.step = "staff"
        staff_list = db.execute(
            select(Staff).where(Staff.department_id == session.department_id, Staff.is_active.is_(True)).order_by(Staff.full_name)
        ).scalars().all()
        options = ["Any available staff member"] + [s.full_name for s in staff_list]
        return ChatReply(
            text=f"Great! Who would you like to meet in the **{session.department_name}** department?",
            intent="appointment_request",
            action="book_appointment",
            suggestions=options + ["Change department", "Cancel"],
            booking_flow=session.to_flow_dict(),
        )

    def _prompt_date(self, session: BookingSession) -> ChatReply:
        session.step = "date"
        staff_str = f"with **{session.staff_name}**" if session.staff_name else f"in **{session.department_name}**"
        return ChatReply(
            text=(
                f"Got it! Scheduling {staff_str}.\n\n"
                f"What date would you like to visit? You can say 'tomorrow', 'next Monday', or provide a date (e.g. 2026-10-27)."
            ),
            intent="appointment_request",
            action="book_appointment",
            suggestions=["Tomorrow", "Day after tomorrow", "Next Monday", "Change staff", "Cancel"],
            booking_flow=session.to_flow_dict(),
        )

    def _prompt_slot(self, db: Session, session: BookingSession) -> ChatReply:
        session.step = "slot"
        if session.staff_id:
            staff = appts._get_bookable_staff(db, session.staff_id)
            _, all_slots = appts.get_staff_slot_grid(db, staff, session.date)
        else:
            _, all_slots = appts.get_department_slot_grid(db, session.department_id, session.date)

        session.available_slots = [item for item in all_slots if item["is_available"]]
        date_display = session.date.strftime("%A, %d %B %Y")

        if not session.available_slots:
            session.step = "date"
            staff_desc = session.staff_name or session.department_name
            return ChatReply(
                text=(
                    f"There are no available appointment slots on **{date_display}** for {staff_desc}.\n\n"
                    f"Would you like to try another date (e.g. tomorrow or next Monday), or select a different staff member?"
                ),
                intent="appointment_request",
                action="book_appointment",
                suggestions=["Tomorrow", "Day after tomorrow", "Next Monday", "Change staff", "Cancel"],
                booking_flow=session.to_flow_dict(),
            )

        slot_labels = [fmt_slot_range(s["start_at"], s["end_at"]) for s in session.available_slots]
        staff_desc = session.staff_name or f"{session.department_name} (Auto-assigned)"
        return ChatReply(
            text=(
                f"Here are the available time slots on **{date_display}** for **{staff_desc}**.\n\n"
                f"Please choose a time slot:"
            ),
            intent="appointment_request",
            action="book_appointment",
            suggestions=slot_labels[:8] + ["Pick another date", "Cancel"],
            booking_flow=session.to_flow_dict(),
        )

    def _handle_booking_step(self, db: Session, message: str, session: BookingSession, current_user=None) -> ChatReply:
        msg_clean = message.strip()
        msg_lower = msg_clean.lower()

        # Step: department
        if session.step == "department":
            active_depts = db.execute(select(Department).where(Department.is_active.is_(True)).order_by(Department.name)).scalars().all()
            matched = None
            for d in active_depts:
                if d.name.lower() == msg_lower or d.name.lower() in msg_lower or msg_lower in d.name.lower():
                    matched = d
                    break
            if not matched:
                return self._prompt_department(db, session)
            session.department_id = matched.id
            session.department_name = matched.name
            if session.staff_id or session.staff_name:
                if session.date:
                    return self._prompt_slot(db, session)
                return self._prompt_date(session)
            return self._prompt_staff(db, session)

        # Step: staff
        if session.step == "staff":
            staff_list = db.execute(
                select(Staff).where(Staff.department_id == session.department_id, Staff.is_active.is_(True)).order_by(Staff.full_name)
            ).scalars().all()
            if any(w in msg_lower for w in ("any", "anyone", "auto", "no preference", "either", "first available")):
                session.staff_id = None
                session.staff_name = "Any available staff member"
                if session.date:
                    return self._prompt_slot(db, session)
                return self._prompt_date(session)

            matched_staff = None
            for s in staff_list:
                if s.full_name.lower() == msg_lower or s.full_name.lower() in msg_lower or msg_lower in s.full_name.lower():
                    matched_staff = s
                    break
            if not matched_staff:
                options = ["Any available staff member"] + [s.full_name for s in staff_list]
                return ChatReply(
                    text=f"Please choose a staff member in {session.department_name} or select 'Any available staff member':",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=options + ["Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            session.staff_id = matched_staff.id
            session.staff_name = matched_staff.full_name
            if session.date:
                return self._prompt_slot(db, session)
            return self._prompt_date(session)

        # Step: date
        if session.step == "date":
            parsed = parse_natural_date(message)
            if not parsed:
                return ChatReply(
                    text="I couldn't recognize that date. Please enter a date such as 'tomorrow', 'next Monday', or 'YYYY-MM-DD'.",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=["Tomorrow", "Day after tomorrow", "Next Monday", "Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            today = now_local().date()
            max_date = today + timedelta(days=get_settings().max_booking_days_ahead)
            if parsed < today:
                return ChatReply(
                    text="Appointments cannot be booked in the past. Please choose today or an upcoming date up to 30 days ahead.",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=["Tomorrow", "Day after tomorrow", "Next Monday", "Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            if parsed > max_date:
                return ChatReply(
                    text=f"Appointments can only be booked up to {get_settings().max_booking_days_ahead} days in advance. Please choose an earlier date.",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=["Tomorrow", "Day after tomorrow", "Next Monday", "Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            session.date = parsed
            return self._prompt_slot(db, session)

        # Step: slot
        if session.step == "slot":
            matched_slot = None
            for s in session.available_slots:
                label = fmt_slot_range(s["start_at"], s["end_at"]).lower()
                iso_str = s["start_at"].isoformat() if hasattr(s["start_at"], "isoformat") else str(s["start_at"])
                time_only = s["start_at"].strftime("%I:%M %p").lower()
                time_24 = s["start_at"].strftime("%H:%M")
                if (
                    msg_lower == label
                    or msg_lower in label
                    or msg_clean == iso_str
                    or msg_lower == time_only
                    or msg_lower == time_24
                    or time_only in msg_lower
                    or time_24 in msg_lower
                ):
                    matched_slot = s
                    break

            if not matched_slot:
                slot_labels = [fmt_slot_range(s["start_at"], s["end_at"]) for s in session.available_slots]
                return ChatReply(
                    text="I couldn't match that to an available time slot. Please select one of the available times listed below:",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=slot_labels[:8] + ["Pick another date", "Cancel"],
                    booking_flow=session.to_flow_dict(),
                )

            session.slot_start = matched_slot["start_at"]
            session.slot_end = matched_slot["end_at"]
            if matched_slot.get("staff_id"):
                session.staff_id = matched_slot["staff_id"]
                session.staff_name = matched_slot.get("staff_name") or session.staff_name

            # Check if user details already provided from logged-in account
            if current_user or session.user_id:
                name = getattr(current_user, "full_name", None) or getattr(current_user, "name", None) or session.full_name
                phone = getattr(current_user, "phone", None) or session.phone
                email = getattr(current_user, "email", None) or session.email
                if name:
                    session.full_name = name
                if phone:
                    session.phone = phone
                if email:
                    session.email = email

            slot_time_str = fmt_slot_range(session.slot_start, session.slot_end)
            if session.full_name and session.phone:
                session.step = "visitor_purpose"
                return ChatReply(
                    text=(
                        f"Selected time: **{slot_time_str}** with **{session.staff_name}**.\n\n"
                        f"I have your contact details as **{session.full_name}** ({session.phone}). "
                        f"What is the **purpose** of your appointment?"
                    ),
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=["General inquiry", "Consultation", "Document verification", "Discussion", "Cancel"],
                    booking_flow=session.to_flow_dict(),
                )

            session.step = "visitor_name"
            return ChatReply(
                text=f"Selected time: **{slot_time_str}** with **{session.staff_name}**.\n\nPlease enter your **full name**:",
                intent="appointment_request",
                action="book_appointment",
                suggestions=["Cancel"],
                booking_flow=session.to_flow_dict(),
            )

        # Step: visitor_name
        if session.step == "visitor_name":
            if len(msg_clean) < 2 or len(msg_clean) > 100 or "<" in msg_clean:
                return ChatReply(
                    text="Please provide a valid full name (between 2 and 100 characters):",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=["Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            session.full_name = msg_clean
            session.step = "visitor_phone"
            return ChatReply(
                text=f"Thank you, {session.full_name}. What is your **contact phone number**? (e.g. +919876543210)",
                intent="appointment_request",
                action="book_appointment",
                suggestions=["Cancel"],
                booking_flow=session.to_flow_dict(),
            )

        # Step: visitor_phone
        if session.step == "visitor_phone":
            digits = re.sub(r"[^\d]", "", msg_clean)
            if len(digits) < 8 or len(digits) > 15:
                return ChatReply(
                    text="Please provide a valid contact phone number with at least 8 digits (e.g. +919876543210):",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=["Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            session.phone = msg_clean
            session.step = "visitor_email"
            return ChatReply(
                text="Got it. What is your **email address**? (You can type your email, or reply 'skip' if you prefer not to provide one)",
                intent="appointment_request",
                action="book_appointment",
                suggestions=["skip", "Cancel"],
                booking_flow=session.to_flow_dict(),
            )

        # Step: visitor_email
        if session.step == "visitor_email":
            if msg_lower in ("skip", "no", "none", "n/a", "no email"):
                session.email = None
            else:
                if "@" not in msg_clean or "." not in msg_clean.split("@")[-1] or len(msg_clean) > 255:
                    return ChatReply(
                        text="That email address looks invalid. Please enter a valid email address (e.g. name@example.com) or reply 'skip':",
                        intent="appointment_request",
                        action="book_appointment",
                        suggestions=["skip", "Cancel"],
                        booking_flow=session.to_flow_dict(),
                    )
                session.email = msg_clean

            session.step = "visitor_purpose"
            return ChatReply(
                text="What is the **purpose** of your appointment? (Brief reason for your visit)",
                intent="appointment_request",
                action="book_appointment",
                suggestions=["General inquiry", "Consultation", "Document verification", "Discussion", "Cancel"],
                booking_flow=session.to_flow_dict(),
            )

        # Step: visitor_purpose
        if session.step == "visitor_purpose":
            if len(msg_clean) < 1 or len(msg_clean) > 255:
                return ChatReply(
                    text="Please provide a brief reason for your visit (up to 255 characters):",
                    intent="appointment_request",
                    action="book_appointment",
                    suggestions=["Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            session.purpose = msg_clean
            session.step = "confirmation"
            return self._prompt_confirmation(session)

        # Step: confirmation
        if session.step == "confirmation":
            if any(w in msg_lower for w in ("confirm", "yes", "proceed", "book", "ok", "sure", "submit")):
                return self._finalize_booking(db, session)
            return ChatReply(
                text="Please reply **Confirm** to schedule your appointment, or reply 'Change time', 'Change date', or 'Cancel'.",
                intent="appointment_request",
                action="book_appointment",
                suggestions=["Confirm", "Change time", "Change date", "Cancel"],
                booking_flow=session.to_flow_dict(),
            )

        return ChatReply(NOT_FOUND_REPLY, "unknown", suggestions=SUGGESTIONS)

    def _prompt_confirmation(self, session: BookingSession) -> ChatReply:
        date_str = session.date.strftime("%A, %d %B %Y")
        time_str = fmt_slot_range(session.slot_start, session.slot_end)
        email_str = session.email if session.email else "Not provided"
        review_text = (
            f"Please review your appointment request details:\n\n"
            f"🏢 **Department:** {session.department_name}\n"
            f"👤 **Person to meet:** {session.staff_name}\n"
            f"📅 **Date:** {date_str}\n"
            f"⏰ **Time:** {time_str}\n"
            f"👤 **Visitor:** {session.full_name}\n"
            f"📞 **Phone:** {session.phone}\n"
            f"✉️ **Email:** {email_str}\n"
            f"📝 **Purpose:** {session.purpose}\n\n"
            f"Reply **Confirm** to submit your appointment request, or tell me if you'd like to change anything."
        )
        return ChatReply(
            text=review_text,
            intent="appointment_request",
            action="book_appointment",
            suggestions=["Confirm", "Change time", "Change date", "Cancel"],
            booking_flow=session.to_flow_dict(),
        )

    def _finalize_booking(self, db: Session, session: BookingSession) -> ChatReply:
        # Prevent duplicate submissions
        if session.reference_code:
            return ChatReply(
                text=(
                    f"Your appointment request is already recorded!\n\n"
                    f"📋 Reference Code: {session.reference_code}\n"
                    f"⏳ Status: Pending Staff Approval"
                ),
                intent="appointment_confirmed",
                action="booking_completed",
                suggestions=["Check Status", "Book another appointment"],
                booking_flow=session.to_flow_dict(),
            )

        try:
            appt = appts.create_appointment(
                db,
                full_name=session.full_name,
                phone=session.phone,
                email=session.email,
                staff_id=session.staff_id,
                department_id=session.department_id,
                start_at=session.slot_start,
                purpose=session.purpose,
                user_id=session.user_id,
            )
            session.reference_code = appt.reference_code
            session.appointment_id = appt.id
            session.step = "completed"
            # Retain in _booking_sessions with step='completed' so duplicate clicks return the same appointment

            date_str = appt.start_at.strftime("%A, %d %B %Y at %I:%M %p")
            reply_text = (
                f"🎉 **Your appointment request has been recorded!**\n\n"
                f"📋 **Reference Code:** {appt.reference_code}\n"
                f"🏢 **Department:** {appt.department.name}\n"
                f"👤 **Staff:** {appt.staff.full_name}\n"
                f"📅 **Scheduled For:** {date_str}\n"
                f"⏳ **Status:** Pending Staff Approval\n\n"
                f"Your request has been received and is awaiting staff approval. "
                f"You can quote reference code **{appt.reference_code}** on the Check Status page anytime."
            )
            return ChatReply(
                text=reply_text,
                intent="appointment_confirmed",
                action="booking_completed",
                suggestions=["Check Status", "Book another appointment", "What are your working hours?"],
                booking_flow={
                    "step": "completed",
                    "reference_code": appt.reference_code,
                    "department_name": appt.department.name,
                    "staff_name": appt.staff.full_name,
                    "start_at": appt.start_at.isoformat(),
                    "end_at": appt.end_at.isoformat(),
                    "status": "pending",
                },
            )
        except AppError as e:
            if e.status_code == 409:
                session.step = "slot"
                if session.staff_id:
                    st = appts._get_bookable_staff(db, session.staff_id)
                    _, all_slots = appts.get_staff_slot_grid(db, st, session.date)
                else:
                    _, all_slots = appts.get_department_slot_grid(db, session.department_id, session.date)
                session.available_slots = [item for item in all_slots if item["is_available"]]
                slot_labels = [fmt_slot_range(s["start_at"], s["end_at"]) for s in session.available_slots]
                date_display = session.date.strftime("%A, %d %B %Y")
                return ChatReply(
                    text=(
                        f"⚠️ That time slot was just taken by another visitor while we were confirming. "
                        f"Don't worry, all your details have been saved! "
                        f"Please select another available slot for {date_display}:"
                    ),
                    intent="slot_conflict",
                    action="book_appointment",
                    suggestions=slot_labels[:8] + ["Cancel"],
                    booking_flow=session.to_flow_dict(),
                )
            raise


class ChatService:
    def __init__(self, responder: ResponderProvider):
        self.responder = responder

    def handle(
        self,
        db: Session,
        message: str,
        session_token: str | None,
        current_user=None,
    ) -> tuple[str, ChatReply]:
        convo = None
        if session_token:
            convo = db.execute(select(Conversation).where(Conversation.session_token == session_token)).scalar_one_or_none()
        if convo is None:
            convo = Conversation(session_token=uuid.uuid4().hex)
            db.add(convo)
            db.flush()
        count = db.execute(select(func.count()).select_from(Message).where(Message.conversation_id == convo.id)).scalar_one()
        if count >= MAX_MESSAGES_PER_CONVERSATION:
            db.rollback()
            raise AppError(429, "This conversation is too long. Please start a new chat.")
        recent = db.execute(select(Message).where(Message.conversation_id == convo.id).order_by(Message.id.desc()).limit(6)).scalars().all()
        history = [ChatTurn(m.sender, m.content) for m in reversed(recent)]
        try:
            reply = self.responder.respond(
                db,
                message,
                history,
                session_token=convo.session_token,
                current_user=current_user,
            )
            db.add(Message(conversation_id=convo.id, sender="visitor", content=message))
            db.add(Message(conversation_id=convo.id, sender="receptionist", content=reply.text, intent=reply.intent))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return convo.session_token, reply

    def get_session_state(
        self,
        db: Session,
        session_token: str,
        current_user=None,
    ) -> tuple[str, ChatReply]:
        convo = db.execute(select(Conversation).where(Conversation.session_token == session_token)).scalar_one_or_none()
        if convo is None:
            return session_token, ChatReply(
                text="Hello! I'm the virtual receptionist. Ask me about departments, working hours or appointments.",
                intent="greeting",
                suggestions=SUGGESTIONS,
            )

        session = _booking_sessions.get(session_token)
        if session and session.step not in ("idle", "completed"):
            flow_dict = session.to_flow_dict()
            # Return current active step prompt
            if session.step == "department":
                reply = self.responder._prompt_department(db, session)
            elif session.step == "staff":
                reply = self.responder._prompt_staff(db, session)
            elif session.step == "date":
                reply = self.responder._prompt_date(session)
            elif session.step == "slot":
                reply = self.responder._prompt_slot(db, session)
            elif session.step == "confirmation":
                reply = self.responder._prompt_confirmation(session)
            else:
                reply = ChatReply(
                    text=f"Resuming your appointment booking. Please provide your {session.step.replace('visitor_', '')}:",
                    intent="appointment_request",
                    action="book_appointment",
                    booking_flow=flow_dict,
                )
            return session_token, reply

        # If last message exists, return it
        last_msg = db.execute(
            select(Message).where(Message.conversation_id == convo.id, Message.sender == "receptionist").order_by(Message.id.desc())
        ).scalars().first()
        if last_msg:
            return session_token, ChatReply(
                text=last_msg.content,
                intent=last_msg.intent or "greeting",
                suggestions=SUGGESTIONS,
            )

        return session_token, ChatReply(
            text="Hello! I'm the virtual receptionist. Ask me about departments, working hours or appointments.",
            intent="greeting",
            suggestions=SUGGESTIONS,
        )
