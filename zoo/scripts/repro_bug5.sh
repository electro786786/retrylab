#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Bug 5: Non-atomic dual write.
# The target charges the provider, then crashes before saving the local row.
# A retry hits the provider again → double charge.
#
# Oracle: mock_call_count for the key should be 1. With this bug it is 2.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEY="bug5-$(date +%s)"

header "Bug 5 — Non-atomic dual write"
info "Restarting app with BUG_5_NON_ATOMIC_DUAL_WRITE=True and crash enabled…"
restart_app BUG_5_NON_ATOMIC_DUAL_WRITE=True BUG_5_CRASH_AFTER_PROVIDER=1
reset_mock

# First: create a customer so we have a wallet
CUST=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: setup-$KEY" \
    -H "Content-Type: application/json" \
    -d '{"name":"Bug5 User","email":"bug5@example.com"}')
CUST_ID=$(echo "$CUST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
info "Customer id: $CUST_ID"

info "Attempt 1 — app will crash after charging the provider…"
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":1000}" > /dev/null 2>&1 || true

COUNT1=$(mock_call_count "$KEY")
info "Provider call count after attempt 1: $COUNT1"

info "Restarting without the crash flag so retry can complete…"
restart_app BUG_5_NON_ATOMIC_DUAL_WRITE=True BUG_5_CRASH_AFTER_PROVIDER=0

info "Attempt 2 — retry of the same payment key…"
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":1000}" > /dev/null

COUNT2=$(mock_call_count "$KEY")
info "Provider call count after retry: $COUNT2"

if [ "$COUNT2" -gt 1 ]; then
    fail "Provider was called $COUNT2 times for the same key — double charge! Bug confirmed."
else
    pass "Provider called exactly once — no double charge."
fi

echo ""
header "Fixed twin — restarting with no bug flags…"
restart_app
reset_mock
CUST=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: setup-$KEY-fixed" \
    -H "Content-Type: application/json" \
    -d '{"name":"Bug5 Fixed","email":"bug5fixed@example.com"}')
CUST_ID=$(echo "$CUST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":500}" > /dev/null
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":500}" > /dev/null
COUNT=$(mock_call_count "$KEY-fixed")
if [ "$COUNT" -eq 1 ]; then
    pass "Fixed: provider called exactly once for key=$KEY-fixed"
else
    fail "Fixed twin still calls provider $COUNT times."
fi
