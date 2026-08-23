"""
Backend configuration loaded from environment variables.
No secrets are hardcoded — all come from .env or system env.
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(
        ..., description="Async PostgreSQL connection string"
    )
    DATABASE_URL_SYNC: str = Field(
        default="", description="Sync PostgreSQL connection string (for Alembic)"
    )

    # JWT
    JWT_SECRET: str = Field(..., description="JWT signing secret")
    JWT_REFRESH_SECRET: str = Field(..., description="JWT refresh token secret")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)
    JWT_ALGORITHM: str = Field(default="HS256")

    # Security
    CORS_ORIGINS: str = Field(default="")
    RATE_LIMIT: str = Field(default="100/minute")
    MAX_UPLOAD_SIZE_MB: int = Field(default=10)

    # Server
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="info")

    # Default Admin
    ADMIN_EMAIL: str | None = Field(default=None)
    ADMIN_PASSWORD: str | None = Field(default=None)
    ADMIN_FULLNAME: str = Field(default="Administrateur Système")

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.CORS_ORIGINS:
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    from pydantic import model_validator
    @model_validator(mode="after")
    def adjust_database_urls(self):
        # SQLAlchemy 1.4+ deprecated postgres:// in favor of postgresql://
        # For async, we need postgresql+asyncpg://
        if self.DATABASE_URL:
            if "postgres://" in self.DATABASE_URL or "postgresql://" in self.DATABASE_URL:
                self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
                self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
                self.DATABASE_URL = self.DATABASE_URL.replace("?sslmode=disable", "")
            
            if not self.DATABASE_URL_SYNC:
                self.DATABASE_URL_SYNC = self.DATABASE_URL.replace("+asyncpg", "")
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


_settings: Settings | None = None
