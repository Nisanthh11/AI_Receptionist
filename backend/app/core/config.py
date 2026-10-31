from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables / .env. No secrets live in code."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Receptionist"
    environment: str = "development"

    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    cors_origins: str = "http://localhost:5173"

    timezone: str = "Asia/Kolkata"
    slot_minutes: int = 30
    min_booking_lead_minutes: int = 30
    max_booking_days_ahead: int = 60

    seed_admin_email: str | None = None
    seed_admin_password: str | None = None
    seed_admin_name: str = "System Administrator"
    seed_receptionist_email: str | None = None
    seed_receptionist_password: str | None = None

    # Email notifications (SMTP)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 10

    # SMS notifications
    sms_provider: str = "auto"
    sms_timeout_seconds: int = 5
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    sms_gateway_url: str | None = None
    sms_api_key: str | None = None
    sms_sender_id: str | None = None

    # Automatic Appointment Reminders (Part B)
    reminders_enabled: bool = True
    reminder_poll_interval_seconds: int = 30
    reminder_max_retries: int = 3
    reminder_retry_backoff_seconds: int = 60
    reminder_stale_claim_minutes: int = 5

    # Google Gemini AI Integration (Phase 4)
    gemini_enabled: bool = False
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: int = 10
    gemini_max_retries: int = 2
    gemini_max_output_tokens: int = 800

    @field_validator("jwt_secret_key")
    @classmethod
    def _secret_long_enough(cls, v: str) -> str:
        if len(v) < 32 or v.startswith("REPLACE_WITH"):
            raise ValueError("JWT_SECRET_KEY must be a random string of at least 32 characters")
        return v

    @field_validator("slot_minutes")
    @classmethod
    def _slot_sane(cls, v: int) -> int:
        if v < 5 or v > 240:
            raise ValueError("SLOT_MINUTES must be between 5 and 240")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
