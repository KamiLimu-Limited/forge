"""Per-cohort points values and session rating questions."""

from fastapi import APIRouter

from forge.api.deps import ActiveUser, DbSession
from forge.api.routes.cohorts import MemberCohort, WritableCohort
from forge.schemas.cohort import (
    PointsConfig,
    PointsConfigRequest,
    RatingQuestion,
    RatingQuestionsRequest,
)
from forge.services import cohort_config as config_service

router = APIRouter(prefix="/cohorts/{cohort_id}", tags=["Cohort Configuration"])


@router.get("/points-config")
async def get_points_config(cohort: MemberCohort) -> PointsConfig:
    """Points for each extra-activity log type, stage points for job and
    scholarship applications, and the per-type logging targets."""
    return config_service.points_config(cohort)


@router.put("/points-config")
async def set_points_config(
    data: PointsConfigRequest, cohort: WritableCohort, user: ActiveUser, db: DbSession
) -> PointsConfig:
    """Set the cohort's point values. Applies to logs submitted or updated from now
    on. **System Admin or Program Lead.**"""
    return await config_service.set_points_config(db, cohort, data, user)


@router.get("/rating-questions")
async def get_rating_questions(cohort: MemberCohort) -> list[RatingQuestion]:
    """The nine session rating questions: 1-3 reaction, 4-6 learning and 7-9
    intended behaviour."""
    return config_service.rating_questions(cohort)


@router.put("/rating-questions")
async def set_rating_questions(
    data: RatingQuestionsRequest,
    cohort: WritableCohort,
    user: ActiveUser,
    db: DbSession,
) -> list[RatingQuestion]:
    """Set the wording of the nine questions, in order. **System Admin or Program
    Lead.**"""
    return await config_service.set_rating_questions(db, cohort, data.questions, user)
