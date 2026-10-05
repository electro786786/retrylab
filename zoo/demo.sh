#!/usr/bin/env bash
set -e

echo "=== Bug Zoo Demo ==="
echo "Note: Make sure the app is running in the background (docker-compose up target_app -d)"
echo ""

# The tests rely on being able to restart the app with different ENV vars for feature flags.
# Since we are using curl against a running container, we should demonstrate how to do it.

echo "Demonstrating Bug 2: No idempotency handling (Duplicate POST creates two rows)"
echo "Starting app with BUG_2_NO_IDEMPOTENCY=True..."
docker-compose up -d db
docker-compose run -d -p 8000:8000 -e BUG_2_NO_IDEMPOTENCY=True --name bug2_app target_app
sleep 3 # wait for startup

echo "Sending first request..."
curl -s -X POST http://localhost:8000/customers \
     -H "Idempotency-Key: bug2-key-123" \
     -H "Content-Type: application/json" \
     -d '{"name": "Alice", "email": "alice@example.com"}' | grep -o '"id"'

echo "Sending duplicate request..."
curl -s -X POST http://localhost:8000/customers \
     -H "Idempotency-Key: bug2-key-123" \
     -H "Content-Type: application/json" \
     -d '{"name": "Alice", "email": "alice@example.com"}' | grep -o '"id"'

echo "Both requests returned a new ID (not cached)!"
docker rm -f bug2_app

echo ""
echo "Demonstrating Correct Behavior"
echo "Starting app normally..."
docker-compose run -d -p 8000:8000 --name fixed_app target_app
sleep 3

echo "Sending first request..."
curl -s -X POST http://localhost:8000/customers \
     -H "Idempotency-Key: correct-key-123" \
     -H "Content-Type: application/json" \
     -d '{"name": "Bob", "email": "bob@example.com"}' > first.json
cat first.json

echo "Sending duplicate request..."
curl -s -X POST http://localhost:8000/customers \
     -H "Idempotency-Key: correct-key-123" \
     -H "Content-Type: application/json" \
     -d '{"name": "Bob", "email": "bob@example.com"}' > second.json
cat second.json

echo "Responses should be identical (same ID):"
diff first.json second.json && echo "Identical!" || echo "Different!"

docker rm -f fixed_app
echo "Done!"
