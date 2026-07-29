# FreeLLMAPI skill/release review — 2026-07-29

**Scope:** the `use-freellmapi` skill was updated today (v1.3.0; SKILL.md, `references/capabilities.md`,
`references/agent-clients.md` all touched 11:05–11:09; `recipes.md` unchanged since 2026-06-21).
Reviewed for: issues it solves for us, new endpoints worth monitoring, and richer data we can consume.

**Everything below was probed against the LIVE install**, not taken from the skill text.

- Container: `freellmapi-freellmapi-1`, `ghcr.io/tashfeenahmed/freellmapi:latest`, healthy.
- `GET /v1/openapi.json` → `info.version` = **0.4.1**, 26 paths.
- Catalog: 244 models.

> **Version-label caveat:** the skill talks about "as of v0.6.5" (keyless providers). Our install
> reports **0.4.1** from its own OpenAPI. Don't map skill version numbers onto this install — probe
> `GET /v1/docs` / `/v1/openapi.json` instead. That is what was done here.

---

## 1. ~~HEADLINE~~ — REFUTED BY EXPERIMENT (2026-07-29, see §1b)

> **Status: the rate-limit hypothesis below is WRONG.** It was measured against a live run the same
> day and does not hold — peak inbound was **12 req/min against the 120/min cap**. The error was in
> the arithmetic, not the release notes: I took `tick_interval_seconds: 3` as the actual cadence.
> Measured, a tick takes **~25 s**. §1b has the data. The §2–§7 findings are unaffected; §2 gets
> *more* valuable, not less. The original text is kept below for the record.

### Original (incorrect) claim — the proxy has its OWN per-IP rate limit, and we run at ~83% of it

New in the skill (*Routing behavior*): "Per-IP proxy rate limit: default 120 req/min per client IP
(`PROXY_RATE_LIMIT_RPM`, `0` disables)."

**Verified live.** Every response — including `/v1/models` — now carries:

```
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 105
X-RateLimit-Reset: 1785341961      # rolling ~60s window
```

And in the container: `PROXY_RATE_LIMIT_RPM` is **unset → default 120**.

**Our steady-state load** (`config/world.yaml`): `tick_interval_seconds: 3` → 20 rounds/min; the cast
is 5 agents, all explicitly protagonist ("acts EVERY round", no `cadence_tier`).

> **5 agents × 20 rounds/min = ~100 requests/min — 83% of the 120/min cap — with ZERO retries.**

On top of that baseline, all of these are separate requests against the same cap:

- adaptive bounce: `max_attempts: 5` per failed turn (`config/lanes.yaml`)
- the JSON-mode double-call (see §3) — a second request whenever `response_format` is rejected
- `discovery` polling `GET /v1/models` (`every_turns: 40`)
- animals runtime turns, image generation via the FreeLLMAPI image provider

This is a **strong new candidate root cause for the EM-301 churn**, and it reframes the memory note
that the idle-fallback flood is "intermittent free-tier request-RATE windows". A 429 from the
*proxy's own limiter* is indistinguishable at our call site from a 429 from a provider — so our lane
health marks lanes sick → bounces → issues MORE requests → deeper into the cap. That is a
self-reinforcing spiral, and it would look exactly like "intermittent windows" that the dashboard
playground (a handful of manual calls) never reproduces.

**Not yet proven** that we actually cross 120 in a live run — the backend was not running during this
review, so no live 429 was observed. That is the one experiment worth running before treating this as
confirmed.

**Levers:** set `PROXY_RATE_LIMIT_RPM=0` (or a high value) in the container env; and log
`X-RateLimit-Remaining` per call so headroom is visible instead of inferred.

---

## 1b. THE EXPERIMENT — run live, hypothesis refuted, and it inverts

**Method.** Backend confirmed running on the **host** (PID 97231), and the proxy publishes
`127.0.0.1:3001`, so host traffic shares one client IP at the limiter — one bucket for the whole sim.
Inbound rate was counted from the proxy's own container log, where **one `start` line == one inbound
request** (failover attempts log as `next`/`fail`), which costs the bucket nothing. The
`X-RateLimit-Remaining` header was sampled every 20 s as the authoritative headroom read. Sim resumed
from tick 7950 via `POST /api/control/start`. Raw data: 13 samples over ~2 min.

**Result — the sim uses ~10% of the proxy's per-IP budget.**

| metric | value |
| --- | --- |
| peak inbound requests / 60 s | **12** (cap: **120**) |
| bucket `X-RateLimit-Remaining` range | **82 – 117** (never approached 0) |
| proxy-limiter 429s observed | **0** |
| proxy calls in 180 s | 22 `start`, 13 `ok`, 3 `fail` |

**Why the estimate was wrong.** `config/world.yaml` sets `tick_interval_seconds: 3`, and I treated
that as the cadence → 20 rounds/min × 5 agents = 100 calls/min. **Measured, ticks advance ~7 ticks per
200 s — one tick per ~25–29 s**, roughly 8× slower than configured. `tick_interval_seconds` is a floor
between ticks, not the achieved rate; turn wall-clock dominates. 5 agents × ~2.4 ticks/min ≈ 12
calls/min, which is exactly what the proxy saw.

**The inversion — this is the finding worth keeping.** Against the standing "max LLM call-rate is the
north star, do MORE never less" directive, the constraint is **not** the proxy and never was: there is
**~10× unused headroom** at the 120/min cap. The bottleneck is turn latency. Proxy-side latency is not
the culprit either — measured over 300 s, successful calls ran **p50 1.9 s / p95 7.4 s / max 17.8 s**
(n=17). The ~25 s tick is therefore mostly our own side: turns serialized per tick, plus bounce
cascades (`max_attempts: 5` × `per_attempt_timeout_s: 12` = up to 60 s worst case for one turn).

**A second discrepancy, unexplained and worth its own look.** Live lane health during the run:

```
sick=True : gemini-flash(3) gemini-flash-lite(4) groq-llama(4) kimi(3)
            llama-fast(4) minimax(timeouts=4) mistral-large(4) mistral-small(4)
sick=False: auto  cerebras-glm(2)  command-r(timeouts=2)  qwen-next(2)
```

**8 of 12 lanes sick**, ~30 accumulated errors, most with `last_routed_via=None`. But over the same
period the proxy logged only **3 upstream failures** and served 17/20 calls OK. Our lane-sickness
accounting is drastically more pessimistic than the proxy's actual behavior, and the `None` routed_via
says those calls failed before any header came back. Whether that is stale window state carried across
the pause, or live failures the proxy never saw, is **not** resolved by this experiment.

**The 3 upstream failures that did occur were daily-allocation exhaustion**, not rate windows:
`Cloudflare API error 429: you have used up your daily free allocation`, and OpenRouter
`Rate limit exceeded: free-models-per-day`. That matches `/v1/providers` reporting those platforms
`rate_limited` with `resume_at` at exactly `00:00:00Z`. **This makes §2 more valuable, not less** —
those lanes are knowably dead until midnight UTC and could be parked deterministically instead of
discovered by burning a turn and a bounce cascade.

---

## 2. `GET /v1/providers` — obsoletes our admin-credential path, and adds `resume_at`

New in the skill's *Ops & discovery* table. **Verified live**, authenticating with the plain unified
key — **no `FREELLMAPI_ADMIN_*` email/password session needed**:

```
cerebras      healthy       keys=2 pct=100
cloudflare    rate_limited  keys=1  resume_at=2026-07-30T00:00:00.000Z
huggingface   rate_limited  keys=1  resume_at=2026-07-30T16:11:17.420Z
openrouter    rate_limited  keys=2  resume_at=2026-07-30T00:00:00.000Z
google/groq/cohere/kilo/llm7/nvidia/ollama/opencode/pollinations/reka/zhipu  healthy
```

Fields: `platform`, `name`, `status`, `keys`, `requests_remaining_pct`, and `resume_at` (present only
when rate-limited). `?ready=true` filters to platforms that can serve now.

**Why this matters to us:** `config/lanes.yaml` has `discovery.admin_quota: false` precisely because
it "needs `FREELLMAPI_ADMIN_*` creds". That barrier is gone. More importantly, `resume_at` is
information we have never had: today lane sickness is *inferred* from demerits and decays on a guess.
With `resume_at` we can park a lane until an exact wall-clock time and un-park it deterministically —
and skip bouncing into platforms that are provably down, which directly reduces the request burn in §1.

Note the granularity: this is **platform**-keyed, not per-model — same shape as the admin
`quotaStates` surface `backend/petridish/providers/discovery.py` already documents.

---

## 3. `supported_parameters` on `/v1/models` — data-driven capability, and it kills a wasted request

`GET /v1/models` rows now carry `supported_parameters` on **242 of 244** models. Coverage across the
catalog:

| parameter | models |
| --- | --- |
| `temperature`, `top_p`, `max_tokens`, `max_completion_tokens`, `stop`, `stream` | 242 |
| `response_format` | **224** |
| `reasoning_effort` | **190** |
| `tools` / `tool_choice` / `parallel_tool_calls` | 168 |

Two concrete consequences:

**(a) The JSON-mode double-call is now avoidable.** `backend/petridish/providers/adapters.py:130`
sends `response_format: {"type":"json_object"}`, and on a 4xx rejection **retries the whole call**
with JSON mode disabled (`adapters.py:141-152`; the docstring at :57 says so outright). That is two
requests where one would do — against the 120/min cap in §1. 20 of 244 models don't advertise
`response_format`; pre-filtering on the advertised value removes the speculative first call.

**(b) It replaces hand-curated `reasoning` tags with vendor data.** `router.py:1219` does
`if require_json and "reasoning" in lane.tags` — hand-maintained tags in `config/profiles.yaml`, and
memory already records that those claims were wrong for `gpt-oss-120b`. Live catalog confirms
`gpt-oss-120b` advertises `response_format` and does **not** advertise `reasoning_effort`.

**(c) New lever on truncation:** `reasoning_effort` is settable on 190 models. Turning it *down* on
strict-JSON turns is a direct attack on the reasoning-preamble bloat that memory records as the cause
of the `finish_reason='length'` flood — a lever we did not previously know we had.

`discovery.parse_models()` (`discovery.py:105-134`) currently reads only `id`, `available`,
`unavailable_reason`, `context_window`/`context_length` — it drops `supported_parameters` and `name`
on the floor.

---

## 4. Prompt compression — a direct lever on the `finish=length` flood

New section in `capabilities.md`. Off by default; **verified live**: responses carry
`X-FreeLLM-Compress: off; saved~=0`.

Modes `lossless` / `standard` / `aggressive` shrink the request **before** routing and token
budgeting, so the router sees the reduced estimate and more small-context lanes stay eligible. It is
fail-open with fidelity gates (numeric literals, diff hunks, explicit constraints and error lines
survive; ≥90% of JSON keys).

This is aimed squarely at our known failure: prompt grew past the output ceiling once comm +
multi-city were enabled → clean lanes truncate → sick → bounce into dirty reasoning lanes. Master
switch is dashboard/`FREELLMAPI_COMPRESSION`; per-request `X-FreeLLM-Compress` can only *lower* the
operator's setting, never raise it — so adopting it means a dashboard/env change, not a code-only one.

Worth noting it also feeds the Lab Setup panel's prompt-weight estimator: compression changes the
effective prompt size the router sees, so the panel's estimate would need to account for it.

---

## 5. Diagnostic headers we are not capturing

`adapters.py:80` reads **only** `X-Routed-Via`. Confirmed live on a real completion, the proxy also
returns:

| header | live value | why we want it |
| --- | --- | --- |
| `X-Request-ID` | `e2116b4c-…` | correlates a call to its row in dashboard analytics, incl. `GET /api/analytics/requests/:id` — the **full failover ladder for one call** |
| `X-RateLimit-Remaining` | `113` | §1 headroom, per call |
| `X-FreeLLM-Compress` | `off; saved~=0` | confirms whether §4 actually fired |
| `X-FreeLLM-Cache` | `OFF` | cache state (we keep the decision cache off by design) |
| `X-Fallback-Attempts` / `X-Fallback-Trail` | *(absent on a clean first-try call)* | the ordered list of what the proxy tried **inside** one request — the invisible half of our bounce diagnostics |

`X-Fallback-Trail` is the notable gap: today we see which lane we *asked* for and which model
*answered*, but nothing about the proxy's own internal failover between those two points. On
exhaustion the error body carries the same trail.

---

## 6. `auto:*` steering — a better terminal fallback than blind `auto`

New: `auto:fast` / `auto:smart` / `auto:reliable` / `auto:balanced` / `auto:cheap` rank **every
enabled model** ignoring chain order, per request, no dashboard change. Plus `auto:<profile-name>`
routes through a named dashboard profile's chain (unknown profile = clear `400`, not a silent
fallback).

`config/lanes.yaml` sets `terminal_fallback: auto`, and the EM-319 comment explains why: during a rate
storm every *specific* lane can be individually rate-limited while blind `auto` still routes — so
`auto` stays on **survivability** grounds. `auto:reliable` preserves exactly that property (it is
still the whole blind pool, not one pinned model) while ranking by *recent success rate* instead of
the default blend. That looks like a strict improvement to the reserved final slot without
re-opening the EM-318/319 argument.

`auto:<profile>` is also a route to expressing our curated lane order **server-side**, which is worth
considering against keeping it in `lanes.yaml`.

---

## 7. Smaller items

- **`GET /livez` · `GET /readyz`** — both verified `200`. Kubernetes-style probes; a cleaner proxy
  liveness check than `/api/ping` for our infra checks (`docker-compose.yml` currently healthchecks
  only our own backend at `:8000/api/health`).
- **`X-Session-Id`** — the proxy keeps a multi-turn conversation on the same model for **30 minutes**
  ("sticky sessions") to avoid mid-conversation model-switch hallucination spikes. Harnesses that
  manage their own conversation ids can pin affinity explicitly. We do not send it. Worth
  understanding whether sticky sessions are silently pinning our agents in ways that interact with
  our own lane pinning.
- **`POST /mcp`** — tools `list_models`, `provider_health`, `usage_summary`, `routing_info`,
  `set_routing_strategy`, `cache_stats`, `compression_stats`. An agent-facing way to read quota burn
  mid-session.
- **`GET /v1/docs` / `/v1/openapi.json`** — install-truth check. Used here; recommend it over trusting
  any doc, given the version-label mismatch noted above.
- **Analytics `null` semantics** — latency percentiles / TTFT / pin-honor return **`null`** (not `0`)
  once a window ages past the prune horizon. Relevant if we ever scrape analytics.

## 8. Checked and found NOT to be problems

- **"Pollinations is no longer keyless."** The skill warns against offering Pollinations as the
  zero-key path. Our image chain (`backend/petridish/imagegen/provider.py:68,189-206`) does a
  **direct public GET** to `image.pollinations.ai/prompt/…`, not a FreeLLMAPI provider call.
  Probed live: `http=200`, `image/jpeg`, 45 KB. **Our free-first art chain is unaffected** — no
  increased fall-through to the paid Gemini backstop. The skill's warning is about FreeLLMAPI's
  provider integration validating a key, not the public image endpoint.
- **`X-Routed-Via` percent-encoding trap.** Non-ASCII model ids get percent-encoded in the header and
  need `unquote()` before display. Checked all 244 catalog rows: **zero** non-ASCII ids or names. This
  is a latent risk for the feed's ground-truth chip, not a live bug.

## 9. Already covered — no action

- `/v1/models` carrying `available` / `unavailable_reason` / `context_window`: EM-300 P2 already
  consumes these (`discovery.py`, `config/lanes.yaml`).
- `X-Routed-Via` as ground truth: already the basis of the fingerprint ticker.
- Admin `/api/health` `quotaStates`: already documented in `discovery.py` — but see §2, it is now
  largely superseded by the credential-free `/v1/providers`.
- Response cache (`X-FreeLLM-Cache`): stays OFF by standing decision.
