"""Async email delivery via Resend (preferred) or SMTP (fallback).

Priority:
1. RESEND_API_KEY set → use Resend HTTP API
2. SMTP_HOST set → use SMTP
3. Neither → log the email body (local dev)
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def _send_resend(*, to: str, subject: str, html: str) -> None:
    """Deliver via Resend HTTP API."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.mail_from,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=10.0,
        )
        resp.raise_for_status()


async def _send_smtp(*, to: str, subject: str, html: str) -> None:
    """Deliver via SMTP."""
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


async def send_email(*, to: str, subject: str, html: str) -> None:
    """Send an HTML email to *to*.

    Uses Resend if configured, falls back to SMTP, then to logging.
    """
    if settings.resend_api_key:
        try:
            await _send_resend(to=to, subject=subject, html=html)
            logger.info("email_sent", extra={"to": to, "subject": subject, "provider": "resend"})
            return
        except Exception:
            logger.exception("email_send_failed", extra={"to": to, "subject": subject, "provider": "resend"})
            raise

    if settings.smtp_host:
        try:
            await _send_smtp(to=to, subject=subject, html=html)
            logger.info("email_sent", extra={"to": to, "subject": subject, "provider": "smtp"})
            return
        except Exception:
            logger.exception("email_send_failed", extra={"to": to, "subject": subject, "provider": "smtp"})
            raise

    logger.warning(
        "email_not_sent (no email provider configured)",
        extra={"to": to, "subject": subject},
    )
    logger.debug("email_body", extra={"html": html})


# ---------------------------------------------------------------------------
# Pre-built email helpers
# ---------------------------------------------------------------------------

async def send_password_reset_email(*, to: str, token: str, base_url: str | None = None) -> None:
    """Send a password-reset email with a link containing *token*."""
    base = (base_url or settings.frontend_url).rstrip("/")
    reset_url = f"{base}/auth/reset-password?token={token}"
    html = f"""\
<h2>Reset your password</h2>
<p>Click the link below to choose a new password. This link expires in 30 minutes.</p>
<p><a href="{reset_url}">{reset_url}</a></p>
<p>If you didn't request this, you can safely ignore this email.</p>
"""
    await send_email(to=to, subject="Reset your password", html=html)


async def send_magic_link_email(*, to: str, token: str, base_url: str | None = None) -> None:
    """Send a magic-link login email."""
    base = (base_url or settings.frontend_url).rstrip("/")
    login_url = f"{base}/auth/magic-link?token={token}"
    html = f"""\
<h2>Sign in to TradeLens</h2>
<p>Click the link below to sign in. This link expires in 15 minutes.</p>
<p><a href="{login_url}">{login_url}</a></p>
<p>If you didn't request this, you can safely ignore this email.</p>
"""
    await send_email(to=to, subject="Your sign-in link", html=html)
