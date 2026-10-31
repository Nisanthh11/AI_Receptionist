from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_staff
from app.schemas.appointment import AppointmentOut
from app.services import analytics_service

router = APIRouter(prefix="/api/admin", tags=["Admin: dashboard"], dependencies=[Depends(require_staff)])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    data = analytics_service.summary(db)
    data["today_appointments"] = [AppointmentOut.model_validate(a).model_dump(mode="json") for a in data["today_appointments"]]
    return data


@router.get("/analytics")
def analytics(days: int = Query(14, ge=7, le=90), db: Session = Depends(get_db)):
    return analytics_service.analytics(db, days)
