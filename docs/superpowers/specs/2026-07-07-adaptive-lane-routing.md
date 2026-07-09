# Spec — Adaptive Lane Routing (custom sorting list + dynamic discovery)

> **Status:** P1 shipped (#83, 2026-07-07); go-live 2026-07-08; P2-P5 open. **Date:** 2026-07-07.
> **Owner seam:** `backend/petridish/providers/router.py` + a new lane registry.
> Supersedes the "delegate everything to `model: auto`" strategy (EM-205) as the
> *primary* fallback; `auto` becomes one entry in the list, not the whole plan.

## 1. Why (the incident this fixes)

The sim ran into a **pause → resume → pause churn** (runs 1365→1368) even after the
soft-pin (EM-177), always-on backup (EM-226 rescinded), and the #77 revert. Root cause,
from the FreeLLMAPI proxy logs during the churn:

```
one `auto` request (636a02): tried a0..a18 = 19 upstream models, EVERY one failed
  openrouter/* → 429 "Rate limit exceeded: free-models-per-day"
  cohere/*     → 429 Too Many Requests
  zhipu/*      → 429 rate limit
  opencode/*   → "operation was aborted" (15s / 30s timeouts)
  ...total wall time ~86s for a SINGLE failed request
```

Two structural problems:

1. **`auto` is blind AND slow.** FreeLLMAPI's `auto` re-tries daily-capped lanes it should
   skip, each with a 15–30s timeout — up to ~86s per doomed request. Eight of those in a
   row trips the sim's `auto_pause_on_provider_errors` guard. We already track lane health
   (EM-135 window) *better* than the proxy exposes it, but we throw that knowledge away by
   delegating to `auto`.
2. **The pool is a moving target.** The user onboards free-provider accounts *slowly* (adds
   keys to FreeLLMAPI over days) and sometimes disables them; and there are **direct**
   providers (Gemini / Anthropic / OpenAI / Ollama) usable without the proxy. Today none of
   this is discovered or adapted to — the model set is static config.

**Not** a capacity problem the app can invent its way out of (the free *daily request* caps
are real), but the app CAN (a) stop wasting 86s on known-dead lanes, and (b) automatically
use every lane the user has actually provisioned. That is what this spec builds.

## 2. Goals / non-goals

**Goals**
- Replace blind `auto` delegation with a **PDoM-controlled, ordered, health-aware,
  time-capped** fallback chain — "our own custom sorting list."
- **Dynamic discovery + refresh:** lanes auto-appear as the user adds provider accounts/keys,
  and drop out when disabled — via polling + on-demand refresh, no code change, no restart.
- **Unify sources:** FreeLLMAPI lanes *and* direct Gemini/Anthropic/OpenAI/Ollama lanes in
  one registry the sorting list spans.
- Kill the 86s-cascade → kill the 8-in-a-row auto-pause churn.

**Non-goals**
- Not abandoning free-first ($0 stays the default; direct *paid* lanes sit low in the order,
  opt-in). Honors [[billing-subscription-only]].
- Not changing pinned-model identity — agents keep their preferred model ([[agent-identity-same-model-ok]]);
  this is the *fallback* path when the pin is unavailable.
- Not a throttle — this is "reach more free capacity, faster," aligned with the
  do-more/never-mute north star ([[session-189-rate-is-the-target]], [[no-throttling-bounce-models-instead]]).

## 3. Core concepts

### 3.1 Lane
A `Lane` is one concrete way to get a completion:
```
Lane {
  id: str                 # stable, e.g. "freellmapi:gpt-oss-120b-free" or "anthropic:claude-sonnet-5"
  source: enum            # freellmapi | gemini | anthropic | openai | ollama
  model_id: str           # what we send as `model`
  base_url / api_key_env  # how to reach it (source-derived defaults)
  priority: int           # from the sorting list (lower = tried first)
  enabled: bool           # gated on key presence + sorting-list inclusion
  free: bool              # free vs paid (default order puts free first)
  ctx_hint / out_hint     # optional: context / max-output ceiling (skip a lane whose
                          #   ceiling can't fit this request — the #77 lesson, encoded)
  tags: [str]             # e.g. "reasoning" (deprioritize for JSON turns), "fast", "big"
}
```

### 3.2 Lane Registry (the live pool)
The **union of all currently-available lanes**, rebuilt on refresh:
- FreeLLMAPI lanes ← discovered from the proxy's model list (§4).
- Direct lanes ← enabled iff their key env is present (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
  `OPENAI_API_KEY`, `OLLAMA_BASE_URL`).
- Each lane carries live health (EM-135 window) + cooldown/cap state (§5).

### 3.3 Sorting List (the user-curated order)
New `config/lanes.yaml` — the ONE place the user controls preference:
```yaml
adaptive_routing:
  enabled: true               # false = today's behavior (pin -> auto), byte-identical
  max_attempts: 3             # curated healthy lanes tried per turn before idle
  per_attempt_timeout_s: 12   # reuse the EM-170 turn budget; no 86s doomed cascades
  refresh:
    discover_every_turns: 40  # counter-based (NO clock reads on the replay path)
    freellmapi_models: true   # poll the proxy's model list
    direct_keys: true         # detect direct-provider env keys
  # priority order, best-headroom-first. matcher = source + model glob.
  order:
    - { source: freellmapi, model: "gpt-oss-120b*",  free: true }   # 110M headroom
    - { source: freellmapi, model: "llama-3.3-70b*", free: true }   # 110M
    - { source: freellmapi, model: "qwen3-next-80b*",free: true }
    - { source: freellmapi, model: "*",              free: true }   # remaining free lanes
    - { source: gemini,     model: "gemini-2.5-flash", free: true } # direct, if GEMINI_API_KEY
    - { source: freellmapi, model: "auto" }                          # proxy's picker — LAST resort
    - { source: anthropic,  model: "claude-sonnet-5", free: false }  # paid, opt-in, dead last
```
Rules: entries matched top-to-bottom assign ascending priority; `free: false` lanes require
an explicit opt-in flag (`adaptive_routing.allow_paid: true`, default false) or stay disabled.
A glob `*` sweeps in everything discovered under that source that isn't already listed.

## 4. Discovery + refresh mechanism (the "slow onboarding" support)

A **counter-based refresher** (off the replay surface — like EM-167/EM-177, no clock reads
in the deterministic path) runs every `discover_every_turns`:

1. **FreeLLMAPI:** `GET {base}/v1/models` (with the bearer key) → the set of currently
   *configured* models → map each to a `freellmapi:<model>` lane, merged with the sorting
   list's priorities. New models the user added to FreeLLMAPI **appear automatically**;
   removed ones **drop out**.
2. **Direct keys:** check env for each direct source; present → enable that source's listed
   lanes, absent → disable. So adding `GEMINI_API_KEY` lights up the gemini lanes next
   refresh; removing it drops them.
3. **Merge → new registry snapshot** (add newly-available, disable vanished). Health/cooldown
   state carries across refreshes by lane id.

**On-demand refresh** (so onboarding is instant, no waiting for the tick counter):
- `POST /api/lanes/refresh` control endpoint.
- Optional watch on `config/lanes.yaml` mtime.

**Onboarding story (the requirement):** a new person sets up, say, a Cerebras + an OpenRouter
account over a week, drops the keys into FreeLLMAPI, and optionally sets `GEMINI_API_KEY`
locally. Each addition is picked up on the next refresh (or an instant `/api/lanes/refresh`)
and joins the pool at its sorting-list priority — **zero code, zero restart.** Turn a key
off → it's gone next refresh. The registry only ever contains lanes that are actually
reachable *right now*.

## 5. Health + reset/cap tracking (why it beats `auto`)

- **Health:** reuse the EM-135 6-window per lane (already built). ≥ threshold demerits ⇒ skip.
- **Cap/cooldown from 429 signals (NEW):** parse the proxy/provider error:
  - `"free-models-per-day"` / daily-quota 429 ⇒ mark the lane **daily-capped**; skip it until
    a reset window (heuristic: next UTC midnight, or a configurable `daily_reset`), NOT every
    4th turn — no more doomed probes into a lane that won't return for hours.
  - transient `429 Too Many Requests` / 5xx ⇒ short cooldown (a few turns).
- This is the crux: **we skip the known-dead lanes** the proxy's `auto` wastes 86s re-hitting.

## 6. The bounce loop (replaces the auto delegation)

Per turn, in `router.chat()` (when `adaptive_routing.enabled`):
```
1. try the agent's PINNED lane (identity preserved), UNLESS it is health-sick or capped
   (then it's pre-emptively skipped, like today's soft-pin detour).
2. on failure / skip: walk the registry in priority order; for each lane, SKIP if
   (health-sick) OR (capped/cooling) OR (ctx/out ceiling can't fit this request) OR
   (already tried this turn) OR (reasoning-tagged AND this is a strict-JSON turn — the #77 lesson).
3. try up to `max_attempts` healthy lanes, each bounded by `per_attempt_timeout_s`.
4. if all fail ⇒ EM-173 idle fallback (rare — only when the curated healthy set is genuinely dry).
```
A turn can no longer take 86s (capped attempts × 12s), so 8-in-a-row can't stack into an
auto-pause under normal stress. `served_by`/`routed_via` is recorded per the existing
contract (EM-205 attribution rules).

## 7. Determinism, $0, never-mute (constraint check)

- **Determinism (EM-155):** routing is a *runtime* decision; the served lane is recorded in
  the event log (`routed_via`), and replay reads the log — it never re-routes. Same property
  today's soft-pin already relies on. The sorting list + refresh knobs live in config →
  captured in `runs.config_json`, so a run's routing config is pinned for fork/replay. The
  discovery poller is off the replay surface (counter-gated, additive), like EM-167.
  `enabled: false` ⇒ exact pre-spec behavior (pin → auto), byte-identical.
- **$0-first:** free lanes precede paid in the default order; paid lanes require
  `allow_paid: true`. Image chain untouched ([[gemini-paid-image-provider]]).
- **Never-mute:** the loop tries multiple curated lanes before idle — the aim is *more* served
  turns per unit wall-time, not fewer calls.

## 8. Observability

`GET /api/lanes` extended to return the live registry: per lane `{id, source, priority,
enabled, health, cap_state, cooling_until, last_served_tick}`. The user watches lanes light
up green as they onboard, and sees exactly which are capped — the feedback loop that makes
"slowly add accounts" pleasant instead of guesswork. A small UI panel (lane board) is a
stretch, not required for P1.

## 9. Build phases (each independently shippable, flag-gated, byte-identical when off)

- **P1 — Registry + sorting list + bounce loop.** Static lanes from `lanes.yaml`; the
  ordered/health-aware/time-capped bounce replaces the `auto`-only backup. Ships behind
  `adaptive_routing.enabled` (default off ⇒ byte-identical). *This alone kills the churn.*
- **P2 — Discovery/refresh.** FreeLLMAPI `/v1/models` poll + direct-key detection +
  `/api/lanes/refresh` + counter-based auto-refresh. (The onboarding mechanism.)
- **P3 — Cap/cooldown tracking.** 429-signal parsing → daily-cap + cooldown skip.
- **P4 — Direct-provider lanes.** Wire gemini/anthropic/openai/ollama adapters into the
  registry as first-class lanes (adapters already exist in `providers/`).
- **P5 — Observability.** `/api/lanes` registry view (+ optional lane-board UI).

## 10. Test plan (per phase)

- Registry merge + sorting: given discovered lanes + a `lanes.yaml` order, the priority
  assignment + glob sweep are correct; paid lanes excluded unless `allow_paid`.
- Bounce loop: pinned healthy ⇒ used; pinned sick ⇒ skipped to next healthy; try-N-then-idle;
  reasoning-tagged skipped on JSON turns; ctx-ceiling skip (the #77 regression, now a *test*:
  a lane whose out_hint < requested max_tokens is skipped, so we never strand ourselves on
  the capped big-output lanes again).
- Discovery: mock FreeLLMAPI model list + env-key presence → registry reflects adds/removes;
  `/api/lanes/refresh` updates live.
- Cap tracking: a `free-models-per-day` 429 ⇒ lane skipped until reset; transient 429 ⇒ short
  cooldown then retried.
- Determinism: `enabled:false` byte-identical to pre-spec (em161 golden + EM-155 snapshot);
  with routing on, a recorded run replays byte-identical (routing read from events, not re-run).

## 11. Open questions for the builder

1. Does FreeLLMAPI's `/v1/models` (with key) list *availability* or just *configuration*? If
   only configuration, discovery = "which models exist"; real-time health stays our
   EM-135 window + 429 signals (fine). Confirm the endpoint shape first.
2. Daily-cap reset time — is it fixed UTC-midnight per provider, or rolling 24h from first
   request? Start with a configurable `daily_reset` and a conservative default; refine from
   observed 429 timing.
3. `lanes.yaml` vs a block inside `profiles.yaml` — new file keeps the sorting list legible
   and hot-reloadable; profiles.yaml keeps one config. Recommend a new `lanes.yaml`.
