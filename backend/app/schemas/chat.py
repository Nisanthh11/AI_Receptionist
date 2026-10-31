from pydantic import BaseModel, Field

from app.schemas.common import ChatText


class ChatOption(BaseModel):
    label: str
    value: str
    description: str | None = None


class BookingFlowState(BaseModel):
    step: str
    department_id: int | None = None
    department_name: str | None = None
    staff_id: int | None = None
    staff_name: str | None = None
    date_str: str | None = None
    slot_start: str | None = None
    slot_end: str | None = None
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    purpose: str | None = None
    reference_code: str | None = None
    time_pref: str | None = None
    options: list[ChatOption] = []


class ChatRequest(BaseModel):
    message: ChatText
    session_token: str | None = Field(default=None, min_length=8, max_length=64)


class ChatResponse(BaseModel):
    session_token: str
    reply: str
    intent: str
    answered_from_records: bool
    suggestions: list[str] = []
    action: str | None = None  # e.g. "book_appointment" so the UI can offer a button
    booking_flow: BookingFlowState | None = None
