#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Bug 4: Idempotency key not scoped to user or endpoint.
# User A's completed key can replay a response to User B.
#
# Expected (bug ON):  User B receives User A's customer record.
# Expected (bug OFF): User B's request creates a brand-new customer.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEY="bug4-$(date +%s)"

header "Bug 4 — Unscoped idempotency key"
info "Restarting app with BUG_4_UNSCOPED_KEY=True…"
restart_app BUG_4_UNSCOPED_KEY=True

info "User A creates a customer with key=$KEY…"
RA=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY" \
    -H "User-Id: user-a" \
    -H "Content-Type: application/json" \
    -d '{"name":"User A Customer","email":"a@example.com"}')
ID_A=$(echo "$RA" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
info "User A's customer id: $ID_A"

info "User B sends a request with the SAME key…"
RB=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY" \
    -H "User-Id: user-b" \
    -H "Content-Type: application/json" \
    -d '{"name":"User B Customer","email":"b@example.com"}')
ID_B=$(echo "$RB" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
info "User B received customer id: $ID_B"

if [ "$ID_A" = "$ID_B" ]; then
    fail "User B got User A's response (id=$ID_A)! Bug confirmed."
else
    pass "User B got a different id ($ID_B) — scoping is working."
fi

echo ""
header "Fixed twin — restarting with no bug flags…"
restart_app
RA=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "User-Id: user-a" \
    -H "Content-Type: application/json" \
    -d '{"name":"User A Customer","email":"a@example.com"}')
ID_A=$(echo "$RA" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
RB=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "User-Id: user-b" \
    -H "Content-Type: application/json" \
    -d '{"name":"User B Customer","email":"b@example.com"}')
ID_B=$(echo "$RB" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
if [ "$ID_A" != "$ID_B" ]; then
    pass "Fixed: User A=$ID_A, User B=$ID_B — keys are scoped correctly."
else
    fail "Fixed twin is still leaking responses across users."
fi
