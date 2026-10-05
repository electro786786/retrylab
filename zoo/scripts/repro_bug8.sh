#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Bug 8: Idempotency key saved before the work runs.
#
# How it works:
#   1. App starts with BUG_8_KEY_SAVED_BEFORE_WORK=True.
#   2. Attempt 1 arrives. The app writes a fake "success" response to the
#      idempotency_keys table and commits it, THEN raises RuntimeError before
#      doing any real work. The client gets a 500.
#   3. We restart the app (same bug flag, crash disabled).
#   4. Attempt 2 (retry) arrives. The app finds the cached "success" key and
#      immediately returns it — even though NO Payment row exists in the DB.
#
# Bug oracle: the retry response has id="pending" (the fake ID we saved) AND
# the payment count delta is 0 (no real payment was ever created).
#
# Expected (bug ON):
#   Attempt 1 → HTTP 500 (crash)
#   Attempt 2 → HTTP 200 with {"id":"pending",...}  ← phantom success
#   Payments created: 0
#
# Expected (bug OFF / fixed twin):
#   Attempt 1 → HTTP 200 (real payment)
#   Attempt 2 → HTTP 200 (same real payment, idempotent replay)
#   Payments created: 1
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEY="bug8-$(date +%s)"

header "Bug 8 — Key saved before work runs"
info "Restarting app with BUG_8_KEY_SAVED_BEFORE_WORK=True and crash enabled…"
restart_app BUG_8_KEY_SAVED_BEFORE_WORK=True BUG_8_CRASH_AFTER_KEY_SAVE=1

CUST=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: setup-$KEY" \
    -H "Content-Type: application/json" \
    -d '{"name":"Bug8 User","email":"bug8@example.com"}')
CUST_ID=$(echo "$CUST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
info "Customer id: $CUST_ID"

START_COUNT=$(curl -sf "$APP_URL/admin/payments/count" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")

info "Attempt 1 — app will crash after saving key but before running payment…"
HTTP1=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":1000}")
info "Attempt 1 HTTP status: $HTTP1 (expected 500)"

# Verify the key was actually committed despite the crash
KEY_STATUS=$(docker compose exec -T db psql -U postgres -d zoo -t -c \
    "SELECT status_code FROM idempotency_keys WHERE key='$KEY';" | tr -d ' \n')
info "Idempotency key status_code in DB after crash: '$KEY_STATUS'"

if [ "$KEY_STATUS" != "200" ]; then
    fail "Premature key was NOT committed to DB (got '$KEY_STATUS'). Cannot demonstrate Bug 8."
    info "This means the crash rolled back the transaction before commit."
    exit 1
fi
pass "Premature key WAS committed (status_code=200 in DB despite 500 response)"

info "Restarting app (crash disabled, bug flag still on)…"
restart_app BUG_8_KEY_SAVED_BEFORE_WORK=True BUG_8_CRASH_AFTER_KEY_SAVE=0

info "Attempt 2 — retry with the same key…"
R=$(curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":1000}")
info "Retry response: $R"

RETRY_ID=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
END_COUNT=$(curl -sf "$APP_URL/admin/payments/count" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")
NEW_PAYMENTS=$((END_COUNT - START_COUNT))
info "New payment rows created: $NEW_PAYMENTS | Retry response id: $RETRY_ID"

if [ "$RETRY_ID" = "pending" ] && [ "$NEW_PAYMENTS" -eq 0 ]; then
    fail "Phantom success! Retry returned {id:pending} but zero payments exist in DB. Bug confirmed."
elif [ "$NEW_PAYMENTS" -eq 0 ]; then
    fail "No payment created, but response id was '$RETRY_ID' (not 'pending'). Unexpected."
else
    pass "Retry correctly created a real payment row (id=$RETRY_ID). Bug NOT triggered."
fi

echo ""
header "Fixed twin — restarting with no bug flags…"
restart_app
CUST=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: setup-$KEY-fixed" \
    -H "Content-Type: application/json" \
    -d '{"name":"Bug8 Fixed","email":"bug8fixed@example.com"}')
CUST_ID=$(echo "$CUST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

START_COUNT=$(curl -sf "$APP_URL/admin/payments/count" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")

R1=$(curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":500}")
R2=$(curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":500}")

ID1=$(echo "$R1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
ID2=$(echo "$R2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
END_COUNT=$(curl -sf "$APP_URL/admin/payments/count" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")
NEW_PAYMENTS=$((END_COUNT - START_COUNT))

if [ "$ID1" = "$ID2" ] && [ "$NEW_PAYMENTS" -eq 1 ]; then
    pass "Fixed: same real payment id=$ID1 returned for both requests, exactly 1 row created."
else
    fail "Fixed twin created $NEW_PAYMENTS rows, id1=$ID1 id2=$ID2"
fi
