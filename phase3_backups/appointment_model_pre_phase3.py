from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutils import now_local
from app.models.department import Department, Staff
from app.models.user import User
from app.models.visitor import Visitor

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
ALL_STATUSES = (STATUS_PENDING, STATUS_CONFIRMED, STATUS_COMPLETED, STATUS_CANCELLED)
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_CONFIRMED)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("status IN ('pending','confirmed','completed','cancelled')", name="status_valid"),
        CheckConstraint("end_at > start_at", name="time_order"),
        Index("ix_appointments_staff_start", "staff_id", "start_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_code: Mapped[str] = mapped_column(String(20), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id", ondelete="RESTRICT"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="RESTRICT"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    purpose: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)
    sms_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(String(255))
    # Database-level guard against double booking: "<staff_id>|<start>" while the appointment is
    # active (pending/confirmed), NULL otherwise. NULLs do not collide in a UNIQUE index (MySQL/SQLite),
    # so cancelled/completed appointments free the slot.
    slot_key: Mapped[str | None] = mapped_column(String(40), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    user: Mapped[User | None] = relationship(lazy="joined")
    visitor: Mapped[Visitor] = relationship(lazy="joined")
    staff: Mapped[Staff] = relationship(lazy="joined")
    department: Mapped[Department] = relationship(lazy="joined")
