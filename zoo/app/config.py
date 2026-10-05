
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5433/zoo"
    mock_url: str = "http://localhost:8002"

    # ── Bug feature flags ───────────────────────────────────────────────────────

    # Bug 1: Check-then-act race on the idempotency key (SELECT then INSERT).
    #        Two concurrent requests can both pass the SELECT check before either
    #        completes the INSERT, causing duplicate work.
    bug_1_race_condition: bool = False

    # Bug 2: No idempotency handling at all.
    #        Every POST creates a new row regardless of the key.
    bug_2_no_idempotency: bool = False

    # Bug 3: Missing unique constraint on the idempotency_key column.
    #        The app logic checks for duplicates but the DB allows them anyway,
    #        so a race always wins.
    bug_3_missing_unique_constraint: bool = False

    # Bug 4: Idempotency key is not scoped to (user_id, endpoint).
    #        User A's key can replay User B's response.
    bug_4_unscoped_key: bool = False

    # Bug 5: Non-atomic dual write.
    #        The target charges the provider first, then saves the local payment
    #        row.  If the process crashes between those two steps, a retry hits
    #        the provider a second time (double charge).
    bug_5_non_atomic_dual_write: bool = False

    # Bug 6: Lost update on wallet balances.
    #        Read-modify-write without a SELECT FOR UPDATE lock, so concurrent
    #        debits can each read the same starting balance and both succeed.
    bug_6_lost_update: bool = False

    # Bug 7: Same key reused with a different payload is silently accepted.
    #        The correct behaviour is to reject it with 422 Unprocessable Entity.
    bug_7_silent_payload_mismatch: bool = False

    # Bug 8: Idempotency key is saved (status=pending) *before* the work runs.
    #        If a crash happens mid-work, the retry sees the cached "success"
    #        response even though the payment never completed.
    bug_8_key_saved_before_work: bool = False


settings = Settings()
