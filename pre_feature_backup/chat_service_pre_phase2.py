"""Receptionist chat.

`ChatService` talks to a `ResponderProvider`. Today the only provider is `RuleBasedResponder`, which answers
strictly from the database (FAQs, departments, organisation info). No LLM, speech or retrieval service is
connected. To add one later, implement `ResponderProvider` and pass it to `ChatService` (see get_chat_service
in app/api/public.py) - routes, persistence and the frontend do not change.
"""
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FAQ, Conversation, Department, Message, OrganizationInfo

MAX_MESSAGES_PER_CONVERSATION = 200
NOT_FOUND_REPLY = ("I'm sorry, I couldn't find that information in the records I have access to. "
                   "Please ask at the reception desk, or try asking about our departments, working hours or appointments.")
_STOP = set("a an the is are am was were be to of in on at for and or do does did can could would should i you we me my your our "
            "it this that with what whats which who where when how please tell about any there have has need want like".split())


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


class ResponderProvider(ABC):
    """Extension point for LLM / retrieval-based responders."""

    name: str

    @abstractmethod
    def respond(self, db: Session, message: str, history: list[ChatTurn]) -> ChatReply: ...


def _stem(w: str) -> str:
    for suf in ("ing", "es", "ed", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


_GREETING = re.compile(r"\b(hi|hello|hey|namaste|vanakkam|good\s+(morning|afternoon|evening))\b", re.I)
_THANKS = re.compile(r"\b(thanks|thank you|thankyou)\b", re.I)
_BYE = re.compile(r"\b(bye|goodbye|see you)\b", re.I)
_HOURS = re.compile(r"\b(hours|timings?|opening|closing|open|close|working time|office time)\b", re.I)
_APPT = re.compile(r"\b(appointments?|book(ing)?|schedule|meeting|meet)\b", re.I)
_DEPT = re.compile(r"\b(departments?|dept|directory|offices?)\b", re.I)
SUGGESTIONS = ["What are your working hours?", "Which departments do you have?", "I want to book an appointment"]


class RuleBasedResponder(ResponderProvider):
    name = "rule-based-faq"

    def respond(self, db: Session, message: str, history: list[ChatTurn]) -> ChatReply:
        words = tokens(message)
        short = len(message.split()) <= 6

        if short and _GREETING.search(message):
            return ChatReply("Hello! Welcome to our reception. I can help with departments, working hours, "
                             "frequently asked questions and booking appointments. What would you like to know?",
                             "greeting", suggestions=SUGGESTIONS)
        if short and _THANKS.search(message):
            return ChatReply("You're welcome! Let me know if there is anything else I can help with.", "thanks")
        if short and _BYE.search(message):
            return ChatReply("Goodbye! Have a great day.", "goodbye")

        departments = db.execute(select(Department).where(Department.is_active.is_(True)).order_by(Department.name)).scalars().all()

        # Department mentioned by name -> answer from its stored record.
        for d in departments:
            dtokens = tokens(d.name)
            if dtokens and dtokens <= words:
                parts = [f"{d.name}: {d.description}" if d.description else d.name]
                if d.location:
                    parts.append(f"Location: {d.location}.")
                if d.working_hours:
                    parts.append(f"Hours: {d.working_hours}.")
                if d.phone:
                    parts.append(f"Phone: {d.phone}.")
                return ChatReply(" ".join(parts), "department_enquiry", suggestions=["I want to book an appointment"], action="book_appointment")

        if _HOURS.search(message):
            info = db.get(OrganizationInfo, "working_hours")
            if info and info.value.strip():
                return ChatReply(f"Our working hours: {info.value}", "working_hours")

        if _APPT.search(message):
            return ChatReply("I can help you request an appointment. Use the booking form to choose a department, staff member and an "
                             "available time slot. Your request will be confirmed by the reception team.",
                             "appointment_request", suggestions=["Which departments do you have?"], action="book_appointment")

        if _DEPT.search(message):
            if departments:
                listing = "; ".join(f"{d.name}" + (f" ({d.location})" if d.location else "") for d in departments)
                return ChatReply(f"We have these departments: {listing}. Ask about any of them for more details.", "department_list")

        # FAQ matching: overlap between the question words and the FAQ question + keywords.
        best, best_score = None, 0.0
        if words:
            for faq in db.execute(select(FAQ).where(FAQ.is_active.is_(True))).scalars():
                ftokens = tokens(faq.question) | tokens(faq.keywords or "")
                overlap = len(words & ftokens)
                score = overlap / len(words)
                if overlap >= 1 and score > best_score:
                    best, best_score = faq, score
        if best is not None and best_score >= 0.5:
            return ChatReply(best.answer, "faq", suggestions=[])
        return ChatReply(NOT_FOUND_REPLY, "unknown", answered_from_records=False, suggestions=SUGGESTIONS)


class ChatService:
    def __init__(self, responder: ResponderProvider):
        self.responder = responder

    def handle(self, db: Session, message: str, session_token: str | None) -> tuple[str, ChatReply]:
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
            reply = self.responder.respond(db, message, history)
            db.add(Message(conversation_id=convo.id, sender="visitor", content=message))
            db.add(Message(conversation_id=convo.id, sender="receptionist", content=reply.text, intent=reply.intent))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return convo.session_token, reply
