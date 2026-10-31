from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

MAX_PASSWORD_BYTES = 72  # bcrypt limit

# Hash used to equalise timing when the e-mail does not exist.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (max 72 bytes).")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        ok = bcrypt.checkpw(password.encode("utf-8")[:MAX_PASSWORD_BYTES], (hashed or _DUMMY_HASH).encode())
    except ValueError:
        return False
    return ok and hashed is not None


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    s = get_settings()
    expires = timedelta(minutes=s.access_token_expire_minutes)
    payload = {"sub": str(user_id), "role": role, "exp": datetime.now(timezone.utc) + expires}
    return jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm), int(expires.total_seconds())


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
