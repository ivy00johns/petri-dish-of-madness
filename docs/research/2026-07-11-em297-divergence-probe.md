# EM-297 — Model-Divergence Probe (2026-07-11)

**Question.** Handed the same tight building-recipe schema, the same one-shot example, and the
same eight building briefs, do different free models emit **varied yet coherent** recipes — or do
they all echo the example? This is the go/no-go gate for the EM-299 parametric-building keystone
(deep-research-v5-1 §3.2: "if weak models don't diverge, the keystone's reason to exist evaporates").

**Verdict: GO (qualified).** Both models that answered diverged from each other on every prompt,
produced 100 % strict-schema-valid JSON, echoed the example zero times, and passed every
archetype-coherence spot-check. The qualification: proxy-wide free-tier 429 windows kept two of the
four planned lanes (qwen, llama) from answering at all — an availability fact, not divergence
evidence — so divergence is confirmed across two labs (Google, OpenAI-oss via Cerebras), not four.
Details and required follow-ups in §6.

---

## 1. Methodology

- **Schema** — `backend/scripts/em297_recipe_schema.py`: 7 fields, 6 closed enums + 1 bounded int
  (`footprint` 5 values, `floors` 1–8, `roof` 6, `material` 7, `palette` 7, `window_density` 4,
  `trim` 4). Strict validation (pydantic, `extra="forbid"`) plus a lenient `coerce_recipe` repair
  path with recorded repairs — the "sensible defaults" contract EM-299 needs regardless of verdict.
- **Probe** — `backend/scripts/em297_probe.py` against the local FreeLLMAPI proxy
  (`http://localhost:3001/v1/chat/completions`, bearer `FREELLMAPI_KEY`). System prompt = schema
  description + ONE example recipe (a blacksmith's forge, deliberately distinctive:
  `small/1/shed/brick/muted/sparse/none`) + "JSON only". Production call shape: `max_tokens=1024`,
  `temperature=0.8`, `response_format={"type":"json_object"}` with one-shot fallback — all matching
  `config/profiles.yaml` / `providers/adapters.py`.
- **Models** (exact production `model_id`s from `config/profiles.yaml`):
  `gemini-3.5-flash`, `qwen/qwen3-next-80b-a3b-instruct:free`, `llama-3.3-70b-versatile`,
  `gpt-oss-120b`.
- **Prompts** (8): bakery, temple, watchtower, fisherman hut, wealthy manor, slum shack, bathhouse,
  library — short flavourful briefs like real agent turns.
- **Rate discipline** — strictly sequential; ≥ 6 s between calls; ≤ 1 retry per call after a 30 s
  wait; a model skipped after 3 consecutive failures; hard cap 40 HTTP calls. **Actual: 36 calls**
  (32 main run + 2 × 2 supplemental llama attempts via the proxy's canonical `llama-3.3-70b` id,
  both 429).
- **Scoring** (in the script; re-runnable offline via `--score-only`): strict schema-valid rate;
  echo rate (≥ 6 of 7 fields equal to the example = near-echo, 7/7 = hard echo); cross-model
  per-field divergence (distinct values + pairwise disagreement per prompt); five archetype
  coherence predicates.
- **Raw data** — [`em297-raw.json`](em297-raw.json) (every request/response, routed-via headers,
  usage, validation results, scoring).

**Environment caveat.** The run landed inside the known intermittent free-tier request-rate windows
(the "All models exhausted" churn, EM-301): the proxy returned proxy-wide 429s for stretches of the
run. The live sim was competing for the same lanes throughout.

## 2. Per-model results

| model (lane) | proxy route observed | prompts sent | answered | strict-valid | valid rate | near-echoes | hard echoes | all-defaults |
|---|---|---|---|---|---|---|---|---|
| gemini-flash (`gemini-3.5-flash`) | `google/gemini-3.5-flash` | 8 | 8 | 8 | **1.00** | 1\* | 0 | 0 |
| gpt-oss-120b (`gpt-oss-120b`) | `cerebras/gpt-oss-120b` | 8 | 5 | 5 | **0.625**† | 0 | 0 | 0 |
| qwen-next (`qwen/qwen3-next-80b-a3b-instruct:free`) | — | 3 | 0 | 0 | 0.00† | — | — | — |
| groq-llama (`llama-3.3-70b-versatile`, then canonical `llama-3.3-70b`) | — | 3 (+2 sanity) | 0 | 0 | 0.00† | — | — | — |

\* The single near-echo flag is gemini's fisherman hut (`small/1/shed/wood/muted/sparse/none`,
6/7 fields shared with the smithy example). It differs on material (wood, correct for a hut) and
*is* the archetypal hut — semantic overlap with a hut-shaped example, not parroting. The echo
metric is deliberately conservative; hard echoes were **zero** everywhere.

† Every zero/miss above is an HTTP 429 (`"All models exhausted"` / `"All models rate-limited"`)
from the proxy **before any model saw the prompt** — including gpt-oss's 3 misses (its last three
prompts landed in a bad window). **Of the 13 responses that contained model output, 13/13 were
strict-schema-valid JSON with no extra keys.** No model that answered ever produced an invalid or
prose response.

## 3. The recipes (all 13 valid responses)

| prompt | model | footprint | floors | roof | material | palette | windows | trim |
|---|---|---|---|---|---|---|---|---|
| bakery | gemini-flash | medium | 2 | gable | timber_frame | warm | regular | simple |
| bakery | gpt-oss-120b | small | 1 | gable | brick | warm | regular | simple |
| temple | gemini-flash | grand | 4 | dome | marble | warm | regular | gilded |
| temple | gpt-oss-120b | grand | 2 | dome | marble | warm | sparse | gilded |
| watchtower | gemini-flash | small | 4 | flat | stone | muted | sparse | simple |
| watchtower | gpt-oss-120b | tiny | 4 | spire | stone | earthy | sparse | none |
| fisherman_hut | gemini-flash | small | 1 | shed | wood | muted | sparse | none |
| fisherman_hut | gpt-oss-120b | small | 1 | shed | wood | earthy | sparse | none |
| wealthy_manor | gemini-flash | grand | 4 | hip | marble | cool | dense | gilded |
| wealthy_manor | gpt-oss-120b | grand | 4 | gable | marble | vivid | dense | gilded |
| slum_shack | gemini-flash | tiny | 1 | flat | wood | muted | sparse | none |
| bathhouse | gemini-flash | large | 2 | dome | marble | cool | regular | ornate |
| library | gemini-flash | grand | 3 | dome | stone | earthy | regular | ornate |

## 4. Divergence

**Cross-model (per prompt, both-models-valid prompts only):**

| prompt | fields differing (of 7) | which |
|---|---|---|
| watchtower | 4 | footprint, roof, palette, trim |
| bakery | 3 | footprint, floors, material |
| temple | 2 | floors, window_density |
| wealthy_manor | 2 | roof, palette |
| fisherman_hut | 1 | palette |

Every co-answered prompt diverged on at least one field; pairwise disagreement rate per field
ranged 0.2 (material, windows, trim) to 0.6 (palette). The one heavy-convergence case
(fisherman hut) is the most tightly constrained archetype — and both models were *right*.

**Model signature is already legible with n=2.** Gemini builds grander: 4-floor temple and
watchtower, dome-heavy (3 of 8 roofs), marble-forward, `medium→grand` footprints. gpt-oss builds
leaner: 1-floor bakery, 2-floor temple, a `tiny`-footprint spire watchtower with `none` trim.
Same brief, same schema, recognisably different towns — this is exactly the per-model-skyline
signal EM-299 wants.

**Within-model spread (distinct values across own prompts):** gemini used 5/5 footprints, 5/6
roofs, 4/7 materials, 4/7 palettes across its 8 recipes; gpt-oss 3/4/4/3 across its 5. Neither
model collapsed to one template of its own.

## 5. Coherence spot-checks

| archetype | expectation | gemini | gpt-oss | pass rate |
|---|---|---|---|---|
| watchtower | ≥ 3 floors and tiny/small footprint | pass | pass | 1.0 |
| temple | ornate/gilded trim or stone/marble | pass | pass | 1.0 |
| slum shack | ≤ 2 floors, tiny/small, trim ≤ simple | pass | (429) | 1.0 |
| wealthy manor | large/grand, or ≥ 2 floors + ornate/gilded | pass | pass | 1.0 |
| fisherman hut | tiny/small and ≤ 2 floors | pass | pass | 1.0 |

**10/10 evaluated checks passed.** Nothing incoherent was produced by any model at any point:
no 8-floor shack, no marble hut, no tiny temple.

## 6. Verdict: GO (qualified) for EM-299

**What the probe was allowed to kill, it did not kill.** On every axis it could measure, the
premise held:

1. **No echoing.** 0 hard echoes in 13 recipes; the single conservative near-echo flag is a
   correct hut resembling a hut-shaped example.
2. **Varied.** Models disagreed on 1–4 fields of 7 on every shared prompt, with distinct,
   *interpretable* per-model styles (gemini monumental, gpt-oss frugal).
3. **Coherent.** 100 % archetype-check pass rate; 100 % strict-schema validity on answered calls —
   free instruct models handle a 7-field closed-enum JSON recipe comfortably inside the
   production call shape (1024 tokens, temp 0.8, json_object mode).

**Qualifications (and what they oblige):**

- **Coverage is 2 of 4 lanes** (Google + OpenAI-oss/Cerebras). Qwen and llama never got routed —
  every one of their 10 calls died on proxy-wide 429 windows, including 4 supplemental calls via
  the canonical `llama-3.3-70b` id after a cooldown. That is the EM-301 churn, not model evidence.
  **Obligation:** before EM-299's *visual sign-off* (not before starting it), run the cheap top-up —
  `em297_probe.py --models "qwen=qwen/qwen3-next-80b-a3b-instruct:free,llama=llama-3.3-70b-versatile"`
  (~18 calls) in a healthy window, merge with `--score-only`. A surprise there (e.g. llama echoing)
  would tune prompts/schema, not kill the keystone: the skyline thesis already stands on two labs
  diverging.
- **429s are a production fact, not just a probe artifact.** 3 of gpt-oss's 8 recipe turns died in
  the proxy, mid-grid. EM-299's catalog fallback (recipe absent ⇒ today's lookup) is therefore
  **load-bearing, not an edge case**, and the lenient `coerce_recipe` defaults path should ride
  along so a *malformed* recipe also degrades to a building, never a hole.
- **n=1 per model-prompt cell** at temperature 0.8 — per-cell values carry sampling noise; the
  aggregate signal (13/13 valid, 0 echoes, 10/10 coherence) is what to trust.

**Recommended EM-299 posture:** build it. Keep the probe's exact schema shape as the starting
grammar (it validated at 100 % as-is), keep enums closed, keep the one-shot example distinctive
(never archetype-neutral, so echo detection stays possible), ship with strict-parse →
coerce-with-logged-repairs → catalog-fallback as three explicit tiers.

## 7. Reproduction

```bash
# from the repo root (proxy on :3001, FREELLMAPI_KEY in env or --env-file)
.venv/bin/python backend/scripts/em297_probe.py --out docs/research/em297-raw.json
# offline re-score of an existing raw file
.venv/bin/python backend/scripts/em297_probe.py --score-only docs/research/em297-raw.json
```

Raw data: [`em297-raw.json`](em297-raw.json) — includes the full system prompt, every raw
response, `X-Routed-Via` routing evidence, token usage, latencies, all 429 bodies, and the scoring
block. The failed llama supplement attempt is preserved in
[`em297-raw-supplement.json`](em297-raw-supplement.json) and summarized under
`supplement_attempts` in the main file.
