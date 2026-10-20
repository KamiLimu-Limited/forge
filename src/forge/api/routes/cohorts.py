"""Cohort and enrollment endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, status

from forge.api.deps import ActiveUser, AdminUser, DbSession
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
    ensure_cohort_member,
    ensure_cohort_staff,
    get_cohort_or_404,
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


async def managed_cohort(cohort_id: UUID, _: AdminUser, db: DbSession) -> Cohort:
    return await get_cohort_or_404(db, cohort_id)


ManagedCohort = Annotated[Cohort, Depends(managed_cohort)]


async def staffed_cohort(cohort: VisibleCohort, user: ActiveUser) -> Cohort:
    ensure_cohort_staff(user, cohort.id)
    return cohort


StaffedCohort = Annotated[Cohort, Depends(staffed_cohort)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CohortResponse)
async def create_cohort(
    data: CohortCreateRequest, admin: AdminUser, db: DbSession
) -> Cohort:
    """Create a cohort. **Admin only.**

    `skill_names` defaults to the six configured programme skills. KamiLimu month
    boundaries, when omitted, fall back to calendar months from `start_date`.
    """
    return await cohort_service.create_cohort(db, data, admin)


@router.get("")
async def list_cohorts(
    filters: Annotated[CohortFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[CohortResponse]:
    """List cohorts. Draft cohorts are visible to admins and committee only."""
    cohorts, total = await cohort_service.list_cohorts(db, user, filters)
    return Page[CohortResponse].build(cohorts, total, filters)


@router.get("/{cohort_id}")
async def get_cohort(cohort: VisibleCohort, db: DbSession) -> CohortDetailResponse:
    """Cohort details with enrollment counts per role."""
    counts = await cohort_service.enrollment_counts(db, cohort.id)
    return CohortDetailResponse.model_validate(
        {
            **CohortResponse.model_validate(cohort).model_dump(),
            "enrollment_counts": counts,
        }
    )


@router.patch("/{cohort_id}", response_model=CohortResponse)
async def update_cohort(
    data: CohortUpdateRequest, cohort: ManagedCohort, admin: AdminUser, db: DbSession
) -> Cohort:
    """Update cohort settings. **Admin only.**"""
    return await cohort_service.update_cohort(db, cohort, data, admin)


@router.delete("/{cohort_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cohort(cohort: ManagedCohort, admin: AdminUser, db: DbSession) -> None:
    """Soft-delete a cohort; its data is retained but hidden from the API."""
    await cohort_service.soft_delete_cohort(db, cohort, admin)


@router.post(
    "/{cohort_id}/enrollments",
    status_code=status.HTTP_201_CREATED,
    response_model=EnrollmentResponse,
)
async def enroll_user(
    data: EnrollmentRequest, cohort: ManagedCohort, admin: AdminUser, db: DbSession
) -> CohortEnrollment:
    """Enroll a user in the cohort and grant the matching cohort-scoped role.

    Mentees can be assigned a 1:1 `peer_mentor_id` (who must be enrolled as
    `peer_mentor_1:1`) and an `ict_track` offered by the cohort.
    """
    return await cohort_service.enroll(db, cohort, data, admin)


@router.post("/{cohort_id}/enrollments/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_enroll(
    data: BulkEnrollmentRequest, cohort: ManagedCohort, admin: AdminUser, db: DbSession
) -> list[BulkEnrollmentResult]:
    """Enroll many users; failures are reported per user without aborting the batch."""
    return await cohort_service.bulk_enroll(db, cohort, data.enrollments, admin)


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
    cohort: ManagedCohort,
    admin: AdminUser,
    db: DbSession,
) -> CohortEnrollment:
    """Change a mentee's peer mentor or ICT track. **Admin only.**"""
    enrollment = await cohort_service.get_enrollment_or_404(db, cohort, enrollment_id)
    return await cohort_service.update_enrollment(db, cohort, enrollment, data, admin)


@router.delete(
    "/{cohort_id}/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_enrollment(
    enrollment_id: UUID, cohort: ManagedCohort, admin: AdminUser, db: DbSession
) -> None:
    """Remove a user from the cohort and revoke the matching cohort-scoped role. **Admin only.**"""
    enrollment = await cohort_service.get_enrollment_or_404(db, cohort, enrollment_id)
    await cohort_service.remove_enrollment(db, enrollment, admin)


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
    """Every mentee's points, rates and graduation status, lowest rate first.
    **Committee of the cohort.**"""
    return await points_service.graduation_report(db, cohort)
