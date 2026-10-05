#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Bug 8: Idempotency key saved before the work runs.
# The key is written with a success status_code before the payment is made.
# A crash mid-payment means the retry returns a cached success even though
# no Payment row was ever created.
#
# Oracle: after the crash + retry, /admin/payments/count should be 1.
# With this bug it is 0 (the payment never happened, but the client thinks it did).
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

info "Attempt 1 — app will crash after saving the key but before running payment…"
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":1000}" > /dev/null 2>&1 || true

info "Restarting app (crash flag still on — to simulate the key is already saved)…"
restart_app BUG_8_KEY_SAVED_BEFORE_WORK=True BUG_8_CRASH_AFTER_KEY_SAVE=0

info "Attempt 2 — retry…"
R=$(curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":1000}")
info "Retry response: $R"

END_COUNT=$(curl -sf "$APP_URL/admin/payments/count" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")
COUNT=$((END_COUNT - START_COUNT))
info "New payment rows created: $COUNT"

if [ "$COUNT" -eq 0 ]; then
    fail "Retry returned success but no Payment row exists — phantom success! Bug confirmed."
else
    pass "Payment row exists ($COUNT) — retry created the payment correctly."
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

curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":500}" > /dev/null
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":500}" > /dev/null

END_COUNT=$(curl -sf "$APP_URL/admin/payments/count" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")
COUNT=$((END_COUNT - START_COUNT))
if [ "$COUNT" -eq 1 ]; then
    pass "Fixed: exactly 1 payment row created for 2 requests with the same key."
else
    fail "Fixed twin created $COUNT payment rows."
fi
