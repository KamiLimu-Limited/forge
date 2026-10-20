"""Transactional email delivery via Resend."""

import html
import logging
from dataclasses import dataclass

import resend
from starlette.concurrency import run_in_threadpool

from forge.core.config import settings

logger = logging.getLogger(__name__)

FOOTER = "KamiLimu - Forging the next generation of tech professionals"


@dataclass(frozen=True)
class EmailContent:
    subject: str
    html: str
    text: str


def render_email(
    *,
    subject: str,
    heading: str,
    first_name: str,
    paragraphs: list[str],
    action: tuple[str, str] | None = None,
    notes: list[str] | None = None,
) -> EmailContent:
    """Render the shared branded layout as HTML and plain text."""
    esc = html.escape
    body = "".join(f"<p>{esc(p)}</p>" for p in paragraphs)
    if action:
        label, url = action
        body += (
            '<div style="text-align:center;margin:30px 0;">'
            f'<a href="{esc(url)}" style="background:#667eea;color:white;padding:14px 28px;'
            'text-decoration:none;border-radius:6px;font-weight:600;display:inline-block;">'
            f"{esc(label)}</a></div>"
        )
    body += "".join(
        f'<p style="color:#666;font-size:14px;">{esc(n)}</p>' for n in notes or []
    )
    html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;line-height:1.6;color:#333;max-width:600px;margin:0 auto;padding:20px;">
<div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:30px;border-radius:10px 10px 0 0;">
<h1 style="color:white;margin:0;font-size:24px;">{esc(heading)}</h1></div>
<div style="background:#f9f9f9;padding:30px;border-radius:0 0 10px 10px;">
<p>Hi {esc(first_name)},</p>{body}
<hr style="border:none;border-top:1px solid #eee;margin:30px 0;">
<p style="color:#999;font-size:12px;">{FOOTER}</p></div></body></html>"""

    lines = [heading, "", f"Hi {first_name},", "", *paragraphs]
    if action:
        lines += ["", f"{action[0]}: {action[1]}"]
    lines += ["", *(notes or []), "", "--", FOOTER]
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
    response = await run_in_threadpool(resend.Emails.send, params)
    logger.info("Email sent to %s", to)
    return response


async def send_invitation_email(
    to: str, first_name: str, invitation_token: str
) -> None:
    url = f"{settings.frontend_base_url}/activate?token={invitation_token}"
    await send_email(
        to,
        render_email(
            subject="You're Invited to KamiLimu Forge",
            heading="Welcome to KamiLimu Forge",
            first_name=first_name,
            paragraphs=[
                "You have been invited to join the KamiLimu Forge platform. "
                "Activate your account and set your password to get started."
            ],
            action=("Activate Account", url),
            notes=[
                f"This invitation link will expire in {settings.INVITATION_TOKEN_EXPIRE_DAYS} days.",
                "If you didn't expect this invitation, you can safely ignore this email.",
            ],
        ),
    )


async def send_password_reset_email(to: str, first_name: str, reset_token: str) -> None:
    url = f"{settings.frontend_base_url}/reset-password?token={reset_token}"
    await send_email(
        to,
        render_email(
            subject="Reset Your KamiLimu Forge Password",
            heading="Password Reset Request",
            first_name=first_name,
            paragraphs=[
                "We received a request to reset the password for your KamiLimu Forge "
                "account. Use the button below to set a new password."
            ],
            action=("Reset Password", url),
            notes=[
                f"This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS} hours.",
                "If you didn't request a password reset, you can safely ignore this email.",
            ],
        ),
    )
