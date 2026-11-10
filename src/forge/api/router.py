"""Aggregate API router."""

from fastapi import APIRouter

from forge.api.routes import (
    admin,
    analytics,
    attendance,
    audit,
    auth,
    cohort_config,
    cohorts,
    consultants,
    dashboards,
    extra_activities,
    facilitator,
    graduation,
    ict_tracks,
    leaderboard,
    mentees,
    notifications,
    objectives,
    sessions,
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

# Competitions and mentor notes (routes.competitions, routes.mentor_notes) are
# Phase 2 features and stay unmounted until then.
for router in (
    auth.router,
    users.router,
    users.alumni_router,
    admin.router,
    audit.router,
    cohorts.router,
    cohort_config.router,
    ict_tracks.router,
    graduation.router,
    sessions.router,
    attendance.router,
    mentees.router,
    objectives.router,
    extra_activities.router,
    consultants.router,
    leaderboard.router,
    facilitator.router,
    dashboards.router,
    dashboards.feedback_router,
    notifications.router,
    analytics.router,
    analytics.cross_router,
    analytics.exports_router,
):
    api_router.include_router(router)
