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

    # ── Database connection pool ───────────────────────────────────────────
    # Sized for the PRODUCTION database VM, not for raw throughput. The hard
    # upper bound on server-side PostgreSQL connections opened by this API is:
    #
    #     (DB_POOL_SIZE + DB_MAX_OVERFLOW) * <number of uvicorn worker processes>
    #
    # The container runs a SINGLE uvicorn worker (docker/Dockerfile.backend has
    # no --workers flag), so the real ceiling is DB_POOL_SIZE + DB_MAX_OVERFLOW.
    # That ceiling must stay well below the database's own `max_connections`
    # minus the slots reserved for repmgr / the monitor / `alembic upgrade` /
    # a manual psql session. The defaults below (10 max) are safe for a small
    # Fly `postgres-flex` node (256 MB–1 GB). An over-large pool on a small DB
    # is an OOM / "too many connections" hazard, which is exactly how the
    # production database fell over. Override per-environment via env vars.
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50,
                              description="Persistent connections kept open per worker")
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50,
                                 description="Extra burst connections per worker beyond the pool")
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1, le=120,
                                 description="Seconds a request waits for a free connection before failing")
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60,
                                 description="Recycle a connection older than this many seconds")
    DB_POOL_PRE_PING: bool = Field(default=True,
                                   description="Validate a pooled connection before handing it out")
    # If the configured pool could ever exceed this, engine initialisation
    # fails loudly instead of letting the API silently exhaust the database.
    DB_MAX_CONNECTIONS_HARD_CAP: int = Field(default=40, ge=2, le=500,
                                             description="Refuse to start if pool_size+max_overflow exceeds this")

    @property
    def db_max_connections_per_worker(self) -> int:
        """Hard upper bound on concurrent server-side connections one worker can open."""
        return self.DB_POOL_SIZE + self.DB_MAX_OVERFLOW

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
        "extra": "ignore",
    }


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


_settings: Settings | None = None
