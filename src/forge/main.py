"""FastAPI application entry point."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException

from forge.api.router import api_router
from forge.core.config import settings
from forge.core.exceptions import ForgeError
from forge.core.logging import configure_logging
from forge.db.session import async_session_factory, engine
from forge.services.scheduler import Scheduler

logger = logging.getLogger("forge")

DESCRIPTION = """
Backend API for the **KamiLimu Forge** mentorship programme: cohorts, sessions,
attendance, points and graduation tracking, extra activities, dashboards,
leaderboards, notifications and analytics.

## Authentication

1. An admin invites a user (`POST /auth/invite`, `/auth/bulk-invite` or `/auth/bulk-invite/csv`).
2. The user activates their account with the emailed token (`POST /auth/activate`).
3. `POST /auth/login` returns an access token (1h) and a refresh token (7d).
4. Send `Authorization: Bearer <access_token>` on every request
   (use the **Authorize** button above).
5. `POST /auth/refresh` rotates the pair; `POST /auth/logout` revokes it.

## Conventions

* **Errors** share one shape: `{"success": false, "error": "<code>", "detail": ...}`.
* **Pagination**: list endpoints take `page` (from 1) and `page_size` (max 100) and
  return `{items, total, page, page_size, total_pages}`.
* **Rate limiting**: login, activation and reset requests are limited per client IP;
  over the limit you get `429`.
* **Access control**: users see their own records, peer mentors their group,
  committee members their cohort, and admins everything.

## Roles

`admin`, `committee`, `mentee`, `peer_mentor_1:1`, `peer_mentor_ict`,
`professional_mentor`, `partner`, `alumni`.
"""

TAGS_METADATA = [
    {
        "name": "Authentication",
        "description": "Invitations (single, bulk JSON, CSV upload), activation, login, token refresh, logout and password reset.",
    },
    {"name": "Users", "description": "The authenticated user's own profile."},
    {
        "name": "Admin",
        "description": "User, role, invitation and audit-log administration. **Admin only.**",
    },
    {"name": "Audit", "description": "Audit trail of the caller's own actions."},
    {
        "name": "Cohorts",
        "description": "Cohorts, enrollments, calendars and the graduation report.",
    },
    {
        "name": "Sessions",
        "description": "Session scheduling, publishing, rescheduling, cancellation, mentors and resources.",
    },
    {
        "name": "Attendance",
        "description": "Attendance submission within windows, override requests and committee/peer-mentor views.",
    },
    {
        "name": "Mentee Progress",
        "description": "Points, attendance rates, graduation status, skill progress and competition status for a mentee.",
    },
    {
        "name": "Extra Activities",
        "description": "Academic work, external events, opportunities and consultations, with committee validation.",
    },
    {
        "name": "Peer Mentorship",
        "description": "Private peer-mentor notes, ICT progress notes and group tasks.",
    },
    {
        "name": "Skills",
        "description": "Early, mid and late-programme skill self-ratings.",
    },
    {
        "name": "Leaderboard & Competitions",
        "description": "Six-dimension leaderboard, competitions, rounds and entries.",
    },
    {
        "name": "Dashboards",
        "description": "Pre-aggregated data for mentee, peer mentor, ICT mentor, professional mentor and committee dashboards.",
    },
    {
        "name": "Notifications",
        "description": "In-app notifications (also emailed) and admin broadcasts.",
    },
    {
        "name": "Analytics",
        "description": "Attendance trends, track performance, session quality, health trajectory, engagement and cross-cohort comparison.",
    },
    {
        "name": "Exports",
        "description": "CSV downloads for leaderboards, attendance and full cohort reports.",
    },
    {"name": "Health", "description": "Liveness and readiness checks."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    scheduler = Scheduler()
    if settings.SCHEDULER_ENABLED:
        scheduler.start()
    yield
    await scheduler.stop()
    await engine.dispose()


def error_response(
    status_code: int,
    error: str,
    detail: object,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder({"success": False, "error": error, "detail": detail}),
        headers=headers,
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        summary="KamiLimu Learning System API",
        description=DESCRIPTION,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        openapi_tags=TAGS_METADATA,
        contact={"name": "KamiLimu Support", "email": "support@kamilimu.org"},
        license_info={"name": "Proprietary"},
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s %s %.1fms rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response

    @app.exception_handler(ForgeError)
    async def forge_error_handler(request: Request, exc: ForgeError) -> JSONResponse:
        return error_response(exc.status_code, exc.error, exc.detail, exc.headers)

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        error = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        return error_response(exc.status_code, error, exc.detail, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", exc.errors()
        )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe; does not touch the database."""
        return {"status": "healthy"}

    @app.get("/health/ready", tags=["Health"])
    async def readiness_check() -> dict[str, str]:
        """Readiness probe; verifies database connectivity."""
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/", tags=["Health"], include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "message": "KamiLimu Learning System API",
            "docs": f"{settings.API_V1_PREFIX}/docs",
            "version": settings.VERSION,
        }

    return app


app = create_app()
