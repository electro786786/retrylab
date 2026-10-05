import uuid

from sqlalchemy import JSON, Column, Integer, String, UniqueConstraint

from app.config import settings
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id = Column(String, primary_key=True, default=generate_uuid)
    key = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    status_code = Column(Integer, nullable=True)
    response_body = Column(JSON, nullable=True)

    # Bug 3: Missing unique constraint on the key column
    if settings.bug_3_missing_unique_constraint:
        __table_args__ = ()
    elif settings.bug_4_unscoped_key:
        # Bug 4: Key not scoped to user or endpoint (unique only on key)
        __table_args__ = (UniqueConstraint("key", name="uq_idempotency_key"),)
    else:
        # Correct behavior: Scoped to key, user_id, and endpoint
        __table_args__ = (UniqueConstraint("key", "user_id", "endpoint", name="uq_idempotency_key"),)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, nullable=False)
    amount = Column(Integer, nullable=False)
    currency = Column(String, default="USD")
    status = Column(String, default="succeeded")

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
