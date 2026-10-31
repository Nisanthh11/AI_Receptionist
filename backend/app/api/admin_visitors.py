from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_staff
from app.models import User
from app.schemas.visitor import StaffVisitCreate, VisitList, VisitorDetail, VisitorList, VisitOut
from app.services import visitor_service as svc

router = APIRouter(prefix="/api/admin", tags=["Admin: visitors"])


@router.get("/visitors", response_model=VisitorList)
def visitors(q: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows, total = svc.list_visitors(db, q=q, page=page, page_size=page_size)
    return VisitorList(items=rows, total=total, page=page, page_size=page_size)


@router.get("/visitors/{visitor_id}", response_model=VisitorDetail)
def visitor_history(visitor_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    visitor, visits, appts = svc.visitor_detail(db, visitor_id)
    return VisitorDetail(visitor=visitor, visits=visits, appointments=appts)


@router.get("/visits", response_model=VisitList)
def visits(status: str | None = None, q: str | None = Query(None, max_length=100), page: int = Query(1, ge=1),
           page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows, total = svc.list_visits(db, status=status, q=q, page=page, page_size=page_size)
    return VisitList(items=rows, total=total, page=page, page_size=page_size)


@router.post("/visits", response_model=VisitOut, status_code=201)
def create_visit(payload: StaffVisitCreate, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return svc.create_visit_by_staff(db, user, full_name=payload.full_name, phone=payload.phone, email=payload.email,
                                     purpose=payload.purpose, staff_id=payload.staff_id,
                                     appointment_id=payload.appointment_id, check_in_now=payload.check_in_now)


@router.post("/visits/{visit_id}/check-in", response_model=VisitOut)
def check_in(visit_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return svc.check_in(db, user, visit_id)


@router.post("/visits/{visit_id}/check-out", response_model=VisitOut)
def check_out(visit_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return svc.check_out(db, user, visit_id)
