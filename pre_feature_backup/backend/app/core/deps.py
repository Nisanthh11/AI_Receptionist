import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models.user import ROLE_ADMIN, ROLE_RECEPTIONIST, User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise AppError(401, "Authentication required.")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AppError(401, "Invalid or expired token. Please sign in again.")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(401, "Account not found or disabled.")
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role.name not in roles:
            raise AppError(403, "You do not have permission to perform this action.")
        return user

    return checker


# Staff accounts (admin or receptionist) vs administrators only.
require_staff = require_roles(ROLE_ADMIN, ROLE_RECEPTIONIST)
require_admin = require_roles(ROLE_ADMIN)
