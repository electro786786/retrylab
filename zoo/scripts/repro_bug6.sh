#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Bug 6: Lost update on wallet balance.
# Two concurrent payments read the same balance, both pass the funds check,
# and both debit — but only one debit is actually applied.
#
# This script fires two payments in parallel and then checks the wallet balance.
# Correct: balance should drop by (amount1 + amount2).
# Bug:     balance drops by only max(amount1, amount2).
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEY1="bug6a-$(date +%s)"
KEY2="bug6b-$(date +%s)"
AMOUNT=500  # cents each; starting balance is 10000

header "Bug 6 — Lost update on wallet balance"
info "Restarting app with BUG_6_LOST_UPDATE=True…"
restart_app BUG_6_LOST_UPDATE=True

# Setup
CUST=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: setup-$KEY1" \
    -H "Content-Type: application/json" \
    -d '{"name":"Bug6 User","email":"bug6@example.com"}')
CUST_ID=$(echo "$CUST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
INITIAL=$(curl -sf "$APP_URL/customers/$CUST_ID/wallet" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['balance'])")
info "Customer id: $CUST_ID  |  Starting balance: $INITIAL"

info "Firing two concurrent payments of \$$AMOUNT each…"
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY1" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":$AMOUNT}" > /dev/null &
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY2" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":$AMOUNT}" > /dev/null &
wait

FINAL=$(curl -sf "$APP_URL/customers/$CUST_ID/wallet" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['balance'])")
EXPECTED=$((INITIAL - AMOUNT * 2))
info "Final balance: $FINAL  |  Expected: $EXPECTED"

if [ "$FINAL" -ne "$EXPECTED" ]; then
    fail "Balance is $FINAL instead of $EXPECTED — lost update! Bug confirmed."
else
    pass "Balance correctly reduced to $FINAL."
fi

echo ""
header "Fixed twin — restarting with no bug flags…"
restart_app
CUST=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: setup-$KEY1-fixed" \
    -H "Content-Type: application/json" \
    -d '{"name":"Bug6 Fixed","email":"bug6fixed@example.com"}')
CUST_ID=$(echo "$CUST" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
INITIAL=$(curl -sf "$APP_URL/customers/$CUST_ID/wallet" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['balance'])")

curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY1-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":$AMOUNT}" > /dev/null &
curl -sf -X POST "$APP_URL/payments" \
    -H "Idempotency-Key: $KEY2-fixed" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$CUST_ID\",\"amount\":$AMOUNT}" > /dev/null &
wait

FINAL=$(curl -sf "$APP_URL/customers/$CUST_ID/wallet" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['balance'])")
EXPECTED=$((INITIAL - AMOUNT * 2))
if [ "$FINAL" -eq "$EXPECTED" ]; then
    pass "Fixed: balance is correctly $FINAL"
else
    fail "Fixed twin balance is $FINAL, expected $EXPECTED."
fi
