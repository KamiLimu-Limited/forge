"""Attendance engine endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from forge.api.deps import (
    ActiveUser,
    DbSession,
    ManagerUser,
    ParticipantUser,
    PeerMentorUser,
)
from forge.api.routes.cohorts import MemberCohort
from forge.api.routes.sessions import VisibleSession
from forge.models import AttendanceRecord, AttendanceWindow, OverrideRequest
from forge.schemas.attendance import (
    AttendanceFilters,
    AttendanceResponse,
    AttendanceStatusUpdateRequest,
    AttendanceSubmissionRequest,
    AttendanceUpdateRequest,
    AttendanceWindowResponse,
    OverrideFilters,
    OverrideRequestCreate,
    OverrideRequestResponse,
    OverrideReviewRequest,
    WindowStatusResponse,
)
from forge.schemas.common import Page
from forge.services import attendance as attendance_service
from forge.services.access import ensure_cohort_staff, group_mentee_ids

router = APIRouter(tags=["Attendance"])


async def visible_record(
    record_id: UUID, user: ActiveUser, db: DbSession
) -> AttendanceRecord:
    return await attendance_service.get_visible_record(db, user, record_id)


VisibleRecord = Annotated[AttendanceRecord, Depends(visible_record)]


async def override_request(request_id: UUID, db: DbSession) -> OverrideRequest:
    return await attendance_service.get_override_request_or_404(db, request_id)


TargetOverrideRequest = Annotated[OverrideRequest, Depends(override_request)]


@router.post(
    "/attendance",
    status_code=status.HTTP_201_CREATED,
    response_model=AttendanceResponse,
)
async def submit_attendance(
    data: AttendanceSubmissionRequest, user: ParticipantUser, db: DbSession
) -> AttendanceRecord:
    """Record your attendance and feedback for a session. **Mentees and peer
    mentors.**

    Allowed only while the session's attendance window (or your approved
    extension) is open. `present` needs all nine ratings (1-5, in question order)
    and feedback; `absent` takes no ratings. `source` records whether it was
    submitted `on_time` or in a `reopened` window.
    """
    return await attendance_service.submit_attendance(db, user, data)


@router.get("/attendance/me")
async def my_attendance(
    filters: Annotated[AttendanceFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[AttendanceResponse]:
    """Your attendance records, filterable by cohort, KamiLimu month
    (`kami_limu_month`), track and status."""
    records, total = await attendance_service.list_records(
        db, filters, mentee_ids=[user.id]
    )
    return Page[AttendanceResponse].build(records, total, filters)


@router.post(
    "/attendance/override-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=OverrideRequestResponse,
)
async def request_override(
    data: OverrideRequestCreate, user: ParticipantUser, db: DbSession
) -> OverrideRequest:
    """Ask a System Admin to reopen a closed attendance window for you, optionally
    with the new deadline you need."""
    return await attendance_service.create_override_request(db, user, data)


@router.get("/attendance/override-requests")
async def list_override_requests(
    filters: Annotated[OverrideFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[OverrideRequestResponse]:
    """Participants see their own requests; staff see their cohorts'."""
    requests, total = await attendance_service.list_override_requests(db, user, filters)
    return Page[OverrideRequestResponse].build(requests, total, filters)


@router.patch(
    "/attendance/override-requests/{request_id}/approve",
    response_model=OverrideRequestResponse,
)
async def approve_override_request(
    request: TargetOverrideRequest,
    data: OverrideReviewRequest,
    reviewer: ManagerUser,
    db: DbSession,
) -> OverrideRequest:
    """Approve and extend the participant's window to `new_closes_at`, defaulting
    to the deadline they asked for, else now + `OVERRIDE_EXTENSION_HOURS`.
    **System Admin or Program Lead.**"""
    return await attendance_service.review_override_request(
        db, reviewer, request, data, approve=True
    )


@router.patch(
    "/attendance/override-requests/{request_id}/deny",
    response_model=OverrideRequestResponse,
)
async def deny_override_request(
    request: TargetOverrideRequest,
    data: OverrideReviewRequest,
    reviewer: ManagerUser,
    db: DbSession,
) -> OverrideRequest:
    """Deny an override request, optionally with a reason. **System Admin or
    Program Lead.**"""
    return await attendance_service.review_override_request(
        db, reviewer, request, data, approve=False
    )


@router.get("/attendance/{record_id}", response_model=AttendanceResponse)
async def get_attendance(record: VisibleRecord) -> AttendanceRecord:
    """A single attendance record."""
    return record


@router.patch("/attendance/{record_id}", response_model=AttendanceResponse)
async def update_attendance(
    data: AttendanceUpdateRequest,
    record: VisibleRecord,
    user: ActiveUser,
    db: DbSession,
) -> AttendanceRecord:
    """Edit your submission while the window is still open. The same rules as
    submitting apply to the result."""
    return await attendance_service.update_attendance(db, user, record, data)


@router.patch("/attendance/{record_id}/status", response_model=AttendanceResponse)
async def set_attendance_status(
    data: AttendanceStatusUpdateRequest,
    record: VisibleRecord,
    staff: ManagerUser,
    db: DbSession,
) -> AttendanceRecord:
    """Set a record's status: `pending`, `present`, `absent`, `missed` or
    `excused`. **System Admin or Program Lead.** Excused sessions are left out of
    the attendance rate."""
    return await attendance_service.set_record_status(db, staff, record, data)


@router.get("/sessions/{session_id}/attendance-window")
async def get_attendance_window(
    session: VisibleSession, user: ActiveUser, db: DbSession
) -> WindowStatusResponse:
    """Window status for the caller, including any personal override."""
    return await attendance_service.window_status(db, user, session)


@router.post(
    "/attendance-windows/{window_id}/close", response_model=AttendanceWindowResponse
)
async def close_attendance_window(
    window_id: UUID, admin: ManagerUser, db: DbSession
) -> AttendanceWindow:
    """Close a window early. **System Admin or Program Lead.** Approved
    extensions still apply."""
    return await attendance_service.close_window(db, admin, window_id)


@router.get("/cohorts/{cohort_id}/attendance")
async def cohort_attendance(
    filters: Annotated[AttendanceFilters, Query()],
    cohort: MemberCohort,
    user: ActiveUser,
    db: DbSession,
) -> Page[AttendanceResponse]:
    """Every attendance record in a cohort. **Staff of the cohort.**"""
    ensure_cohort_staff(user, cohort.id)
    filters = filters.model_copy(update={"cohort_id": cohort.id})
    records, total = await attendance_service.list_records(db, filters)
    return Page[AttendanceResponse].build(records, total, filters)


@router.get("/peer-mentors/me/attendance")
async def group_attendance(
    filters: Annotated[AttendanceFilters, Query()],
    mentor: PeerMentorUser,
    db: DbSession,
) -> Page[AttendanceResponse]:
    """Attendance records for the mentees in your 1:1 group."""
    mentee_ids = await group_mentee_ids(db, mentor.id, filters.cohort_id)
    records, total = await attendance_service.list_records(
        db, filters, mentee_ids=mentee_ids
    )
    return Page[AttendanceResponse].build(records, total, filters)
