"""Cohort and enrollment endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from forge.api.deps import ActiveUser, DbSession, ManagerUser
from forge.models import Cohort, CohortEnrollment
from forge.schemas.cohort import (
    BulkEnrollmentRequest,
    BulkEnrollmentResult,
    CohortCreateRequest,
    CohortDetailResponse,
    CohortFilters,
    CohortResponse,
    CohortUpdateRequest,
    EnrollmentFilters,
    EnrollmentRequest,
    EnrollmentResponse,
    EnrollmentUpdateRequest,
)
from forge.schemas.common import Page
from forge.schemas.points import GraduationReportResponse
from forge.schemas.session import CalendarMonth
from forge.services import cohorts as cohort_service
from forge.services import points as points_service
from forge.services import sessions as session_service
from forge.services.access import (
    ensure_cohort_manager,
    ensure_cohort_member,
    ensure_cohort_staff,
    ensure_cohort_writable,
)

router = APIRouter(prefix="/cohorts", tags=["Cohorts"])


async def visible_cohort(cohort_id: UUID, user: ActiveUser, db: DbSession) -> Cohort:
    return await cohort_service.get_visible_cohort(db, user, cohort_id)


VisibleCohort = Annotated[Cohort, Depends(visible_cohort)]


async def member_cohort(
    cohort: VisibleCohort, user: ActiveUser, db: DbSession
) -> Cohort:
    await ensure_cohort_member(db, user, cohort.id)
    return cohort


MemberCohort = Annotated[Cohort, Depends(member_cohort)]


async def managed_cohort(cohort: VisibleCohort, user: ActiveUser) -> Cohort:
    ensure_cohort_manager(user, cohort.id)
    return cohort


ManagedCohort = Annotated[Cohort, Depends(managed_cohort)]
"""A cohort the caller manages: System Admin or Program Lead."""


async def writable_cohort(cohort: ManagedCohort) -> Cohort:
    ensure_cohort_writable(cohort)
    return cohort


WritableCohort = Annotated[Cohort, Depends(writable_cohort)]
"""A managed cohort that is not completed or archived."""


async def staffed_cohort(cohort: VisibleCohort, user: ActiveUser) -> Cohort:
    ensure_cohort_staff(user, cohort.id)
    return cohort


StaffedCohort = Annotated[Cohort, Depends(staffed_cohort)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CohortResponse)
async def create_cohort(
    data: CohortCreateRequest, user: ManagerUser, db: DbSession
) -> Cohort:
    """Create a cohort. **System Admin or Program Lead.**

    KamiLimu month boundaries, when omitted, fall back to calendar months from
    `start_date`. The points config and rating questions start from the defaults.
    """
    return await cohort_service.create_cohort(db, data, user)


@router.get("")
async def list_cohorts(
    filters: Annotated[CohortFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[CohortResponse]:
    """List cohorts. Draft cohorts are visible to admins and committee only."""
    cohorts, total = await cohort_service.list_cohorts(db, user, filters)
    return Page[CohortResponse].build(cohorts, total, filters)


@router.get("/{cohort_id}")
async def get_cohort(cohort: VisibleCohort, db: DbSession) -> CohortDetailResponse:
    """Cohort details: configuration, ICT tracks with their lead mentors, the
    track selection window and enrollment counts per role."""
    counts = await cohort_service.enrollment_counts(db, cohort.id)
    return CohortDetailResponse.model_validate(
        {
            **CohortResponse.model_validate(cohort).model_dump(),
            "ict_tracks": cohort.ict_tracks,
            "enrollment_counts": counts,
        }
    )


@router.patch("/{cohort_id}", response_model=CohortResponse)
async def update_cohort(
    data: CohortUpdateRequest, cohort: WritableCohort, user: ActiveUser, db: DbSession
) -> Cohort:
    """Update cohort settings. **System Admin or Program Lead.**"""
    return await cohort_service.update_cohort(db, cohort, data, user)


@router.post(
    "/{cohort_id}/enrollments",
    status_code=status.HTTP_201_CREATED,
    response_model=EnrollmentResponse,
)
async def enroll_user(
    data: EnrollmentRequest, cohort: WritableCohort, user: ActiveUser, db: DbSession
) -> CohortEnrollment:
    """Enroll a user in the cohort and grant the matching cohort-scoped role.

    No peer mentor or ICT track is needed: 1:1 peer mentors are assigned about a
    month in, and mentees pick their ICT track during track selection.
    """
    return await cohort_service.enroll(db, cohort, data, user)


@router.post("/{cohort_id}/enrollments/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_enroll(
    data: BulkEnrollmentRequest,
    cohort: WritableCohort,
    user: ActiveUser,
    db: DbSession,
) -> list[BulkEnrollmentResult]:
    """Enroll many users; failures are reported per user without aborting the batch."""
    return await cohort_service.bulk_enroll(db, cohort, data.enrollments, user)


@router.get("/{cohort_id}/enrollments")
async def list_enrollments(
    filters: Annotated[EnrollmentFilters, Query()],
    cohort: VisibleCohort,
    user: ActiveUser,
    db: DbSession,
) -> Page[EnrollmentResponse]:
    """Committee and admins see every enrollment; others see their own and, for
    peer mentors, their group's."""
    enrollments, total = await cohort_service.list_enrollments(
        db, user, cohort, filters
    )
    return Page[EnrollmentResponse].build(enrollments, total, filters)


@router.patch(
    "/{cohort_id}/enrollments/{enrollment_id}", response_model=EnrollmentResponse
)
async def update_enrollment(
    enrollment_id: UUID,
    data: EnrollmentUpdateRequest,
    cohort: WritableCohort,
    user: ActiveUser,
    db: DbSession,
) -> CohortEnrollment:
    """Assign or change a mentee's 1:1 peer mentor, allowed from about a month
    into the cohort. ICT tracks change only through track selection."""
    enrollment = await cohort_service.get_enrollment_or_404(db, cohort, enrollment_id)
    return await cohort_service.update_enrollment(db, cohort, enrollment, data, user)


@router.delete(
    "/{cohort_id}/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_enrollment(
    enrollment_id: UUID, cohort: WritableCohort, user: ActiveUser, db: DbSession
) -> None:
    """Remove a user from the cohort and revoke the matching cohort-scoped role."""
    enrollment = await cohort_service.get_enrollment_or_404(db, cohort, enrollment_id)
    await cohort_service.remove_enrollment(db, enrollment, user)


@router.get("/{cohort_id}/calendar")
async def get_calendar(
    cohort: MemberCohort, user: ActiveUser, db: DbSession
) -> list[CalendarMonth]:
    """The cohort's full session calendar grouped by KamiLimu month."""
    return await session_service.cohort_calendar(db, user, cohort)


@router.get("/{cohort_id}/calendar/{month}")
async def get_calendar_month(
    month: Annotated[int, Path(ge=1, le=24)],
    cohort: MemberCohort,
    user: ActiveUser,
    db: DbSession,
) -> list[CalendarMonth]:
    """Sessions for a single KamiLimu month."""
    return await session_service.cohort_calendar(db, user, cohort, month)


@router.get("/{cohort_id}/graduation-report")
async def graduation_report(
    cohort: StaffedCohort, db: DbSession
) -> GraduationReportResponse:
    """Every mentee's points and rates, ranked on the core rate, lowest first.
    Graduation status is set once the cohort has graduated."""
    return await points_service.graduation_report(db, cohort)
