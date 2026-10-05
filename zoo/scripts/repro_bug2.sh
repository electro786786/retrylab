#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Bug 2: No idempotency handling.
# Every POST creates a new row regardless of the Idempotency-Key header.
#
# Expected (bug ON):  two different customer IDs for the same key.
# Expected (bug OFF): identical customer ID for both requests.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEY="bug2-$(date +%s)"

header "Bug 2 — No idempotency handling"
info "Restarting app with BUG_2_NO_IDEMPOTENCY=True…"
restart_app BUG_2_NO_IDEMPOTENCY=True

info "Sending first request (key=$KEY)…"
R1=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}')
ID1=$(echo "$R1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
info "Response 1 id: $ID1"

info "Sending duplicate request (same key, same body)…"
R2=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}')
ID2=$(echo "$R2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
info "Response 2 id: $ID2"

if [ "$ID1" != "$ID2" ]; then
    fail "IDs differ ($ID1 vs $ID2) — two customer rows were created! Bug confirmed."
else
    pass "IDs are identical — idempotency is working."
fi

echo ""
header "Fixed twin — restarting with no bug flags…"
restart_app
R1=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}')
ID1=$(echo "$R1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
R2=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}')
ID2=$(echo "$R2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
if [ "$ID1" = "$ID2" ]; then
    pass "Fixed: both responses returned id=$ID1"
else
    fail "Fixed twin still returns different IDs — something is wrong."
fi
