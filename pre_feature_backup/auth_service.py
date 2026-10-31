from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.core.timeutils import now_local
from app.models.user import ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_USER, Role, User

VALID_ROLES = (ROLE_ADMIN, ROLE_RECEPTIONIST, ROLE_USER)


def ensure_roles(db: Session) -> None:
    existing = {r.name for r in db.execute(select(Role)).scalars()}
    descriptions = {
        ROLE_ADMIN: "Full access",
        ROLE_RECEPTIONIST: "Appointments and visitors",
        ROLE_USER: "Registered visitor",
    }
    for name in VALID_ROLES:
        if name not in existing:
            db.add(Role(name=name, description=descriptions[name]))
    db.commit()


def authenticate(db: Session, email: str, password: str) -> tuple[User, str, int]:
    user = db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none()
    ok = verify_password(password, user.hashed_password if user else None)
    if not user or not ok or not user.is_active:
        raise AppError(401, "Incorrect e-mail or password.")
    user.last_login_at = now_local()
    db.commit()
    token, expires = create_access_token(user.id, user.role.name)
    return user, token, expires


def create_user(db: Session, *, email: str, full_name: str, password: str, role: str) -> User:
    if role not in VALID_ROLES:
        raise AppError(422, f"Role must be one of: {', '.join(VALID_ROLES)}.")
    if db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none():
        raise AppError(409, "A user with this e-mail already exists.")
    role_row = db.execute(select(Role).where(Role.name == role)).scalar_one_or_none()
    if role_row is None:
        raise AppError(500, "Roles have not been seeded. Run: python -m app.seed")
    user = User(email=email.lower(), full_name=full_name, hashed_password=hash_password(password), role_id=role_row.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def register_user(db: Session, *, email: str, full_name: str, password: str) -> tuple[User, str, int]:
    ensure_roles(db)
    user = create_user(db, email=email, full_name=full_name, password=password, role=ROLE_USER)
    token, expires = create_access_token(user.id, user.role.name)
    return user, token, expires

