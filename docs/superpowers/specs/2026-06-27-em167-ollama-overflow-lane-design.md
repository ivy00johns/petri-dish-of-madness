# EM-167 — Ollama overflow lane (design)

> Wave M4. Deps EM-158 (cadence tiers ✅), EM-164 (✅). Contract: `contracts/wave-m.md` §3.

## Goal

Move ~40% of background LLM traffic OFF FreeLLMAPI by routing **background/
supporting cadence-tier** turns to a **local Ollama lane** as an
off-critical-path overflow — the animal-task pattern: a slow, non-survival lane
that, if it stalls, falls back to the existing routing without ever
hard-failing a turn.

Ollama is **NOT reachable in this build environment** (`curl localhost:11434`
fails), so this ships the **wiring + a test using a mock Ollama adapter**. Live
verification (a real `ollama serve`) is pending; recorded as
`code-complete; live-verify pending a running Ollama`.

## Where it hooks

`Router.effective_profile(agent_id, preferred, tier=None)` is the existing
per-turn lane resolver (EM-177). It is called ONCE per LLM turn from
`AgentRuntime.run_turn` (after the reflex/cadence gate, so reflex turns never
trigger it). The overflow lane piggybacks here:

1. **Overflow first.** If `world.overflow_lane.enabled` AND the turn's
   `tier` is in `overflow_lane.tiers` (default `["background","supporting"]`)
   AND the configured overflow `profile` (default `"ollama"`) exists, is not
   the home lane, is non-mock, is `available()`, and is NOT `lane_sick`, the
   call routes to the overflow profile with reason `"overflow"`.
2. **Else** the existing EM-177 sick-lane failover runs unchanged.

Background/supporting tiers are explicitly the off-critical-path traffic
(protagonists always stay on their pinned lane), so protagonist turns are
byte-identical to today.

## Graceful fallback (no hard-fail)

The overflow detour reuses the normal `chat()` path. If the Ollama adapter
raises `ProviderError` (server down/unreachable):
- EM-205 auto-backup retries the SAME call once on the `auto` lane, then
- EM-173 idle fallback keeps the agent acting.

So an absent/disabled/unreachable Ollama never silences an agent — identical to
how an animal background task degrades. The overflow lane also self-suppresses
when the Ollama profile is missing, unavailable (no api key env), or already
`lane_sick` (3 demerits in its window) — those turns fall straight back to the
home/failover routing, so a stalling Ollama stops being chosen automatically.

## Config — `world.overflow_lane` (R2)

```yaml
overflow_lane:
  enabled: false          # default OFF ⇒ absent block is a strict no-op
  profile: ollama         # the overflow target profile (must exist in profiles.yaml)
  tiers: [background, supporting]
```

`OverflowLaneParams` dataclass (defaults above) + `_parse_overflow_lane` +
`WorldParams.overflow_lane` field + mirror in `EMBEDDED_WORLD_YAML` and
`config/world.yaml`. The Router reads it via a defensive `_ol_value` accessor
(dataclass | dict | None ⇒ defaults), so an absent block = pre-EM-167 routing.

**Default OFF** because routing to Ollama changes behavior for existing worlds:
absent/`enabled:false` ⇒ `effective_profile` ignores the overflow path entirely
(byte-identical pre-EM-167 routing, zero new spans). Flip `enabled:true` once a
real Ollama is reachable.

## Profile — `profiles.yaml`

The scaffolded `ollama-llama` profile is enabled (uncommented) and named
`ollama` so the default `overflow_lane.profile: ollama` resolves. It points at
`${OLLAMA_BASE_URL:-http://localhost:11434/v1}` with `api_key_env: OLLAMA_API_KEY`.
With the lane DISABLED by default and no `OLLAMA_API_KEY` set, the profile is
inert (`available()` is False ⇒ never chosen even if someone flips the flag
without an Ollama).

## Determinism / invariants

- No `random.*`, no clock reads — the overflow decision is a pure function of
  config + tier + lane health (counters only, like EM-177).
- em161 golden: the prompt is untouched (routing-only change).
- EM-155 snapshot: no new AgentState/World state (config-only + in-memory
  router routing). Byte-identical.
- Span: a `"overflow"` reason stamps additive `requested_profile` +
  `overflow: True` on the llm_call span (forensics: which lane actually
  served), mirroring the `detour`/`probe` keys. Home-lane turns keep the exact
  pre-EM-167 key set.

## Tests (`tests/test_em167_ollama_overflow.py`)

- Router unit: enabled + background/supporting tier ⇒ overflow profile;
  protagonist tier ⇒ home; disabled/absent ⇒ home; missing/unavailable/sick
  Ollama ⇒ home; configurable tiers + profile name.
- Runtime e2e (mock Ollama adapter): a background turn REALLY calls the ollama
  adapter at its budget; span carries `requested_profile` + `overflow`;
  identity untouched.
- Graceful fallback: an unreachable Ollama (adapter raises) falls back via
  EM-205/EM-173 — the turn still resolves (not a hard error).
- Config: yaml → OverflowLaneParams round-trip; EMBEDDED mirror; shipped
  world.yaml block; default OFF.
- profiles.yaml: an `ollama` profile is present and enabled.
```
