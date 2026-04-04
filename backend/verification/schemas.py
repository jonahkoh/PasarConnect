"""
Verification Service — Pydantic response schemas.

Used by FastAPI routes and for documenting gRPC response shapes.
"""
from __future__ import annotations

import datetime
import enum

from pydantic import BaseModel


class AppealStatus(str, enum.Enum):
    NONE     = "NONE"
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CharityStatusResponse(BaseModel):
    model_config = {"from_attributes": True}

    is_banned:      bool
    ban_reason:     str                         # "TOO_MANY_NOSHOWS" | ""
    cooldown_until: datetime.datetime | None    # None when not in cooldown
    warning_count:  int
    recent_noshows: int                         # live rolling-window count
    claimed_today:  int                         # live today count
    appeal_status:  AppealStatus


class PublicUserStatusResponse(BaseModel):
    model_config = {"from_attributes": True}

    is_flagged:  bool
    flag_reason: str | None
    flag_count:  int


class VendorStatusResponse(BaseModel):
    model_config = {"from_attributes": True}

    is_compliant:       bool
    compliance_flag:    str | None
    license_expires_at: datetime.datetime | None
