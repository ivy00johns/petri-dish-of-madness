# EM-300 P2 — Adaptive Lane Routing: dynamic discovery/refresh — RESULTS

**Branch:** `feat/em300-lane-discovery` (worktree `/Users/johns/Projects/petri-dish-em300`)
**Date:** 2026-07-15 · **Status:** BUILT, gates green, pending live flag-flip sign-off.
Builds on PR #108 (merge after it). Flag-gated **default OFF** ⇒ byte-identical.

---

## 1. Probe findings — spec §11 Q1 answered EMPIRICALLY

Probed the live proxy read-only FIRST (before designing), using the runtime key +
admin creds from the MAIN checkout `.env`.

**Q1: Does `/v1/models` express availability or just configuration? → BOTH — it
expresses AVAILABILITY.** Each row carries `available: bool` + `unavailable_reason`
alongside the config, plus `context_window`/`context_length`:

```json
{"id":"minimax-m3","available":true,"unavailable_reason":null,"context_window":196608,...}
{"id":"llama-3.3-70b-instruct","available":false,"unavailable_reason":"no_key",...}
{"id":"gemini-2.5-pro","available":false,"unavailable_reason":"disabled",...}
```

Live counts: **132 models total, 96 available, 36 unavailable** (29 `no_key`,
7 `disabled`). `owned_by` is always `"freellmapi"` (no per-provider attribution),
and there is **no free/paid flag** on the model rows — so discovery treats all
freellmapi lanes as free (matching P1's `_build_lane_universe`).

**Design consequence:** discovery filters to `available: true`. A model the user
has no key for reports `available:false, "no_key"` and is never placed;
provisioning a key flips it available and it joins the pool next refresh — the
onboarding story is real, not inferred. `context_window` seeds each lane's ctx_hint.

**Admin `/api/health` `quotaStates`** (behind the `FREELLMAPI_ADMIN_*` login flow)
IS richer per-key health — `{platform, metric, remaining, limit, confidence,
resetAt, resetStrategy, retryAfterMs, statusCode, ...}`, 23 rows live — **but it is
PLATFORM-keyed** (cerebras/cohere/google/groq/cloudflare), NOT model-keyed, so it
cannot cleanly gate a model-id lane. It is therefore treated as **optional
enrichment** (opt-in `admin_quota`, default OFF, fetched + recorded but not folded
into availability). 429-driven daily-cap/cooldown tracking is **P3**, not this phase.

Probe artifacts: `scratchpad/v1_models.json`, `scratchpad/api_health.json`.

---

## 2. What shipped

Data-driven lane registry — the pool auto-follows what the user provisions.

| Area | File | Change |
|---|---|---|
| Discovery module | `backend/petridish/providers/discovery.py` (new) | `DiscoveredModel`/`SynthLaneSpec`/`FreeLLMTemplate`/`MergeResult`; `parse_models`, `fetch_freellmapi_catalog`, `fetch_admin_quota`, `detect_direct_sources`, and the pure `merge_universe`. httpx via injected `client_factory` (hermetic tests). |
| Config | `backend/petridish/config/loader.py` | `DiscoveryParams` dataclass nested on `AdaptiveRoutingParams` (`discovery` field); `_parse_discovery` defensive parser wired into `_parse_adaptive_routing`. |
| Router | `backend/petridish/providers/router.py` | `refresh_lanes()` (rebuilds the registry from the catalog + direct keys, synthesizes `disco:` adapters, re-ranks via the SAME sorting list), `note_served_turn()` (pure counter gate), `_freellmapi_template()`, `lanes_view()`, discovery accessors; `clear_cache()` drops synth adapters + resets to the static registry. |
| Loop | `backend/petridish/engine/loop.py` | `_maybe_schedule_lane_refresh()` — off-critical-path background refresh every N served turns (narrator/animal pattern), called from `_execute_turn`; task cancelled on reset. |
| API | `backend/petridish/api/app.py` | `POST /api/lanes/refresh` (on-demand) + `GET /api/lanes/registry` (the discovery view). `GET /api/lanes` left byte-identical. |
| Config file | `config/lanes.yaml` | Documented `adaptive_routing.discovery` block, `enabled: false`. |
| Tests | `backend/tests/test_em300_lane_discovery.py` (new) | 30 hermetic tests. |

### Semantics honored (per the ledger reframe)
- **lanes.yaml order/pins stay authoritative** — discovery only shapes the UNIVERSE;
  the SortingList still owns priority, the `*` sweep, exclude, and allow_paid.
- **Discovery adds/retires sweep-tier lanes** — a newly-available model joins via
  the `{source: freellmapi, model: "*"}` sweep; a configured lane the catalog
  marks unavailable is retired; a lane the catalog doesn't mention is kept (defensive).
- **Excluded lanes never placed** — the `exclude` denylist bars a discovered model
  even after synthesis (SortingList downstream).
- **Paid lanes respect allow_paid** — unchanged; freellmapi discovered lanes are free.
- **Terminal `auto` reservation follows `auto` by NAME** — `_terminal_fallback_profile()`
  is unchanged; a discovered lane never inherits the reserved final slot (P4 caveat honored).
- **Health carries across refreshes by lane id** — stable `disco:<model>` profile
  names; the EM-135 window survives a rebuild.

### Determinism / $0 / never-mute / #77
- **Determinism (EM-155):** discovery is counter-gated (no clock reads) and LIVE-only
  (`_execute_turn`, which replay never runs). Config `discovery` round-trips via asdict.
  `enabled:false` ⇒ no fetch, no synth, no registry delta — byte-identical.
- **$0-first / #77:** discovery only ADDS free freellmapi lanes + gates direct keys;
  no token-config touched; the #77 clamp/ceiling logic is untouched.
- **Never-mute:** discovery widens the reachable pool; it never removes the terminal
  `auto` backstop or idles an agent.

---

## 3. Live end-to-end verification (real proxy, read-only)

A router with a 2-lane static config (`minimax-m3` + `auto`) + `discovery.enabled=True`,
calling the REAL `refresh_lanes()` (real `GET /v1/models`):

```
lanes before: 2  →  after live discovery: 96
discovered (disco:) lanes: 94   retired: []
auto still terminal_fallback: auto
```

The registry rebuilt to every currently-available freellmapi model, `auto` stayed
the reserved terminal, nothing wrongly retired. The data-driven path works against
the real catalog.

---

## 4. Gates

- **Backend (this worktree's venv):** `.venv/bin/python -m pytest backend/tests/ -q`
  → **2505 passed, 1 skipped** (pre-existing skip). New file: **30 passed**.
- **Typecheck / vitest:** N/A — no web files touched (`git status` clean of web/).
- Determinism goldens (em250/256/259/310/311/315, settlements-off) all green.
- Config round-trip goldens green (asdict ↔ `_parse_adaptive_routing`, incl. new discovery).

---

## 5. How to flip it on (live)

1. In `config/lanes.yaml`, set `adaptive_routing.discovery.enabled: true`
   (keep `admin_quota: false` unless you want the `FREELLMAPI_ADMIN_*` enrichment).
2. Restart the sim (config bakes into `runs.config_json` per run).
3. Onboarding is now live: add a provider key to FreeLLMAPI → the model flips
   `available:true` → it joins the pool at the next auto-refresh (every
   `every_turns` served turns) or instantly via `POST /api/lanes/refresh`.
4. Watch the registry: `GET /api/lanes/registry` (per-lane `discovered`/`health`/
   `cap_state` + a `discovery` meta block). `GET /api/lanes` is unchanged.

**Sign-off owed:** a live run with the flag on, confirming the pool tracks
key adds/removes and the churn stays down. P3 (429-cap/cooldown), P4
(direct-provider first-class adapters), P5 (lane-board UI) remain open.
