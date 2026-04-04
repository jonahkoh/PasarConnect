"""
Unit tests for the Verification Service gRPC handlers.

Strategy:
  - SQLite in-memory database replaces PostgreSQL — no running DB required.
  - The real SQLAlchemy models and grpc_server business logic are tested directly.
  - verification_pb2 / verification_pb2_grpc are mocked; response objects are
    simple attribute-bearing Msg instances so assertions work naturally.
  - grpc context is a lightweight AsyncMock that records abort() calls.

Coverage:
  VerifyCharity    — approved / quota_exceeded / banned / expired_cooldown / appeal_approved
  VerifyPublicUser — approved (no record) / approved (not flagged) / rejected (flagged)
  RecordNoShow     — first/second warning / third triggers ban / escalation / during cooldown
  GetCharityStatus — no record / active ban / live counts / appeal approved
  GetUserStatus    — no record / flagged / not flagged
  GetVendorStatus  — no record / compliant / not compliant / license expired / valid license

Run with:
    pytest backend/tests/test_verification_service.py -v
"""
from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Path setup ────────────────────────────────────────────────────────────────

VERIFICATION_DIR = os.path.join(os.path.dirname(__file__), "..", "verification")
if VERIFICATION_DIR not in sys.path:
    sys.path.insert(0, VERIFICATION_DIR)

# ── Mock pb2 modules before importing grpc_server ─────────────────────────────

class _Msg:
    """Lightweight substitute for generated proto message classes.
    Captures keyword arguments as attributes so assertions work naturally."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
    def __repr__(self):
        return f"Msg({self.__dict__})"


def _make_pb2_mock():
    mock = MagicMock()
    for cls_name in (
        "VerifyResponse",
        "RecordNoShowResponse",
        "CharityStatusResponse",
        "UserStatusResponse",
        "VendorStatusResponse",
    ):
        setattr(mock, cls_name, MagicMock(side_effect=lambda **kw: _Msg(**kw)))
    return mock


class _FakeServicerBase:
    """Real (non-mock) base class so VerificationServicer can inherit without issues."""
    pass


_mock_pb2       = _make_pb2_mock()
_mock_pb2_grpc  = MagicMock()
# Must be a real class, not a MagicMock, so Python metaclass machinery works
_mock_pb2_grpc.VerificationServiceServicer = _FakeServicerBase
sys.modules["verification_pb2"]      = _mock_pb2
sys.modules["verification_pb2_grpc"] = _mock_pb2_grpc

# These modules all live in VERIFICATION_DIR; flush any cached copies first.
for _mod in ("database", "models", "schemas", "grpc_server"):
    sys.modules.pop(_mod, None)

import models       # noqa: E402
import grpc_server  # noqa: E402

# ── In-memory SQLite engine ───────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


async def _make_test_session_factory():
    """Create a fresh in-memory SQLite engine and return its session factory."""
    eng = create_async_engine(TEST_DB_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    return async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False), eng


# ── Mock gRPC context ─────────────────────────────────────────────────────────

class MockContext:
    def __init__(self):
        self.abort = AsyncMock()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def db_session_factory():
    """Fresh in-memory DB per test + patched grpc_server.AsyncSessionLocal."""
    factory, eng = await _make_test_session_factory()
    original = grpc_server.AsyncSessionLocal
    grpc_server.AsyncSessionLocal = factory
    yield factory
    grpc_server.AsyncSessionLocal = original
    await eng.dispose()


@pytest.fixture()
def servicer():
    return grpc_server.VerificationServicer()


@pytest.fixture()
def ctx():
    return MockContext()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC (handles naive datetimes from SQLite)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _seed_charity_standing(factory, charity_id: int, **kwargs) -> models.CharityStanding:
    """Insert a CharityStanding row and return it."""
    async with factory() as db:
        row = models.CharityStanding(charity_id=charity_id, **kwargs)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _seed_user_standing(factory, user_id: int, **kwargs) -> models.PublicUserStanding:
    async with factory() as db:
        row = models.PublicUserStanding(user_id=user_id, **kwargs)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _seed_vendor_compliance(factory, vendor_id: int, **kwargs) -> models.VendorCompliance:
    async with factory() as db:
        row = models.VendorCompliance(vendor_id=vendor_id, **kwargs)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def _add_claims_today(factory, charity_id: int, count: int):
    """Add `count` CharityClaim rows stamped at now UTC."""
    async with factory() as db:
        for i in range(count):
            db.add(models.CharityClaim(charity_id=charity_id, listing_id=i + 1))
        await db.commit()


async def _add_noshows(factory, charity_id: int, count: int, at: datetime | None = None):
    """Add `count` CharityNoShow rows."""
    ts = at or _now()
    async with factory() as db:
        for i in range(count):
            row = models.CharityNoShow(charity_id=charity_id, claim_id=i + 1)
            row.created_at = ts
            db.add(row)
        await db.commit()


def _req(**kwargs):
    """Lightweight request stub."""
    return SimpleNamespace(**kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# VerifyCharity
# ══════════════════════════════════════════════════════════════════════════════

class TestVerifyCharity:

    async def test_approved_no_prior_state(self, servicer, ctx, db_session_factory):
        """No standing row and no claims today → approved, CharityClaim inserted."""
        resp = await servicer.VerifyCharity(_req(charity_id=1, listing_id=10), ctx)
        assert resp.approved is True
        assert resp.rejection_reason == ""
        ctx.abort.assert_not_called()

    async def test_claim_inserted_on_approval(self, servicer, ctx, db_session_factory):
        """Approved call must insert exactly one CharityClaim row."""
        from sqlalchemy import select, func
        await servicer.VerifyCharity(_req(charity_id=2, listing_id=20), ctx)
        async with db_session_factory() as db:
            count = (await db.execute(
                select(func.count(models.CharityClaim.id)).where(
                    models.CharityClaim.charity_id == 2
                )
            )).scalar()
        assert count == 1

    async def test_quota_exceeded(self, servicer, ctx, db_session_factory):
        """Charity with MAX_DAILY_CLAIMS claims today must be rejected QUOTA_EXCEEDED."""
        grpc_server.MAX_DAILY_CLAIMS = 3
        await _add_claims_today(db_session_factory, charity_id=3, count=3)
        resp = await servicer.VerifyCharity(_req(charity_id=3, listing_id=30), ctx)
        assert resp.approved is False
        assert resp.rejection_reason == "QUOTA_EXCEEDED"
        grpc_server.MAX_DAILY_CLAIMS = 5  # reset

    async def test_banned_due_to_active_cooldown(self, servicer, ctx, db_session_factory):
        """Charity with active cooldown must be rejected TOO_MANY_NOSHOWS."""
        await _seed_charity_standing(
            db_session_factory, charity_id=4,
            cooldown_expires_at=_now() + timedelta(days=7),
            appeal_status=models.AppealStatus.NONE,
            ban_count=1,
        )
        resp = await servicer.VerifyCharity(_req(charity_id=4, listing_id=40), ctx)
        assert resp.approved is False
        assert resp.rejection_reason == "TOO_MANY_NOSHOWS"

    async def test_expired_cooldown_is_approved(self, servicer, ctx, db_session_factory):
        """Charity whose cooldown has already expired must be approved."""
        await _seed_charity_standing(
            db_session_factory, charity_id=5,
            cooldown_expires_at=_now() - timedelta(days=1),  # past
            appeal_status=models.AppealStatus.NONE,
            ban_count=1,
        )
        resp = await servicer.VerifyCharity(_req(charity_id=5, listing_id=50), ctx)
        assert resp.approved is True

    async def test_appeal_approved_bypasses_cooldown(self, servicer, ctx, db_session_factory):
        """Charity with active cooldown but APPROVED appeal must be let through."""
        await _seed_charity_standing(
            db_session_factory, charity_id=6,
            cooldown_expires_at=_now() + timedelta(days=7),
            appeal_status=models.AppealStatus.APPROVED,
            ban_count=1,
        )
        resp = await servicer.VerifyCharity(_req(charity_id=6, listing_id=60), ctx)
        assert resp.approved is True


# ══════════════════════════════════════════════════════════════════════════════
# VerifyPublicUser
# ══════════════════════════════════════════════════════════════════════════════

class TestVerifyPublicUser:

    async def test_approved_no_record(self, servicer, ctx, db_session_factory):
        """User with no standing record must always be approved."""
        resp = await servicer.VerifyPublicUser(_req(user_id=1, listing_id=10), ctx)
        assert resp.approved is True
        assert resp.rejection_reason == ""

    async def test_approved_not_flagged(self, servicer, ctx, db_session_factory):
        """User with standing but is_flagged=False must be approved."""
        await _seed_user_standing(db_session_factory, user_id=2, is_flagged=False)
        resp = await servicer.VerifyPublicUser(_req(user_id=2, listing_id=20), ctx)
        assert resp.approved is True

    async def test_rejected_flagged(self, servicer, ctx, db_session_factory):
        """User with is_flagged=True must be rejected SCALPING_FLAG."""
        await _seed_user_standing(
            db_session_factory, user_id=3,
            is_flagged=True,
            flag_reason="Suspicious bulk purchasing pattern",
            flag_count=1,
        )
        resp = await servicer.VerifyPublicUser(_req(user_id=3, listing_id=30), ctx)
        assert resp.approved is False
        assert resp.rejection_reason == "SCALPING_FLAG"

    async def test_no_purchase_record_inserted(self, servicer, ctx, db_session_factory):
        """Public user approval must NOT insert any DB rows (no quota tracking)."""
        from sqlalchemy import select, func
        await servicer.VerifyPublicUser(_req(user_id=4, listing_id=40), ctx)
        # Verify no standing row was created automatically
        async with db_session_factory() as db:
            count = (await db.execute(
                select(func.count(models.PublicUserStanding.id)).where(
                    models.PublicUserStanding.user_id == 4
                )
            )).scalar()
        assert count == 0


# ══════════════════════════════════════════════════════════════════════════════
# RecordNoShow
# ══════════════════════════════════════════════════════════════════════════════

class TestRecordNoShow:

    async def test_first_noshow_increments_warning(self, servicer, ctx, db_session_factory):
        """First no-show increments warning_count; no cooldown triggered."""
        from sqlalchemy import select

        grpc_server.MAX_NOSHOWS = 3
        resp = await servicer.RecordNoShow(_req(charity_id=10, claim_id=1), ctx)
        assert resp.recorded is True
        assert resp.total_noshows == 1

        async with db_session_factory() as db:
            standing = (await db.execute(
                select(models.CharityStanding).where(models.CharityStanding.charity_id == 10)
            )).scalar_one()
        assert standing.warning_count == 1
        assert standing.ban_count == 0
        assert standing.cooldown_expires_at is None

    async def test_second_noshow_warning(self, servicer, ctx, db_session_factory):
        """Second no-show: warning_count=2, still no ban."""
        from sqlalchemy import select

        grpc_server.MAX_NOSHOWS = 3
        await servicer.RecordNoShow(_req(charity_id=11, claim_id=1), ctx)
        await servicer.RecordNoShow(_req(charity_id=11, claim_id=2), ctx)

        async with db_session_factory() as db:
            standing = (await db.execute(
                select(models.CharityStanding).where(models.CharityStanding.charity_id == 11)
            )).scalar_one()
        assert standing.warning_count == 2
        assert standing.ban_count == 0

    async def test_third_noshow_triggers_first_ban(self, servicer, ctx, db_session_factory):
        """Third no-show (=MAX_NOSHOWS) must trigger the first cooldown."""
        from sqlalchemy import select

        grpc_server.MAX_NOSHOWS = 3
        grpc_server.BASE_COOLDOWN_DAYS = 14
        for i in range(3):
            await servicer.RecordNoShow(_req(charity_id=12, claim_id=i + 1), ctx)

        async with db_session_factory() as db:
            standing = (await db.execute(
                select(models.CharityStanding).where(models.CharityStanding.charity_id == 12)
            )).scalar_one()

        assert standing.ban_count == 1
        assert standing.cooldown_expires_at is not None
        # cooldown should be ~14 days from now
        expected_min = _now() + timedelta(days=13)
        expected_max = _now() + timedelta(days=15)
        assert expected_min < _utc(standing.cooldown_expires_at) < expected_max
        assert standing.appeal_status == models.AppealStatus.NONE

    async def test_noshow_during_cooldown_only_warns(self, servicer, ctx, db_session_factory):
        """No-show recorded while charity is already in cooldown just increments warning."""
        from sqlalchemy import select

        grpc_server.MAX_NOSHOWS = 3
        # Seed with active ban
        await _seed_charity_standing(
            db_session_factory, charity_id=13,
            ban_count=1,
            warning_count=0,
            cooldown_expires_at=_now() + timedelta(days=10),
            appeal_status=models.AppealStatus.NONE,
        )
        # Add 3 existing no-shows so recent count >= MAX_NOSHOWS
        await _add_noshows(db_session_factory, charity_id=13, count=3)

        resp = await servicer.RecordNoShow(_req(charity_id=13, claim_id=99), ctx)
        assert resp.recorded is True

        async with db_session_factory() as db:
            standing = (await db.execute(
                select(models.CharityStanding).where(models.CharityStanding.charity_id == 13)
            )).scalar_one()

        # ban_count must not increase — they were already banned
        assert standing.ban_count == 1
        # warning_count must increase
        assert standing.warning_count == 1

    async def test_cooldown_escalation_second_ban(self, servicer, ctx, db_session_factory):
        """
        After the first cooldown expires, hitting MAX_NOSHOWS again must escalate
        to ban_count=2 with doubled cooldown (28 days).
        """
        from sqlalchemy import select

        grpc_server.MAX_NOSHOWS = 3
        grpc_server.BASE_COOLDOWN_DAYS = 14
        grpc_server.NOSHOWS_WINDOW_DAYS = 30

        # Seed expired first ban with old no-shows outside the window
        await _seed_charity_standing(
            db_session_factory, charity_id=14,
            ban_count=1,
            warning_count=0,
            cooldown_expires_at=_now() - timedelta(days=1),  # expired
            appeal_status=models.AppealStatus.NONE,
        )
        # Add 3 more current no-shows (within window) → should trigger second ban
        for i in range(3):
            await servicer.RecordNoShow(_req(charity_id=14, claim_id=100 + i), ctx)

        async with db_session_factory() as db:
            standing = (await db.execute(
                select(models.CharityStanding).where(models.CharityStanding.charity_id == 14)
            )).scalar_one()

        assert standing.ban_count == 2
        # Second ban = 14 * 2^(2-1) = 28 days
        expected_min = _now() + timedelta(days=27)
        expected_max = _now() + timedelta(days=29)
        assert expected_min < _utc(standing.cooldown_expires_at) < expected_max

    async def test_noshow_row_inserted(self, servicer, ctx, db_session_factory):
        """RecordNoShow must always insert a CharityNoShow event row."""
        from sqlalchemy import select, func

        await servicer.RecordNoShow(_req(charity_id=15, claim_id=1), ctx)
        async with db_session_factory() as db:
            count = (await db.execute(
                select(func.count(models.CharityNoShow.id)).where(
                    models.CharityNoShow.charity_id == 15
                )
            )).scalar()
        assert count == 1

    async def test_total_noshows_returned_is_lifetime(self, servicer, ctx, db_session_factory):
        """total_noshows in the response is the LIFETIME count, not just the window."""
        await servicer.RecordNoShow(_req(charity_id=16, claim_id=1), ctx)
        await servicer.RecordNoShow(_req(charity_id=16, claim_id=2), ctx)
        resp = await servicer.RecordNoShow(_req(charity_id=16, claim_id=3), ctx)
        assert resp.total_noshows == 3


# ══════════════════════════════════════════════════════════════════════════════
# GetCharityStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestGetCharityStatus:

    async def test_no_record_returns_defaults(self, servicer, ctx, db_session_factory):
        """Charity with no DB records must return clean default state."""
        resp = await servicer.GetCharityStatus(_req(charity_id=20), ctx)
        assert resp.is_banned is False
        assert resp.ban_reason == ""
        assert resp.cooldown_until == ""
        assert resp.warning_count == 0
        assert resp.recent_noshows == 0
        assert resp.claimed_today == 0
        assert resp.appeal_status == "NONE"

    async def test_active_ban_is_reported(self, servicer, ctx, db_session_factory):
        """Charity with active cooldown must report is_banned=True."""
        grpc_server.NOSHOWS_WINDOW_DAYS = 30
        await _seed_charity_standing(
            db_session_factory, charity_id=21,
            ban_count=1,
            warning_count=2,
            cooldown_expires_at=_now() + timedelta(days=7),
            appeal_status=models.AppealStatus.NONE,
        )
        resp = await servicer.GetCharityStatus(_req(charity_id=21), ctx)
        assert resp.is_banned is True
        assert resp.ban_reason == "TOO_MANY_NOSHOWS"
        assert resp.cooldown_until != ""
        assert resp.warning_count == 2

    async def test_appeal_approved_not_banned(self, servicer, ctx, db_session_factory):
        """Active cooldown with APPROVED appeal must report is_banned=False."""
        await _seed_charity_standing(
            db_session_factory, charity_id=22,
            ban_count=1,
            cooldown_expires_at=_now() + timedelta(days=7),
            appeal_status=models.AppealStatus.APPROVED,
        )
        resp = await servicer.GetCharityStatus(_req(charity_id=22), ctx)
        assert resp.is_banned is False
        assert resp.appeal_status == "APPROVED"

    async def test_live_counts_populated(self, servicer, ctx, db_session_factory):
        """recent_noshows and claimed_today must reflect live DB counts."""
        grpc_server.NOSHOWS_WINDOW_DAYS = 30
        await _add_noshows(db_session_factory, charity_id=23, count=2)
        await _add_claims_today(db_session_factory, charity_id=23, count=1)

        resp = await servicer.GetCharityStatus(_req(charity_id=23), ctx)
        assert resp.recent_noshows == 2
        assert resp.claimed_today == 1

    async def test_expired_cooldown_not_banned(self, servicer, ctx, db_session_factory):
        """Expired cooldown must report is_banned=False."""
        await _seed_charity_standing(
            db_session_factory, charity_id=24,
            ban_count=1,
            cooldown_expires_at=_now() - timedelta(hours=1),
            appeal_status=models.AppealStatus.NONE,
        )
        resp = await servicer.GetCharityStatus(_req(charity_id=24), ctx)
        assert resp.is_banned is False


# ══════════════════════════════════════════════════════════════════════════════
# GetUserStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestGetUserStatus:

    async def test_no_record_defaults(self, servicer, ctx, db_session_factory):
        """User with no record returns clean default: not flagged."""
        resp = await servicer.GetUserStatus(_req(user_id=30), ctx)
        assert resp.is_flagged is False
        assert resp.flag_reason == ""
        assert resp.flag_count == 0

    async def test_not_flagged(self, servicer, ctx, db_session_factory):
        """User with standing row but is_flagged=False returns True for approval."""
        await _seed_user_standing(db_session_factory, user_id=31, is_flagged=False, flag_count=0)
        resp = await servicer.GetUserStatus(_req(user_id=31), ctx)
        assert resp.is_flagged is False

    async def test_flagged_returns_details(self, servicer, ctx, db_session_factory):
        """Flagged user must return is_flagged=True with reason and count."""
        await _seed_user_standing(
            db_session_factory, user_id=32,
            is_flagged=True,
            flag_reason="Automated bulk buy detected",
            flag_count=2,
        )
        resp = await servicer.GetUserStatus(_req(user_id=32), ctx)
        assert resp.is_flagged is True
        assert resp.flag_reason == "Automated bulk buy detected"
        assert resp.flag_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# GetVendorStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestGetVendorStatus:

    async def test_no_record_defaults_compliant(self, servicer, ctx, db_session_factory):
        """Vendor with no compliance record defaults to is_compliant=True."""
        resp = await servicer.GetVendorStatus(_req(vendor_id=40), ctx)
        assert resp.is_compliant is True
        assert resp.compliance_flag == ""
        assert resp.license_expires_at == ""

    async def test_compliant_vendor(self, servicer, ctx, db_session_factory):
        """Vendor with is_compliant=True and no expiry returns compliant."""
        await _seed_vendor_compliance(
            db_session_factory, vendor_id=41,
            nea_license_number="NEA-2026-001",
            is_compliant=True,
        )
        resp = await servicer.GetVendorStatus(_req(vendor_id=41), ctx)
        assert resp.is_compliant is True

    async def test_db_flag_non_compliant(self, servicer, ctx, db_session_factory):
        """Vendor flagged as non-compliant in DB returns is_compliant=False."""
        await _seed_vendor_compliance(
            db_session_factory, vendor_id=42,
            is_compliant=False,
            compliance_flag="NEA inspection failed — premises closure ordered",
        )
        resp = await servicer.GetVendorStatus(_req(vendor_id=42), ctx)
        assert resp.is_compliant is False
        assert "NEA inspection" in resp.compliance_flag

    async def test_expired_license_non_compliant(self, servicer, ctx, db_session_factory):
        """Vendor with expired license must return is_compliant=False even if db flag=True."""
        await _seed_vendor_compliance(
            db_session_factory, vendor_id=43,
            is_compliant=True,
            nea_license_number="NEA-2025-expired",
            license_expires_at=_now() - timedelta(days=1),  # expired yesterday
        )
        resp = await servicer.GetVendorStatus(_req(vendor_id=43), ctx)
        assert resp.is_compliant is False
        assert resp.license_expires_at != ""

    async def test_valid_license_compliant(self, servicer, ctx, db_session_factory):
        """Vendor with db flag=True and future expiry is compliant."""
        await _seed_vendor_compliance(
            db_session_factory, vendor_id=44,
            is_compliant=True,
            nea_license_number="NEA-2026-valid",
            license_expires_at=_now() + timedelta(days=365),
        )
        resp = await servicer.GetVendorStatus(_req(vendor_id=44), ctx)
        assert resp.is_compliant is True
        assert resp.license_expires_at != ""

    async def test_no_expiry_set_compliant(self, servicer, ctx, db_session_factory):
        """Vendor with is_compliant=True and NULL license_expires_at is compliant."""
        await _seed_vendor_compliance(
            db_session_factory, vendor_id=45,
            is_compliant=True,
            license_expires_at=None,
        )
        resp = await servicer.GetVendorStatus(_req(vendor_id=45), ctx)
        assert resp.is_compliant is True
        assert resp.license_expires_at == ""


# ══════════════════════════════════════════════════════════════════════════════
# Cross-cutting: _is_banned helper
# ══════════════════════════════════════════════════════════════════════════════

class TestIsBannedHelper:

    def test_no_cooldown_not_banned(self):
        s = models.CharityStanding(
            charity_id=99, appeal_status=models.AppealStatus.NONE,
            cooldown_expires_at=None,
        )
        assert grpc_server._is_banned(s) is False

    def test_future_cooldown_none_appeal_banned(self):
        s = models.CharityStanding(
            charity_id=99, appeal_status=models.AppealStatus.NONE,
            cooldown_expires_at=_now() + timedelta(days=1),
        )
        assert grpc_server._is_banned(s) is True

    def test_future_cooldown_approved_appeal_not_banned(self):
        s = models.CharityStanding(
            charity_id=99, appeal_status=models.AppealStatus.APPROVED,
            cooldown_expires_at=_now() + timedelta(days=1),
        )
        assert grpc_server._is_banned(s) is False

    def test_future_cooldown_pending_appeal_still_banned(self):
        s = models.CharityStanding(
            charity_id=99, appeal_status=models.AppealStatus.PENDING,
            cooldown_expires_at=_now() + timedelta(days=1),
        )
        assert grpc_server._is_banned(s) is True

    def test_past_cooldown_not_banned(self):
        s = models.CharityStanding(
            charity_id=99, appeal_status=models.AppealStatus.NONE,
            cooldown_expires_at=_now() - timedelta(seconds=1),
        )
        assert grpc_server._is_banned(s) is False
