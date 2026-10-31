from pydantic import BaseModel, EmailStr

from app.schemas.common import Name, ORMModel, Password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: Name
    password: Password


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    full_name: str
    user_id: int | None = None


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    role: str


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Name
    password: Password
    role: str


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = None
    password: Password | None = None
