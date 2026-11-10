"""Per-cohort points values and session rating questions."""

from sqlalchemy.ext.asyncio import AsyncSession

from forge.models import RATING_QUESTION_COUNT, Cohort, User
from forge.models.cohort import RatingGroup
from forge.schemas.cohort import PointsConfig, RatingQuestion
from forge.services.audit import log_action

QUESTIONS_PER_GROUP = RATING_QUESTION_COUNT // len(RatingGroup)


def group_for(number: int) -> RatingGroup:
    return list(RatingGroup)[(number - 1) // QUESTIONS_PER_GROUP]


def points_config(cohort: Cohort) -> PointsConfig:
    return PointsConfig.model_validate(cohort.points_config)


async def set_points_config(
    db: AsyncSession, cohort: Cohort, data: PointsConfig, actor: User
) -> PointsConfig:
    cohort.points_config = data.model_dump(mode="json")
    log_action(
        db,
        "update_points_config",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()
    return points_config(cohort)


def rating_questions(cohort: Cohort) -> list[RatingQuestion]:
    return [
        RatingQuestion(number=number, group=group_for(number), text=q["text"])
        for number, q in enumerate(cohort.rating_questions, start=1)
    ]


async def set_rating_questions(
    db: AsyncSession, cohort: Cohort, questions: list[str], actor: User
) -> list[RatingQuestion]:
    cohort.rating_questions = [
        {"group": group_for(number), "text": text}
        for number, text in enumerate(questions, start=1)
    ]
    log_action(
        db,
        "update_rating_questions",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
    )
    await db.commit()
    return rating_questions(cohort)
