from datetime import datetime, time

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import Label, LongText, Name, ORMModel, ShortText


class StaffPublic(ORMModel):
    id: int
    full_name: str
    designation: str | None


class DepartmentPublic(ORMModel):
    id: int
    name: str
    description: str | None
    location: str | None
    phone: str | None
    working_hours: str | None
    staff: list[StaffPublic]


class FAQPublic(ORMModel):
    id: int
    question: str
    answer: str
    category: str | None


class AvailabilityIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @field_validator("end_time")
    @classmethod
    def _ordered(cls, v, info):
        if "start_time" in info.data and v <= info.data["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v


class AvailabilityOut(ORMModel, AvailabilityIn):
    id: int


class DepartmentIn(BaseModel):
    name: Name
    description: LongText | None = None
    location: Label | None = None
    phone: Label | None = None
    working_hours: Label | None = None
    is_active: bool = True


class DepartmentOut(ORMModel):
    id: int
    name: str
    description: str | None
    location: str | None
    phone: str | None
    working_hours: str | None
    is_active: bool
    created_at: datetime


class StaffIn(BaseModel):
    department_id: int = Field(gt=0)
    full_name: Name
    designation: Label | None = None
    email: EmailStr | None = None
    is_active: bool = True


class StaffOut(ORMModel):
    id: int
    department_id: int
    full_name: str
    designation: str | None
    email: str | None
    is_active: bool
    availability: list[AvailabilityOut]


class AvailabilitySet(BaseModel):
    windows: list[AvailabilityIn]


class FAQIn(BaseModel):
    question: ShortText
    answer: LongText
    keywords: Label | None = None
    category: Label | None = None
    is_active: bool = True


class FAQOut(ORMModel):
    id: int
    question: str
    answer: str
    keywords: str | None
    category: str | None
    is_active: bool


class OrgInfoUpdate(BaseModel):
    values: dict[str, LongText]
