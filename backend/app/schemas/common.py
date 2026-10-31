"""Shared validated field types. Text is trimmed and rejects HTML angle brackets / control characters."""
import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ONE_LINE_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_PHONE_JUNK = re.compile(r"[\s\-().]")
_PHONE_OK = re.compile(r"^\+?\d{7,15}$")


def _single_line(v: str) -> str:
    v = re.sub(r"\s+", " ", v).strip()
    if "<" in v or ">" in v or _ONE_LINE_CTRL.search(v):
        raise ValueError("contains characters that are not allowed")
    return v


def _multi_line(v: str) -> str:
    v = v.strip()
    if "<" in v or ">" in v or _CTRL.search(v):
        raise ValueError("contains characters that are not allowed")
    return v


def _phone(v: str) -> str:
    v = _PHONE_JUNK.sub("", v)
    if not _PHONE_OK.match(v):
        raise ValueError("enter a valid phone number (7-15 digits, optional leading +)")
    return v


def _password(v: str) -> str:
    if len(v.encode("utf-8")) > 72:
        raise ValueError("password must be at most 72 bytes")
    return v


Name = Annotated[str, StringConstraints(min_length=2, max_length=100), AfterValidator(_single_line)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=255), AfterValidator(_single_line)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=150), AfterValidator(_single_line)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=4000), AfterValidator(_multi_line)]
Phone = Annotated[str, StringConstraints(min_length=7, max_length=30), AfterValidator(_phone)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128), AfterValidator(_password)]
ChatText = Annotated[str, StringConstraints(min_length=1, max_length=500), AfterValidator(_single_line)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    total: int
    page: int
    page_size: int


def page_params(page: int, page_size: int) -> tuple[int, int]:
    return max(page, 1), min(max(page_size, 1), 100)


PageQuery = Field(default=1, ge=1)
