"""Graduation, cohort close and archive endpoints."""

from fastapi import APIRouter, status

from forge.api.deps import ActiveUser, ConfirmedProgramLead, DbSession, ProgramLeadUser
from forge.api.routes.cohorts import ManagedCohort, StaffedCohort
from forge.models import Cohort, GraduationCorrection
from forge.schemas.cohort import CohortResponse
from forge.schemas.graduation import (
    GraduationCorrectionRequest,
    GraduationCorrectionResponse,
    GraduationPreview,
    GraduationRecord,
    GraduationSequence,
    SequenceSettingsRequest,
)
from forge.services import graduation as graduation_service
from forge.services.access import ensure_cohort_manager

router = APIRouter(prefix="/cohorts/{cohort_id}", tags=["Graduation"])


@router.get("/graduation/preview")
async def get_preview(cohort: ManagedCohort, db: DbSession) -> GraduationPreview:
    """Each mentee's core rate against the threshold, split into graduates and
    non-graduates: the last preview run, or a fresh one. **System Admin or
    Program Lead.**"""
    return await graduation_service.preview(db, cohort)


@router.post("/graduation/preview")
async def refresh_preview(cohort: ManagedCohort, db: DbSession) -> GraduationPreview:
    """Run or refresh the graduation calculation. Nothing permanent changes.
    **System Admin or Program Lead.**"""
    return await graduation_service.refresh_preview(db, cohort)


@router.post("/graduate", status_code=status.HTTP_201_CREATED)
async def graduate_cohort(
    cohort: StaffedCohort, user: ConfirmedProgramLead, db: DbSession
) -> GraduationRecord:
    """Confirm graduation: freeze every mentee's results, mark the cohort
    completed, give graduates alumni status and record it in the audit log.
    **Program Lead**, with an `X-Confirmation-Token` from `/auth/confirm-password`.
    """
    ensure_cohort_manager(user, cohort.id)
    return await graduation_service.graduate(db, cohort, user)


@router.get("/graduation")
async def get_graduation(cohort: StaffedCohort, db: DbSession) -> GraduationRecord:
    """The confirmed graduation record. **Program Lead, System Admin and
    committee.**"""
    return await graduation_service.confirmed(db, cohort)


@router.get("/graduation/sequence")
async def get_sequence(
    cohort: StaffedCohort, user: ProgramLeadUser, db: DbSession
) -> GraduationSequence:
    """What the graduation sequence plays: graduates in reveal order, programme
    statistics and the mentors who served. **Program Lead.**"""
    return await graduation_service.sequence(db, cohort)


@router.patch("/graduation/sequence-settings")
async def set_sequence_settings(
    data: SequenceSettingsRequest,
    cohort: StaffedCohort,
    user: ProgramLeadUser,
    db: DbSession,
) -> GraduationSequence:
    """Set the order graduates are revealed in. **Program Lead.**"""
    return await graduation_service.set_reveal_order(
        db, cohort, data.reveal_order, user
    )


@router.post(
    "/graduation/corrections",
    status_code=status.HTTP_201_CREATED,
    response_model=GraduationCorrectionResponse,
)
async def correct_result(
    data: GraduationCorrectionRequest,
    cohort: StaffedCohort,
    user: ProgramLeadUser,
    db: DbSession,
) -> GraduationCorrection:
    """Correct a confirmed graduation result, with a reason; alumni status
    follows the correction. **Program Lead.**"""
    return await graduation_service.correct(
        db, cohort, data.user_id, data.graduated, data.reason, user
    )


@router.post("/close", response_model=CohortResponse)
async def close_cohort(
    cohort: ManagedCohort, user: ActiveUser, db: DbSession
) -> Cohort:
    """Close a graduated cohort and archive its peer mentor assignments.
    **Program Lead or System Admin.**"""
    return await graduation_service.close(db, cohort, user)


@router.patch("/archive", response_model=CohortResponse)
async def archive_cohort(
    cohort: ManagedCohort, user: ActiveUser, db: DbSession
) -> Cohort:
    """Mark a closed or imported cohort as an archived, read-only record.
    **System Admin or Program Lead.**"""
    return await graduation_service.archive(db, cohort, user)
