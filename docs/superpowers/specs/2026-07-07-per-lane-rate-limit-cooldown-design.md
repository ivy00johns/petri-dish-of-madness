# Per-lane rate-limit cooldown (lane cooldown window)

**Status:** Design (approved 2026-07-07)
**Area:** `backend/petridish/providers/` (Router + adapters)
**Relates to:** EM-173 idle fallback · EM-177 lane failover · EM-198 bounce · EM-205 auto-backup · EM-226 auto-breaker · north-star "bounce models, never mute agents"

---

## 1. Problem

Agents pin a specific model profile (`Ada→gemini-flash`, `Bram→groq-llama`, `Vesper→mistral-small`, …) — the pins are intentional and feed the upcoming *same-persona-across-models* comparison feature, so they must stay.

On free tiers, individual pinned lanes get hard **rate-limited (HTTP 429)** for minutes-to-hours at a time. Live evidence (2026-07-07): of the 5 active agent lanes, 3 (`groq-llama`, `gemini-flash`, `mistral-small`) returned 429 while 2 (`cerebras-glm`, `kimi`) served fine — and the `auto` lane served fine. So the pool is **not** globally exhausted; specific pinned lanes are down while healthy capacity exists.

Today's flow (EM-205) reacts *per call*: the pinned lane is hit, 429s, and only *then* bounces to `auto`. Two costs:

1. **A wasted doomed POST every turn** on the known-down pinned lane, adding load that keeps the upstream window pinned.
2. When `auto` blips under that concentrated load, the EM-226 breaker trips and the agent takes the **EM-173 idle fallback** — surfacing `"<agent> failed to produce a valid action (idle fallback): … All models exhausted"` in the feed, repeatedly, on the rate-limited agents. The live run showed 39 idle-fallbacks in 500 events, clustered on exactly the 429'd lanes.

The user's model: a pinned lane that's rate-limited should be **remembered as down until its limit resets**, and its agent routed **straight to `auto`** in the meantime (which serves a real action → no idle message), then the pin **resumes** once the window passes.

## 2. Goals / Non-goals

**Goals**
- When a pinned lane is rate-limited, skip the doomed pinned call and route that agent's turn directly to `auto` **until the lane's cooldown expires**, then probe and resume the pin.
- Keep per-agent pins intact (identity feature).
- Fewer idle-fallback messages: an agent idles only when `auto` *itself* can't serve (true pool exhaustion).
- Deterministic + testable (injected clock).

**Non-goals (YAGNI)**
- Persisting cooldown across process restart (re-probe on boot is acceptable).
- Per-*provider* grouping (per-*lane*/profile granularity matches the pin model).
- Config-wiring the timing knobs now (sensible hardcoded defaults; wiring can follow if needed).
- Changing pin assignments or the global auto-breaker (already retuned 8→3 separately).

## 3. Design

Lives entirely in `Router` (`providers/router.py`) alongside the existing lane-health / auto-backup / auto-breaker state, plus a small header capture in `adapters.py`. The cooldown route reuses the existing `_auto_backup_call` machinery — a cooldown hop is simply a **proactive** bounce.

### 3.1 Rate-limit classification
A helper `_is_rate_limit(exc: ProviderError) -> bool`:
- `exc.status == 429`, **or**
- `exc.detail` matches (case-insensitive) `rate.?limit | exhausted | quota | too many requests`.

Only rate-limits set a cooldown. 5xx / transport / timeout / parse-failure keep the existing path unchanged (they are transient and already handled by auto-backup; cooling a lane for a one-off 500 would wrongly park it on `auto`).

### 3.2 Reset-time capture (`adapters.py` + `ProviderError`)
- Extend `ProviderError` with `retry_after: float | None = None` (seconds until reset).
- In `_post_with_retry`, on a non-success response, parse (case-insensitive, first present wins):
  - `Retry-After` — integer seconds, or an HTTP-date (convert to seconds-from-now, floored at 0);
  - `X-RateLimit-Reset` — epoch seconds (convert to remaining) or seconds-remaining, whichever parses sane (0 < v ≤ 86400).
- Pass the parsed value to `ProviderError(..., retry_after=...)`. Absent/unparseable ⇒ `None`.
- The aggregating proxy may not surface any of these; `None` is the expected common case and the backoff (3.4) covers it.

### 3.3 Per-lane cooldown state (Router)
```
self._lane_cooldown: dict[str, float]         # profile → clock() expiry
self._lane_cooldown_strikes: dict[str, int]   # profile → consecutive 429 count
```
Injected clock: `Router(..., clock: Callable[[], float] = time.monotonic)`. Tests pass a fake monotonic clock; production uses `time.monotonic` (monotonic avoids wall-clock jumps; we only need *elapsed* time, not calendar time).

Helper `_lane_cooling(profile) -> bool`: `profile in _lane_cooldown and clock() < _lane_cooldown[profile]`. Expired entries are cleared lazily on read.

### 3.4 Cooldown computation
Constants: `_COOLDOWN_BASE_S = 45`, `_COOLDOWN_MULT = 2`, `_COOLDOWN_CAP_S = 600`.

On a 429 for lane `L`:
```
strikes = self._lane_cooldown_strikes[L] = strikes(L) + 1
window  = retry_after if (retry_after is not None and retry_after > 0)
          else min(_COOLDOWN_BASE_S * _COOLDOWN_MULT ** (strikes - 1), _COOLDOWN_CAP_S)
self._lane_cooldown[L] = clock() + window
```
On a **success** for `L`: `strikes[L] = 0`, `_lane_cooldown.pop(L, None)` (lane recovered → resume the pin at full trust).

Rationale for defaults: a per-minute limit resets in ≤60s, so a 45s base probes right around reset; a daily-quota exhaustion backs off to a 10-min probe cadence (cheap) rather than hammering. A `Retry-After` header, when present, always wins.

### 3.5 Routing in `chat()`
Before calling the pinned adapter, branch on cooldown (only when an `auto` backup exists and `profile != auto` — otherwise cooldown is inert and behavior is unchanged):

```
router.chat(profile = L):
  if _lane_cooling(L):
      # PRE-EMPTIVE bounce: skip the doomed pinned POST entirely.
      text, served = _auto_backup_call(L, <synthetic cooling ProviderError>, …)
      return text                      # served_by=auto, bounced_to=auto → NO idle
  try:
      text = adapter.chat(…)           # healthy OR probe-on-expiry
      _clear_cooldown(L)               # success ⇒ resume pin, reset strikes
      return text
  except ProviderError as exc:
      if _is_rate_limit(exc):
          _set_cooldown(L, exc.retry_after)   # open/extend the window (backoff/header)
      text, served = _auto_backup_call(L, exc, …)   # existing bounce
      return text
```

Notes:
- **Probe on expiry is implicit**: once the window passes, `_lane_cooling` is false, so the next call hits the pinned lane exactly once. Success clears it; another 429 re-cools with a grown backoff. No separate probe counter needed.
- **Pre-emptive path must not double-count lane errors.** The 429 that opened the cooldown already recorded the home lane's error in the EM-135 window; a cooling turn made no home POST, so it must **not** re-note a home error (doing so would pin the lane "sick" forever and inflate the error count). Implementation: give `_auto_backup_call` a `note_home_error: bool = True` param and pass `False` on the pre-emptive route (or factor the auto hop into a small `_route_to_auto(...)` helper the pre-emptive path and `_auto_backup_call` both call). Either way the auto hop still (a) respects the EM-226 breaker — if `auto` is dead, the agent idles — and (b) surfaces the EM-198 `bounced_to=auto` snapshot for observability.

### 3.6 Interaction with existing mechanisms
- **EM-205 auto-backup** — reused verbatim for the actual `auto` hop.
- **EM-226 auto-breaker** — unchanged and still authoritative for `auto` health. If `auto` also fails while `L` is cooling, the breaker trips and the agent idles (pool genuinely dry — unavoidable and correct). Cooling *reduces* doomed pinned POSTs, lightening total load so `auto` stays healthier. Complements the breaker's retuned 8→3 recovery.
- **EM-135 lane health / EM-177 sick detour** — orthogonal and unchanged; the error window still records outcomes. Cooldown is the time-based "skip this lane for now" layer that health-counters can't express.
- **Cache** — unchanged; a cached hit still short-circuits before any of this.
- **Never mutes** — a cooling lane always routes to `auto`; agents keep acting.

### 3.7 Observability
- `lane_cooldowns() -> dict` snapshot for `/api/lanes` (merged into the existing lane payload): per cooling lane `{cooling: true, expires_in_s: float, strikes: int}`; healthy lanes absent. Lets the UI show "Bram — on auto, resets in 38s".
- `log.info` on cool-open (`"%s rate-limited (retry_after=%s) — cooling %.0fs, routing to auto"`) and on recovery (`"%s recovered — resuming pin"`). Open/close transitions only, never per skip.

## 4. Error handling & edge cases
- No `auto` lane configured ⇒ cooldown never engages (can't pre-empt to nothing); byte-identical to today.
- `profile == auto` (e.g. a narrator pinned to auto) ⇒ never cools itself (no self-recursion; matches the EM-205 `home==auto` guard).
- Non-rate-limit error ⇒ no cooldown; existing path.
- Clock is monotonic ⇒ immune to NTP/wall-clock jumps; only elapsed deltas matter.
- Strikes are unbounded integers but the window is capped at `_COOLDOWN_CAP_S`; `2 ** (strikes-1)` is only evaluated until it exceeds the cap, so no overflow concern in practice (capped by `min`).

## 5. Testing (TDD, fake clock + mock adapters)
1. 429 on pinned ⇒ **next** call routes to `auto` and the pinned adapter is **not** called while cooling.
2. Advance fake clock past the window ⇒ pinned lane probed exactly once; on success cooldown clears and the pin resumes.
3. Repeated 429s ⇒ window grows `45 → 90 → 180 …` capped at 600; strikes increment.
4. `Retry-After: 12` present ⇒ window == 12 regardless of strikes.
5. `X-RateLimit-Reset` epoch parsing ⇒ correct remaining seconds.
6. Non-429 `ProviderError` ⇒ **no** cooldown (pinned lane still called next turn).
7. No `auto` lane ⇒ cooldown inert (pinned called every turn as today).
8. `profile == auto` ⇒ never self-cools.
9. Determinism: identical `(clock sequence, adapter outcomes)` ⇒ identical routing decisions.
10. `lane_cooldowns()` snapshot shape while cooling vs recovered.

## 6. Rollout
- Pure additive behavior behind the presence of an `auto` lane; no config flag required (the mechanism is strictly better than today's per-turn 429-then-bounce and never mutes).
- Defaults hardcoded (`45s / ×2 / 600s`). If tuning is wanted later, wire a `world.lane_cooldown` block mirroring `lane_failover` — out of scope now.
- Ships with the EM-226 breaker retune (8→3) already applied.

## 7. Risks
- **Clock introduction** departs from the codebase's "counter-only, no clock reads" convention (EM-177/226). Mitigated by injecting the clock (deterministic tests) and using monotonic elapsed deltas only; sim replay reconstructs state from persisted events, not from live routing decisions, so wall-clock in routing does not affect replay determinism.
- **Header parsing variance** across 19 providers behind one proxy. Mitigated: parse defensively, treat anything unparseable/out-of-range as `None`, and lean on backoff as the always-present fallback.
- **Over-parking on `auto`** if a lane recovers before its window. Mitigated by short base (45s) and immediate clear on any successful probe.
