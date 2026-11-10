"""Branded email copy for each notification type."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from string import Template

from forge.core.config import settings
from forge.models import NotificationType
from forge.services.email import Detail, EmailContent, render_email

T = NotificationType

# Kenya has kept UTC+3 without DST since 1960, so a fixed offset avoids relying on
# tzdata being installed in the container.
NAIROBI = timezone(timedelta(hours=3), "EAT")

DATETIME_KEYS = frozenset(
    {
        "starts_at",
        "ends_at",
        "previous_starts_at",
        "previous_ends_at",
        "closes_at",
        "submitted_at",
        "deadline",
    }
)

PARTICIPANT = "You're getting this because you have a KamiLimu account."
ADMIN = "You're getting this because you're a System Admin."
ADMIN_REASON = "Reason from the System Admin"

# Mentee and peer mentor screens don't exist in the frontend yet, so their emails
# land on the dashboard until they do.
PATHS: dict[NotificationType, str] = {
    T.SESSION_PUBLISHED: "/dashboard",
    T.SESSION_RESCHEDULED: "/dashboard",
    T.SESSION_CANCELLED: "/dashboard",
    T.WINDOW_OPENING: "/dashboard",
    T.WINDOW_CLOSING_SOON: "/dashboard",
    T.GRADUATION_WARNING: "/dashboard",
    T.GRADUATION_AT_RISK: "/dashboard",
    T.OVERRIDE_SUBMITTED: "/admin/attendance-queue",
    T.OVERRIDE_APPROVED: "/dashboard",
    T.OVERRIDE_DENIED: "/dashboard",
    T.ACTIVITY_APPROVED: "/dashboard",
    T.ACTIVITY_REJECTED: "/dashboard",
    T.TASK_LAUNCHED: "/dashboard",
    T.TASK_DEADLINE_REMINDER: "/dashboard",
    T.COHORT_INVITATION: "/dashboard",
    T.BROADCAST: "/dashboard",
}
FALLBACK_PATH = "/dashboard"


@dataclass(frozen=True)
class Row:
    label: str
    value: str
    struck: bool = False


@dataclass(frozen=True)
class EmailSpec:
    """Copy for one notification type; every string is a ``string.Template``."""

    subject: str
    heading: str
    paragraphs: tuple[str, ...]
    button: str
    details: tuple[Row, ...] = ()
    quote: tuple[str, str] | None = None
    paragraphs_after: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    footer: str = PARTICIPANT


SESSION = Row("Session", "$title")
WHEN = Row("When", "$when")

SPECS: dict[NotificationType, EmailSpec] = {
    T.WINDOW_OPENING: EmailSpec(
        subject="Attendance is open: $title",
        heading="Attendance is open",
        paragraphs=("You can now record your attendance for this session.",),
        details=(SESSION, WHEN, Row("Window closes", "$closes_at")),
        paragraphs_after=(
            "To earn the points, mark yourself present, answer the rating questions "
            "and leave written feedback.",
        ),
        button="Record attendance",
    ),
    T.WINDOW_CLOSING_SOON: EmailSpec(
        subject="$hours hours left: $title",
        heading="$hours hours left to record attendance",
        paragraphs=(
            "You haven't recorded your attendance for this session yet. "
            "The window closes in $hours hours.",
        ),
        details=(SESSION, WHEN, Row("Window closes", "$closes_at")),
        button="Record attendance",
        notes=(
            "If the window closes before you submit, you can ask the System Admin "
            "for an extension from your dashboard.",
        ),
    ),
    T.SESSION_RESCHEDULED: EmailSpec(
        subject="Session moved: $title",
        heading="A session has moved",
        paragraphs=(
            "The date or time of this session has changed. "
            "The attendance window moves with it.",
        ),
        details=(
            SESSION,
            Row("Was", "$previous_when", struck=True),
            Row("Now", "$when"),
        ),
        quote=(ADMIN_REASON, "reason"),
        button="View session",
    ),
    T.SESSION_CANCELLED: EmailSpec(
        subject="Session cancelled: $title",
        heading="A session has been cancelled",
        paragraphs=(
            "This session won't run. It's been removed from your calendar and "
            "doesn't count towards your attendance rate.",
        ),
        details=(SESSION, Row("Was", "$when")),
        quote=(ADMIN_REASON, "reason"),
        button="View your sessions",
    ),
    T.OVERRIDE_SUBMITTED: EmailSpec(
        subject="Extension request: $mentee",
        heading="New extension request",
        paragraphs=(
            "A participant missed an attendance window and is asking for it to be "
            "reopened.",
        ),
        details=(
            Row("From", "$mentee"),
            SESSION,
            WHEN,
            Row("Submitted", "$submitted_at"),
        ),
        quote=("Their reason", "reason"),
        button="Review request",
        footer=ADMIN,
    ),
    T.OVERRIDE_APPROVED: EmailSpec(
        subject="Extension approved: $title",
        heading="Your extension was approved",
        paragraphs=("The System Admin has reopened the attendance window for you.",),
        details=(SESSION, WHEN, Row("Submit by", "$closes_at")),
        button="Record attendance",
    ),
    T.OVERRIDE_DENIED: EmailSpec(
        subject="Extension request: $title",
        heading="Your extension request was declined",
        paragraphs=(
            "The System Admin reviewed your request and couldn't reopen the window "
            "for this session, so it will count as missed.",
        ),
        details=(SESSION, WHEN),
        quote=(ADMIN_REASON, "reason"),
        button="View your sessions",
    ),
    T.SESSION_PUBLISHED: EmailSpec(
        subject="New session: $title",
        heading="A new session is on your calendar",
        paragraphs=("A new session has been scheduled for your cohort.",),
        details=(SESSION, WHEN, Row("Where", "$location")),
        button="View session",
    ),
    T.GRADUATION_WARNING: EmailSpec(
        subject="Your attendance is close to the graduation threshold",
        heading="Your attendance is close to the threshold",
        paragraphs=(
            "Your attendance is $rate%, close to the $threshold% needed to graduate.",
        ),
        details=(
            Row("Cohort", "$cohort"),
            Row("Your attendance", "$rate%"),
            Row("Required", "$threshold%"),
        ),
        paragraphs_after=(
            "Attending and recording the sessions ahead will keep you on track.",
        ),
        button="View your progress",
    ),
    T.GRADUATION_AT_RISK: EmailSpec(
        subject="Your attendance is below the graduation threshold",
        heading="Your attendance is below the threshold",
        paragraphs=(
            "Your attendance is $rate%, below the $threshold% needed to graduate.",
        ),
        details=(
            Row("Cohort", "$cohort"),
            Row("Your attendance", "$rate%"),
            Row("Required", "$threshold%"),
        ),
        paragraphs_after=(
            "There's still time to close the gap by attending and recording the "
            "sessions ahead. If something is getting in the way, talk to your peer "
            "mentor.",
        ),
        button="View your progress",
    ),
    T.ACTIVITY_APPROVED: EmailSpec(
        subject="Activity approved: $title",
        heading="Your activity was approved",
        paragraphs=(
            "Your $type activity was approved and the points added to your total.",
        ),
        details=(Row("Activity", "$title"), Row("Points", "$points")),
        button="View your progress",
    ),
    T.ACTIVITY_REJECTED: EmailSpec(
        subject="Activity not approved: $title",
        heading="Your activity wasn't approved",
        paragraphs=(
            "Your $type activity was reviewed and wasn't approved, so it won't add "
            "points.",
        ),
        details=(Row("Activity", "$title"),),
        quote=(ADMIN_REASON, "reason"),
        button="View your activities",
    ),
    T.TASK_LAUNCHED: EmailSpec(
        subject="New task: $title",
        heading="Your peer mentor set a new task",
        paragraphs=("Your peer mentor launched a new task for your group.",),
        details=(Row("Task", "$title"), Row("Due", "$deadline")),
        button="View task",
    ),
    T.TASK_DEADLINE_REMINDER: EmailSpec(
        subject="Task due soon: $title",
        heading="A task is due soon",
        paragraphs=("You haven't marked this task complete yet.",),
        details=(Row("Task", "$title"), Row("Due", "$deadline")),
        paragraphs_after=("Mark it complete once you're done.",),
        button="View task",
    ),
    T.COHORT_INVITATION: EmailSpec(
        subject="Welcome to $cohort",
        heading="Welcome to $cohort",
        paragraphs=(
            "You've been added to $cohort. Your upcoming sessions are on your "
            "dashboard.",
        ),
        button="Open your dashboard",
    ),
    T.BROADCAST: EmailSpec(
        subject="$title",
        heading="$title",
        paragraphs=("$message",),
        button="Open KamiLimu",
    ),
}


def _parse(value: str) -> datetime | date | None:
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _clock(moment: datetime, meridiem: bool = True) -> str:
    text = f"{moment.hour % 12 or 12}:{moment:%M}"
    return f"{text} {moment:%p}" if meridiem else text


def _day(moment: date) -> str:
    return f"{moment:%a} {moment.day} {moment:%b}"


def format_when(start: str, end: str | None = None) -> str:
    """'Thu 27 Aug, 5:30 PM', or a range like 'Thu 27 Aug, 5:30 to 8:00 PM'.

    Values are the ``str(datetime)`` stored in notification metadata; anything
    unparseable is returned unchanged.
    """
    begin = _parse(start)
    if begin is None:
        return start
    if not isinstance(begin, datetime):
        return _day(begin)
    begin = begin.astimezone(NAIROBI)
    finish = _parse(end) if end else None
    if not isinstance(finish, datetime):
        return f"{_day(begin)}, {_clock(begin)}"
    finish = finish.astimezone(NAIROBI)
    if finish.date() != begin.date():
        return f"{_day(begin)}, {_clock(begin)} to {_day(finish)}, {_clock(finish)}"
    same_half = f"{begin:%p}" == f"{finish:%p}"
    return f"{_day(begin)}, {_clock(begin, not same_half)} to {_clock(finish)}"


def _number(value: str) -> str:
    try:
        return f"{float(value):g}"
    except ValueError:
        return value


def email_context(meta: Mapping[str, str]) -> dict[str, str]:
    """Turn stored notification metadata into display strings."""
    ctx = {k: v.strip() for k, v in meta.items() if v is not None}
    if ctx.get("starts_at"):
        ctx["when"] = format_when(ctx["starts_at"], ctx.get("ends_at"))
    if ctx.get("previous_starts_at"):
        ctx["previous_when"] = format_when(
            ctx["previous_starts_at"], ctx.get("previous_ends_at")
        )
    for key in DATETIME_KEYS & ctx.keys():
        ctx[key] = format_when(ctx[key])
    for key in ("rate", "threshold", "points"):
        if ctx.get(key):
            ctx[key] = _number(ctx[key])
    ctx["hours"] = str(settings.WINDOW_CLOSING_REMINDER_HOURS)
    return ctx


def fill(template: str, ctx: Mapping[str, str]) -> str | None:
    """Substitute ``template``, or ``None`` if any placeholder has no value."""
    tpl = Template(template)
    if any(not ctx.get(name) for name in tpl.get_identifiers()):
        return None
    return tpl.substitute(ctx).strip()


def notification_email(
    notification_type: NotificationType,
    meta: Mapping[str, str] | None,
    *,
    first_name: str,
    title: str,
    message: str,
) -> EmailContent:
    """Build the email for a notification, falling back to its in-app copy."""
    url = settings.frontend_base_url + PATHS.get(notification_type, FALLBACK_PATH)
    spec = SPECS.get(notification_type)
    if spec is None:
        return render_email(
            subject=title,
            heading=title,
            first_name=first_name,
            paragraphs=[message],
            action=("View in KamiLimu", url),
        )

    ctx = email_context(meta or {})

    def paragraphs(templates: tuple[str, ...]) -> list[str]:
        filled = (fill(t, ctx) for t in templates)
        return [part for text in filled if text for part in text.split("\n\n")]

    body = paragraphs(spec.paragraphs) or [message]
    quote = None
    if spec.quote and ctx.get(spec.quote[1]):
        quote = (spec.quote[0], ctx[spec.quote[1]])
    return render_email(
        subject=fill(spec.subject, ctx) or title,
        heading=fill(spec.heading, ctx) or title,
        first_name=first_name,
        paragraphs=body,
        details=[
            Detail(row.label, value, row.struck)
            for row in spec.details
            if (value := fill(row.value, ctx))
        ],
        quote=quote,
        paragraphs_after=paragraphs(spec.paragraphs_after),
        action=(spec.button, url),
        notes=[n for t in spec.notes if (n := fill(t, ctx))],
        footer_reason=spec.footer,
    )
