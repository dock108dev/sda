"""Unit tests for the transactional email service (ISSUE-017).

All tests use mock transports — no live SMTP or SES connections are made.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _settings(**overrides):
    """Return a MagicMock settings object with sensible defaults."""
    s = MagicMock()
    s.email_backend = "smtp"
    s.smtp_host = "localhost"
    s.smtp_port = 1025
    s.smtp_user = None
    s.smtp_password = None
    s.smtp_use_tls = False
    s.mail_from = "test@example.com"
    s.frontend_url = "http://localhost:3000"
    s.aws_region = "us-east-1"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# Startup validation — EMAIL_BACKEND
# ---------------------------------------------------------------------------


class TestEmailBackendValidation:
    """Settings model validator rejects unknown EMAIL_BACKEND values at startup."""

    def test_invalid_backend_raises_validation_error(self) -> None:
        from app.config import Settings

        with pytest.raises((ValueError, ValidationError)):
            Settings(
                _env_file=None,
                DATABASE_URL="postgresql://test:test@localhost/test",
                EMAIL_BACKEND="invalid_backend",
            )

    def test_smtp_backend_is_valid(self) -> None:
        from app.config import Settings

        s = Settings(
            _env_file=None,
            DATABASE_URL="postgresql://test:test@localhost/test",
            EMAIL_BACKEND="smtp",
        )
        assert s.email_backend == "smtp"

    def test_ses_backend_is_valid(self) -> None:
        from app.config import Settings

        s = Settings(
            _env_file=None,
            DATABASE_URL="postgresql://test:test@localhost/test",
            EMAIL_BACKEND="ses",
        )
        assert s.email_backend == "ses"


# ---------------------------------------------------------------------------
# SMTP backend
# ---------------------------------------------------------------------------


class TestSMTPBackend:

    def test_send_smtp_invokes_aiosmtplib(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings(email_backend="smtp")
        sent: list[dict] = []

        async def _fake_send(msg, **kwargs):
            sent.append({"subject": msg["Subject"], "to": msg["To"]})

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_email(
                    to="user@example.com",
                    subject="Test subject",
                    html="<p>hello</p>",
                )
            )

        assert len(sent) == 1
        assert sent[0]["subject"] == "Test subject"
        assert sent[0]["to"] == "user@example.com"

    def test_send_smtp_uses_configured_credentials(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings(
            email_backend="smtp",
            smtp_host="mail.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
            smtp_use_tls=True,
        )
        call_kwargs: list[dict] = []

        async def _capture(msg, **kwargs):
            call_kwargs.append(kwargs)

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_capture),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_email(
                    to="a@b.com",
                    subject="s",
                    html="<p>h</p>",
                )
            )

        assert call_kwargs[0]["hostname"] == "mail.example.com"
        assert call_kwargs[0]["port"] == 587
        assert call_kwargs[0]["start_tls"] is True


# ---------------------------------------------------------------------------
# SES backend
# ---------------------------------------------------------------------------


class TestSESBackend:

    def test_send_ses_calls_boto3(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings(email_backend="ses", aws_region="us-west-2")
        ses_calls: list[dict] = []

        mock_client = MagicMock()
        mock_client.send_email = MagicMock(
            side_effect=lambda **kw: ses_calls.append(kw)
        )

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("boto3.client", return_value=mock_client),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_email(
                    to="dest@example.com",
                    subject="SES subject",
                    html="<p>ses</p>",
                )
            )

        assert len(ses_calls) == 1
        assert ses_calls[0]["Destination"] == {"ToAddresses": ["dest@example.com"]}
        assert ses_calls[0]["Message"]["Subject"]["Data"] == "SES subject"

    def test_send_ses_uses_configured_region(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings(email_backend="ses", aws_region="eu-west-1")
        client_calls: list[tuple] = []

        def _fake_client(service, *, region_name, **kw):
            client_calls.append((service, region_name))
            m = MagicMock()
            m.send_email = MagicMock()
            return m

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("boto3.client", side_effect=_fake_client),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_email(
                    to="x@y.com", subject="s", html="<p>h</p>"
                )
            )

        assert client_calls[0] == ("ses", "eu-west-1")


# ---------------------------------------------------------------------------
# Magic-link template
# ---------------------------------------------------------------------------


class TestMagicLinkEmail:

    def test_magic_link_contains_token_url(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        captured: list[dict] = []

        async def _fake_send(msg, **kw):
            captured.append({"subject": msg["Subject"], "html": msg.get_content()})

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_magic_link_email(
                    to="user@example.com",
                    token="abc123",
                )
            )

        assert len(captured) == 1
        assert captured[0]["subject"] == "Your sign-in link"
        assert "abc123" in captured[0]["html"]
        assert "/auth/magic-link" in captured[0]["html"]

    def test_magic_link_respects_base_url_override(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        captured: list[str] = []

        async def _fake_send(msg, **kw):
            captured.append(msg.get_content())

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_magic_link_email(
                    to="user@example.com",
                    token="tok",
                    base_url="https://custom.example.com",
                )
            )

        assert "custom.example.com" in captured[0]

    def test_magic_link_subject(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        subjects: list[str] = []

        async def _fake_send(msg, **kw):
            subjects.append(msg["Subject"])

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(email_mod.send_magic_link_email(to="u@e.com", token="t"))

        assert subjects[0] == "Your sign-in link"


# ---------------------------------------------------------------------------
# Payment confirmation template
# ---------------------------------------------------------------------------


class TestPaymentConfirmationEmail:

    def test_payment_confirmation_contains_plan_id(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        captured: list[str] = []

        async def _fake_send(msg, **kw):
            captured.append(msg.get_content())

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_payment_confirmation_email(
                    to="buyer@example.com",
                    plan_id="price_pro",
                )
            )

        assert "price_pro" in captured[0]

    def test_payment_confirmation_subject(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        subjects: list[str] = []

        async def _fake_send(msg, **kw):
            subjects.append(msg["Subject"])

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(email_mod.send_payment_confirmation_email(to="b@e.com"))

        assert subjects[0] == "Payment confirmed"


# ---------------------------------------------------------------------------
# Welcome template
# ---------------------------------------------------------------------------


class TestWelcomeEmail:

    def test_welcome_contains_club_name_and_url(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings(frontend_url="https://app.example.com")
        captured: list[str] = []

        async def _fake_send(msg, **kw):
            captured.append(msg.get_content())

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_welcome_email(
                    to="owner@example.com",
                    club_name="Pebble Beach GC",
                    slug="pebble-beach-gc",
                )
            )

        body = captured[0]
        assert "Pebble Beach GC" in body
        assert "pebble-beach-gc" in body
        assert "app.example.com" in body

    def test_welcome_subject_includes_club_name(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        subjects: list[str] = []

        async def _fake_send(msg, **kw):
            subjects.append(msg["Subject"])

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit"),
        ):
            _run(
                email_mod.send_welcome_email(
                    to="o@e.com",
                    club_name="Augusta National",
                    slug="augusta-national",
                )
            )

        assert "Augusta National" in subjects[0]


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


class TestAuditLogging:

    def test_send_email_emits_audit_event(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        emit_calls: list[tuple] = []

        def _fake_emit(event_type, **kw):
            emit_calls.append((event_type, kw))

        async def _fake_send(msg, **kw):
            pass

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit", side_effect=_fake_emit),
        ):
            _run(
                email_mod.send_email(
                    to="audit@example.com",
                    subject="Audit test",
                    html="<p>hi</p>",
                    template_name="test_template",
                )
            )

        assert len(emit_calls) == 1
        event_type, kwargs = emit_calls[0]
        assert event_type == "email_sent"
        assert kwargs["resource_id"] == "audit@example.com"
        assert kwargs["payload"]["template_name"] == "test_template"
        assert kwargs["payload"]["recipient"] == "audit@example.com"

    def test_audit_event_not_emitted_on_send_failure(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        emit_calls: list[str] = []

        async def _fail_send(msg, **kw):
            raise OSError("connection refused")

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fail_send),
            patch.object(email_mod.audit, "emit", side_effect=lambda *a, **k: emit_calls.append(a[0])),
        ):
            with pytest.raises(OSError):
                _run(
                    email_mod.send_email(
                        to="x@y.com",
                        subject="s",
                        html="<p>h</p>",
                    )
                )

        assert emit_calls == []

    def test_magic_link_audit_uses_correct_template_name(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        emit_calls: list[dict] = []

        def _fake_emit(event_type, **kw):
            emit_calls.append({"event_type": event_type, **kw})

        async def _fake_send(msg, **kw):
            pass

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit", side_effect=_fake_emit),
        ):
            _run(email_mod.send_magic_link_email(to="u@e.com", token="tok123"))

        assert emit_calls[0]["event_type"] == "email_sent"
        assert emit_calls[0]["payload"]["template_name"] == "magic_link"

    def test_payment_confirmation_audit_uses_correct_template_name(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        emit_calls: list[dict] = []

        def _fake_emit(event_type, **kw):
            emit_calls.append({"event_type": event_type, **kw})

        async def _fake_send(msg, **kw):
            pass

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit", side_effect=_fake_emit),
        ):
            _run(email_mod.send_payment_confirmation_email(to="p@e.com"))

        assert emit_calls[0]["payload"]["template_name"] == "payment_confirmation"

    def test_welcome_audit_uses_correct_template_name(self) -> None:
        from app.services import email as email_mod

        mock_settings = _settings()
        emit_calls: list[dict] = []

        def _fake_emit(event_type, **kw):
            emit_calls.append({"event_type": event_type, **kw})

        async def _fake_send(msg, **kw):
            pass

        with (
            patch.object(email_mod, "settings", mock_settings),
            patch("aiosmtplib.send", side_effect=_fake_send),
            patch.object(email_mod.audit, "emit", side_effect=_fake_emit),
        ):
            _run(
                email_mod.send_welcome_email(
                    to="w@e.com",
                    club_name="Test Club",
                    slug="test-club",
                )
            )

        assert emit_calls[0]["payload"]["template_name"] == "welcome"


# ---------------------------------------------------------------------------
# Integration points: webhook dispatches payment email
# ---------------------------------------------------------------------------


class TestWebhookEmailDispatch:
    """Verify the webhook handler schedules a payment confirmation email."""

    def _make_checkout_event(
        self,
        checkout_id: str = "cs_test",
        customer_email: str | None = "buyer@example.com",
    ) -> SimpleNamespace:
        obj = SimpleNamespace(id=checkout_id, customer_email=customer_email)
        event = SimpleNamespace()
        event.type = "checkout.session.completed"
        event.id = "evt_test"
        event.data = SimpleNamespace(object=obj)
        return event

    def test_checkout_completed_dispatches_email_when_customer_email_present(
        self,
    ) -> None:
        from unittest.mock import AsyncMock, patch

        from app.routers import webhooks

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(rowcount=1))

        dispatched: list[str] = []

        async def _fake_payment_email(*, to: str, plan_id: str = "") -> None:
            dispatched.append(to)

        event = self._make_checkout_event(customer_email="buyer@example.com")

        async def _run_handler() -> None:
            with patch.object(
                webhooks, "send_payment_confirmation_email", side_effect=_fake_payment_email
            ):
                await webhooks._handle_checkout_completed(db, event)
                # Allow tasks to run
                await asyncio.sleep(0)

        asyncio.run(_run_handler())
        assert "buyer@example.com" in dispatched

    def test_checkout_completed_skips_email_when_no_customer_email(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.routers import webhooks

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(rowcount=1))

        dispatched: list[str] = []

        async def _fake_payment_email(*, to: str, plan_id: str = "") -> None:
            dispatched.append(to)

        event = self._make_checkout_event(customer_email=None)

        async def _run_handler() -> None:
            with patch.object(
                webhooks, "send_payment_confirmation_email", side_effect=_fake_payment_email
            ):
                await webhooks._handle_checkout_completed(db, event)
                await asyncio.sleep(0)

        asyncio.run(_run_handler())
        assert dispatched == []

    def test_checkout_completed_uses_customer_details_email_as_fallback(
        self,
    ) -> None:
        from unittest.mock import AsyncMock, patch

        from app.routers import webhooks

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(rowcount=1))

        dispatched: list[str] = []

        async def _fake_payment_email(*, to: str, plan_id: str = "") -> None:
            dispatched.append(to)

        obj = SimpleNamespace(
            id="cs_fallback",
            customer_email=None,
            customer_details=SimpleNamespace(email="fallback@example.com"),
        )
        event = SimpleNamespace(
            type="checkout.session.completed",
            id="evt_fallback",
            data=SimpleNamespace(object=obj),
        )

        async def _run_handler() -> None:
            with patch.object(
                webhooks, "send_payment_confirmation_email", side_effect=_fake_payment_email
            ):
                await webhooks._handle_checkout_completed(db, event)
                await asyncio.sleep(0)

        asyncio.run(_run_handler())
        assert "fallback@example.com" in dispatched


# ---------------------------------------------------------------------------
# Integration point: provisioning dispatches welcome email
# ---------------------------------------------------------------------------


class TestProvisioningWelcomeEmail:
    """Verify provisioning dispatches welcome email exactly once for new clubs."""

    def _run(self, coro):  # type: ignore[no-untyped-def]
        return asyncio.run(coro)

    def _make_result(
        self,
        scalar=None,
        scalar_one=None,
        rowcount: int | None = None,
    ) -> MagicMock:
        r = MagicMock()
        r.scalar_one_or_none.return_value = scalar
        r.scalar_one.return_value = scalar_one if scalar_one is not None else scalar
        if rowcount is not None:
            r.rowcount = rowcount
        return r

    def _make_db(self, *results: MagicMock):  # type: ignore[no-untyped-def]
        class _DB:
            def __init__(self, *rs):
                self._q = list(rs)
                self.added = []
                self.flushed = False

            async def execute(self, _):
                return self._q.pop(0)

            def add(self, obj):
                self.added.append(obj)

            async def flush(self):
                self.flushed = True

        return _DB(*results)

    def test_welcome_email_dispatched_on_new_club(self) -> None:
        from app.db.club import Club
        from app.db.golf_pools import GolfPool
        from app.db.onboarding import ClubClaim, OnboardingSession
        from app.db.users import User
        from app.services import provisioning as prov_mod

        session = OnboardingSession(
            claim_id="claim_abc",
            session_token="sess_xyz",
            stripe_checkout_session_id="cs_001",
            plan_id="price_pro",
            status="claimed",
        )
        claim = ClubClaim(
            claim_id="claim_abc",
            club_name="Augusta National",
            contact_email="owner@augusta.example",
            status="new",
        )
        user = User(email="owner@augusta.example", role="club_admin", is_active=True)
        user.id = 1

        club = Club(
            club_id="uuid-1",
            slug="augusta-national",
            name="Augusta National",
            plan_id="price_pro",
            status="active",
            owner_user_id=1,
        )
        club.id = 1

        db = self._make_db(
            self._make_result(scalar=session),
            self._make_result(scalar=claim),
            self._make_result(scalar=user),
            self._make_result(rowcount=1),   # new club
            self._make_result(scalar_one=club),
        )

        dispatched: list[dict] = []

        async def _fake_welcome(*, to: str, club_name: str, slug: str) -> None:
            dispatched.append({"to": to, "club_name": club_name, "slug": slug})

        async def _run_provision() -> None:
            with patch.object(prov_mod, "send_welcome_email", side_effect=_fake_welcome):
                await prov_mod.ClubProvisioningService().provision(db, "claim_abc")
                await asyncio.sleep(0)

        self._run(_run_provision())

        assert len(dispatched) == 1
        assert dispatched[0]["to"] == "owner@augusta.example"
        assert dispatched[0]["club_name"] == "Augusta National"

    def test_welcome_email_not_dispatched_on_duplicate_provision(self) -> None:
        from app.db.club import Club
        from app.db.onboarding import ClubClaim, OnboardingSession
        from app.db.users import User
        from app.services import provisioning as prov_mod

        session = OnboardingSession(
            claim_id="claim_abc",
            session_token="sess_xyz",
            stripe_checkout_session_id="cs_001",
            plan_id="price_pro",
            status="claimed",
        )
        claim = ClubClaim(
            claim_id="claim_abc",
            club_name="Augusta National",
            contact_email="owner@augusta.example",
            status="new",
        )
        user = User(email="owner@augusta.example", role="club_admin", is_active=True)
        user.id = 1
        club = Club(
            club_id="uuid-1",
            slug="augusta-national",
            name="Augusta National",
            plan_id="price_pro",
            status="active",
            owner_user_id=1,
        )
        club.id = 1

        db = self._make_db(
            self._make_result(scalar=session),
            self._make_result(scalar=claim),
            self._make_result(scalar=user),
            self._make_result(rowcount=0),   # existing club — no new insert
            self._make_result(scalar_one=club),
        )

        dispatched: list[dict] = []

        async def _fake_welcome(*, to: str, club_name: str, slug: str) -> None:
            dispatched.append({"to": to})

        async def _run_provision() -> None:
            with patch.object(prov_mod, "send_welcome_email", side_effect=_fake_welcome):
                await prov_mod.ClubProvisioningService().provision(db, "claim_abc")
                await asyncio.sleep(0)

        self._run(_run_provision())

        assert dispatched == []
