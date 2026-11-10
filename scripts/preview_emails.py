"""Write every email to build/email-previews/ as HTML, with sample data.

    python scripts/preview_emails.py

FRONTEND_URL decides where links and the logo point; it defaults to the deployed
frontend so the logo loads when the files are opened locally.
"""

import os
from pathlib import Path

os.environ.setdefault("FRONTEND_URL", "https://forge-liard-sigma.vercel.app")

from forge.models import NotificationType as T  # noqa: E402
from forge.services.email import (  # noqa: E402
    EmailContent,
    invitation_email,
    password_reset_email,
)
from forge.services.email_templates import notification_email  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "build" / "email-previews"

TRAINING = {
    "title": "Cybersecurity: ICT Training 8",
    "starts_at": "2026-08-27 14:30:00+00:00",
    "ends_at": "2026-08-27 17:00:00+00:00",
    "closes_at": "2026-08-28 07:00:00+00:00",
}
CAREER = {
    "title": "Career Development: CVs, Applications & Opportunities",
    "previous_starts_at": "2026-09-12 06:30:00+00:00",
    "previous_ends_at": "2026-09-12 09:00:00+00:00",
    "starts_at": "2026-09-19 06:30:00+00:00",
    "ends_at": "2026-09-19 09:00:00+00:00",
    "reason": "Sample reason: the venue is unavailable that morning.",
}
VALIDATION = {
    "title": "User Validation and the Competitions Ahead",
    "starts_at": "2026-08-22 07:00:00+00:00",
    "ends_at": "2026-08-22 09:00:00+00:00",
}

SAMPLES: dict[T, dict[str, str]] = {
    T.WINDOW_OPENING: TRAINING,
    T.WINDOW_CLOSING_SOON: TRAINING,
    T.SESSION_RESCHEDULED: CAREER,
    T.SESSION_CANCELLED: {
        **CAREER,
        "starts_at": CAREER["previous_starts_at"],
        "ends_at": CAREER["previous_ends_at"],
    },
    T.OVERRIDE_SUBMITTED: {
        **VALIDATION,
        "mentee": "Sample Mentee",
        "submitted_at": "2026-08-23 06:10:00+00:00",
        "reason": "Sample reason: my phone died before I could submit.",
    },
    T.OVERRIDE_APPROVED: {**VALIDATION, "closes_at": "2026-08-25 15:00:00+00:00"},
    T.OVERRIDE_DENIED: {
        **VALIDATION,
        "reason": "Sample reason: the request came in after the review deadline.",
    },
    T.SESSION_PUBLISHED: {**TRAINING, "location": "Sample venue, Nairobi"},
    T.GRADUATION_WARNING: {"rate": "78", "threshold": "80", "cohort": "Cohort 11"},
    T.GRADUATION_AT_RISK: {"rate": "72", "threshold": "80", "cohort": "Cohort 11"},
    T.ACTIVITY_APPROVED: {
        "title": "Sample hackathon",
        "type": "event",
        "points": "5",
    },
    T.ACTIVITY_REJECTED: {
        "title": "Sample hackathon",
        "type": "event",
        "reason": "Sample reason: we couldn't verify attendance from the link given.",
    },
    T.TASK_LAUNCHED: {"title": "Sample task: update your CV", "deadline": "2026-09-03"},
    T.TASK_DEADLINE_REMINDER: {
        "title": "Sample task: update your CV",
        "deadline": "2026-09-03",
    },
    T.COHORT_INVITATION: {"cohort": "Cohort 11"},
    T.BROADCAST: {
        "title": "Sample announcement",
        "message": "Sample broadcast message from the programme team.",
    },
}


def previews() -> dict[str, EmailContent]:
    emails = {
        "invitation": invitation_email(
            "Sample", "sample-token", ["mentee"], "Cohort 11"
        ),
        "password-reset": password_reset_email(
            "sample.mentee@example.com", "Sample", "sample-token"
        ),
    }
    for notification_type in T:
        emails[notification_type.value] = notification_email(
            notification_type,
            SAMPLES.get(notification_type, {}),
            first_name="Sample",
            title=f"Sample {notification_type.value}",
            message="Sample in-app message.",
        )
    return emails


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, content in previews().items():
        path = OUT / f"{name}.html"
        path.write_text(content.html, encoding="utf-8")
        (OUT / f"{name}.txt").write_text(
            f"Subject: {content.subject}\n\n{content.text}\n", encoding="utf-8"
        )
        print(path.relative_to(OUT.parent.parent))


if __name__ == "__main__":
    main()
