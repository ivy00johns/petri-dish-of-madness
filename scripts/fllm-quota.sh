#!/usr/bin/env bash
# fllm-quota.sh — query the FreeLLMAPI *admin* API for live provider quota / keys / models.
#
# Two auth surfaces on the proxy (see .env): /v1/* uses the unified freellmapi-… key;
# the /api/* admin surface (this script) needs a session token minted from the dashboard
# account email+password. Reads FREELLMAPI_ADMIN_{BASE_URL,EMAIL,PASSWORD} from ./.env.
#
# Usage:
#   scripts/fllm-quota.sh            # summary: provider health + quota, keys, model count, budget
#   scripts/fllm-quota.sh health     # raw GET /api/health          (platforms + keys + quotaStates)
#   scripts/fllm-quota.sh keys       # raw GET /api/keys
#   scripts/fllm-quota.sh models     # raw GET /api/models
#   scripts/fllm-quota.sh usage      # raw GET /api/fallback/token-usage
#
# Requires: curl, python3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${FLLM_ENV_FILE:-$ROOT/.env}"
[ -f "$ENV_FILE" ] || { echo "no .env at $ENV_FILE" >&2; exit 1; }
set -a; . "$ENV_FILE"; set +a

: "${FREELLMAPI_ADMIN_BASE_URL:?set FREELLMAPI_ADMIN_BASE_URL in .env (e.g. http://localhost:3001)}"
: "${FREELLMAPI_ADMIN_EMAIL:?set FREELLMAPI_ADMIN_EMAIL in .env}"
: "${FREELLMAPI_ADMIN_PASSWORD:?set FREELLMAPI_ADMIN_PASSWORD in .env}"
B="${FREELLMAPI_ADMIN_BASE_URL%/}"

login() {
  local resp
  resp="$(curl -fsS "$B/api/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$FREELLMAPI_ADMIN_EMAIL\",\"password\":\"$FREELLMAPI_ADMIN_PASSWORD\"}")" \
    || { echo "login request failed (is the proxy up on $B?)" >&2; exit 1; }
  TOKEN="$(printf '%s' "$resp" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("token",""))')"
  [ -n "$TOKEN" ] || { echo "login failed: $resp" >&2; exit 1; }
}

api() { curl -fsS "$B$1" -H "Authorization: Bearer $TOKEN"; }

login

case "${1:-summary}" in
  health) api /api/health | python3 -m json.tool ;;
  keys)   api /api/keys   | python3 -m json.tool ;;
  models) api /api/models | python3 -m json.tool ;;
  usage)  api /api/fallback/token-usage | python3 -m json.tool ;;
  summary)
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    api /api/health              > "$TMP/h.json"
    api /api/fallback/token-usage > "$TMP/u.json"
    api /api/models              > "$TMP/m.json"
    python3 - "$TMP/h.json" "$TMP/u.json" "$TMP/m.json" <<'PY'
import sys, json
h, u, m = [json.load(open(p)) for p in sys.argv[1:4]]

print("=== providers (health) ===")
for p in sorted(h.get("platforms", []), key=lambda x: -x.get("enabledKeys", 0)):
    if not p.get("totalKeys"): continue
    flag = "OK " if p["enabledKeys"] and not p["invalidKeys"] and not p["errorKeys"] else "!! "
    print(f"  {flag}{p['platform']:<13} enabled={p['enabledKeys']}/{p['totalKeys']} "
          f"healthy={p['healthyKeys']} rl={p['rateLimitedKeys']} invalid={p['invalidKeys']} err={p['errorKeys']}")

qs = h.get("quotaStates", [])
hi = [q for q in qs if (q.get("confidence") or 0) >= 1]
print(f"\n=== quota (header-sourced, confidence=1 — trustworthy) ===")
for q in hi:
    lim = q.get("limit"); rem = q.get("remaining")
    print(f"  {q['platform']:<12} {q['metric']:<8} remaining={rem}/{lim}  ({q.get('modelId') or q.get('endpoint')})")
low = [q for q in qs if (q.get("confidence") or 0) < 1]
print(f"  … plus {len(low)} low-confidence inferred rows (remaining:0 there is NOT authoritative)")

models = m.get("models", m) if isinstance(m, dict) else m
en = sum(1 for x in models if isinstance(x, dict) and x.get("enabled"))
print(f"\n=== models: {len(models)} total, {en} enabled ===")

used, tot = u.get("totalUsed", 0), u.get("totalBudget", 0)
pct = (100 * used / tot) if tot else 0
print(f"\n=== token budget: {used:,} / {tot:,} used ({pct:.1f}%) ===")
PY
    ;;
  *) echo "unknown section '$1' (health|keys|models|usage|summary)" >&2; exit 2 ;;
esac
