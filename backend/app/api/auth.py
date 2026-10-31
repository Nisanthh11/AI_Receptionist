from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, ProfileUpdate, RegisterRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        is_active=u.is_active,
        role=u.role.name,
        phone=u.phone,
        created_at=u.created_at,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user, token, expires = auth_service.authenticate(db, payload.email, payload.password)
    return TokenResponse(access_token=token, expires_in=expires, role=user.role.name, full_name=user.full_name, user_id=user.id)


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user, token, expires = auth_service.register_user(
        db, email=payload.email, full_name=payload.full_name, password=payload.password, phone=payload.phone
    )
    return TokenResponse(access_token=token, expires_in=expires, role=user.role.name, full_name=user.full_name, user_id=user.id)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


@router.patch("/me", response_model=UserOut)
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if payload.phone is not None:
        current_user.phone = payload.phone
    db.commit()
    db.refresh(current_user)
    return _user_out(current_user)
