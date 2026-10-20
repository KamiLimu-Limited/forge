"""Aggregate API router."""

from fastapi import APIRouter

from forge.api.routes import (
    admin,
    analytics,
    attendance,
    audit,
    auth,
    cohorts,
    competitions,
    dashboards,
    extra_activities,
    mentees,
    notifications,
    peer_mentorship,
    sessions,
    skills,
    users,
)
from forge.schemas.common import ErrorResponse

api_router = APIRouter(
    responses={
        401: {
            "model": ErrorResponse,
            "description": "Missing, invalid or revoked token",
        },
        403: {"model": ErrorResponse, "description": "Insufficient permissions"},
        404: {"model": ErrorResponse, "description": "Resource not found"},
        422: {
            "model": ErrorResponse,
            "description": "Validation error or business-rule violation",
        },
    }
)

for router in (
    auth.router,
    users.router,
    admin.router,
    audit.router,
    cohorts.router,
    sessions.router,
    attendance.router,
    mentees.router,
    extra_activities.router,
    peer_mentorship.router,
    skills.router,
    competitions.router,
    dashboards.router,
    dashboards.feedback_router,
    notifications.router,
    analytics.router,
    analytics.cross_router,
    analytics.exports_router,
):
    api_router.include_router(router)
