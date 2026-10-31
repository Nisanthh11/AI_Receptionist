from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import Name, ORMModel, Phone, ShortText, LongText


class BookingRequest(BaseModel):
    full_name: Name
    phone: Phone
    email: EmailStr | None = None
    staff_id: int | None = Field(default=None, gt=0)
    department_id: int | None = Field(default=None, gt=0)
    start_at: datetime
    purpose: ShortText


class PublicBookingResult(BaseModel):
    """What a visitor gets back. Deliberately contains no visitor personal details."""

    reference_code: str
    status: str
    start_at: datetime
    end_at: datetime
    staff_name: str
    department_name: str
    message: str


class UserAppointmentOut(BaseModel):
    id: int
    reference_code: str
    status: str
    start_at: datetime
    end_at: datetime
    purpose: str
    staff_name: str
    department_name: str
    notes: str | None = None
    cancelled_reason: str | None = None
    created_at: datetime
    sms_status: str | None = None
    email_status: str | None = None


class UserAppointmentList(BaseModel):
    upcoming: list[UserAppointmentOut]
    previous: list[UserAppointmentOut]
    total: int


class LookupRequest(BaseModel):
    reference_code: str = Field(min_length=6, max_length=20)
    phone: Phone


class SlotItem(BaseModel):
    start_at: datetime
    end_at: datetime
    is_available: bool
    staff_id: int
    staff_name: str | None = None
    reason: str = "available"  # "available", "booked", "past", "lead_time", "break"


class SlotsOut(BaseModel):
    staff_id: int | None = None
    department_id: int | None = None
    date: date
    slot_minutes: int
    slots: list[datetime]
    all_slots: list[SlotItem] = []


class VisitorBrief(ORMModel):
    id: int
    full_name: str
    phone: str
    email: str | None


class StaffBrief(ORMModel):
    id: int
    full_name: str
    designation: str | None


class DepartmentBrief(ORMModel):
    id: int
    name: str


class AppointmentOut(ORMModel):
    id: int
    reference_code: str
    status: str
    start_at: datetime
    end_at: datetime
    purpose: str
    notes: str | None
    cancelled_reason: str | None
    created_at: datetime
    visitor: VisitorBrief
    staff: StaffBrief
    department: DepartmentBrief


class AppointmentList(BaseModel):
    items: list[AppointmentOut]
    total: int
    page: int
    page_size: int


class StatusUpdate(BaseModel):
    status: str
    notes: LongText | None = None
    reason: ShortText | None = None


class RescheduleRequest(BaseModel):
    start_at: datetime
    staff_id: int | None = Field(default=None, gt=0)


class CancelRequest(BaseModel):
    reason: ShortText | None = None
