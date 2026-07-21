# Probe results — 2026-07-21 (lanes-agent, feed-truth W1)

Protocol: 2 live strict-JSON probes per model via `$FREELLMAPI_BASE_URL`
(sourced read-only from the main repo's `.env`), asserting HTTP 200 +
extractable JSON object + `finish_reason=="stop"`, production-like
`max_tokens=1024`, NO `response_format` (worst-case: raw prompt-JSON
compliance, matching what happens when a provider rejects `response_format`
and the real adapter falls back — `backend/petridish/providers/adapters.py`).
On a rate-limit/timeout hit, retried once after a cooldown per the contract;
persistent failures got a third confirmation round before being rejected.

Probe script + raw JSON: `scratchpad/probe_models.py`,
`scratchpad/probe_retry.py`, `scratchpad/probe_raw_results.json`,
`scratchpad/probe_retry_results.json` (session scratchpad, not committed).

## Dead-pin fixes (S1)

| profile | old model_id | catalog status | new model_id | probe verdict |
|---|---|---|---|---|
| `groq-llama` | `llama-3.3-70b-versatile` | **NOT in catalog** (guaranteed fail) | `llama-3.3-70b-fp8-fast` | **PASS 2/2** — see note below |
| `cerebras-glm` | `zai-glm-4.7` | **NOT in catalog** (guaranteed fail) | `glm-4.7` | **PASS 2/2 on retry** — see below |
| `embed` | `bge-m3` | absent from `/v1/models` | **unchanged** | **PASS** direct `/v1/embeddings` probe — see below |

### `groq-llama` — detour from plan
The natural fix is the plain catalogued `llama-3.3-70b` (listed
`available: true`). Live-probed it 5 times across ~2 minutes: **5/5
failures** — 2 timeouts (30s), 1 `routing_error` ("2 routes checked, 1
rate-limited, 2 no usable key configured"), then 2 more timeouts. That's not
a single rate-limit window (which recovers on retry, see `glm-4.7` below);
it reads as a genuinely broken route on the proxy right now, despite the
catalog claiming availability. Repinned instead to `llama-3.3-70b-fp8-fast`
— **PASS 2/2**, finish=stop, ~1s, routed via
`cloudflare/@cf/meta/llama-3.3-70b-instruct-fp8-fast`. This is the SAME
model_id the `llama-fast` profile already uses, so `groq-llama` and
`llama-fast` now share one upstream/ctx budget (ctx_window=24000, the
smallest lane in the registry) instead of being provider-diverse. Trade-off
accepted: a working shared route beats a currently-dead provider-exclusive
one. Worth re-probing `llama-3.3-70b` (the un-shared id) later — if it
recovers, re-diversify `groq-llama` onto it.

### `cerebras-glm` — clean, same physical model
`glm-4.7` attempt 1 hit a Cerebras 429 ("Soonest cooldown reset ~87s").
Retried after a 30s cooldown: **2/2 clean**, finish=stop, valid JSON, routed
via `cerebras/zai-glm-4.7` — the exact same upstream the dead id used to
resolve to; only the catalogued alias was wrong.

### `embed` — NOT actually stale, corrected the diagnosis
`fallback-review.md` flagged `bge-m3` as "NOT in catalog" based on its
absence from `GET /v1/models`. That endpoint only enumerates
chat-completion models — embeddings aren't listed there, which is expected
(the catalog snapshot has zero `embed`-tagged entries at all, for any
model). Direct-probed `POST /v1/embeddings {"model":"bge-m3", "input": "..."}`
live: **HTTP 200**, valid embedding vector returned, routed via
`cloudflare`. No change made — the profile was never actually broken.

## New lanes (M1) — probe-verified subset of the requested 5

| model | verdict | evidence |
|---|---|---|
| `glm-5.2` | **PASS 2/2** | finish=stop, both clean, 1.7-6s, routed `nvidia/z-ai/glm-5.2` — new profile `glm-5` added |
| `deepseek-v4-flash` | **PASS 3/4** (clean 2/2 on retry) | first cold attempt timed out; retry-round 2/2 clean, finish=stop, routed `opencode/deepseek-v4-flash-free` — new profile `deepseek-flash` added |
| `kimi-k2.6` | **PASS 2/2** | already a profile (`kimi`); reconfirmed live, routed `cloudflare/@cf/moonshotai/kimi-k2.6` — no new profile needed |
| `minimax-m3` | **PASS 2/2** | already a profile (`minimax`); reconfirmed live, two different routes served (`huggingface/MiniMaxAI/MiniMax-M3` then `ollama/minimax-m3`) — no new profile needed |
| `qwen3.5-122b-a10b` | **REJECTED** | both attempts: NVIDIA NIM 410 — *"the model 'qwen/qwen3.5-122b-a10b' has reached its end of life on 2026-07-20T00:00:00Z and is no longer available."* This is a definitive EOL, not a rate limit — the static catalog snapshot (`freellmapi-models.json`, listing it `available: true`) was already stale within 24h. **NOT added as a lane or profile.** |

## Reasoning-tag (S2/W6)

`config/lanes.yaml`'s `gpt-oss-120b*` order entry now carries
`tags: ["reasoning"]`. This flips the router's existing
`require_json`-skip mechanism (`router.py:1219`,
`if require_json and "reasoning" in lane.tags: continue`) to keep it out of
the strict-JSON bounce path. `profiles.yaml`'s old comment ("intentionally
NOT reasoning-tagged") is updated to document why this supersedes the prior
decision: on the real ~4900-token agent prompt it CoT-truncates
(`finish_reason=length`, 118 recent failures per `data/run.sqlite`), so the
old worry (losing it from the bounce pool entirely) is the correct outcome
here, not a regression — it was failing on exactly the turns it would have
been tried on.

## Config audit (item 2, second half)

Cross-checked every remaining `model_id` in `config/profiles.yaml` against
the live catalog snapshot (`scratchpad/freellmapi-models.json`, 239
entries): `gemini-3.5-flash`, `qwen3-next-80b`, `deepseek-v4-pro`,
`mistral-small-4-119b`, `kimi-k2.6`, `mistral-large-3-675b`, `command-a-2`,
`gemini-3.1-flash-lite`, `llama-3.3-70b-fp8-fast`, `command-r-2`,
`minimax-m3`, `gpt-oss-120b`, `auto` — all resolve, all `available: true`.
No other stale ids found.

## De-stale personas.yaml + cast pins (S3/W2)

- `config/world.yaml` — already on the EM-324 clean set
  (`gemini-flash-lite`/`llama-fast`/`command-r`/`mistral-small`/`minimax`).
  No stale ids. No change made.
- `config/world.city25.yaml` — cast pins reference the SAME profile names
  `backend/tests/test_city25_roster.py` locks (`REAL_LANES` =
  `{gemini-flash, qwen-next, deepseek-pro, groq-llama, cerebras-glm,
  mistral-small, kimi}`). Fixing the dead model_ids in `profiles.yaml`
  de-stales this cast without touching the file or the profile names — the
  roster parity test stays green untouched.
- `config/personas.yaml` — repointed `suggested_profile` off
  `groq-llama`/`gemini-flash` for the three seed cards NOT locked by any
  test (`Vesper`, `Lumen`, `Marrow` → `llama-fast`/`gemini-flash-lite`
  ×2). **Reverted** the same de-stale for `Roop`/`Sledge`/`Wisp`/`Pip`:
  `backend/tests/test_em240_integration.py::test_seed_personas_include_criminals_and_enforcers`
  hardcodes a `real_lanes` set of the OLD profile names for exactly those
  four cards, and that test file is outside this agent's config-only
  ownership. Since the underlying model_ids are already fixed at the
  source, those four personas are no longer "stale" even on the old names
  — reverting them keeps the gate green with a surgical, in-scope change
  instead of touching a test file owned elsewhere. Left a `NOTE:` comment
  at each reverted card pointing at this doc.

## Gates

- Targeted: `backend/tests/test_city25_roster.py backend/tests -q -k
  "config or lanes or router or profile or roster"` → **121 passed**.
- Full: `backend -q` → **2840 passed, 1 skipped** (pre-existing skip,
  unrelated to this change).
- Both run via `PYTHONPATH=/Users/johns/Projects/petri-dish-build/backend`
  against the shared `.venv` — confirmed via `python -c "import petridish;
  print(petridish.__file__)"` that this resolves the WORKTREE's code, not
  the main repo's (the bare venv without `PYTHONPATH` resolves the main
  repo instead, since `.venv-link` points there).
