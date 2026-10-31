from datetime import datetime, time

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutils import now_local


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(30))
    working_hours: Mapped[str | None] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    staff: Mapped[list["Staff"]] = relationship(back_populates="department", order_by="Staff.full_name")


class Staff(Base):
    """People that visitors can meet (not the same as login users)."""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"), index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    designation: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    department: Mapped[Department] = relationship(back_populates="staff")
    availability: Mapped[list["StaffAvailability"]] = relationship(
        back_populates="staff", cascade="all, delete-orphan", order_by="StaffAvailability.weekday, StaffAvailability.start_time"
    )


class StaffAvailability(Base):
    """Weekly recurring availability window (weekday 0 = Monday)."""

    __tablename__ = "staff_availability"
    __table_args__ = (
        UniqueConstraint("staff_id", "weekday", "start_time", name="staff_window"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="window_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    staff: Mapped[Staff] = relationship(back_populates="availability")
