import uuid

from sqlalchemy import JSON, Column, Integer, String, UniqueConstraint

from app.config import settings
from app.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class IdempotencyKey(Base):
    """
    Stores the result of every idempotent request so that retries can be served
    from cache without re-executing business logic.

    Columns:
        key           – the client-supplied Idempotency-Key header value
        user_id       – the authenticated user (scoping, unless bug_4 is active)
        endpoint      – the request path (scoping, unless bug_4 is active)
        request_hash  – SHA-256 of the canonical request payload (for bug_7
                        detection; null when bug_7 is active)
        status_code   – HTTP status of the original response (null while pending)
        response_body – JSON body of the original response (null while pending)
    """

    __tablename__ = "idempotency_keys"

    id = Column(String, primary_key=True, default=generate_uuid)
    key = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    # Payload fingerprint — used to detect key-reuse with a different body
    request_hash = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)

    # The unique constraint varies by active bug flags:
    #   correct  → (key, user_id, endpoint)   prevents cross-user replay
    #   bug 3    → no constraint              DB allows duplicates silently
    #   bug 4    → (key,) only               cross-user replay is possible
    if settings.bug_3_missing_unique_constraint:
        __table_args__ = ()
    elif settings.bug_4_unscoped_key:
        __table_args__ = (UniqueConstraint("key", name="uq_idempotency_key"),)
    else:
        __table_args__ = (
            UniqueConstraint("key", "user_id", "endpoint", name="uq_idempotency_key"),
        )


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)


class Wallet(Base):
    """
    A simple balance ledger so Bug 6 (lost update) has something to race over.
    The initial balance is seeded when a customer is created.
    """

    __tablename__ = "wallets"

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, nullable=False, unique=True)
    balance = Column(Integer, nullable=False, default=10_000)  # in cents


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    currency = Column(String, default="USD")
    status = Column(String, default="succeeded")
    # Provider-side charge ID — present only after the downstream call succeeds
    provider_charge_id = Column(String, nullable=True)


class Refund(Base):
    __tablename__ = "refunds"

    id = Column(String, primary_key=True, default=generate_uuid)
    payment_id = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)


class Transfer(Base):
    __tablename__ = "transfers"

    id = Column(String, primary_key=True, default=generate_uuid)
    destination_id = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
