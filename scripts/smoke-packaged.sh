#!/usr/bin/env bash
# Packaged-install smoke test.
#
# Installs engine and api non-editable into a throwaway venv and boots
# the app the way the container does. Three deployment-only defects got
# through the normal suite because an editable install resolves paths
# the real one does not:
#
#   * the engine configuration path walked out of site-packages;
#   * item_bank.json was never declared as package data;
#   * the candidate access token lived on an RLS-protected table, so no
#     candidate could authenticate.
#
# None of them was visible in a source checkout. This catches that class.
#
# Usage: ./scripts/smoke-packaged.sh <database-url>
set -euo pipefail

DB_URL="${1:?usage: smoke-packaged.sh <database-url>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$(mktemp -d)/venv"

python -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q "$ROOT/engine"
"$VENV/bin/pip" install -q "$ROOT/api[postgres]"

# Deliberately NOT run from the repository root: a path that only works
# because of the checkout layout must fail here.
cd /

export APTUS_ENV=production
export APTUS_SECRET_KEY="smoke-test-key-at-least-thirty-two-characters"
export APTUS_DATABASE_URL="$DB_URL"
export APTUS_ALLOWED_ORIGINS="https://smoke.example.edu.au"
export APTUS_ENGINE_CONFIG_DIR="$ROOT/engine/config/v1.0.0"
export APTUS_REQUIRE_EMAIL_VERIFICATION=false

"$VENV/bin/uvicorn" aptus_api.main:create_app --factory \
  --host 127.0.0.1 --port 8137 > /tmp/smoke.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:8137/health >/dev/null 2>&1 && break
  sleep 1
done

fail() { echo "SMOKE FAILED: $1"; echo "--- server log ---"; tail -30 /tmp/smoke.log; exit 1; }

B=http://127.0.0.1:8137
curl -sf "$B/health"  >/dev/null || fail "/health unreachable"
curl -sf "$B/version" >/dev/null || fail "/version failed (engine config not found?)"

python - <<'PY' || exit 1
import json, urllib.request
r = json.load(urllib.request.urlopen("http://127.0.0.1:8137/rls"))
assert r["enforced"], f"row-level security not enforced: {r['problems']}"
print(f"  rls enforced as {r['role']} across {len(r['tables'])} tables")
PY

# The whole flow, because each of the three defects surfaced at a
# different point in it.
python - <<'PY' || exit 1
import json, urllib.request as u

B = "http://127.0.0.1:8137"

def call(path, body=None, token=None):
    req = u.Request(B + path, method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    return json.load(u.urlopen(req, data))

import secrets
who = f"smoke{secrets.token_hex(4)}@example.edu.au"
call("/auth/signup", {"email": who, "password": "a-long-enough-password",
                      "organisation_name": "Smoke RTO"})
token = call("/auth/signin", {"email": who, "password": "a-long-enough-password"})["token"]
org = call("/auth/me", token=token)["organisations"][0]["id"]

cand = call(f"/orgs/{org}/candidates", {"email": f"learner-{who}"}, token=token)
access = cand["access_token"]

items = call(f"/assessment/full", token=access)["items"]
assert len(items) == 24, f"expected 24 items, got {len(items)}"

result = call("/assessment/full/submit",
              {"responses": {i["item_id"]: "A" for i in items}}, token=access)
assert result["overall"]["band"] == "Strong", result["overall"]
assert len(result["constructs"]) == 12

detail = call(f"/orgs/{org}/candidates/{cand['id']}", token=token)
assert detail["passport"]["attempt_count"] == 1, detail["passport"]

pathway = call(f"/orgs/{org}/candidates/{cand['id']}/pathway", token=token)
assert len(pathway["strongest_constructs"]) == 3

print("  signup, invite, assess, score, passport and pathway all OK")
PY

echo "SMOKE PASSED"
