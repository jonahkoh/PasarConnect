"""
Verification Service — SQLAlchemy 2.0 ORM models.

Tables:
  charity_claims        — append-only log of approved VerifyCharity calls (daily quota)
  charity_noshows       — append-only log of RecordNoShow calls (pattern tracking)
  charity_standing      — one row per charity: rolling ban/warning/cooldown state
  public_user_standing  — one row per user: admin-set scalping flag
  vendor_compliance     — one row per vendor: NEA licence compliance state

Removed from prior version:
  public_user_purchases — dropped; public users have no daily quota
"""
from __future__ import annotations

import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class AppealStatus(str, enum.Enum):
    NONE     = "NONE"
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ── Append-only event logs ────────────────────────────────────────────────────

class CharityClaim(Base):
    """One row per approved VerifyCharity — counts toward the daily hoarding quota."""

    __tablename__ = "charity_claims"

    id:           Mapped[int]               = mapped_column(Integer, primary_key=True, index=True)
    charity_id:   Mapped[int]               = mapped_column(Integer, index=True, nullable=False)
    listing_id:   Mapped[int]               = mapped_column(Integer, nullable=False)
    is_cancelled: Mapped[bool]              = mapped_column(Boolean, default=False, nullable=False)
    created_at:   Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CharityNoShow(Base):
    """One row per RecordNoShow — charity failed to collect a claimed item."""

    __tablename__ = "charity_noshows"

    id:         Mapped[int]               = mapped_column(Integer, primary_key=True, index=True)
    charity_id: Mapped[int]               = mapped_column(Integer, index=True, nullable=False)
    claim_id:   Mapped[int]               = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CharityLateCancelWarning(Base):
    """
    Append-only log of late-cancellation warnings.

    Written by RecordLateCancelWarning RPC when a charity cancels a PENDING_COLLECTION
    claim after the CANCEL_WINDOW_MINUTES grace period has elapsed.

    Also increments CharityStanding.warning_count so the full standing check
    (GetCharityStatus) reflects the cumulative warning history.
    """

    __tablename__ = "charity_late_cancel_warnings"

    id:         Mapped[int]               = mapped_column(Integer, primary_key=True, index=True)
    charity_id: Mapped[int]               = mapped_column(Integer, index=True, nullable=False)
    claim_id:   Mapped[int]               = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Standing / compliance state (upserted rows) ───────────────────────────────

class CharityStanding(Base):
    """
    Rolling ban/warning/cooldown state for a charity.
    One row per charity, upserted on each RecordNoShow.

    is_banned is DERIVED (not stored):
        cooldown_expires_at > now AND appeal_status != APPROVED

    Cooldown escalation: days = BASE_COOLDOWN_DAYS * 2^(ban_count - 1)
        ban_count=1 → 14 days, ban_count=2 → 28 days, ban_count=3 → 56 days
    """

    __tablename__ = "charity_standing"

    id:                  Mapped[int]                    = mapped_column(Integer, primary_key=True, index=True)
    charity_id:          Mapped[int]                    = mapped_column(Integer, unique=True, nullable=False, index=True)
    warning_count:       Mapped[int]                    = mapped_column(Integer, default=0, nullable=False)
    ban_count:           Mapped[int]                    = mapped_column(Integer, default=0, nullable=False)
    cooldown_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appeal_status:       Mapped[AppealStatus]           = mapped_column(
        SAEnum(AppealStatus, name="appealstatus"), default=AppealStatus.NONE, nullable=False
    )
    appeal_submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_noshow_at:      Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at:          Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class PublicUserNoShow(Base):
    """
    Append-only log of public user no-shows after a paid purchase.
    Tracked to detect food wastage patterns — admin reviews and sets is_flagged
    on PublicUserStanding when the count is unacceptable.
    """

    __tablename__ = "public_user_noshows"

    id:             Mapped[int]               = mapped_column(Integer, primary_key=True, index=True)
    user_id:        Mapped[int]               = mapped_column(Integer, index=True, nullable=False)
    transaction_id: Mapped[str]               = mapped_column(String(128), nullable=False)
    created_at:     Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PublicUserStanding(Base):
    """
    Scalping flag for a public user. No daily quota — admin-set flag only.
    VerifyPublicUser checks is_flagged; if True → rejected with SCALPING_FLAG.
    Public user no-show history lives in PublicUserNoShow (append-only log).
    """

    __tablename__ = "public_user_standing"

    id:               Mapped[int]                      = mapped_column(Integer, primary_key=True, index=True)
    user_id:          Mapped[int]                      = mapped_column(Integer, unique=True, nullable=False, index=True)
    is_flagged:       Mapped[bool]                     = mapped_column(Boolean, default=False, nullable=False)
    flag_reason:      Mapped[str | None]               = mapped_column(String(255), nullable=True)
    flag_count:       Mapped[int]                      = mapped_column(Integer, default=0, nullable=False)
    last_purchase_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at:       Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class VendorCompliance(Base):
    """
    NEA licence compliance state for a vendor.
    effective is_compliant = db.is_compliant AND (license_expires_at is None OR license_expires_at > now)
    """

    __tablename__ = "vendor_compliance"

    id:                 Mapped[int]                      = mapped_column(Integer, primary_key=True, index=True)
    vendor_id:          Mapped[int]                      = mapped_column(Integer, unique=True, nullable=False, index=True)
    nea_license_number: Mapped[str | None]               = mapped_column(String(100), nullable=True)
    license_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_compliant:       Mapped[bool]                     = mapped_column(Boolean, default=True, nullable=False)
    compliance_flag:    Mapped[str | None]               = mapped_column(String(255), nullable=True)
    last_verified_at:   Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at:         Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


# ── Time helpers ──────────────────────────────────────────────────────────────

def today_start() -> datetime.datetime:
    """Midnight UTC — lower bound for today's daily quota count queries."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def noshows_window_start(days: int) -> datetime.datetime:
    """Start of the rolling no-show lookback window."""
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
