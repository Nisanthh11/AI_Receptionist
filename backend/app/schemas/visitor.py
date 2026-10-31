from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.appointment import AppointmentOut, StaffBrief, VisitorBrief
from app.schemas.common import Name, ORMModel, Phone, ShortText


class WalkInRegistration(BaseModel):
    full_name: Name
    phone: Phone
    email: EmailStr | None = None
    purpose: ShortText
    staff_id: int | None = Field(default=None, gt=0)


class WalkInResult(BaseModel):
    reference_code: str
    message: str


class StaffVisitCreate(BaseModel):
    full_name: Name
    phone: Phone
    email: EmailStr | None = None
    purpose: ShortText
    staff_id: int | None = Field(default=None, gt=0)
    appointment_id: int | None = Field(default=None, gt=0)
    check_in_now: bool = True


class VisitOut(ORMModel):
    id: int
    reference_code: str
    status: str
    purpose: str
    registered_at: datetime
    check_in_at: datetime | None
    check_out_at: datetime | None
    appointment_id: int | None
    visitor: VisitorBrief
    staff: StaffBrief | None


class VisitList(BaseModel):
    items: list[VisitOut]
    total: int
    page: int
    page_size: int


class VisitorOut(VisitorBrief):
    created_at: datetime


class VisitorList(BaseModel):
    items: list[VisitorOut]
    total: int
    page: int
    page_size: int


class VisitorDetail(BaseModel):
    visitor: VisitorOut
    visits: list[VisitOut]
    appointments: list[AppointmentOut]
