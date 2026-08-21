"""
FastAPI application — main entry point.
Configures CORS, middleware, startup/shutdown hooks, and error handling.
Never exposes stack traces, SQL errors, or internal details in production.
"""
import logging
from contextlib import asynccontextmanager

import json
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.database import init_engine, dispose_engine
from app.api.v1.router import router as v1_router
from app.security.middleware import (
    SecurityHeadersMiddleware,
    RequestSizeLimitMiddleware,
    limiter,
)
from app.i18n import get_message

# Structured logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — startup and shutdown."""
    settings = get_settings()
    init_engine(settings.DATABASE_URL, echo=settings.DEBUG)
    logger.info("Application started")

    # Create initial admin if configured
    await _create_initial_admin(settings)

    yield

    await dispose_engine()
    logger.info("Application shut down")


async def _create_initial_admin(settings):
    """Create default admin user on first run if configured."""
    if not settings.ADMIN_PASSWORD or settings.ADMIN_PASSWORD == "CHANGE_ME_USE_STRONG_PASSWORD":
        logger.warning("No admin password configured — skipping initial admin creation")
        return

    try:
        from app.database import _async_session_factory
        from app.repositories.user_repository import UserRepository
        from app.auth.password import hash_password
        from app.models.user import User

        if _async_session_factory is None:
            return

        async with _async_session_factory() as session:
            if not settings.ADMIN_EMAIL:
                return
            repo = UserRepository(session)
            existing = await repo.get_by_email(settings.ADMIN_EMAIL)
            if not existing:
                admin = User(
                    email=settings.ADMIN_EMAIL,
                    username="admin",
                    password_hash=hash_password(settings.ADMIN_PASSWORD),
                    full_name=settings.ADMIN_FULLNAME,
                    role="ADMIN",
                )
                session.add(admin)
                await session.commit()
                logger.info("Initial admin user created")
            else:
                logger.info("Admin user already exists")
    except Exception as e:
        logger.error("Failed to create initial admin: %s", str(e))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="ATELIER BERLIN LOCATION CAR API",
        description="Professional car rental management system with offline-first sync",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    # Security middleware
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_size_mb=settings.MAX_UPLOAD_SIZE_MB)

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Global exception handler — never expose internal details
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": get_message("server.error")},
        )

    # Static files for uploads
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path
    upload_dir = Path("uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "vehicles").mkdir(parents=True, exist_ok=True)
    app.mount("/static/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")

    # Include API routes
    app.include_router(v1_router)

    # Root WebSocket endpoint for direct ws://host:8000/ws
    from app.services.event_broadcaster import broadcaster
    @app.websocket("/ws")
    async def root_websocket_endpoint(websocket: WebSocket):
        await broadcaster.connect_socket(websocket)
        try:
            recent = broadcaster.get_recent_events(limit=10)
            await websocket.send_text(json.dumps({
                "event_type": "CONNECTED",
                "message": "Connected to Realtime Events Stream",
                "recent_events": recent
            }))
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "PING":
                        await websocket.send_text(json.dumps({"type": "PONG"}))
                except Exception:
                    pass
        except WebSocketDisconnect:
            await broadcaster.disconnect_socket(websocket)
        except Exception as e:
            logger.warning("WebSocket exception: %s", e)
            await broadcaster.disconnect_socket(websocket)

    # Health check
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": "1.0.0"}

    return app


app = create_app()
