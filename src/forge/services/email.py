"""Transactional email delivery via Resend."""

import html
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

import resend
from starlette.concurrency import run_in_threadpool

from forge.core.config import settings

logger = logging.getLogger(__name__)

PAGE_BG = "#f8f9f0"
BORDER = "#dde0d6"
INK = "#050505"
BODY = "#444444"
MUTED = "#666666"
TEAL = "#00b4c2"
LINK = "#007f8a"
MONO = "'JetBrains Mono', 'Courier New', monospace"
SANS = "'Hind Guntur', Arial, Helvetica, sans-serif"

# The wordmark PNG is 1152x186; Outlook needs both dimensions to avoid stretching it.
LOGO_RATIO = 1152 / 186

TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'


class Strong(str):
    """A paragraph segment rendered in bold ink."""


Paragraph = str | Sequence[str]


class Detail(NamedTuple):
    label: str
    value: str
    struck: bool = False


@dataclass(frozen=True)
class EmailContent:
    subject: str
    html: str
    text: str


def _segments(paragraph: Paragraph) -> list[str]:
    return [paragraph] if isinstance(paragraph, str) else list(paragraph)


def _paragraph_html(paragraph: Paragraph) -> str:
    inner = "".join(
        f'<b style="color: {INK}">{html.escape(s)}</b>'
        if isinstance(s, Strong)
        else html.escape(s)
        for s in _segments(paragraph)
    )
    return (
        f'<p style="margin: 0 0 14px; font-family: {SANS}; font-size: 16px; '
        f'line-height: 1.6; color: {BODY}">{inner}</p>'
    )


def _logo(height: int, style: str) -> str:
    width = round(height * LOGO_RATIO)
    return (
        f'<img src="{html.escape(settings.email_logo_url)}" alt="KamiLimu" '
        f'width="{width}" height="{height}" style="height: {height}px; '
        f'width: {width}px; border: 0; display: block; {style}">'
    )


def _details_html(rows: Sequence[Detail]) -> str:
    cells = []
    for row in rows:
        value = html.escape(row.value)
        if row.struck:
            value = (
                f'<span style="text-decoration: line-through; color: {MUTED}; '
                f'font-weight: 400">{value}</span>'
            )
        cells.append(
            f'<tr><td width="120" style="padding: 6px 0; font-family: {SANS}; '
            f'font-size: 14px; color: {MUTED}; width: 120px; vertical-align: top">'
            f"{html.escape(row.label)}</td>"
            f'<td style="padding: 6px 0; font-family: {SANS}; font-size: 15px; '
            f'color: {INK}; font-weight: 600">{value}</td></tr>'
        )
    return (
        f'<table {TABLE} width="100%" bgcolor="{PAGE_BG}" style="background: '
        f'{PAGE_BG}; border-radius: 10px; margin: 20px 0"><tr><td style="padding: '
        f'14px 20px"><table {TABLE} width="100%">{"".join(cells)}</table>'
        "</td></tr></table>"
    )


def _quote_html(label: str, text: str) -> str:
    return (
        f'<table {TABLE} width="100%" style="margin: 20px 0"><tr><td style="'
        f'border-left: 3px solid {TEAL}; padding: 4px 0 4px 16px">'
        f'<div style="font-family: {SANS}; font-size: 13px; color: {MUTED}">'
        f"{html.escape(label)}</div>"
        f'<div style="font-family: {SANS}; font-size: 15px; color: {INK}; '
        f'margin-top: 2px">{html.escape(text)}</div></td></tr></table>'
    )


def _button_html(label: str, url: str) -> str:
    href = html.escape(url)
    return (
        f'<table {TABLE} style="margin: 24px 0 8px"><tr><td bgcolor="{TEAL}" '
        f'style="background: {TEAL}; border-radius: 10px">'
        f'<a href="{href}" style="display: inline-block; padding: 14px 26px; '
        f"background: {TEAL}; border-radius: 10px; font-family: {MONO}; "
        f'font-size: 15px; font-weight: 600; color: {INK}; text-decoration: none">'
        f"{html.escape(label)}</a></td></tr></table>"
        f'<p style="margin: 0 0 4px; font-family: {SANS}; font-size: 13px; '
        f'color: {MUTED}">Button not working? Copy this link into your browser:<br>'
        f'<span style="color: {LINK}; word-break: break-all">{href}</span></p>'
    )


def render_email(
    *,
    subject: str,
    heading: str,
    first_name: str,
    paragraphs: Sequence[Paragraph],
    action: tuple[str, str] | None = None,
    notes: Sequence[str] | None = None,
    details: Sequence[Detail | tuple[str, str]] | None = None,
    quote: tuple[str, str] | None = None,
    paragraphs_after: Sequence[Paragraph] | None = None,
    footer_reason: str = "You're getting this because you have a KamiLimu account.",
) -> EmailContent:
    """Render the shared branded layout as HTML and plain text.

    Every argument is treated as text and escaped; ``Strong`` segments inside a
    paragraph are bolded and ``Detail(struck=True)`` rows are struck through.
    """
    esc = html.escape
    rows = [r if isinstance(r, Detail) else Detail(*r) for r in details or []]

    card = [
        f'<h1 style="margin: 0 0 18px; font-family: {MONO}; font-size: 22px; '
        f'line-height: 1.3; font-weight: 600; color: {INK}">{esc(heading)}</h1>',
        _paragraph_html(f"Hi {first_name},"),
        *(_paragraph_html(p) for p in paragraphs),
    ]
    if rows:
        card.append(_details_html(rows))
    if quote:
        card.append(_quote_html(*quote))
    card += [_paragraph_html(p) for p in paragraphs_after or []]
    if action:
        card.append(_button_html(*action))
    card += [
        f'<p style="margin: 0 0 14px; font-family: {SANS}; font-size: 14px; '
        f'line-height: 1.6; color: {MUTED}">{esc(n)}</p>'
        for n in notes or []
    ]

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{esc(subject)}</title>
</head>
<body bgcolor="{PAGE_BG}" style="margin: 0; padding: 0; background: {PAGE_BG}">
<table {TABLE} width="100%" bgcolor="{PAGE_BG}" style="background: {PAGE_BG}">
<tr><td align="center" style="padding: 32px 16px">
<table {TABLE} width="560" style="width: 100%; max-width: 560px">
<tr><td style="padding: 0 4px 20px">{_logo(28, "")}</td></tr>
<tr><td bgcolor="#ffffff" style="background: #ffffff; border: 1px solid {BORDER}; border-radius: 12px; padding: 32px 32px 24px">
{"".join(card)}
</td></tr>
<tr><td align="center" style="padding: 20px 8px 0; font-family: {SANS}; font-size: 13px; line-height: 1.6; color: {MUTED}; text-align: center">
{_logo(18, "margin: 0 auto 6px")}{esc(footer_reason)}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

    lines = [heading, "", f"Hi {first_name},", ""]
    lines += ["".join(_segments(p)) + "\n" for p in paragraphs]
    if rows:
        lines += [*(f"{r.label}: {r.value}" for r in rows), ""]
    if quote:
        lines += [f'{quote[0]}: "{quote[1]}"', ""]
    lines += ["".join(_segments(p)) + "\n" for p in paragraphs_after or []]
    if action:
        lines += [f"{action[0]}: {action[1]}", ""]
    lines += [f"{n}\n" for n in notes or []]
    lines += ["--", footer_reason, "KamiLimu"]
    return EmailContent(subject=subject, html=html_doc, text="\n".join(lines))


async def send_email(
    to: str | list[str], content: EmailContent
) -> resend.Emails.SendResponse | None:
    """Send an email; returns ``None`` when no email provider is configured."""
    if not settings.RESEND_API_KEY:
        logger.warning("Email service not configured, skipping email to %s", to)
        return None

    resend.api_key = settings.RESEND_API_KEY
    params: resend.Emails.SendParams = {
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
        "to": [to] if isinstance(to, str) else to,
        "subject": content.subject,
        "html": content.html,
        "text": content.text,
    }
    if settings.EMAIL_REPLY_TO:
        params["reply_to"] = settings.EMAIL_REPLY_TO
    response = await run_in_threadpool(resend.Emails.send, params)
    logger.info("Email sent to %s", to)
    return response


# Mirrors ROLE_LABELS in the frontend so emails name roles the way the app does.
ROLE_LABELS = {
    "mentee": "Mentee",
    "peer_mentor_1:1": "1:1 Peer Mentor",
    "peer_mentor_ict": "ICT Peer Mentor",
    "professional_mentor": "Professional Mentor",
    "committee": "Committee",
    "partner": "Partner",
    "alumni": "Alumni",
    "admin": "System Admin",
}


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


def _invitation_sentence(roles: Sequence[str], cohort_name: str | None) -> list[str]:
    labels = [ROLE_LABELS.get(r, r.replace("_", " ").title()) for r in roles]
    if not labels:
        return ["You've been invited to the KamiLimu dashboard. "]
    article = "an" if labels[0][0] in "AEIOU" else "a"
    parts = ["You've been invited to the KamiLimu dashboard as ", f"{article} "]
    for i, label in enumerate(labels):
        if i:
            parts.append(" and " if i == len(labels) - 1 else ", ")
        parts.append(Strong(label))
    if cohort_name:
        parts += [" in ", Strong(cohort_name)]
    parts.append(". ")
    return parts


def invitation_email(
    first_name: str,
    invitation_token: str,
    roles: Sequence[str] = (),
    cohort_name: str | None = None,
) -> EmailContent:
    url = f"{settings.frontend_base_url}/activate?token={invitation_token}"
    paragraph = _invitation_sentence(roles, cohort_name)
    paragraph.append("Set a password to activate your account.")
    if "mentee" in roles:
        paragraph.append(
            " You'll use it to record attendance, log activities and follow your "
            "progress through the programme."
        )
    expiry = _plural(settings.INVITATION_TOKEN_EXPIRE_DAYS, "day")
    return render_email(
        subject="You're invited to KamiLimu",
        heading="Activate your KamiLimu account",
        first_name=first_name,
        paragraphs=[paragraph],
        action=("Activate account", url),
        notes=[
            f"This link expires in {expiry}. If you weren't expecting this "
            "invitation, you can ignore this email."
        ],
        footer_reason="You're getting this because a KamiLimu admin invited this address.",
    )


def password_reset_email(to: str, first_name: str, reset_token: str) -> EmailContent:
    url = f"{settings.frontend_base_url}/reset-password?token={reset_token}"
    expiry = _plural(settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS, "hour")
    return render_email(
        subject="Reset your KamiLimu password",
        heading="Reset your password",
        first_name=first_name,
        paragraphs=[f"We got a request to reset the password for {to}."],
        action=("Choose a new password", url),
        notes=[
            f"This link expires in {expiry} and works once. If you didn't ask for "
            "a reset, ignore this email and your password stays the same."
        ],
        footer_reason="You're getting this because you have a KamiLimu account.",
    )


async def send_invitation_email(
    to: str,
    first_name: str,
    invitation_token: str,
    roles: Sequence[str] = (),
    cohort_name: str | None = None,
) -> None:
    await send_email(
        to, invitation_email(first_name, invitation_token, roles, cohort_name)
    )


async def send_password_reset_email(to: str, first_name: str, reset_token: str) -> None:
    await send_email(to, password_reset_email(to, first_name, reset_token))
