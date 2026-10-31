"""Departments, staff, availability, FAQs, organisation info and user accounts.
Reads are open to any signed-in staff account; writes are administrator-only."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import require_admin, require_staff
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import FAQ, Department, OrganizationInfo, Staff, StaffAvailability, User
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.schemas.directory import (AvailabilitySet, DepartmentIn, DepartmentOut, FAQIn, FAQOut, OrgInfoUpdate, StaffIn, StaffOut)
from app.services import auth_service

router = APIRouter(prefix="/api/admin", tags=["Admin: directory & content"])

ORG_KEYS = {"organization_name", "working_hours", "address", "contact_phone", "contact_email", "welcome_message"}


def _commit(db: Session, conflict_msg: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, conflict_msg)


# ---- departments ----
@router.get("/departments", response_model=list[DepartmentOut], dependencies=[Depends(require_staff)])
def list_departments(db: Session = Depends(get_db)):
    return db.execute(select(Department).order_by(Department.name)).scalars().all()


@router.post("/departments", response_model=DepartmentOut, status_code=201, dependencies=[Depends(require_admin)])
def create_department(payload: DepartmentIn, db: Session = Depends(get_db)):
    dept = Department(**payload.model_dump())
    db.add(dept)
    _commit(db, "A department with this name already exists.")
    return dept


@router.put("/departments/{dept_id}", response_model=DepartmentOut, dependencies=[Depends(require_admin)])
def update_department(dept_id: int, payload: DepartmentIn, db: Session = Depends(get_db)):
    dept = db.get(Department, dept_id)
    if dept is None:
        raise AppError(404, "Department not found.")
    for k, v in payload.model_dump().items():
        setattr(dept, k, v)
    _commit(db, "A department with this name already exists.")
    return dept


@router.delete("/departments/{dept_id}", response_model=DepartmentOut, dependencies=[Depends(require_admin)])
def deactivate_department(dept_id: int, db: Session = Depends(get_db)):
    """Soft delete: history (appointments, visits) must keep pointing at the department."""
    dept = db.get(Department, dept_id)
    if dept is None:
        raise AppError(404, "Department not found.")
    dept.is_active = False
    db.commit()
    return dept


# ---- staff ----
@router.get("/staff", response_model=list[StaffOut], dependencies=[Depends(require_staff)])
def list_staff(department_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(Staff).options(selectinload(Staff.availability)).order_by(Staff.full_name)
    if department_id:
        stmt = stmt.where(Staff.department_id == department_id)
    return db.execute(stmt).scalars().all()


def _check_department(db: Session, department_id: int) -> None:
    if db.get(Department, department_id) is None:
        raise AppError(404, "Department not found.")


@router.post("/staff", response_model=StaffOut, status_code=201, dependencies=[Depends(require_admin)])
def create_staff(payload: StaffIn, db: Session = Depends(get_db)):
    _check_department(db, payload.department_id)
    staff = Staff(**payload.model_dump())
    db.add(staff)
    db.commit()
    return staff


@router.put("/staff/{staff_id}", response_model=StaffOut, dependencies=[Depends(require_admin)])
def update_staff(staff_id: int, payload: StaffIn, db: Session = Depends(get_db)):
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise AppError(404, "Staff member not found.")
    _check_department(db, payload.department_id)
    for k, v in payload.model_dump().items():
        setattr(staff, k, v)
    db.commit()
    return staff


@router.delete("/staff/{staff_id}", response_model=StaffOut, dependencies=[Depends(require_admin)])
def deactivate_staff(staff_id: int, db: Session = Depends(get_db)):
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise AppError(404, "Staff member not found.")
    staff.is_active = False
    db.commit()
    return staff


@router.put("/staff/{staff_id}/availability", response_model=StaffOut, dependencies=[Depends(require_admin)])
def set_availability(staff_id: int, payload: AvailabilitySet, db: Session = Depends(get_db)):
    """Replaces the weekly availability. Existing appointments are not touched."""
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise AppError(404, "Staff member not found.")
    windows = sorted(payload.windows, key=lambda w: (w.weekday, w.start_time))
    for a, b in zip(windows, windows[1:]):
        if a.weekday == b.weekday and b.start_time < a.end_time:
            raise AppError(422, "Availability windows on the same weekday must not overlap.")
    staff.availability = [StaffAvailability(**w.model_dump()) for w in windows]
    db.commit()
    return staff


# ---- FAQs ----
@router.get("/faqs", response_model=list[FAQOut], dependencies=[Depends(require_staff)])
def list_faqs(db: Session = Depends(get_db)):
    return db.execute(select(FAQ).order_by(FAQ.category, FAQ.id)).scalars().all()


@router.post("/faqs", response_model=FAQOut, status_code=201, dependencies=[Depends(require_admin)])
def create_faq(payload: FAQIn, db: Session = Depends(get_db)):
    faq = FAQ(**payload.model_dump())
    db.add(faq)
    db.commit()
    return faq


@router.put("/faqs/{faq_id}", response_model=FAQOut, dependencies=[Depends(require_admin)])
def update_faq(faq_id: int, payload: FAQIn, db: Session = Depends(get_db)):
    faq = db.get(FAQ, faq_id)
    if faq is None:
        raise AppError(404, "FAQ not found.")
    for k, v in payload.model_dump().items():
        setattr(faq, k, v)
    db.commit()
    return faq


@router.delete("/faqs/{faq_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_faq(faq_id: int, db: Session = Depends(get_db)):
    faq = db.get(FAQ, faq_id)
    if faq is None:
        raise AppError(404, "FAQ not found.")
    db.delete(faq)
    db.commit()


# ---- organisation info ----
@router.get("/organization", dependencies=[Depends(require_staff)])
def get_org(db: Session = Depends(get_db)):
    return {r.key: r.value for r in db.execute(select(OrganizationInfo)).scalars()}


@router.put("/organization", dependencies=[Depends(require_admin)])
def update_org(payload: OrgInfoUpdate, db: Session = Depends(get_db)):
    unknown = set(payload.values) - ORG_KEYS
    if unknown:
        raise AppError(422, f"Unknown organisation fields: {', '.join(sorted(unknown))}.")
    for key, value in payload.values.items():
        row = db.get(OrganizationInfo, key)
        if row:
            row.value = value
        else:
            db.add(OrganizationInfo(key=key, value=value))
    db.commit()
    return {r.key: r.value for r in db.execute(select(OrganizationInfo)).scalars()}


# ---- user accounts (admin only) ----
def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, is_active=u.is_active, role=u.role.name)


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.execute(select(User).order_by(User.email)).unique().scalars()]


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(require_admin)])
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    return _user_out(auth_service.create_user(db, email=payload.email, full_name=payload.full_name,
                                              password=payload.password, role=payload.role))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), me: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "User not found.")
    if user.id == me.id and (payload.is_active is False or (payload.role and payload.role != me.role.name)):
        raise AppError(409, "You cannot disable or demote your own account.")
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.role:
        if payload.role not in auth_service.VALID_ROLES:
            raise AppError(422, "Invalid role.")
        from app.models import Role
        user.role_id = db.execute(select(Role).where(Role.name == payload.role)).scalar_one().id
    if payload.password:
        user.hashed_password = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return _user_out(user)
