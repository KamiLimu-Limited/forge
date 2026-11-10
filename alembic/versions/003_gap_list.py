"""Gap list: roles, profiles, cohort config, ICT tracks, nine-question ratings,
activity reversal, objectives, consultants, leaderboard snapshots and graduation.

Removes skills, peer mentor tasks, cohort soft-delete and leaderboard anonymity.

Revision ID: 003
Revises: 002
Create Date: 2026-11-09 23:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGE_POINTS = {
    "applied": 2,
    "general_interview": 3,
    "technical_interview": 4,
    "final_interview": 5,
    "offer_made": 6,
}
DEFAULT_POINTS_CONFIG = {
    "academic": 4,
    "event": 4,
    "consultation": 5,
    "opportunity": _STAGE_POINTS,
    "scholarship": _STAGE_POINTS,
    "targets": {
        "academic": 0,
        "event": 0,
        "opportunity": 0,
        "scholarship": 0,
        "consultation": 0,
    },
}
DEFAULT_RATING_QUESTIONS = [
    {
        "group": "reaction",
        "text": "How would you rate the overall quality of this session?",
    },
    {"group": "reaction", "text": "How useful was this session to you?"},
    {"group": "reaction", "text": "How engaging was the facilitator?"},
    {"group": "learning", "text": "How well did you understand the topics covered?"},
    {
        "group": "learning",
        "text": "How confident are you that you could explain what you learnt to someone else?",
    },
    {"group": "learning", "text": "How much new knowledge or skill did you gain?"},
    {
        "group": "intended_behaviour",
        "text": "How likely are you to apply these lessons in your academic work?",
    },
    {
        "group": "intended_behaviour",
        "text": "How likely are you to apply these lessons in your career preparation?",
    },
    {
        "group": "intended_behaviour",
        "text": "How likely are you to act on this topic within the next two weeks?",
    },
]

NEW_ENUMS: dict[str, tuple[str, ...]] = {
    "degreelevel": ("diploma", "bachelors", "masters", "doctorate"),
    "gender": ("female", "male", "non_binary", "prefer_not_to_say"),
    "attendancesource": ("on_time", "reopened"),
    "objectivetype": ("human", "technical"),
    "leaderboardkind": ("mentee", "peer_mentor"),
}

# name -> (old values, new values, columns as (table, column, server default))
CHANGED_ENUMS: dict[
    str, tuple[tuple[str, ...], tuple[str, ...], list[tuple[str, str, str | None]]]
] = {
    "userrole": (
        (
            "mentee",
            "peer_mentor_1:1",
            "peer_mentor_ict",
            "professional_mentor",
            "committee",
            "partner",
            "alumni",
            "admin",
        ),
        (
            "mentee",
            "peer_mentor_1_1",
            "peer_mentor_ict",
            "professional_mentor",
            "committee",
            "program_delivery_lead",
            "program_lead",
            "alumni",
            "admin",
        ),
        [("user_roles", "role", None), ("cohort_enrollments", "role", None)],
    ),
    "cohortstatus": (
        ("draft", "active", "completed"),
        ("draft", "active", "completed", "archived"),
        [("cohorts", "status", "draft")],
    ),
    "sessiontype": (
        ("core", "ict", "professional", "peer_mentorship"),
        ("theory", "tell_and_show", "hands_on", "simulation"),
        [("sessions", "session_type", None)],
    ),
    "sessionmode": (
        ("physical", "virtual", "hybrid"),
        ("physical", "virtual"),
        [("sessions", "mode", None)],
    ),
    "sessionstatus": (
        ("draft", "published", "cancelled", "completed"),
        ("draft", "published", "live", "completed", "rescheduled", "cancelled"),
        [("sessions", "status", None)],
    ),
    "attendancestatus": (
        ("pending", "attended", "not_attended", "missed", "excused", "disputed"),
        ("pending", "present", "absent", "missed", "excused"),
        [("attendance_records", "status", None)],
    ),
    "activitytype": (
        ("academic", "event", "opportunity", "consultation"),
        ("academic", "event", "opportunity", "scholarship", "consultation"),
        [("extra_activities", "type", None)],
    ),
    "activitystatus": (
        ("pending", "approved", "rejected"),
        ("active", "reversed"),
        [("extra_activities", "status", None)],
    ),
    "notificationtype": (
        (
            "session_published",
            "session_rescheduled",
            "session_cancelled",
            "attendance_window_opening",
            "attendance_window_closing_soon",
            "graduation_warning",
            "graduation_at_risk",
            "override_request_submitted",
            "override_request_approved",
            "override_request_denied",
            "extra_activity_approved",
            "extra_activity_rejected",
            "peer_task_launched",
            "peer_task_deadline_reminder",
            "cohort_onboarding_invitation",
            "broadcast",
        ),
        (
            "invitation",
            "password_reset",
            "attendance_window_opens",
            "attendance_window_closing_soon",
            "session_rescheduled",
            "session_cancelled",
            "override_request_submitted",
            "override_request_approved",
            "override_request_denied",
            "broadcast",
        ),
        [("notifications", "notification_type", None)],
    ),
}

UPGRADE_MAPPINGS: dict[str, dict[str, str]] = {
    "userrole": {"peer_mentor_1:1": "peer_mentor_1_1"},
    "sessiontype": {
        "core": "theory",
        "ict": "theory",
        "professional": "theory",
        "peer_mentorship": "theory",
    },
    "sessionmode": {"hybrid": "physical"},
    "attendancestatus": {
        "attended": "present",
        "not_attended": "absent",
        "disputed": "absent",
    },
    "activitystatus": {
        "pending": "active",
        "approved": "active",
        "rejected": "reversed",
    },
    "notificationtype": {
        "attendance_window_opening": "attendance_window_opens",
        "cohort_onboarding_invitation": "invitation",
    },
}

DOWNGRADE_MAPPINGS: dict[str, dict[str, str]] = {
    "userrole": {"peer_mentor_1_1": "peer_mentor_1:1"},
    "cohortstatus": {"archived": "completed"},
    "sessiontype": {
        "theory": "core",
        "tell_and_show": "core",
        "hands_on": "core",
        "simulation": "core",
    },
    "sessionstatus": {"live": "published", "rescheduled": "published"},
    "attendancestatus": {"present": "attended", "absent": "not_attended"},
    "activitytype": {"scholarship": "opportunity"},
    "activitystatus": {"active": "approved", "reversed": "rejected"},
    "notificationtype": {
        "attendance_window_opens": "attendance_window_opening",
        "invitation": "cohort_onboarding_invitation",
    },
}


def _recreate_enum(
    name: str,
    values: tuple[str, ...],
    columns: list[tuple[str, str, str | None]],
    mapping: dict[str, str],
) -> None:
    """Swap enum ``name`` for one with ``values``, mapping existing column data."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_old")
    postgresql.ENUM(*values, name=name).create(op.get_bind())
    for table, column, default in columns:
        whens = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in mapping.items())
        expr = (
            f"(CASE {column}::text {whens} ELSE {column}::text END)"
            if mapping
            else f"{column}::text"
        )
        if default is not None:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {name} USING {expr}::{name}"
        )
        if default is not None:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{default}'"
            )
    op.execute(f"DROP TYPE {name}_old")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _fk(column: str, target: str, table: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in NEW_ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # Rows whose values no longer exist.
    op.execute("DELETE FROM user_roles WHERE role = 'partner'")
    op.execute("DELETE FROM cohort_enrollments WHERE role = 'partner'")
    op.execute(
        "DELETE FROM notifications WHERE notification_type IN ("
        "'session_published', 'graduation_warning', 'graduation_at_risk', "
        "'extra_activity_approved', 'extra_activity_rejected', "
        "'peer_task_launched', 'peer_task_deadline_reminder')"
    )

    # Extra activities: points on submission, reversal replaces rejection.
    op.add_column(
        "extra_activities",
        sa.Column("reversed_by", sa.UUID(), nullable=True),
    )
    op.add_column(
        "extra_activities",
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "extra_activities", sa.Column("reversal_reason", sa.Text(), nullable=True)
    )
    op.execute(
        "UPDATE extra_activities SET points_awarded = CASE type::text "
        "WHEN 'consultation' THEN 5 WHEN 'opportunity' THEN 2 ELSE 4 END, "
        'details = details || \'{"stage": "applied"}\'::jsonb '
        "WHERE status = 'pending' AND type = 'opportunity'"
    )
    op.execute(
        "UPDATE extra_activities SET points_awarded = CASE type::text "
        "WHEN 'consultation' THEN 5 ELSE 4 END "
        "WHERE status = 'pending' AND type <> 'opportunity'"
    )
    op.execute(
        "UPDATE extra_activities SET points_awarded = 0, reversed_by = reviewed_by, "
        "reversed_at = reviewed_at, reversal_reason = review_reason "
        "WHERE status = 'rejected'"
    )
    op.drop_constraint(
        op.f("fk_extra_activities_reviewed_by_users"),
        "extra_activities",
        type_="foreignkey",
    )
    op.drop_column("extra_activities", "reviewed_by")
    op.drop_column("extra_activities", "reviewed_at")
    op.drop_column("extra_activities", "review_reason")
    op.create_foreign_key(
        op.f("fk_extra_activities_reversed_by_users"),
        "extra_activities",
        "users",
        ["reversed_by"],
        ["id"],
        ondelete="SET NULL",
    )

    for name, (_, values, columns) in CHANGED_ENUMS.items():
        _recreate_enum(name, values, columns, UPGRADE_MAPPINGS.get(name, {}))

    op.execute(
        "UPDATE invitations SET intended_roles = ("
        "SELECT coalesce(jsonb_agg(CASE WHEN r = 'peer_mentor_1:1' "
        "THEN 'peer_mentor_1_1' ELSE r END), '[]'::jsonb) "
        "FROM jsonb_array_elements_text(intended_roles) AS r WHERE r <> 'partner') "
        "WHERE jsonb_typeof(intended_roles) = 'array'"
    )
    op.add_column(
        "invitations",
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Users: profile, alumni status and active cohort context.
    op.add_column("users", sa.Column("university", sa.String(200), nullable=True))
    op.add_column(
        "users", sa.Column("programme_of_study", sa.String(200), nullable=True)
    )
    op.add_column(
        "users", sa.Column("degree_level", _enum("degreelevel"), nullable=True)
    )
    op.add_column("users", sa.Column("gender", _enum("gender"), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "social_links", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column("users", sa.Column("alumni_since", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("active_cohort_id", sa.UUID(), nullable=True))
    op.add_column("users", sa.Column("active_role", _enum("userrole"), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_active_cohort_id_cohorts"),
        "users",
        "cohorts",
        ["active_cohort_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Cohorts: configuration and lifecycle.
    for column, default in (
        ("thursday_window_hours", "24"),
        ("saturday_window_hours", "48"),
        ("extra_log_window_days", "30"),
    ):
        op.add_column(
            "cohorts",
            sa.Column(column, sa.Integer(), server_default=default, nullable=False),
        )
    op.add_column(
        "cohorts",
        sa.Column(
            "objective_windows", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "cohorts",
        sa.Column(
            "track_selection_opens_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "cohorts",
        sa.Column(
            "track_selection_closes_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    for column, default in (
        ("points_config", DEFAULT_POINTS_CONFIG),
        ("rating_questions", DEFAULT_RATING_QUESTIONS),
    ):
        op.add_column(
            "cohorts",
            sa.Column(
                column,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text(f"'{json.dumps(default)}'::jsonb"),
                nullable=False,
            ),
        )
        op.alter_column("cohorts", column, server_default=None)
    op.add_column(
        "cohorts",
        sa.Column("is_imported", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "cohorts", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "cohorts", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "cohort_ict_tracks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("cohort_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lead_mentor_id", sa.UUID(), nullable=True),
        *_timestamps(),
        _fk("cohort_id", "cohorts", "cohort_ict_tracks", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["lead_mentor_id"],
            ["users.id"],
            name=op.f("fk_cohort_ict_tracks_lead_mentor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cohort_ict_tracks")),
        sa.UniqueConstraint(
            "cohort_id", "name", name=op.f("uq_cohort_ict_tracks_cohort_id")
        ),
    )
    op.create_index(
        op.f("ix_cohort_ict_tracks_cohort_id"), "cohort_ict_tracks", ["cohort_id"]
    )
    op.execute(
        "INSERT INTO cohort_ict_tracks (id, cohort_id, name) "
        "SELECT gen_random_uuid(), c.id, t FROM cohorts c, "
        "jsonb_array_elements_text(c.ict_tracks_offered) AS t "
        "WHERE jsonb_typeof(c.ict_tracks_offered) = 'array'"
    )
    for column in (
        "skill_names",
        "skill_rating_windows",
        "leaderboard_anonymous",
        "peer_mentorship_deadline_hours",
        "deleted_at",
        "ict_tracks_offered",
    ):
        op.drop_column("cohorts", column)

    op.add_column(
        "cohort_enrollments",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Sessions: a stored end time; a task's deadline is its end.
    op.add_column(
        "sessions", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE sessions SET ends_at = CASE "
        "WHEN category = 'peer_mentorship' AND attendance_deadline IS NOT NULL "
        "THEN attendance_deadline "
        "ELSE starts_at + duration_minutes * interval '1 minute' END"
    )
    op.alter_column("sessions", "ends_at", nullable=False)
    op.drop_column("sessions", "duration_minutes")
    op.drop_column("sessions", "attendance_deadline")

    # Attendance: nine ratings, a source, and notes in their own table.
    op.add_column(
        "attendance_records",
        sa.Column("source", _enum("attendancesource"), nullable=True),
    )
    op.add_column(
        "attendance_records",
        sa.Column("ratings", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
    )
    op.execute(
        "UPDATE attendance_records SET source = 'on_time' WHERE submitted_at IS NOT NULL"
    )
    op.execute(
        "UPDATE attendance_records SET ratings = ARRAY[quality_rating, "
        "usefulness_rating, NULL, understanding_score, NULL, NULL, "
        "academic_application_score, career_application_score, NULL]::smallint[] "
        "WHERE coalesce(quality_rating, usefulness_rating, understanding_score, "
        "academic_application_score, career_application_score) IS NOT NULL"
    )
    op.create_check_constraint(
        op.f("ck_attendance_records_ratings_count"),
        "attendance_records",
        "ratings IS NULL OR cardinality(ratings) = 9",
    )
    op.create_table(
        "session_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        *_timestamps(),
        _fk("user_id", "users", "session_notes", "CASCADE"),
        _fk("session_id", "sessions", "session_notes", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_notes")),
        sa.UniqueConstraint(
            "user_id", "session_id", name=op.f("uq_session_notes_user_id")
        ),
    )
    op.create_index(op.f("ix_session_notes_user_id"), "session_notes", ["user_id"])
    op.create_index(
        op.f("ix_session_notes_session_id"), "session_notes", ["session_id"]
    )
    op.execute(
        "INSERT INTO session_notes (id, user_id, session_id, body) "
        "SELECT gen_random_uuid(), mentee_id, session_id, personal_notes "
        "FROM attendance_records WHERE personal_notes IS NOT NULL"
    )
    for column in (
        "quality_rating",
        "usefulness_rating",
        "understanding_score",
        "academic_application_score",
        "career_application_score",
        "personal_notes",
    ):
        op.drop_column("attendance_records", column)

    op.add_column(
        "override_requests",
        sa.Column("requested_closes_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Consultants roster.
    op.create_table(
        "consultants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("organisation", sa.String(200), nullable=True),
        sa.Column("expertise", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultants")),
    )
    op.add_column(
        "extra_activities", sa.Column("consultant_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_extra_activities_consultant_id_consultants"),
        "extra_activities",
        "consultants",
        ["consultant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_extra_activities_consultant_id"),
        "extra_activities",
        ["consultant_id"],
    )

    # Skills and peer mentor tasks are gone.
    op.drop_table("task_submissions")
    op.drop_table("peer_mentor_tasks")
    op.drop_table("skill_ratings")
    op.execute("DROP TYPE submissionstatus")
    op.execute("DROP TYPE ratingpoint")
    postgresql.ENUM("start", "mid", "end", name="ratingpoint").create(bind)

    # Objectives.
    op.create_table(
        "objectives",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("cohort_id", sa.UUID(), nullable=False),
        sa.Column("type", _enum("objectivetype"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        *_timestamps(),
        _fk("user_id", "users", "objectives", "CASCADE"),
        _fk("cohort_id", "cohorts", "objectives", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_objectives")),
    )
    op.create_index(op.f("ix_objectives_user_id"), "objectives", ["user_id"])
    op.create_index(op.f("ix_objectives_cohort_id"), "objectives", ["cohort_id"])
    op.create_table(
        "objective_ratings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("objective_id", sa.UUID(), nullable=False),
        sa.Column("rating_point", _enum("ratingpoint"), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column(
            "rated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _fk("objective_id", "objectives", "objective_ratings", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_objective_ratings")),
        sa.UniqueConstraint(
            "objective_id",
            "rating_point",
            name=op.f("uq_objective_ratings_objective_id"),
        ),
    )
    op.create_index(
        op.f("ix_objective_ratings_objective_id"),
        "objective_ratings",
        ["objective_id"],
    )

    # Leaderboard snapshots and graduation.
    op.create_table(
        "leaderboard_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("cohort_id", sa.UUID(), nullable=False),
        sa.Column("kind", _enum("leaderboardkind"), nullable=False),
        sa.Column(
            "taken_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("taken_by", sa.UUID(), nullable=True),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _fk("cohort_id", "cohorts", "leaderboard_snapshots", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["taken_by"],
            ["users.id"],
            name=op.f("fk_leaderboard_snapshots_taken_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leaderboard_snapshots")),
    )
    op.create_index(
        op.f("ix_leaderboard_snapshots_cohort_id"),
        "leaderboard_snapshots",
        ["cohort_id"],
    )
    op.create_table(
        "cohort_graduations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("cohort_id", sa.UUID(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("preview", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("preview_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.UUID(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reveal_order", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        *_timestamps(),
        _fk("cohort_id", "cohorts", "cohort_graduations", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["users.id"],
            name=op.f("fk_cohort_graduations_confirmed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cohort_graduations")),
        sa.UniqueConstraint("cohort_id", name=op.f("uq_cohort_graduations_cohort_id")),
    )
    op.create_table(
        "graduation_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("graduation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("core_rate", sa.Float(), nullable=False),
        sa.Column("overall_rate", sa.Float(), nullable=False),
        sa.Column("core_points", sa.Integer(), nullable=False),
        sa.Column("extra_points", sa.Integer(), nullable=False),
        sa.Column("total_points", sa.Integer(), nullable=False),
        sa.Column("graduated", sa.Boolean(), nullable=False),
        _fk("graduation_id", "cohort_graduations", "graduation_results", "CASCADE"),
        _fk("user_id", "users", "graduation_results", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graduation_results")),
        sa.UniqueConstraint(
            "graduation_id",
            "user_id",
            name=op.f("uq_graduation_results_graduation_id"),
        ),
    )
    op.create_index(
        op.f("ix_graduation_results_graduation_id"),
        "graduation_results",
        ["graduation_id"],
    )
    op.create_index(
        op.f("ix_graduation_results_user_id"), "graduation_results", ["user_id"]
    )
    op.create_table(
        "graduation_corrections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("result_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("old_value", sa.String(50), nullable=False),
        sa.Column("new_value", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("corrected_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _fk("result_id", "graduation_results", "graduation_corrections", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["corrected_by"],
            ["users.id"],
            name=op.f("fk_graduation_corrections_corrected_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graduation_corrections")),
    )
    op.create_index(
        op.f("ix_graduation_corrections_result_id"),
        "graduation_corrections",
        ["result_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("graduation_corrections")
    op.drop_table("graduation_results")
    op.drop_table("cohort_graduations")
    op.drop_table("leaderboard_snapshots")
    op.drop_table("objective_ratings")
    op.drop_table("objectives")
    op.execute("DROP TYPE ratingpoint")
    postgresql.ENUM("early", "mid", "late", name="ratingpoint").create(bind)
    postgresql.ENUM("pending", "completed", name="submissionstatus").create(bind)

    op.create_table(
        "skill_ratings",
        sa.Column("mentee_id", sa.UUID(), nullable=False),
        sa.Column("cohort_id", sa.UUID(), nullable=False),
        sa.Column("rating_point", _enum("ratingpoint"), nullable=False),
        sa.Column("ratings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        _fk("cohort_id", "cohorts", "skill_ratings", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["mentee_id"],
            ["users.id"],
            name=op.f("fk_skill_ratings_mentee_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_ratings")),
        sa.UniqueConstraint(
            "mentee_id",
            "cohort_id",
            "rating_point",
            name=op.f("uq_skill_ratings_mentee_id"),
        ),
    )
    op.create_index(op.f("ix_skill_ratings_cohort_id"), "skill_ratings", ["cohort_id"])
    op.create_index(op.f("ix_skill_ratings_mentee_id"), "skill_ratings", ["mentee_id"])
    op.create_table(
        "peer_mentor_tasks",
        sa.Column("peer_mentor_id", sa.UUID(), nullable=False),
        sa.Column("cohort_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("launch_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resource_link", sa.String(length=2048), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        _fk("cohort_id", "cohorts", "peer_mentor_tasks", "CASCADE"),
        sa.ForeignKeyConstraint(
            ["peer_mentor_id"],
            ["users.id"],
            name=op.f("fk_peer_mentor_tasks_peer_mentor_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_peer_mentor_tasks")),
    )
    op.create_index(
        op.f("ix_peer_mentor_tasks_cohort_id"), "peer_mentor_tasks", ["cohort_id"]
    )
    op.create_index(
        op.f("ix_peer_mentor_tasks_peer_mentor_id"),
        "peer_mentor_tasks",
        ["peer_mentor_id"],
    )
    op.create_table(
        "task_submissions",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("mentee_id", sa.UUID(), nullable=False),
        sa.Column("submission_status", _enum("submissionstatus"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["mentee_id"],
            ["users.id"],
            name=op.f("fk_task_submissions_mentee_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["peer_mentor_tasks.id"],
            name=op.f("fk_task_submissions_task_id_peer_mentor_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_submissions")),
        sa.UniqueConstraint(
            "task_id", "mentee_id", name=op.f("uq_task_submissions_task_id")
        ),
    )
    op.create_index(
        op.f("ix_task_submissions_mentee_id"), "task_submissions", ["mentee_id"]
    )
    op.create_index(
        op.f("ix_task_submissions_task_id"), "task_submissions", ["task_id"]
    )

    op.drop_index(
        op.f("ix_extra_activities_consultant_id"), table_name="extra_activities"
    )
    op.drop_constraint(
        op.f("fk_extra_activities_consultant_id_consultants"),
        "extra_activities",
        type_="foreignkey",
    )
    op.drop_column("extra_activities", "consultant_id")
    op.drop_table("consultants")
    op.drop_column("override_requests", "requested_closes_at")

    for column in (
        "quality_rating",
        "usefulness_rating",
        "understanding_score",
        "academic_application_score",
        "career_application_score",
    ):
        op.add_column(
            "attendance_records", sa.Column(column, sa.SmallInteger(), nullable=True)
        )
    op.add_column(
        "attendance_records", sa.Column("personal_notes", sa.Text(), nullable=True)
    )
    op.execute(
        "UPDATE attendance_records SET quality_rating = ratings[1], "
        "usefulness_rating = ratings[2], understanding_score = ratings[4], "
        "academic_application_score = ratings[7], "
        "career_application_score = ratings[8] WHERE ratings IS NOT NULL"
    )
    op.execute(
        "UPDATE attendance_records r SET personal_notes = n.body FROM session_notes n "
        "WHERE n.user_id = r.mentee_id AND n.session_id = r.session_id"
    )
    op.drop_table("session_notes")
    op.drop_constraint(
        op.f("ck_attendance_records_ratings_count"), "attendance_records", type_="check"
    )
    op.drop_column("attendance_records", "ratings")
    op.drop_column("attendance_records", "source")

    op.add_column(
        "sessions", sa.Column("duration_minutes", sa.Integer(), nullable=True)
    )
    op.add_column(
        "sessions",
        sa.Column("attendance_deadline", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE sessions SET duration_minutes = "
        "GREATEST(1, EXTRACT(EPOCH FROM ends_at - starts_at)::int / 60), "
        "attendance_deadline = CASE WHEN category = 'peer_mentorship' "
        "THEN ends_at END"
    )
    op.alter_column("sessions", "duration_minutes", nullable=False)
    op.drop_column("sessions", "ends_at")

    op.drop_column("cohort_enrollments", "archived_at")

    op.add_column(
        "cohorts",
        sa.Column(
            "ict_tracks_offered", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.execute(
        "UPDATE cohorts c SET ict_tracks_offered = t.names FROM ("
        "SELECT cohort_id, jsonb_agg(name ORDER BY name) AS names "
        "FROM cohort_ict_tracks GROUP BY cohort_id) t WHERE t.cohort_id = c.id"
    )
    op.drop_table("cohort_ict_tracks")
    op.add_column(
        "cohorts",
        sa.Column(
            "skill_names", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "cohorts",
        sa.Column(
            "skill_rating_windows",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "cohorts",
        sa.Column(
            "leaderboard_anonymous",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "cohorts",
        sa.Column("peer_mentorship_deadline_hours", sa.Integer(), nullable=True),
    )
    op.add_column(
        "cohorts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    for column in (
        "thursday_window_hours",
        "saturday_window_hours",
        "extra_log_window_days",
        "objective_windows",
        "track_selection_opens_at",
        "track_selection_closes_at",
        "points_config",
        "rating_questions",
        "is_imported",
        "closed_at",
        "archived_at",
    ):
        op.drop_column("cohorts", column)

    op.drop_constraint(
        op.f("fk_users_active_cohort_id_cohorts"), "users", type_="foreignkey"
    )
    for column in (
        "university",
        "programme_of_study",
        "degree_level",
        "gender",
        "phone",
        "birthday",
        "social_links",
        "alumni_since",
        "active_cohort_id",
        "active_role",
    ):
        op.drop_column("users", column)
    op.drop_column("invitations", "profile")
    op.execute(
        "UPDATE invitations SET intended_roles = ("
        "SELECT coalesce(jsonb_agg(CASE WHEN r = 'peer_mentor_1_1' "
        "THEN 'peer_mentor_1:1' ELSE r END), '[]'::jsonb) "
        "FROM jsonb_array_elements_text(intended_roles) AS r "
        "WHERE r NOT IN ('program_lead', 'program_delivery_lead')) "
        "WHERE jsonb_typeof(intended_roles) = 'array'"
    )

    op.execute(
        "DELETE FROM user_roles WHERE role IN ('program_lead', 'program_delivery_lead')"
    )
    op.execute(
        "DELETE FROM cohort_enrollments "
        "WHERE role IN ('program_lead', 'program_delivery_lead')"
    )
    op.execute("DELETE FROM notifications WHERE notification_type = 'password_reset'")
    for name, (values, _, columns) in CHANGED_ENUMS.items():
        _recreate_enum(name, values, columns, DOWNGRADE_MAPPINGS.get(name, {}))

    op.drop_constraint(
        op.f("fk_extra_activities_reversed_by_users"),
        "extra_activities",
        type_="foreignkey",
    )
    op.add_column(
        "extra_activities", sa.Column("reviewed_by", sa.UUID(), nullable=True)
    )
    op.add_column(
        "extra_activities",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "extra_activities", sa.Column("review_reason", sa.Text(), nullable=True)
    )
    op.execute(
        "UPDATE extra_activities SET reviewed_by = reversed_by, "
        "reviewed_at = reversed_at, review_reason = reversal_reason "
        "WHERE status = 'rejected'"
    )
    op.create_foreign_key(
        op.f("fk_extra_activities_reviewed_by_users"),
        "extra_activities",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("extra_activities", "reversed_by")
    op.drop_column("extra_activities", "reversed_at")
    op.drop_column("extra_activities", "reversal_reason")

    for name in NEW_ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")
