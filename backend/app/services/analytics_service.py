from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutils import now_local
from app.models import Appointment, Department, Notification, Visitor, VisitLog
from app.models.appointment import ALL_STATUSES, STATUS_PENDING


def summary(db: Session) -> dict:
    now = now_local()
    start = datetime.combine(now.date(), datetime.min.time())
    end = start + timedelta(days=1)
    today = db.execute(select(Appointment).where(Appointment.start_at >= start, Appointment.start_at < end)
                       .order_by(Appointment.start_at)).unique().scalars().all()
    pending = db.execute(select(func.count()).select_from(Appointment).where(Appointment.status == STATUS_PENDING)).scalar_one()
    total_visitors = db.execute(select(func.count()).select_from(Visitor)).scalar_one()
    on_site = db.execute(select(func.count()).select_from(VisitLog).where(VisitLog.check_in_at.is_not(None), VisitLog.check_out_at.is_(None))).scalar_one()
    waiting = db.execute(select(func.count()).select_from(VisitLog).where(VisitLog.check_in_at.is_(None))).scalar_one()
    recent = db.execute(select(Notification).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(10)).scalars().all()
    return {
        "today_appointments": today,
        "today_count": len(today),
        "pending_appointments": pending,
        "total_visitors": total_visitors,
        "visitors_on_site": on_site,
        "visitors_waiting_check_in": waiting,
        "recent_activity": [{"id": n.id, "type": n.type, "message": n.message, "created_at": n.created_at} for n in recent],
    }


def analytics(db: Session, days: int = 14) -> dict:
    now = now_local()
    since = datetime.combine(now.date() - timedelta(days=days - 1), datetime.min.time())
    by_status = {s: 0 for s in ALL_STATUSES}
    for status, n in db.execute(select(Appointment.status, func.count()).group_by(Appointment.status)):
        by_status[status] = n
    by_dept = [{"department": name, "appointments": n} for name, n in db.execute(
        select(Department.name, func.count(Appointment.id)).join(Appointment, Appointment.department_id == Department.id)
        .group_by(Department.name).order_by(func.count(Appointment.id).desc()))]
    appt_days = Counter(d.date().isoformat() for (d,) in db.execute(select(Appointment.start_at).where(Appointment.start_at >= since)))
    visit_rows = db.execute(select(VisitLog.check_in_at, VisitLog.check_out_at).where(VisitLog.check_in_at >= since)).all()
    visit_days = Counter(ci.date().isoformat() for ci, _ in visit_rows)
    durations = [(co - ci).total_seconds() / 60 for ci, co in visit_rows if co]
    labels = [(since.date() + timedelta(days=i)).isoformat() for i in range(days)]
    return {
        "appointments_by_status": by_status,
        "appointments_by_department": by_dept,
        "daily": [{"date": d, "appointments": appt_days.get(d, 0), "visits": visit_days.get(d, 0)} for d in labels],
        "average_visit_minutes": round(sum(durations) / len(durations), 1) if durations else None,
        "completed_visits_in_range": len(durations),
    }
