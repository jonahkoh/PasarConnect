"""
SQLAlchemy 2.0 ORM model for the Payment Log Service.

PaymentRecord is the single source of truth for every transaction.
It serves two purposes:
  1. Idempotency — stripe_transaction_id is UNIQUE; the Orchestrator
     queries this before doing any work on a duplicate webhook.
  2. Audit trail — every state transition (PENDING → SUCCESS / REFUNDED)
     is timestamped so ops can reconstruct exactly what happened.
"""
import datetime
import enum

from sqlalchemy import DateTime, Enum as SAEnum, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class PaymentStatus(str, enum.Enum):
    PENDING  = "PENDING"   # intent created, waiting for Stripe confirmation
    SUCCESS  = "SUCCESS"   # charge confirmed (payment succeeded)
    COLLECTED = "COLLECTED"  # item collection approved and completed
    REFUNDED = "REFUNDED"  # money returned to user
    FAILED   = "FAILED"    # refund itself failed — requires manual ops
    FORFEITED = "FORFEITED" # user no-showed after cancellation window; no refund issued


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id : Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # SQLAlchemy 2.0: Mapped[T] (non-optional) implies NOT NULL automatically.
    stripe_transaction_id : Mapped[str]                      = mapped_column(String(128), unique=True, index=True)
    listing_id            : Mapped[int]                      = mapped_column(Integer, index=True)
    # Stored so the Orchestrator can call LockListing(SOLD) with the correct
    # optimistic-lock version it held at intent-creation time.
    listing_version       : Mapped[int]                      = mapped_column(Integer)
    amount                : Mapped[float]                    = mapped_column(Float)
    status                : Mapped[PaymentStatus]            = mapped_column(SAEnum(PaymentStatus), default=PaymentStatus.PENDING)
    created_at            : Mapped[datetime.datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at            : Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
