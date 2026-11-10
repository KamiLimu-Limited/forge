"""ICT tracks offered in a cohort and mentees' track selection."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.core.exceptions import BusinessRuleViolation, NotFound
from forge.models import (
    Cohort,
    CohortEnrollment,
    CohortIctTrack,
    User,
    UserRole,
)
from forge.schemas.cohort import (
    IctTracksRequest,
    TrackCount,
    TrackSelectionResponse,
    TrackSelectionSummary,
    TrackSelectionWindow,
    TrackSelectionWindowRequest,
)
from forge.schemas.user import UserSummary
from forge.services.access import get_enrollment
from forge.services.audit import log_action


async def set_tracks(
    db: AsyncSession, cohort: Cohort, data: IctTracksRequest, actor: User
) -> list[CohortIctTrack]:
    """Replace the tracks offered; each lead must be an ICT peer mentor in the cohort."""
    ict_mentors = {
        e.user_id: e
        for e in await db.scalars(
            select(CohortEnrollment).where(
                CohortEnrollment.cohort_id == cohort.id,
                CohortEnrollment.role == UserRole.PEER_MENTOR_ICT,
            )
        )
    }
    for entry in data.tracks:
        if entry.lead_mentor_id and entry.lead_mentor_id not in ict_mentors:
            raise BusinessRuleViolation(
                f"Lead mentor of '{entry.name}' must be an ICT peer mentor in this cohort"
            )

    requested = {entry.name: entry for entry in data.tracks}
    removed = [t for t in cohort.ict_tracks if t.name not in requested]
    if removed:
        selected = await db.scalar(
            select(func.count()).where(
                CohortEnrollment.cohort_id == cohort.id,
                CohortEnrollment.role == UserRole.MENTEE,
                CohortEnrollment.ict_track.in_([t.name for t in removed]),
            )
        )
        if selected:
            raise BusinessRuleViolation(
                "Cannot remove a track that mentees have already selected"
            )

    existing = {t.name: t for t in cohort.ict_tracks}
    for old in removed:
        await db.delete(old)
    for name, entry in requested.items():
        track = existing.get(name)
        if track is None:
            track = CohortIctTrack(cohort_id=cohort.id, name=name)
            db.add(track)
        track.description = entry.description
        track.lead_mentor_id = entry.lead_mentor_id

    led = {e.lead_mentor_id: name for name, e in requested.items() if e.lead_mentor_id}
    for user_id, enrollment in ict_mentors.items():
        enrollment.ict_track = led.get(user_id)

    log_action(
        db,
        "set_ict_tracks",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
        tracks=sorted(requested),
    )
    await db.commit()
    await db.refresh(cohort, ["ict_tracks"])
    return cohort.ict_tracks


def window(cohort: Cohort, now: datetime | None = None) -> TrackSelectionWindow:
    now = now or datetime.now(UTC)
    opens, closes = cohort.track_selection_opens_at, cohort.track_selection_closes_at
    return TrackSelectionWindow(
        opens_at=opens,
        closes_at=closes,
        is_open=opens is not None and closes is not None and opens <= now < closes,
    )


async def set_window(
    db: AsyncSession,
    cohort: Cohort,
    data: TrackSelectionWindowRequest,
    actor: User,
) -> TrackSelectionWindow:
    cohort.track_selection_opens_at = data.opens_at
    cohort.track_selection_closes_at = data.closes_at
    log_action(
        db,
        "set_track_selection_window",
        user_id=actor.id,
        resource_type="cohort",
        resource_id=cohort.id,
        opens_at=data.opens_at.isoformat() if data.opens_at else None,
        closes_at=data.closes_at.isoformat() if data.closes_at else None,
    )
    await db.commit()
    return window(cohort)


async def _mentee_enrollment(
    db: AsyncSession, cohort: Cohort, mentee_id: uuid.UUID
) -> CohortEnrollment:
    enrollment = await get_enrollment(db, mentee_id, cohort.id)
    if enrollment is None:
        raise NotFound("Mentee is not enrolled in this cohort")
    return enrollment


def _ensure_offered(cohort: Cohort, name: str) -> None:
    if name not in cohort.ict_track_names:
        raise BusinessRuleViolation(f"ICT track '{name}' is not offered in this cohort")


async def selection(
    db: AsyncSession, cohort: Cohort, user: User
) -> TrackSelectionResponse:
    enrollment = await _mentee_enrollment(db, cohort, user.id)
    return TrackSelectionResponse(window=window(cohort), ict_track=enrollment.ict_track)


async def choose(
    db: AsyncSession, cohort: Cohort, user: User, name: str
) -> TrackSelectionResponse:
    enrollment = await _mentee_enrollment(db, cohort, user.id)
    if not window(cohort).is_open:
        raise BusinessRuleViolation("Track selection is closed")
    _ensure_offered(cohort, name)
    enrollment.ict_track = name
    log_action(
        db,
        "select_ict_track",
        user_id=user.id,
        resource_type="cohort_enrollment",
        resource_id=enrollment.id,
        ict_track=name,
    )
    await db.commit()
    return TrackSelectionResponse(window=window(cohort), ict_track=name)


async def override(
    db: AsyncSession,
    cohort: Cohort,
    mentee_id: uuid.UUID,
    name: str,
    reason: str | None,
    actor: User,
) -> TrackSelectionResponse:
    """Set a mentee's track on their behalf, whether or not the window is open."""
    enrollment = await _mentee_enrollment(db, cohort, mentee_id)
    _ensure_offered(cohort, name)
    previous = enrollment.ict_track
    enrollment.ict_track = name
    log_action(
        db,
        "override_ict_track",
        user_id=actor.id,
        resource_type="cohort_enrollment",
        resource_id=enrollment.id,
        mentee_id=str(mentee_id),
        old=previous,
        new=name,
        reason=reason,
    )
    await db.commit()
    return TrackSelectionResponse(window=window(cohort), ict_track=name)


async def summary(db: AsyncSession, cohort: Cohort) -> TrackSelectionSummary:
    mentees = list(
        await db.scalars(
            select(CohortEnrollment).where(
                CohortEnrollment.cohort_id == cohort.id,
                CohortEnrollment.role == UserRole.MENTEE,
            )
        )
    )
    counts = dict.fromkeys(cohort.ict_track_names, 0)
    for enrollment in mentees:
        if enrollment.ict_track is not None:
            counts[enrollment.ict_track] = counts.get(enrollment.ict_track, 0) + 1
    not_selected = sorted(
        (e.user for e in mentees if e.ict_track is None),
        key=lambda u: (u.last_name, u.first_name),
    )
    return TrackSelectionSummary(
        window=window(cohort),
        counts=[TrackCount(ict_track=name, mentees=n) for name, n in counts.items()],
        not_selected=[UserSummary.model_validate(u) for u in not_selected],
    )
