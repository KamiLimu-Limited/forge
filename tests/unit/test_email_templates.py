"""Unit tests for the branded email layout and the per-type notification specs."""

import re

import pytest
from pydantic import AnyHttpUrl

from forge.core.config import settings
from forge.models import NotificationType
from forge.services.email import (
    Detail,
    EmailContent,
    invitation_email,
    password_reset_email,
    render_email,
)
from forge.services.email_templates import PATHS, SPECS, notification_email

FRONTEND = "https://app.kamilimu.test"

SAMPLE_META = {
    "title": "Cybersecurity: ICT Training 8",
    "starts_at": "2026-08-27 14:30:00+00:00",
    "ends_at": "2026-08-27 17:00:00+00:00",
    "previous_starts_at": "2026-08-26 14:30:00+00:00",
    "previous_ends_at": "2026-08-26 17:00:00+00:00",
    "closes_at": "2026-08-28 07:00:00+00:00",
    "submitted_at": "2026-08-29 06:10:00+00:00",
    "deadline": "2026-09-03",
    "location": "iHub, Nairobi",
    "reason": "The venue is closed for maintenance.",
    "mentee": "Sample Mentee",
    "rate": "72.5",
    "threshold": "75",
    "cohort": "Cohort 11",
    "type": "academic",
    "points": "5",
    "message": "Sessions resume next week.",
}


@pytest.fixture(autouse=True)
def https_frontend(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", AnyHttpUrl(FRONTEND))
    monkeypatch.setattr(settings, "EMAIL_LOGO_URL", "")


def build(notification_type: NotificationType, meta=SAMPLE_META) -> EmailContent:
    return notification_email(
        notification_type,
        meta,
        first_name="Sample",
        title="In-app title",
        message="In-app message",
    )


def all_emails() -> list[EmailContent]:
    return [
        invitation_email("Sample", "tok123", ["mentee"], "Cohort 11"),
        password_reset_email("sample@example.com", "Sample", "reset123"),
        *(build(t) for t in NotificationType),
    ]


@pytest.fixture(params=range(len(NotificationType) + 2))
def email(request) -> EmailContent:
    return all_emails()[request.param]


@pytest.mark.parametrize("notification_type", list(NotificationType))
def test_every_type_has_a_spec_and_path(notification_type):
    assert notification_type in SPECS
    assert notification_type in PATHS


@pytest.mark.parametrize("notification_type", list(NotificationType))
def test_spec_renders_without_leftover_placeholders(notification_type):
    content = build(notification_type)
    for part in (content.subject, content.html, content.text):
        assert not re.search(r"\$\{?[A-Za-z_]", part)
    assert content.subject != "In-app title"


def test_render_escapes_data():
    content = render_email(
        subject="<i>s</i>",
        heading="<b>Title</b>",
        first_name="<img src=x>",
        paragraphs=["a & b"],
        details=[("Session", "<em>x</em>")],
        quote=("Reason", "<script>alert(1)</script>"),
    )
    assert "<script>" not in content.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content.html
    assert "&lt;b&gt;Title&lt;/b&gt;" in content.html
    assert "Hi &lt;img src=x&gt;," in content.html
    assert "&lt;em&gt;x&lt;/em&gt;" in content.html


def test_reason_in_notification_is_escaped():
    content = build(
        NotificationType.OVERRIDE_DENIED, {**SAMPLE_META, "reason": "<script>x"}
    )
    assert "&lt;script&gt;x" in content.html
    assert "<script" not in content.html


def test_struck_detail_row():
    content = render_email(
        subject="s",
        heading="h",
        first_name="n",
        paragraphs=[],
        details=[Detail("Was", "Mon", struck=True)],
    )
    assert "text-decoration: line-through" in content.html


def test_rescheduled_shows_old_time_struck():
    assert "line-through" in build(NotificationType.SESSION_RESCHEDULED).html


def test_empty_values_hide_rows_and_quote():
    content = build(NotificationType.SESSION_CANCELLED, {**SAMPLE_META, "reason": ""})
    assert "Reason from the System Admin" not in content.html
    published = build(
        NotificationType.SESSION_PUBLISHED, {**SAMPLE_META, "location": ""}
    )
    assert ">Where<" not in published.html


def test_unparseable_date_falls_back_to_raw_value():
    content = build(
        NotificationType.WINDOW_OPENING, {**SAMPLE_META, "closes_at": "soon-ish"}
    )
    assert "soon-ish" in content.html


def test_dates_use_nairobi_time():
    content = build(NotificationType.WINDOW_OPENING)
    assert "Thu 27 Aug, 5:30 to 8:00 PM" in content.text
    assert "Fri 28 Aug, 10:00 AM" in content.text


def test_closing_soon_uses_reminder_setting(monkeypatch):
    monkeypatch.setattr(settings, "WINDOW_CLOSING_REMINDER_HOURS", 6)
    assert build(NotificationType.WINDOW_CLOSING_SOON).subject.startswith(
        "6 hours left"
    )


def test_missing_spec_falls_back_to_in_app_copy(monkeypatch):
    monkeypatch.delitem(SPECS, NotificationType.BROADCAST)
    content = build(NotificationType.BROADCAST)
    assert content.subject == "In-app title"
    assert "View in KamiLimu" in content.html


def test_admin_type_links_to_admin_route():
    content = build(NotificationType.OVERRIDE_SUBMITTED)
    assert f"{FRONTEND}/admin/attendance-queue" in content.html
    assert "System Admin" in content.text.split("--")[-1]


def test_invitation_and_reset_links():
    invite = invitation_email("Sample", "tok123", ["mentee"], "Cohort 11")
    assert f"{FRONTEND}/activate?token=tok123" in invite.html
    assert f"{FRONTEND}/activate?token=tok123" in invite.text
    assert "<b" in invite.html and ">Mentee</b>" in invite.html
    reset = password_reset_email("sample@example.com", "Sample", "reset123")
    assert f"{FRONTEND}/reset-password?token=reset123" in reset.html
    assert "sample@example.com" in reset.text


def test_invitation_without_role_is_generic():
    assert "You've been invited to the KamiLimu dashboard. " in (
        invitation_email("Sample", "tok").text
    )


def test_no_forge_anywhere(email):
    for part in (email.subject, email.html, email.text):
        assert "forge" not in part.lower()


def test_no_style_blocks_or_classes(email):
    assert "<style" not in email.html.lower()
    assert "class=" not in email.html.lower()


def test_button_is_teal_with_black_text(email):
    button = re.search(r'<td bgcolor="#00b4c2"[^>]*><a [^>]*>', email.html)
    assert button
    assert "background: #00b4c2" in button.group(0)
    assert "color: #050505" in button.group(0)


def test_text_part_has_button_url(email):
    href = re.search(r'<a href="([^"]+)"', email.html)
    assert href
    assert href.group(1).replace("&amp;", "&") in email.text


def test_fallback_link_prints_exact_href(email):
    href = re.search(r'<a href="([^"]+)"', email.html).group(1)
    assert f'word-break: break-all">{href}</span>' in email.html


@pytest.mark.parametrize(
    "pattern",
    [
        r"<script",
        r"<form",
        r"<iframe",
        r"<svg",
        r"<style",
        r"<link",
        r"data:",
        r"javascript:",
        r"display\s*:\s*none",
        r"\son[a-z]+\s*=",
    ],
)
def test_no_unsafe_markup(email, pattern):
    assert not re.search(pattern, email.html, re.IGNORECASE)


def test_urls_are_https_on_frontend(email):
    urls = re.findall(r'(?:href|src)="([^"]+)"', email.html)
    assert urls
    for url in urls:
        assert url.startswith(f"{FRONTEND}/")


def test_images_have_alt(email):
    images = re.findall(r"<img [^>]*>", email.html)
    assert len(images) == 2
    for img in images:
        assert re.search(r'alt="[^"]+"', img)


def test_document_shell(email):
    assert email.html.startswith("<!DOCTYPE html>")
    assert '<html lang="en">' in email.html
    assert '<meta name="color-scheme" content="light">' in email.html
    assert f"<title>{email.subject.replace(chr(39), '&#x27;')}</title>" in email.html


def test_size_and_text_part(email):
    assert len(email.html.encode()) < 60_000
    assert email.text.strip()
