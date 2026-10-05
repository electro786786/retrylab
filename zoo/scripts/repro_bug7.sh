#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Bug 7: Same key reused with a different payload is silently accepted.
# Correct behaviour: a 422 Unprocessable Entity with a clear message.
# Bug:              the second (different) request is silently processed.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
source "$(dirname "$0")/lib.sh"

KEY="bug7-$(date +%s)"

header "Bug 7 — Silent payload mismatch"
info "Restarting app with BUG_7_SILENT_PAYLOAD_MISMATCH=True…"
restart_app BUG_7_SILENT_PAYLOAD_MISMATCH=True

info "First request: name=Alice"
R1=$(curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}')
ID1=$(echo "$R1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
info "Response 1: id=$ID1"

info "Second request with SAME key but DIFFERENT payload (name=Mallory)…"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d '{"name":"Mallory","email":"mallory@example.com"}')
info "HTTP status: $STATUS"

if [ "$STATUS" = "200" ]; then
    fail "Different payload accepted silently (HTTP $STATUS). Bug confirmed."
else
    pass "Mismatch rejected with HTTP $STATUS."
fi

echo ""
header "Fixed twin — restarting with no bug flags…"
restart_app
curl -sf -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d '{"name":"Alice","email":"alice@example.com"}' > /dev/null
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$APP_URL/customers" \
    -H "Idempotency-Key: $KEY-fixed" \
    -H "Content-Type: application/json" \
    -d '{"name":"Mallory","email":"mallory@example.com"}')
if [ "$STATUS" = "422" ]; then
    pass "Fixed: mismatch correctly returns HTTP 422."
else
    fail "Fixed twin returned HTTP $STATUS instead of 422."
fi
