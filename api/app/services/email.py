"""Transactional email service.

Backend selection via EMAIL_BACKEND env var:
  smtp — aiosmtplib SMTP transport
  ses  — AWS SES via boto3 (runs in a thread pool to avoid blocking)

All sends emit an audit event with event_type='email_sent'.
Call send_email() directly to await delivery, or use asyncio.create_task()
for fire-and-forget dispatching on hot paths (webhooks, provisioning).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

import app.services.audit as audit
from app.config import settings

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "email"

# Initialized once; FileSystemLoader raises at template-render time if a
# template is missing, not at module import.
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _render(template_name: str, context: dict) -> str:  # type: ignore[type-arg]
    return _jinja_env.get_template(template_name).render(**context)


# ---------------------------------------------------------------------------
# Backend transports
# ---------------------------------------------------------------------------


async def _send_smtp(*, to: str, subject: str, html: str) -> None:
    """Deliver via SMTP using aiosmtplib."""
    import aiosmtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(html, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=settings.smtp_use_tls,
    )


async def _send_ses(*, to: str, subject: str, html: str) -> None:
    """Deliver via AWS SES using boto3 in a thread pool."""
    import boto3

    def _do_send() -> None:
        client = boto3.client("ses", region_name=settings.aws_region)
        client.send_email(
            Source=settings.mail_from,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Html": {"Data": html}},
            },
        )

    await asyncio.to_thread(_do_send)


# ---------------------------------------------------------------------------
# Core send
# ---------------------------------------------------------------------------


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    template_name: str = "custom",
) -> None:
    """Send an HTML email and emit an audit event on success.

    Raises on delivery failure — callers that want fire-and-forget should
    wrap this in asyncio.create_task().
    """
    backend = settings.email_backend
    try:
        if backend == "smtp":
            await _send_smtp(to=to, subject=subject, html=html)
        else:  # ses
            await _send_ses(to=to, subject=subject, html=html)
    except Exception:
        logger.exception(
            "email_send_failed",
            extra={"to": to, "template": template_name, "backend": backend},
        )
        raise

    logger.info(
        "email_sent",
        extra={"to": to, "template": template_name, "backend": backend},
    )
    audit.emit(
        "email_sent",
        actor_type="system",
        resource_type="email",
        resource_id=to,
        payload={"template_name": template_name, "recipient": to, "subject": subject},
    )


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------


async def send_magic_link_email(
    *, to: str, token: str, base_url: str | None = None
) -> None:
    """Send a magic-link login email. Token link expires in 15 minutes."""
    base = (base_url or settings.frontend_url).rstrip("/")
    login_url = f"{base}/auth/magic-link?token={token}"
    html = _render("magic_link.html", {"login_url": login_url})
    await send_email(
        to=to,
        subject="Your sign-in link",
        html=html,
        template_name="magic_link",
    )


async def send_password_reset_email(
    *, to: str, token: str, base_url: str | None = None
) -> None:
    """Send a password-reset email with a link containing *token*."""
    base = (base_url or settings.frontend_url).rstrip("/")
    reset_url = f"{base}/auth/reset-password?token={token}"
    html = f"""\
<h2>Reset your password</h2>
<p>Click the link below to choose a new password. This link expires in 30 minutes.</p>
<p><a href="{reset_url}">{reset_url}</a></p>
<p>If you didn't request this, you can safely ignore this email.</p>
"""
    await send_email(
        to=to,
        subject="Reset your password",
        html=html,
        template_name="password_reset",
    )


async def send_payment_confirmation_email(*, to: str, plan_id: str = "") -> None:
    """Send a payment confirmation email after a successful Stripe checkout."""
    html = _render("payment_confirmation.html", {"plan_id": plan_id})
    await send_email(
        to=to,
        subject="Payment confirmed",
        html=html,
        template_name="payment_confirmation",
    )


async def send_club_invite_email(
    *,
    to: str,
    club_name: str,
    inviter_email: str,
    role: str,
    token: str,
    base_url: str | None = None,
) -> None:
    """Send a club membership invite email with a signed JWT accept link."""
    base = (base_url or settings.frontend_url).rstrip("/")
    accept_url = f"{base}/clubs/invites/{token}/accept"
    html = _render(
        "club_invite.html",
        {
            "club_name": club_name,
            "inviter_email": inviter_email,
            "role": role,
            "accept_url": accept_url,
        },
    )
    await send_email(
        to=to,
        subject=f"You've been invited to join {club_name}",
        html=html,
        template_name="club_invite",
    )


async def send_dunning_email(*, to: str) -> None:
    """Send a dunning email after an invoice payment failure."""
    html = _render("dunning.html", {})
    await send_email(
        to=to,
        subject="Action required: payment failed for your subscription",
        html=html,
        template_name="dunning",
    )


async def send_welcome_email(*, to: str, club_name: str, slug: str) -> None:
    """Send a welcome email after a club is provisioned for the first time."""
    base = settings.frontend_url.rstrip("/")
    club_url = f"{base}/clubs/{slug}"
    html = _render("welcome.html", {"club_name": club_name, "club_url": club_url})
    await send_email(
        to=to,
        subject=f"Welcome — {club_name} is live",
        html=html,
        template_name="welcome",
    )
