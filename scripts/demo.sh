#!/usr/bin/env bash
# Narrated walkthrough of every built feature against a running API.
#
# Each step prints what it is proving, calls the real endpoint, and
# checks the answer. A step that fails stops the run and says what it
# expected, so this doubles as an acceptance test you can hand someone.
#
# Usage:  ./scripts/demo.sh [base-url]        (default http://127.0.0.1:8000)
set -uo pipefail

BASE="${1:-http://127.0.0.1:8000}"
PASS=0; FAIL=0
RUN="$(date +%s)$$"

bold()  { printf '\033[1m%s\033[0m\n' "$1"; }
step()  { printf '\n\033[1m%s\033[0m\n' "── $1"; }
why()   { printf '   \033[2m%s\033[0m\n' "$1"; }
ok()    { PASS=$((PASS+1)); printf '   \033[32m✓\033[0m %s\n' "$1"; }
bad()   { FAIL=$((FAIL+1)); printf '   \033[31m✗\033[0m %s\n' "$1"; }

# check <description> <actual> <expected>
check() { [ "$2" = "$3" ] && ok "$1" || bad "$1 — expected '$3', got '$2'"; }

api() { # api METHOD PATH [TOKEN] [BODY]
  local method="$1" path="$2" token="${3:-}" body="${4:-}"
  local args=(-s -X "$method" "$BASE$path" -H 'Content-Type: application/json')
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  [ -n "$body" ]  && args+=(-d "$body")
  curl "${args[@]}"
}
code() { # same, but print the HTTP status only
  local method="$1" path="$2" token="${3:-}" body="${4:-}"
  local args=(-s -o /dev/null -w '%{http_code}' -X "$method" "$BASE$path" -H 'Content-Type: application/json')
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  [ -n "$body" ]  && args+=(-d "$body")
  curl "${args[@]}"
}
jq_() { python3 -c "import json,sys
try: d=json.load(sys.stdin)
except Exception: print(''); raise SystemExit
try:
    $1
except Exception: print('')"; }

rate_limited() {
  printf '\n\033[31mSignup is rate limited on this server.\033[0m\n'
  echo "That is the limiter doing its job — five signups per hour per IP."
  echo "It is in-process, so restarting the API clears it:"
  echo "  docker compose restart       (or restart uvicorn)"
  echo "Then run this script again."
  exit 1
}

# Every signup goes through here. Checking only the first was not
# enough: the window can have room for one signup and not for four,
# which then fails later steps for the wrong reason.
signup() { # signup EMAIL ORG_NAME -> prints the response body
  api POST /auth/signup "" "{\"email\":\"$1\",\"password\":\"$PW\",\"organisation_name\":\"$2\"}"
}

# Must be called in the parent shell, never inside $( ). An exit inside
# a command substitution leaves only the subshell, so the script would
# carry on and fail later steps for the wrong reason.
bail_if_limited() {
  case "$1" in *"Too many requests"*) rate_limited ;; esac
}

PW="a-long-enough-password"

bold "Aptus walkthrough against $BASE"


# ───────────────────────────────────────────────────────── operations
step "1. The service is up and says what it is running"
why  "The engine digest identifies the exact scoring configuration behind every result."
check "health" "$(api GET /health | jq_ "print(d['status'])")" "ok"
VER=$(api GET /version)
echo "   engine config $(echo "$VER" | jq_ "print(d['engine_config_version'])") · digest $(echo "$VER" | jq_ "print(d['engine_config_digest'][:12])")"

step "2. Tenant isolation is enforced by the database"
why  "A superuser or BYPASSRLS connection ignores every policy silently. This is how you check."
RLS=$(api GET /rls)
check "row-level security enforced" "$(echo "$RLS" | jq_ "print(d['enforced'])")" "True"
echo "   role $(echo "$RLS" | jq_ "print(d['role'])") · $(echo "$RLS" | jq_ "print(len(d['tables']))") protected tables"

# ───────────────────────────────────────────────────────── self-serve
step "3. An institution signs itself up"
why  "No one provisions it by hand. That is the self-serve architecture."
A_EMAIL="north-$RUN@example.edu.au"
FIRST=$(signup "$A_EMAIL" "North TAFE"); bail_if_limited "$FIRST"
A_TOK=$(api POST /auth/signin "" "{\"email\":\"$A_EMAIL\",\"password\":\"$PW\"}" | jq_ "print(d['token'])")
[ -n "$A_TOK" ] && ok "signed up and signed in" || { bad "could not sign in"; exit 1; }
A_ORG=$(api GET /auth/me "$A_TOK" | jq_ "print(d['organisations'][0]['id'])")
echo "   organisation id $A_ORG, role $(api GET /auth/me "$A_TOK" | jq_ "print(d['organisations'][0]['role'])")"

step "4. Signup reveals nothing about who already has an account"
why  "A different answer for a known address turns signup into an account-enumeration oracle."
R1=$(signup "$A_EMAIL" "Impostor"); bail_if_limited "$R1"
R2=$(signup "fresh-$RUN@example.edu.au" "Fresh"); bail_if_limited "$R2"
check "duplicate and fresh signup are indistinguishable" "$([ "$R1" = "$R2" ] && echo same || echo different)" "same"
check "wrong password rejected" "$(code POST /auth/signin "" "{\"email\":\"$A_EMAIL\",\"password\":\"wrong-password-entirely\"}")" "401"
check "unknown address rejected identically" "$(code POST /auth/signin "" "{\"email\":\"nobody-$RUN@example.edu.au\",\"password\":\"wrong-password-entirely\"}")" "401"

step "5. Weak and disposable signups are refused"
check "short password refused" "$(code POST /auth/signup "" "{\"email\":\"x-$RUN@example.edu.au\",\"password\":\"short\",\"organisation_name\":\"X\"}")" "422"
check "disposable domain refused" "$(code POST /auth/signup "" "{\"email\":\"x-$RUN@mailinator.com\",\"password\":\"$PW\",\"organisation_name\":\"X\"}")" "422"

# ───────────────────────────────────────────────────────── roster
step "6. The institution invites a candidate"
why  "The access token is shown once. Only its digest is stored."
CAND=$(api POST "/orgs/$A_ORG/candidates" "$A_TOK" "{\"email\":\"learner-$RUN@example.edu.au\",\"display_name\":\"A Learner\"}")
CID=$(echo "$CAND" | jq_ "print(d['id'])")
CTOK=$(echo "$CAND" | jq_ "print(d['access_token'])")
[ -n "$CTOK" ] && ok "candidate invited (id $CID)" || bad "invite failed: $CAND"
check "duplicate invite refused" "$(code POST "/orgs/$A_ORG/candidates" "$A_TOK" "{\"email\":\"learner-$RUN@example.edu.au\"}")" "409"

step "7. The free tier stops at two seats"
why  "Entitlement is enforced server-side, not in the UI."
api POST "/orgs/$A_ORG/candidates" "$A_TOK" "{\"email\":\"second-$RUN@example.edu.au\"}" >/dev/null
check "third candidate refused with payment required" \
      "$(code POST "/orgs/$A_ORG/candidates" "$A_TOK" "{\"email\":\"third-$RUN@example.edu.au\"}")" "402"

# ───────────────────────────────────────────────────────── assessment
step "8. The candidate takes the assessment"
why  "Candidates hold no password. One token, one assessment: their own."
ASSESS=$(api GET /assessment/full "$CTOK")
check "full set is 24 items" "$(echo "$ASSESS" | jq_ "print(len(d['items']))")" "24"
check "counts toward the passport" "$(echo "$ASSESS" | jq_ "print(d['counts_toward_passport'])")" "True"
RESP=$(echo "$ASSESS" | jq_ "print(json.dumps({i['item_id']:'A' for i in d['items']}))")
RESULT=$(api POST /assessment/full/submit "$CTOK" "{\"responses\":$RESP}")
check "scored across all twelve domains" "$(echo "$RESULT" | jq_ "print(len(d['constructs']))")" "12"
check "all top answers score Strong" "$(echo "$RESULT" | jq_ "print(d['overall']['band'])")" "Strong"
echo "   result bound to engine config $(echo "$RESULT" | jq_ "print(d['engine_config_version'])")"

step "9. Scoring is deterministic"
why  "The product's central claim: identical answers always produce an identical result."
C2=$(api POST "/orgs/$A_ORG/candidates" "$A_TOK" "{\"email\":\"twin-$RUN@example.edu.au\"}" 2>/dev/null)
# Seat cap may block a third; reuse the second candidate instead.
T2=$(echo "$C2" | jq_ "print(d.get('access_token',''))")
if [ -z "$T2" ]; then
  why "(seat cap reached — comparing two submissions by the same candidate instead)"
  R_A=$(api POST /assessment/quick/submit "$CTOK" "{\"responses\":$RESP}" | jq_ "print(json.dumps(d['constructs'],sort_keys=True))")
  R_B=$(api POST /assessment/quick/submit "$CTOK" "{\"responses\":$RESP}" | jq_ "print(json.dumps(d['constructs'],sort_keys=True))")
else
  R_A=$(api POST /assessment/full/submit "$CTOK" "{\"responses\":$RESP}" | jq_ "print(json.dumps(d['constructs'],sort_keys=True))")
  R_B=$(api POST /assessment/full/submit "$T2"  "{\"responses\":$RESP}" | jq_ "print(json.dumps(d['constructs'],sort_keys=True))")
fi
check "two runs give byte-identical scores" "$([ "$R_A" = "$R_B" ] && echo identical || echo differ)" "identical"

step "10. Practice never reaches the formal record"
why  "A document handed to a learner comes from the assessment that counts."
PRAC=$(api POST /assessment/quick/submit "$CTOK" "{\"responses\":$RESP}")
check "practice is marked as not counting" "$(echo "$PRAC" | jq_ "print(d['counts_toward_passport'])")" "False"

step "11. Admin assignment narrows the assessment"
why  "The assessment matches the programme actually delivered."
api PUT "/orgs/$A_ORG/candidates/$CID/assignments" "$A_TOK" '{"construct_ids":["SK_ETHICS","SK_NUMERACY"]}' >/dev/null
NARROW=$(api GET /assessment/full "$CTOK" | jq_ "print(len(d['items']))")
[ "$NARROW" -lt 24 ] && [ "$NARROW" -gt 0 ] && ok "item set narrowed to $NARROW items" || bad "expected fewer than 24 items, got $NARROW"
check "unknown construct refused" \
      "$(code PUT "/orgs/$A_ORG/candidates/$CID/assignments" "$A_TOK" '{"construct_ids":["SK_NOT_REAL"]}')" "422"
api PUT "/orgs/$A_ORG/candidates/$CID/assignments" "$A_TOK" '{"construct_ids":[]}' >/dev/null

step "12. The skill passport accumulates over time"
DETAIL=$(api GET "/orgs/$A_ORG/candidates/$CID" "$A_TOK")
N=$(echo "$DETAIL" | jq_ "print(d['passport']['attempt_count'])")
[ "$N" -ge 1 ] && ok "passport holds $N formal attempt(s)" || bad "passport empty"
check "each attempt records its engine digest" \
      "$(echo "$DETAIL" | jq_ "print(bool(d['passport']['attempts'][0]['engine_config_digest']))")" "True"

step "13. The Recommended Pathway"
why  "The differentiator: a score becomes a citable next step. Reference gaps are reported, not hidden."
PATH_=$(api GET "/orgs/$A_ORG/candidates/$CID/pathway" "$A_TOK")
check "built from three strongest constructs" "$(echo "$PATH_" | jq_ "print(len(d['strongest_constructs']))")" "3"
echo "   constructs without a mapping: $(echo "$PATH_" | jq_ "print(len(d['constructs_without_references']))") (expected until the library is seeded)"
echo "   unverified mappings counted: $(echo "$PATH_" | jq_ "print(d['unverified_reference_count'])")"

# ───────────────────────────────────────────────────────── isolation
step "14. A second institution cannot see the first"
why  "The test that matters. Both tenants are real, both are active."
B_EMAIL="south-$RUN@example.edu.au"
B_SIGNUP=$(signup "$B_EMAIL" "South TAFE"); bail_if_limited "$B_SIGNUP"
B_TOK=$(api POST /auth/signin "" "{\"email\":\"$B_EMAIL\",\"password\":\"$PW\"}" | jq_ "print(d['token'])")
B_ORG=$(api GET /auth/me "$B_TOK" | jq_ "print(d['organisations'][0]['id'])")
echo "   North is organisation $A_ORG, South is organisation $B_ORG"
check "South cannot read North's organisation"      "$(code GET "/orgs/$A_ORG" "$B_TOK")" "404"
check "South cannot list North's candidates"        "$(code GET "/orgs/$A_ORG/candidates" "$B_TOK")" "404"
check "South cannot open North's candidate"         "$(code GET "/orgs/$A_ORG/candidates/$CID" "$B_TOK")" "404"
check "South cannot read North's pathway"           "$(code GET "/orgs/$A_ORG/candidates/$CID/pathway" "$B_TOK")" "404"
why  "The subtler one: South uses its OWN organisation id with North's candidate id."
check "candidate lookup is filtered by organisation" "$(code GET "/orgs/$B_ORG/candidates/$CID" "$B_TOK")" "404"
why  "404 rather than 403 throughout, so tenant ids cannot be enumerated."
check "absent organisation answers the same way"    "$(code GET "/orgs/999999" "$B_TOK")" "404"

step "15. A candidate token is not an institution credential"
check "candidate cannot list the roster" "$(code GET "/orgs/$A_ORG/candidates" "$CTOK")" "401"
check "candidate cannot read /auth/me"   "$(code GET /auth/me "$CTOK")" "401"

step "16. Sessions revoke immediately"
why  "Why sessions are opaque database rows rather than self-contained signed tokens."
api POST /auth/signout "$B_TOK" >/dev/null
check "revoked session is rejected at once" "$(code GET /auth/me "$B_TOK")" "401"

step "17. Browser security posture"
HDRS=$(curl -sI "$BASE/health")
for h in x-content-type-options x-frame-options referrer-policy content-security-policy; do
  echo "$HDRS" | grep -qi "^$h:" && ok "$h present" || bad "$h missing"
done
check "unlisted origin gets no CORS grant" \
  "$(curl -sI "$BASE/health" -H 'Origin: https://evil.example' | grep -ci 'access-control-allow-origin')" "0"

printf '\n'
bold "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
