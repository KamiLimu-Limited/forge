"""Application configuration using pydantic-settings."""

from functools import lru_cache
from typing import Annotated

from pydantic import AnyHttpUrl, BeforeValidator, Field
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def parse_csv_list(v: str | list[str]) -> list[str]:
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Forge"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://forge:forge@localhost:5433/forge"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Security
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    INVITATION_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 24
    # Fernet key for encrypting private notes at rest; derived from SECRET_KEY when empty.
    DATA_ENCRYPTION_KEY: str = ""

    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True

    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_TIMES: int = 10
    RATE_LIMIT_AUTH_SECONDS: int = 60

    CORS_ORIGINS: Annotated[list[str], NoDecode, BeforeValidator(parse_csv_list)] = [
        "http://localhost:3000"
    ]

    # Email (Resend)
    RESEND_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "noreply@kamilimu.org"
    EMAIL_FROM_NAME: str = "KamiLimu Forge"
    FRONTEND_URL: AnyHttpUrl = AnyHttpUrl("http://localhost:3000")

    # Background scheduler
    SCHEDULER_ENABLED: bool = False
    SCHEDULER_INTERVAL_SECONDS: int = 300
    NOTIFICATION_MAX_ATTEMPTS: int = 5
    WINDOW_CLOSING_REMINDER_HOURS: int = 12
    TASK_DEADLINE_REMINDER_HOURS: int = 24

    # Programme rules
    DEFAULT_GRADUATION_THRESHOLD: int = 80
    GRADUATION_WARNING_MARGIN: int = 5
    DEFAULT_SESSION_POINTS: int = 10
    THURSDAY_WINDOW_HOURS: int = 24
    SATURDAY_WINDOW_HOURS: int = 48
    PEER_MENTORSHIP_WINDOW_HOURS: int = 72
    OVERRIDE_EXTENSION_HOURS: int = 48
    EXTRA_ACTIVITY_DEFAULT_POINTS: dict[str, int] = Field(
        default_factory=lambda: {
            "academic": 5,
            "event": 5,
            "opportunity": 5,
            "consultation": 5,
        }
    )
    DEFAULT_SKILL_NAMES: Annotated[
        list[str], NoDecode, BeforeValidator(parse_csv_list)
    ] = [
        "communication",
        "leadership",
        "technical",
        "teamwork",
        "problem_solving",
        "professionalism",
    ]

    @property
    def frontend_base_url(self) -> str:
        return str(self.FRONTEND_URL).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
