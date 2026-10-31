from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutils import now_local
from app.models.department import Staff


class Visitor(Base):
    """Only the minimum personal data: name, phone, optional e-mail."""

    __tablename__ = "visitors"
    __table_args__ = (Index("ix_visitors_phone_name", "phone", "full_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class VisitLog(Base):
    """One physical visit. registered -> checked_in -> checked_out."""

    __tablename__ = "visit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_code: Mapped[str] = mapped_column(String(20), unique=True)
    visitor_id: Mapped[int] = mapped_column(ForeignKey("visitors.id", ondelete="RESTRICT"), index=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    purpose: Mapped[str] = mapped_column(String(255))
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime)
    checked_in_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checked_out_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    visitor: Mapped[Visitor] = relationship(lazy="joined")
    staff: Mapped[Staff | None] = relationship(lazy="joined")

    @property
    def status(self) -> str:
        if self.check_out_at:
            return "checked_out"
        if self.check_in_at:
            return "checked_in"
        return "registered"
