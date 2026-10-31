from pydantic import BaseModel, Field

from app.schemas.common import ChatText


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
