#!/usr/bin/env bash
# Smoke test: verifies all 3 containers are working correctly in the fixed (default) mode.
set -euo pipefail

APP="http://localhost:8000"
MOCK="http://localhost:8002"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}PASS${NC}  $*"; }
fail() { echo -e "  ${RED}FAIL${NC}  $*"; exit 1; }
info() { echo -e "  ${CYAN}-->${NC}   $*"; }

echo ""
echo "========================================"
echo "  RetryLab Week 3 - Smoke Test"
echo "========================================"

KEY_CUST="smoke-cust-$(date +%s)"
KEY_PAY="smoke-pay-$(date +%s)"

# ── 1. Create customer ────────────────────────────────────────────────────────
echo ""
echo "1. Create customer"
R1=$(curl -sf -X POST "$APP/customers" \
    -H "Idempotency-Key: $KEY_CUST" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}')
ID1=$(echo "$R1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
BAL=$(echo "$R1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['wallet_balance'])")
info "Customer id=$ID1  wallet_balance=$BAL"
[ -n "$ID1" ] && pass "Customer created" || fail "Missing id in response"

# ── 2. Idempotent retry returns same id ───────────────────────────────────────
echo ""
echo "2. Retry same key -> same id"
R2=$(curl -sf -X POST "$APP/customers" \
    -H "Idempotency-Key: $KEY_CUST" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}')
ID2=$(echo "$R2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
info "Retry id=$ID2"
[ "$ID1" = "$ID2" ] && pass "Same id returned (idempotent)" || fail "Different id returned!"

# ── 3. Bug 7 guard: different payload on same key -> 422 ─────────────────────
echo ""
echo "3. Same key, different payload -> HTTP 422"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$APP/customers" \
    -H "Idempotency-Key: $KEY_CUST" \
    -H "Content-Type: application/json" \
    -d '{"name":"Mallory","email":"mallory@example.com"}')
info "HTTP status=$STATUS"
[ "$STATUS" = "422" ] && pass "Payload mismatch correctly rejected" || fail "Expected 422, got $STATUS"

# ── 4. Create payment (calls mock downstream) ─────────────────────────────────
echo ""
echo "4. Create payment -> calls mock downstream"
R3=$(curl -sf -X POST "$APP/payments" \
    -H "Idempotency-Key: $KEY_PAY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$ID1\",\"amount\":500,\"currency\":\"USD\"}")
PAY_ID=$(echo "$R3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")
CHG_ID=$(echo "$R3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['provider_charge_id'])")
info "Payment id=$PAY_ID  provider_charge_id=$CHG_ID"
[ -n "$PAY_ID" ] && pass "Payment created" || fail "Missing payment id"

# ── 5. Mock downstream recorded exactly 1 call ───────────────────────────────
echo ""
echo "5. Mock downstream call count for payment key = 1"
COUNT=$(curl -sf "$MOCK/admin/calls/$KEY_PAY" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['call_count'])")
info "Call count=$COUNT"
[ "$COUNT" = "1" ] && pass "Provider called exactly once" || fail "Expected 1 call, got $COUNT"

# ── 6. Duplicate payment returns cached response, NOT a second charge ─────────
echo ""
echo "6. Duplicate payment key -> mock call count stays at 1"
curl -sf -X POST "$APP/payments" \
    -H "Idempotency-Key: $KEY_PAY" \
    -H "Content-Type: application/json" \
    -d "{\"customer_id\":\"$ID1\",\"amount\":500,\"currency\":\"USD\"}" > /dev/null
COUNT2=$(curl -sf "$MOCK/admin/calls/$KEY_PAY" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['call_count'])")
info "Call count after retry=$COUNT2"
[ "$COUNT2" = "1" ] && pass "No double charge - count still 1" || fail "Double charge! Count=$COUNT2"

# ── 7. Wallet balance reduced correctly ───────────────────────────────────────
echo ""
echo "7. Wallet balance after payment"
BAL2=$(curl -sf "$APP/customers/$ID1/wallet" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['balance'])")
EXPECTED=$((BAL - 500))
info "Balance=$BAL2  Expected=$EXPECTED"
[ "$BAL2" = "$EXPECTED" ] && pass "Balance correctly reduced" || fail "Balance wrong: got $BAL2, expected $EXPECTED"

# ── 8. Mock downstream reset endpoint works ───────────────────────────────────
echo ""
echo "8. Mock reset"
curl -sf -X POST "$MOCK/admin/reset" > /dev/null
COUNT3=$(curl -sf "$MOCK/admin/calls" \
    | python3 -c "import sys,json; print(len(json.load(sys.stdin)['calls']))")
info "Call entries after reset=$COUNT3"
[ "$COUNT3" = "0" ] && pass "Mock reset cleanly" || fail "Mock still has $COUNT3 entries after reset"

echo ""
echo "========================================"
echo "  All smoke tests passed!"
echo "========================================"
echo ""
