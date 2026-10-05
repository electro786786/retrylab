"""
Bug Zoo Payments API — target application for the RetryLab fuzzer.

Every endpoint is idempotent *by default*.  Bug flags (loaded from environment
variables via config.py) disable or corrupt specific parts of that contract so
the fuzzer oracle can detect each failure mode independently.

Bug map
-------
Bug 1  bug_1_race_condition          check_idempotency  SELECT then INSERT race
Bug 2  bug_2_no_idempotency          check_idempotency  no key handling at all
Bug 3  bug_3_missing_unique_constraint models.py        no DB-level uniqueness
Bug 4  bug_4_unscoped_key            check_idempotency  key not scoped to user
Bug 5  bug_5_non_atomic_dual_write   create_payment     provider charged, then crash
Bug 6  bug_6_lost_update             create_payment     balance R-M-W without lock
Bug 7  bug_7_silent_payload_mismatch check_idempotency  different body silently accepted
Bug 8  bug_8_key_saved_before_work   create_payment     key saved before work runs
"""

import hashlib
import json
import os

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import settings
from app.database import AsyncSessionLocal, Base, engine, get_db
from app.models import Customer, IdempotencyKey, Payment, Refund, Transfer, Wallet
from app.schemas import (
    CustomerCreate,
    CustomerResponse,
    PaymentCreate,
    PaymentResponse,
    RefundCreate,
    RefundResponse,
    TransferCreate,
    TransferResponse,
    WalletResponse,
)

app = FastAPI(title="Bug Zoo Payments API")


# ── startup ───────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup_event() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── helpers ───────────────────────────────────────────────────────────────────


def _payload_hash(body: dict) -> str:  # type: ignore[type-arg]
    """Stable SHA-256 fingerprint of a request body (sorted keys)."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _scope(
    stmt,  # type: ignore[no-untyped-def]
    user_id: str,
    endpoint: str,
):
    """
    Apply user/endpoint scoping to a SELECT statement unless Bug 4 is active.
    Bug 4 makes the key global, so User A's key can replay User B's response.
    """
    if not settings.bug_4_unscoped_key:
        stmt = stmt.where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.endpoint == endpoint,
        )
    return stmt


async def _fetch_key(
    db: AsyncSession,
    idempotency_key: str,
    user_id: str,
    endpoint: str,
) -> IdempotencyKey | None:
    stmt = _scope(
        select(IdempotencyKey).where(IdempotencyKey.key == idempotency_key),
        user_id,
        endpoint,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def check_idempotency(
    request: Request,
    db: AsyncSession,
    idempotency_key: str,
    user_id: str,
    payload_hash: str | None = None,
) -> JSONResponse | None:
    """
    Gate every mutating endpoint.

    Returns a JSONResponse (cached replay) if the key is already complete,
    raises HTTPException 409 if the key is in-flight, or returns None to
    let the handler proceed with fresh execution.

    Bug 2: skipped entirely — no idempotency at all.
    Bug 1: uses SELECT-then-INSERT instead of atomic INSERT…ON CONFLICT.
    Bug 7: skips the payload fingerprint check.
    """

    # ── Bug 2: no idempotency ──────────────────────────────────────────────────
    if settings.bug_2_no_idempotency:
        return None

    endpoint = request.url.path

    # ── Bug 1: check-then-act (SELECT then INSERT) ────────────────────────────
    if settings.bug_1_race_condition:
        existing = await _fetch_key(db, idempotency_key, user_id, endpoint)
        if existing:
            if existing.status_code is None:
                raise HTTPException(status_code=409, detail="Request in progress")
            return JSONResponse(
                status_code=existing.status_code,
                content=existing.response_body,
            )
        # The window between the SELECT above and the INSERT below is the race.
        new_key = IdempotencyKey(
            key=idempotency_key,
            user_id=user_id,
            endpoint=endpoint,
            request_hash=payload_hash,
        )
        db.add(new_key)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Concurrent request detected")
        return None

    # ── Correct path: atomic INSERT … ON CONFLICT DO NOTHING ─────────────────

    # Decide which column(s) the conflict target covers based on active bugs.
    if settings.bug_3_missing_unique_constraint:
        # Bug 3: no unique index → ON CONFLICT has nothing to match against,
        # so we fall back to a plain INSERT (no deduplication).
        new_key = IdempotencyKey(
            key=idempotency_key,
            user_id=user_id,
            endpoint=endpoint,
            request_hash=payload_hash,
        )
        db.add(new_key)
        await db.flush()
        return None

    conflict_cols: list[str]
    if settings.bug_4_unscoped_key:
        conflict_cols = ["key"]
    else:
        conflict_cols = ["key", "user_id", "endpoint"]

    stmt = (
        insert(IdempotencyKey)
        .values(
            key=idempotency_key,
            user_id=user_id,
            endpoint=endpoint,
            request_hash=payload_hash,
        )
        .on_conflict_do_nothing(index_elements=conflict_cols)
        .returning(IdempotencyKey.id)
    )
    result = await db.execute(stmt)
    inserted_id = result.scalar()

    if inserted_id:
        # Brand-new key: the caller should continue with fresh execution.
        return None

    # The key already exists — fetch it and decide what to do.
    existing = await _fetch_key(db, idempotency_key, user_id, endpoint)
    if existing is None:
        raise HTTPException(status_code=500, detail="Key conflict but row not found")

    # ── Bug 7: silent payload mismatch ────────────────────────────────────────
    # Correct: reject if the payload fingerprint has changed.
    # Bug 7 skips this check → a different body is silently accepted.
    if (
        not settings.bug_7_silent_payload_mismatch
        and payload_hash is not None
        and existing.request_hash is not None
        and existing.request_hash != payload_hash
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Idempotency key reused with a different request payload. "
                "Use a new key for a different operation."
            ),
        )

    if existing.status_code is None:
        raise HTTPException(status_code=409, detail="Request in progress")

    return JSONResponse(
        status_code=existing.status_code,
        content=existing.response_body,
    )


async def save_idempotency_result(
    db: AsyncSession,
    idempotency_key: str,
    user_id: str,
    endpoint: str,
    status_code: int,
    response_body: dict,  # type: ignore[type-arg]
) -> None:
    """Stamp the cached response onto the idempotency key record."""
    if settings.bug_2_no_idempotency:
        return

    existing = await _fetch_key(db, idempotency_key, user_id, endpoint)
    if existing:
        existing.status_code = status_code
        existing.response_body = response_body
        await db.flush()


# ── /customers ────────────────────────────────────────────────────────────────


@app.post("/customers", response_model=CustomerResponse)
async def create_customer(
    customer: CustomerCreate,
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse | JSONResponse:
    body_hash = _payload_hash(customer.model_dump())
    cached = await check_idempotency(request, db, idempotency_key, user_id, body_hash)
    if cached:
        return cached

    new_customer = Customer(name=customer.name, email=customer.email)
    db.add(new_customer)
    await db.flush()

    wallet = Wallet(customer_id=new_customer.id)
    db.add(wallet)
    await db.flush()

    response_data = {
        "id": new_customer.id,
        "name": new_customer.name,
        "email": new_customer.email,
        "wallet_balance": wallet.balance,
    }
    await save_idempotency_result(
        db, idempotency_key, user_id, request.url.path, 200, response_data
    )
    await db.commit()
    return CustomerResponse(**response_data)


@app.get("/customers/{customer_id}/wallet", response_model=WalletResponse)
async def get_wallet(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
) -> WalletResponse:
    result = await db.execute(
        select(Wallet).where(Wallet.customer_id == customer_id)
    )
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return WalletResponse(customer_id=wallet.customer_id, balance=wallet.balance)


# ── /payments ─────────────────────────────────────────────────────────────────


@app.post("/payments", response_model=PaymentResponse)
async def create_payment(
    payment: PaymentCreate,
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse | JSONResponse:
    """
    Charge the customer's wallet and record a payment.

    This is the richest endpoint in the bug zoo because it has two side effects
    (wallet debit and downstream provider charge) that must be atomic.

    ── Bug 5: non-atomic dual write ──────────────────────────────────────────
    The target calls the provider first, then saves the local Payment row.
    If BUG_5_CRASH_AFTER_PROVIDER=1 is set via the admin endpoint, the
    process raises after the provider call so that a retry hits the provider
    a second time.

    ── Bug 6: lost update on wallet balance ──────────────────────────────────
    With bug_6_lost_update, we read the balance with a plain SELECT (no lock),
    check it, then write back balance - amount.  Two concurrent requests both
    read the same starting value, both pass the check, and both write their
    reduced balance — the second write wins and the net debit is only one
    payment even though two rows are created.

    ── Bug 8: key saved before work ──────────────────────────────────────────
    With bug_8_key_saved_before_work, we write the idempotency record with a
    success status_code *before* doing the actual work.  If a crash happens
    mid-work, the retry sees the cached success and returns it — even though
    the payment never completed.
    """
    body_hash = _payload_hash(payment.model_dump())
    cached = await check_idempotency(request, db, idempotency_key, user_id, body_hash)
    if cached:
        return cached

    # ── Bug 8: save the key BEFORE doing any real work ────────────────────────
    if settings.bug_8_key_saved_before_work:
        # ── Bug 8 simulation ──────────────────────────────────────────────────
        # In a real buggy app, the code would commit the idempotency key with
        # a success status BEFORE doing the actual work. If the process is then
        # killed (OOM, SIGKILL), the key is durably committed but the work never
        # ran. On retry the cached "success" is returned — a phantom success.
        #
        # Simulation mechanics:
        #   Step 1 — commit the main session so the key row (status_code=None)
        #            is durable and visible to other connections.
        #   Step 2 — open an *independent* session, update the row to
        #            status_code=200 with a fake response body, commit it.
        #            This second commit survives the upcoming RuntimeError
        #            because it is already done; the RuntimeError only affects
        #            code that runs after it.
        #   Step 3 — raise RuntimeError to simulate the process crash.
        premature_response = {
            "id": "pending",
            "customer_id": payment.customer_id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": "succeeded",
            "provider_charge_id": None,
        }
        # Step 1: make the key row visible to other connections.
        await db.commit()

        # Step 2: stamp the premature success in a separate session.
        async with AsyncSessionLocal() as sep:
            await save_idempotency_result(
                sep, idempotency_key, user_id, request.url.path, 200, premature_response
            )
            await sep.commit()

        # Step 3: simulate crash — payment work never runs.
        if os.environ.get("BUG_8_CRASH_AFTER_KEY_SAVE", "0") == "1":
            raise RuntimeError("Simulated crash after key save (Bug 8)")

    # ── Wallet debit ──────────────────────────────────────────────────────────
    if settings.bug_6_lost_update:
        # Bug 6: plain SELECT (no lock) — vulnerable to a race.
        result = await db.execute(
            select(Wallet).where(Wallet.customer_id == payment.customer_id)
        )
    else:
        # Correct: SELECT FOR UPDATE acquires a row-level lock.
        result = await db.execute(
            select(Wallet)
            .where(Wallet.customer_id == payment.customer_id)
            .with_for_update()
        )

    wallet = result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if wallet.balance < payment.amount:
        raise HTTPException(status_code=402, detail="Insufficient funds")

    wallet.balance -= payment.amount
    await db.flush()

    # ── Bug 5: call the provider, then crash before saving locally ───────────
    provider_charge_id: str | None = None
    if settings.bug_5_non_atomic_dual_write:
        # Call provider first.
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.mock_url}/charges",
                json={
                    "amount": payment.amount,
                    "currency": payment.currency,
                    "customer_id": payment.customer_id,
                },
                headers={"idempotency-key": idempotency_key},
                timeout=5.0,
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Provider charge failed")
        provider_charge_id = resp.json()["provider_charge_id"]

        # Crash point: the BUG_5_CRASH_AFTER_PROVIDER env var is set by the
        # reproduction script to simulate a process death here.
        if os.environ.get("BUG_5_CRASH_AFTER_PROVIDER", "0") == "1":
            raise RuntimeError("Simulated crash after provider charge (Bug 5)")

        # Now save the local payment row.
        new_payment = Payment(
            customer_id=payment.customer_id,
            amount=payment.amount,
            currency=payment.currency,
            provider_charge_id=provider_charge_id,
        )
        db.add(new_payment)
        await db.flush()
    else:
        # Correct: wrap both the provider call and the DB write in one
        # transaction.  If either fails the whole thing rolls back.
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.mock_url}/charges",
                json={
                    "amount": payment.amount,
                    "currency": payment.currency,
                    "customer_id": payment.customer_id,
                },
                headers={"idempotency-key": idempotency_key},
                timeout=5.0,
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Provider charge failed")
        provider_charge_id = resp.json()["provider_charge_id"]

        new_payment = Payment(
            customer_id=payment.customer_id,
            amount=payment.amount,
            currency=payment.currency,
            provider_charge_id=provider_charge_id,
        )
        db.add(new_payment)
        await db.flush()

    response_data = {
        "id": new_payment.id,
        "customer_id": new_payment.customer_id,
        "amount": new_payment.amount,
        "currency": new_payment.currency,
        "status": new_payment.status,
        "provider_charge_id": new_payment.provider_charge_id,
    }

    if not settings.bug_8_key_saved_before_work:
        await save_idempotency_result(
            db, idempotency_key, user_id, request.url.path, 200, response_data
        )
    await db.commit()
    return PaymentResponse(**response_data)


# ── /refunds ──────────────────────────────────────────────────────────────────


@app.post("/refunds", response_model=RefundResponse)
async def create_refund(
    refund: RefundCreate,
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db),
) -> RefundResponse | JSONResponse:
    body_hash = _payload_hash(refund.model_dump())
    cached = await check_idempotency(request, db, idempotency_key, user_id, body_hash)
    if cached:
        return cached

    new_refund = Refund(payment_id=refund.payment_id, amount=refund.amount)
    db.add(new_refund)
    await db.flush()

    response_data = {
        "id": new_refund.id,
        "payment_id": new_refund.payment_id,
        "amount": new_refund.amount,
    }
    await save_idempotency_result(
        db, idempotency_key, user_id, request.url.path, 200, response_data
    )
    await db.commit()
    return RefundResponse(**response_data)


# ── /transfers ────────────────────────────────────────────────────────────────


@app.post("/transfers", response_model=TransferResponse)
async def create_transfer(
    transfer: TransferCreate,
    request: Request,
    idempotency_key: str = Header(...),
    user_id: str = Header(default="test-user"),
    db: AsyncSession = Depends(get_db),
) -> TransferResponse | JSONResponse:
    body_hash = _payload_hash(transfer.model_dump())
    cached = await check_idempotency(request, db, idempotency_key, user_id, body_hash)
    if cached:
        return cached

    new_transfer = Transfer(
        destination_id=transfer.destination_id, amount=transfer.amount
    )
    db.add(new_transfer)
    await db.flush()

    response_data = {
        "id": new_transfer.id,
        "destination_id": new_transfer.destination_id,
        "amount": new_transfer.amount,
    }
    await save_idempotency_result(
        db, idempotency_key, user_id, request.url.path, 200, response_data
    )
    await db.commit()
    return TransferResponse(**response_data)


# ── admin helpers (used by reproduction scripts) ──────────────────────────────


@app.get("/admin/payments/count")
async def payment_count(db: AsyncSession = Depends(get_db)) -> dict:  # type: ignore[type-arg]
    result = await db.execute(text("SELECT COUNT(*) FROM payments"))
    return {"count": result.scalar()}


@app.get("/admin/idempotency_keys/count")
async def key_count(db: AsyncSession = Depends(get_db)) -> dict:  # type: ignore[type-arg]
    result = await db.execute(text("SELECT COUNT(*) FROM idempotency_keys"))
    return {"count": result.scalar()}
