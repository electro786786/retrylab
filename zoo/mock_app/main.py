"""
Fake Stripe — a minimal mock payment provider.

Records every charge/refund call and the idempotency key that was used.
Can be made to crash on demand via the /admin/crash endpoint so that
fault-injection tests can simulate a downstream failure mid-request.
"""

import threading
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Mock Payment Provider")

# ── in-memory state ────────────────────────────────────────────────────────────

_lock = threading.Lock()

# provider_idempotency_key → response dict
_recorded_charges: dict[str, dict[str, Any]] = {}
_recorded_refunds: dict[str, dict[str, Any]] = {}

# call counter: provider_idempotency_key → number of times the endpoint was hit
_call_counts: dict[str, int] = defaultdict(int)

# when True, every charge/refund request will raise a 500
_crash_mode: bool = False


# ── schemas ────────────────────────────────────────────────────────────────────


class ChargeRequest(BaseModel):
    amount: int
    currency: str = "USD"
    customer_id: str


class ChargeResponse(BaseModel):
    provider_charge_id: str
    amount: int
    currency: str
    status: str


class RefundRequest(BaseModel):
    provider_charge_id: str
    amount: int


class RefundResponse(BaseModel):
    provider_refund_id: str
    amount: int
    status: str


# ── endpoints ──────────────────────────────────────────────────────────────────


@app.post("/charges", response_model=ChargeResponse)
def create_charge(
    body: ChargeRequest,
    idempotency_key: str = Header(...),
) -> ChargeResponse:
    """
    Create a charge.  Idempotent: a second call with the same key returns the
    cached response without incrementing the side-effect counter beyond 1.

    NOTE: this mock is intentionally correct — the buggy behaviour lives in
    the target app, not here.  The oracle checks that the *target* only calls
    us once per unique business operation.
    """
    with _lock:
        if _crash_mode:
            raise HTTPException(status_code=500, detail="Provider unavailable (crash mode)")

        _call_counts[idempotency_key] += 1

        if idempotency_key in _recorded_charges:
            return ChargeResponse(**_recorded_charges[idempotency_key])

        charge_id = f"ch_{idempotency_key[:8]}"
        result = {
            "provider_charge_id": charge_id,
            "amount": body.amount,
            "currency": body.currency,
            "status": "succeeded",
        }
        _recorded_charges[idempotency_key] = result
        return ChargeResponse(**result)


@app.post("/refunds", response_model=RefundResponse)
def create_refund(
    body: RefundRequest,
    idempotency_key: str = Header(...),
) -> RefundResponse:
    with _lock:
        if _crash_mode:
            raise HTTPException(status_code=500, detail="Provider unavailable (crash mode)")

        _call_counts[idempotency_key] += 1

        if idempotency_key in _recorded_refunds:
            return RefundResponse(**_recorded_refunds[idempotency_key])

        refund_id = f"re_{idempotency_key[:8]}"
        result = {
            "provider_refund_id": refund_id,
            "amount": body.amount,
            "status": "succeeded",
        }
        _recorded_refunds[idempotency_key] = result
        return RefundResponse(**result)


# ── admin endpoints (used by the fuzzer oracle and test scripts) ───────────────


@app.get("/admin/calls/{idempotency_key}")
def get_call_count(idempotency_key: str) -> dict[str, Any]:
    """Return how many times the provider was called for this idempotency key."""
    with _lock:
        return {
            "idempotency_key": idempotency_key,
            "call_count": _call_counts[idempotency_key],
        }


@app.get("/admin/calls")
def list_all_calls() -> dict[str, Any]:
    """Return the full call-count table — useful for oracle diffing."""
    with _lock:
        return {"calls": dict(_call_counts)}


@app.post("/admin/crash")
def enable_crash() -> dict[str, str]:
    """Make every subsequent charge/refund return 500."""
    global _crash_mode
    with _lock:
        _crash_mode = True
    return {"status": "crash mode enabled"}


@app.post("/admin/recover")
def disable_crash() -> dict[str, str]:
    """Return to normal operation."""
    global _crash_mode
    with _lock:
        _crash_mode = False
    return {"status": "crash mode disabled"}


@app.post("/admin/reset")
def reset_state() -> dict[str, str]:
    """Wipe all recorded calls — call this between test runs."""
    global _crash_mode
    with _lock:
        _crash_mode = False
        _recorded_charges.clear()
        _recorded_refunds.clear()
        _call_counts.clear()
    return {"status": "reset"}
