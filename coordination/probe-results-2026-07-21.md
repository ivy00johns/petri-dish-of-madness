# Probe results — 2026-07-21 (lanes-agent, feed-truth W1)

Protocol (contracts/2026-07-21-feed-truth.md §C): live strict-JSON probes
per model via `$FREELLMAPI_BASE_URL` (sourced read-only from the main repo's
`.env`), asserting HTTP 200 + extractable JSON object + `finish_reason==
"stop"`, production `max_tokens=1024`, NO `response_format` (matching what
happens when a provider rejects it and the real adapter falls back —
`backend/petridish/providers/adapters.py`), using **the repo's real
action-schema system prompt shape**. 2 probes per candidate minimum,
rate-window tolerant (one retry after cooldown on a transient hit).

**Two rounds, and round 2 changed the verdict on two lanes — read this
before the tables below.** Round 1 used a hand-rolled short system prompt
(a reasonable first pass, but NOT the real prompt shape §C actually
requires). Round 2 re-probed every repin/addition through
`petridish.agents.runtime._assemble_context` — the ACTUAL production
prompt-assembly function (`backend/tests/test_json_mode.py:141-158` shows
the fixture pattern; script: `scratchpad/probe_real_prompt.py`), rendering
a real 2-agent/plaza/recent-events fixture (5,847 chars ≈ 1,461 tokens —
still lighter than a busy mid-game turn, but real production code, not an
approximation). This caught exactly the failure mode
`research/fallback-review.md` W1 warned about for `gpt-oss-120b` (a short
probe missing a truncation-under-load problem) — it happened AGAIN here,
to a lane I'd already added based on round-1 results:
- `deepseek-v4-flash` looked clean on the short prompt (3/4 pass) but hit
  `finish_reason=length` (prose reasoning, no JSON) **3/3** under the real
  prompt.
- `glm-5.2` was content-clean both rounds, but round 2 surfaced a LATENCY
  problem the short prompt's fast responses hid: 17-26s per call, 3/3
  trials — over `lanes.yaml`'s `per_attempt_timeout_s: 12` bound for the
  bounce walk.
Both are corrected in the config (details below); round-1 tables are kept
for the full trail, round 2 is the one that decided the final config.

Probe scripts + raw JSON (session scratchpad, not committed):
`scratchpad/probe_models.py`, `scratchpad/probe_retry.py`,
`scratchpad/probe_raw_results.json`, `scratchpad/probe_retry_results.json`
(round 1); `scratchpad/probe_real_prompt.py`,
`scratchpad/probe_real_prompt_results.json` (round 2).

## Dead-pin fixes (S1) — round 1 (short prompt)

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

## New lanes (M1) — round 1 (short prompt), probe-verified subset of the requested 5

| model | verdict | evidence |
|---|---|---|
| `glm-5.2` | **PASS 2/2** | finish=stop, both clean, 1.7-6s, routed `nvidia/z-ai/glm-5.2` |
| `deepseek-v4-flash` | **PASS 3/4** (clean 2/2 on retry) | first cold attempt timed out; retry-round 2/2 clean, finish=stop, routed `opencode/deepseek-v4-flash-free` |
| `kimi-k2.6` | **PASS 2/2** | already a profile (`kimi`); reconfirmed live, routed `cloudflare/@cf/moonshotai/kimi-k2.6` — no new profile needed |
| `minimax-m3` | **PASS 2/2** | already a profile (`minimax`); reconfirmed live, two different routes served (`huggingface/MiniMaxAI/MiniMax-M3` then `ollama/minimax-m3`) — no new profile needed |
| `qwen3.5-122b-a10b` | **REJECTED** | both attempts: NVIDIA NIM 410 — *"the model 'qwen/qwen3.5-122b-a10b' has reached its end of life on 2026-07-20T00:00:00Z and is no longer available."* This is a definitive EOL, not a rate limit — the static catalog snapshot (`freellmapi-models.json`, listing it `available: true`) was already stale within 24h. **NOT added as a lane or profile**, round 1 or 2. |

## Round 2 — REAL production system prompt (`_assemble_context`)

Re-probed every repin/addition through the actual prompt-assembly code
(prompt: 2 messages, 5,847 chars ≈ 1,461 tokens — see script header above).
This is the run that decided the committed config.

| model | round-2 verdict | detail |
|---|---|---|
| `llama-3.3-70b-fp8-fast` (groq-llama) | **PASS 3/3** | finish=stop, valid JSON every time; latency 16.8s / 4.5s / 2.6s (one cold-start outlier, then fast) — fine either way since the PINNED first-call path has no `per_attempt_timeout_s` cap (router.py:583 passes no `timeout=`; only the bounce walk does, router.py:1136/1226) |
| `glm-4.7` (cerebras-glm) | **PASS 1/1** | finish=stop, valid JSON, ~0.7s |
| `glm-5.2` | **CONTENT clean 3/3, but LATENCY fails the bounce cap** | finish=stop, valid JSON every trial, but 26.1s / 17.2s / 25.2s — all three over `per_attempt_timeout_s: 12`. As a bounce-only lane (never pinned) it would time out on every attempt in production. **Removed from `lanes.yaml` `order`**; kept in `profiles.yaml` (`glm-5`) as an explicit-pin-only option, since the pinned path isn't time-capped the same way. |
| `deepseek-v4-flash` | **FAIL 3/3** | `finish_reason=length` every trial — the model plans in prose ("We are at Central Plaza. Bram is here...") and never reaches the JSON object before the 1024-token budget runs out. Round 1's 3/4 pass was a false pass from a lighter/shorter prompt. **Tagged `reasoning` in `lanes.yaml`** (same mechanism/treatment as `gpt-oss-120b`) instead of removed outright — still a valid last-resort non-strict-JSON lane. |

## Reasoning-tag (S2/W6)

`config/lanes.yaml`'s `gpt-oss-120b*` AND `deepseek-v4-flash` order entries
now carry `tags: ["reasoning"]`. This flips the router's existing
`require_json`-skip mechanism (`router.py:1219`,
`if require_json and "reasoning" in lane.tags: continue`) to keep both out
of the strict-JSON bounce path.

`gpt-oss-120b`: `profiles.yaml`'s old comment ("intentionally NOT
reasoning-tagged") is updated to document why this supersedes the prior
decision — on the real agent prompt it CoT-truncates (`finish_reason=
length`, 118 recent failures per `data/run.sqlite`), so the old worry
(losing it from the bounce pool entirely) is the correct outcome here, not
a regression.

`deepseek-v4-flash`: added tagged + demoted from the start, based on round
2 above (never was in an un-tagged committed state).

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
