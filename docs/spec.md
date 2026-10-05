# Idempotency Fuzzer Specification

## Concept of Idempotency
An idempotent endpoint guarantees that applying the same operation multiple times has the same side-effects and returns the same response as applying it once.

For our bug zoo and fuzzer, we follow Stripe's design principles:
1. **Idempotency Key**: Clients provide an `Idempotency-Key` header (usually a UUID).
2. **First Request**: The server processes the request normally, saves the response status and payload against the idempotency key, and returns the response.
3. **Subsequent Requests**: If the server sees a request with an already-used idempotency key, it skips execution, avoids side effects, and replays the original response.
4. **Concurrency Race Condition**: If a request with an idempotency key is currently executing, concurrent requests with the same key should either wait for the first to finish (and return the cached response) or return a 409 Conflict. They must not double-execute.
5. **Payload Mismatch**: If a request uses an existing key but a different request payload, it should be rejected to prevent silent errors.

## The Oracle
The tool uses a diff-based oracle to detect idempotency violations. It works by running the same scenario on two identical database clones.

### Process
1. **Snapshot**: Create a pristine snapshot of the database (e.g., via `CREATE DATABASE ... TEMPLATE`).
2. **Clone A (Clean Run)**: Execute the scenario with exactly 1 request per operation.
3. **Clone B (Fuzzed Run)**: Execute the scenario with $k$ duplicate requests (sequential, concurrent, with race conditions and fault injections).
4. **Diff**: Compare Clone A and Clone B.

### Oracle Checks
The fuzzer flags a bug if it detects any of the following:
1. **State Mismatch**: The business state of the databases (excluding auto-increment IDs, generated UUIDs, and timestamps) differs. Example: Two rows created instead of one, or a balance incorrectly deducted twice.
2. **Side-Effect Mismatch**: The number of calls to the external mock downstream system differs. Example: The user was charged twice on Stripe.
3. **Invariant Violation**: Standard assertions on the database (e.g., `SELECT SUM(balance)` remains consistent) are violated.
4. **Response Mismatch**: A duplicate request returns a different response body or status code than the original request, or fails to return the cached result.

## Shrinking
To make bugs understandable, we use a minimization strategy (inspired by Hypothesis):
When a failing trace is found (e.g., 50 requests over 10 seconds), the shrinker iteratively reduces the test case:
1. Try fewer duplicate requests.
2. Try simpler payloads / fewer fields.
3. Try simpler thread interleavings or fewer fault injections.
The minimal case that still reliably triggers the oracle mismatch is presented to the user.
