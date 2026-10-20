"""Attendance engine endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from forge.api.deps import (
    ActiveUser,
    AdminUser,
    CommitteeUser,
    DbSession,
    MenteeUser,
    PeerMentorUser,
)
from forge.api.routes.cohorts import MemberCohort
from forge.api.routes.sessions import VisibleSession
from forge.models import AttendanceRecord, AttendanceWindow, OverrideRequest, User
from forge.schemas.attendance import (
    AttendanceFilters,
    AttendanceResponse,
    AttendanceStatusUpdateRequest,
    AttendanceSubmissionRequest,
    AttendanceUpdateRequest,
    AttendanceWindowResponse,
    MyAttendanceResponse,
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


def present(record: AttendanceRecord, viewer: User) -> AttendanceResponse:
    """Personal notes are only ever shown to the mentee who wrote them."""
    schema = (
        MyAttendanceResponse if record.mentee_id == viewer.id else AttendanceResponse
    )
    return schema.model_validate(record)


@router.post(
    "/attendance",
    status_code=status.HTTP_201_CREATED,
    response_model=MyAttendanceResponse,
)
async def submit_attendance(
    data: AttendanceSubmissionRequest, mentee: MenteeUser, db: DbSession
) -> AttendanceRecord:
    """Record your attendance and feedback for a session. **Mentees only.**

    Allowed only while the session's attendance window (or your approved
    override) is open. Ratings (1–5) apply only when `status` is `attended`.
    """
    return await attendance_service.submit_attendance(db, mentee, data)


@router.get("/attendance/me")
async def my_attendance(
    filters: Annotated[AttendanceFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[MyAttendanceResponse]:
    """Your attendance records, filterable by cohort, month, track and status."""
    records, total = await attendance_service.list_records(
        db, filters, mentee_ids=[user.id]
    )
    return Page[MyAttendanceResponse].build(records, total, filters)


@router.post(
    "/attendance/override-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=OverrideRequestResponse,
)
async def request_override(
    data: OverrideRequestCreate, mentee: MenteeUser, db: DbSession
) -> OverrideRequest:
    """Ask the committee to reopen a closed attendance window for you."""
    return await attendance_service.create_override_request(db, mentee, data)


@router.get("/attendance/override-requests")
async def list_override_requests(
    filters: Annotated[OverrideFilters, Query()], user: ActiveUser, db: DbSession
) -> Page[OverrideRequestResponse]:
    """Mentees see their own requests; committee members see their cohorts'."""
    requests, total = await attendance_service.list_override_requests(db, user, filters)
    return Page[OverrideRequestResponse].build(requests, total, filters)


@router.patch(
    "/attendance/override-requests/{request_id}/approve",
    response_model=OverrideRequestResponse,
)
async def approve_override_request(
    request: TargetOverrideRequest,
    data: OverrideReviewRequest,
    reviewer: CommitteeUser,
    db: DbSession,
) -> OverrideRequest:
    """Approve and extend the mentee's window to `new_closes_at`
    (default: now + `OVERRIDE_EXTENSION_HOURS`). **Committee.**"""
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
    reviewer: CommitteeUser,
    db: DbSession,
) -> OverrideRequest:
    """Deny an override request, optionally with a reason. **Committee.**"""
    return await attendance_service.review_override_request(
        db, reviewer, request, data, approve=False
    )


@router.get(
    "/attendance/{record_id}", response_model=MyAttendanceResponse | AttendanceResponse
)
async def get_attendance(record: VisibleRecord, user: ActiveUser) -> AttendanceResponse:
    """A single attendance record. Personal notes are included only for its mentee."""
    return present(record, user)


@router.patch("/attendance/{record_id}", response_model=MyAttendanceResponse)
async def update_attendance(
    data: AttendanceUpdateRequest,
    record: VisibleRecord,
    user: ActiveUser,
    db: DbSession,
) -> AttendanceRecord:
    """Edit your submission while the window is still open."""
    return await attendance_service.update_attendance(db, user, record, data)


@router.patch("/attendance/{record_id}/status", response_model=AttendanceResponse)
async def set_attendance_status(
    data: AttendanceStatusUpdateRequest,
    record: VisibleRecord,
    staff: CommitteeUser,
    db: DbSession,
) -> AttendanceRecord:
    """Set a record's status (e.g. `excused`, `disputed`). **Committee.**
    Excused sessions are left out of the mentee's attendance rate."""
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
    window_id: UUID, admin: AdminUser, db: DbSession
) -> AttendanceWindow:
    """Close a window early. **Admin only.** Approved overrides still apply."""
    return await attendance_service.close_window(db, admin, window_id)


@router.get("/cohorts/{cohort_id}/attendance")
async def cohort_attendance(
    filters: Annotated[AttendanceFilters, Query()],
    cohort: MemberCohort,
    user: ActiveUser,
    db: DbSession,
) -> Page[AttendanceResponse]:
    """Every attendance record in a cohort. **Committee of the cohort.**"""
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
