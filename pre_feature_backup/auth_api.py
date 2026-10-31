from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, is_active=u.is_active, role=u.role.name)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user, token, expires = auth_service.authenticate(db, payload.email, payload.password)
    return TokenResponse(access_token=token, expires_in=expires, role=user.role.name, full_name=user.full_name, user_id=user.id)


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user, token, expires = auth_service.register_user(
        db, email=payload.email, full_name=payload.full_name, password=payload.password
    )
    return TokenResponse(access_token=token, expires_in=expires, role=user.role.name, full_name=user.full_name, user_id=user.id)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
