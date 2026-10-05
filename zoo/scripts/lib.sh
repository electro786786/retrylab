#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers for all bug reproduction scripts.
# Source this file at the top of each script: source "$(dirname "$0")/lib.sh"
# ──────────────────────────────────────────────────────────────────────────────

APP_URL="http://localhost:8000"
MOCK_URL="http://localhost:8002"

# Colour codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓ PASS${NC}  $*"; }
fail() { echo -e "  ${RED}✗ FAIL${NC}  $*"; }
info() { echo -e "  ${CYAN}→${NC}      $*"; }
header() { echo -e "\n${YELLOW}▶ $*${NC}"; }

# Wait until the app is healthy (up to 30 s)
wait_for_app() {
    local url="${1:-$APP_URL}"
    local i=0
    while ! curl -sf "$url/docs" > /dev/null 2>&1; do
        sleep 1
        i=$((i+1))
        if [ $i -ge 30 ]; then
            echo "App at $url did not become ready in 30 s" >&2
            exit 1
        fi
    done
}

# Reset mock downstream state between runs
reset_mock() {
    curl -sf -X POST "$MOCK_URL/admin/reset" > /dev/null
}

# Return the number of times the mock was called for a given idempotency key
mock_call_count() {
    curl -sf "$MOCK_URL/admin/calls/$1" | python3 -c "import sys,json; print(json.load(sys.stdin)['call_count'])"
}

# Restart target_app with given env vars, then wait for it to be healthy.
# Usage: restart_app BUG_2_NO_IDEMPOTENCY=True BUG_5_NON_ATOMIC_DUAL_WRITE=True
restart_app() {
    docker compose rm -s -f target_app > /dev/null 2>&1
    env "$@" docker compose up -d target_app > /dev/null 2>&1
    wait_for_app
}
