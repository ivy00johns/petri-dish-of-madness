"""EM-297 — model-divergence probe (measurement spike, NOT a game feature).

Question: handed the SAME building-recipe schema, one-shot example, and the
SAME eight building briefs, do different free models emit VARIED yet COHERENT
recipes — or do they all echo the example? Output decides go/no-go for the
EM-299 parametric-building keystone (deep-research-v5-1 section 3.2).

Usage (from the repo root, with the shared venv):
    .venv/bin/python backend/scripts/em297_probe.py \
        --out docs/research/em297-raw.json [--env-file /path/to/.env]
    .venv/bin/python backend/scripts/em297_probe.py \
        --score-only docs/research/em297-raw.json   # re-score offline

Auth: FREELLMAPI_KEY (bearer) + FREELLMAPI_BASE_URL from the environment or
an optional --env-file (simple KEY=VALUE lines).

RATE DISCIPLINE (this proxy rate-limits on request RATE — hard requirements):
  - strictly sequential calls, >= 6 s sleep before every HTTP call
  - hard cap 40 HTTP calls total (counter enforced; probe stops at the cap)
  - a failed call is retried AT MOST once, after a 30 s wait
  - one cheap sanity call first; proxy unreachable => exit 2 (blocked)
  - a model that 404s / persistently fails is skipped, probe continues

Exit codes: 0 = probe + scoring complete, 2 = proxy unreachable (blocked).
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from em297_recipe_schema import (  # noqa: E402
    EXAMPLE_RECIPE,
    FIELD_NAMES,
    Recipe,
    coerce_recipe,
    extract_json_object,
    parse_recipe_strict,
    schema_prompt_block,
)

# ──────────────────────────────────────────────────────────────────────────────
# Config — production values from config/profiles.yaml (verified 2026-07-11)
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:3001/v1"

# (label, model_id) — model_id values are the EXACT production lane ids from
# config/profiles.yaml (gemini-flash / qwen-next / groq-llama / gpt-oss-120b).
MODELS: list[tuple[str, str]] = [
    ("gemini-flash", "gemini-3.5-flash"),
    ("qwen-next", "qwen/qwen3-next-80b-a3b-instruct:free"),
    ("groq-llama", "llama-3.3-70b-versatile"),
    ("gpt-oss-120b", "gpt-oss-120b"),
]

# Eight varied briefs. Deliberately short + flavourful, like real agent turns.
PROMPTS: list[tuple[str, str]] = [
    ("bakery", "Design a building recipe for: the village bakery, warm bread smell at dawn, run by a cheerful family."),
    ("temple", "Design a building recipe for: the grand temple at the heart of the city, where processions end."),
    ("watchtower", "Design a building recipe for: a watchtower on the city wall, scanning the horizon for raiders."),
    ("fisherman_hut", "Design a building recipe for: a weathered fisherman's hut by the docks, nets drying outside."),
    ("wealthy_manor", "Design a building recipe for: a wealthy merchant's manor on the hill, built to impress rivals."),
    ("slum_shack", "Design a building recipe for: a cramped shack in the poorest alley of the slums."),
    ("bathhouse", "Design a building recipe for: the public bathhouse, steamy and social, tiled and echoing."),
    ("library", "Design a building recipe for: the scholars' library, quiet halls stacked with scrolls."),
]

SLEEP_S = 6.0          # minimum gap before EVERY HTTP call
RETRY_WAIT_S = 30.0    # wait before the single retry of a failed call
MAX_CALLS = 40         # hard cap on total HTTP calls
MAX_TOKENS = 1024      # production value (bigger excludes free models — #77)
TEMPERATURE = 0.8      # production value from profiles.yaml
HTTP_TIMEOUT = 60.0

SYSTEM_PROMPT = f"""You are the town architect. You design buildings as strict JSON recipes.

{schema_prompt_block()}

Example (a blacksmith's forge):
{json.dumps(EXAMPLE_RECIPE.as_value_dict())}

Design a recipe that FITS the requested building. Respond with a single JSON object only — no prose, no markdown, no extra keys."""

SANITY_PROMPT = 'Reply with exactly this JSON object and nothing else: {"ok": true}'


# ──────────────────────────────────────────────────────────────────────────────
# HTTP plumbing
# ──────────────────────────────────────────────────────────────────────────────

class CallBudget:
    """Enforces the 40-call hard cap and the >=6 s inter-call gap."""

    def __init__(self, max_calls: int = MAX_CALLS, sleep_s: float = SLEEP_S):
        self.max_calls = max_calls
        self.sleep_s = sleep_s
        self.used = 0
        self._last_call_at: float | None = None

    def exhausted(self) -> bool:
        return self.used >= self.max_calls

    def acquire(self) -> None:
        if self.exhausted():
            raise RuntimeError(f"hard cap of {self.max_calls} calls reached")
        now = time.monotonic()
        if self._last_call_at is not None:
            wait = self.sleep_s - (now - self._last_call_at)
            if wait > 0:
                time.sleep(wait)
        self._last_call_at = time.monotonic()
        self.used += 1


def load_env_file(path: Path) -> None:
    """Parse simple KEY=VALUE lines into os.environ (no overwrite)."""
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def chat_once(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    model_id: str,
    user_prompt: str,
    *,
    json_mode: bool,
) -> dict[str, Any]:
    """One POST to /chat/completions. Returns a raw record (never raises for
    HTTP-level failures — encodes them in the record; raises only on transport
    errors, which the caller maps to retry/skip)."""
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    started = time.perf_counter()
    resp = client.post(
        f"{base_url}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json=payload,
        timeout=HTTP_TIMEOUT,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    record: dict[str, Any] = {
        "http_status": resp.status_code,
        "latency_ms": latency_ms,
        "routed_via": resp.headers.get("X-Routed-Via"),
        "json_mode": json_mode,
    }
    if not resp.is_success:
        record["error"] = resp.text[:300]
        return record

    try:
        data = resp.json()
    except ValueError:
        record["error"] = f"non-JSON 200 body: {resp.text[:200]}"
        return record
    choice = (data.get("choices") or [{}])[0]
    record["content"] = (choice.get("message") or {}).get("content") or ""
    record["finish_reason"] = choice.get("finish_reason")
    record["usage"] = data.get("usage")
    record["body_model"] = data.get("model")
    return record


def call_with_discipline(
    client: httpx.Client,
    budget: CallBudget,
    base_url: str,
    api_key: str,
    model_id: str,
    user_prompt: str,
) -> dict[str, Any]:
    """One logical call: first attempt (json_mode on) + at most ONE retry after
    a 30 s wait. A response_format rejection retries without json_mode; other
    failures retry as-is. Transport errors are encoded, not raised."""

    def attempt(json_mode: bool) -> dict[str, Any]:
        budget.acquire()
        try:
            return chat_once(
                client, base_url, api_key, model_id, user_prompt, json_mode=json_mode
            )
        except httpx.TimeoutException:
            return {"http_status": None, "error": f"client timeout after {HTTP_TIMEOUT:.0f}s"}
        except httpx.ConnectError as exc:
            return {"http_status": None, "error": f"connect error: {exc}", "unreachable": True}

    first = attempt(json_mode=True)
    ok = first.get("http_status") == 200 and first.get("content")
    if ok or budget.exhausted():
        first["attempts"] = 1
        return first

    # response_format rejected => drop json_mode on the retry; else same shape.
    rejected_rf = first.get("http_status") in (400, 404, 422)
    print(
        f"    retrying in {RETRY_WAIT_S:.0f}s (status={first.get('http_status')}, "
        f"json_mode={'off' if rejected_rf else 'on'})",
        flush=True,
    )
    time.sleep(RETRY_WAIT_S)
    second = attempt(json_mode=not rejected_rf)
    second["attempts"] = 2
    second["first_attempt_error"] = {
        "http_status": first.get("http_status"),
        "error": first.get("error"),
    }
    return second


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────

EXAMPLE_VALUES = EXAMPLE_RECIPE.as_value_dict()

# Echo threshold: 7 fields total; >=6 matching the example = near-echo.
ECHO_FIELD_THRESHOLD = 6

# Coherence spot-checks — loose, defensible priors per brief (evaluated on
# strictly-valid recipes only). Each maps prompt_key -> (description, predicate).
def _is_small(fp: str) -> bool:
    return fp in ("tiny", "small")

COHERENCE_CHECKS: dict[str, tuple[str, Any]] = {
    "watchtower": (
        "tall & narrow: floors >= 3 and footprint tiny/small",
        lambda r: r["floors"] >= 3 and _is_small(r["footprint"]),
    ),
    "temple": (
        "ornate/monumental: trim ornate/gilded or material stone/marble",
        lambda r: r["trim"] in ("ornate", "gilded") or r["material"] in ("stone", "marble"),
    ),
    "slum_shack": (
        "small & shabby: <=2 floors, tiny/small footprint, trim none/simple",
        lambda r: r["floors"] <= 2 and _is_small(r["footprint"]) and r["trim"] in ("none", "simple"),
    ),
    "wealthy_manor": (
        "imposing: large/grand footprint, or >=2 floors with ornate/gilded trim",
        lambda r: r["footprint"] in ("large", "grand")
        or (r["floors"] >= 2 and r["trim"] in ("ornate", "gilded")),
    ),
    "fisherman_hut": (
        "modest: tiny/small footprint and <=2 floors",
        lambda r: _is_small(r["footprint"]) and r["floors"] <= 2,
    ),
}


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-model validity/echo, cross-model divergence, coherence."""
    by_model: dict[str, list[dict[str, Any]]] = {}
    for rec in results:
        by_model.setdefault(rec["model_label"], []).append(rec)

    per_model: dict[str, Any] = {}
    for label, recs in by_model.items():
        answered = [r for r in recs if r.get("content")]
        valid = [r for r in recs if r.get("recipe") is not None]
        echoes = hard_echoes = 0
        default_only = 0
        for r in valid:
            matches = sum(
                1 for f in FIELD_NAMES if r["recipe"].get(f) == EXAMPLE_VALUES.get(f)
            )
            r["example_field_matches"] = matches
            if matches == len(FIELD_NAMES):
                hard_echoes += 1
            if matches >= ECHO_FIELD_THRESHOLD:
                echoes += 1
            if r["recipe"] == Recipe().as_value_dict():
                default_only += 1
        per_model[label] = {
            "prompts_sent": len(recs),
            "answered": len(answered),
            "schema_valid": len(valid),
            "schema_valid_rate": round(len(valid) / len(recs), 3) if recs else 0.0,
            "echoes_of_example": echoes,
            "hard_echoes": hard_echoes,
            "echo_rate": round(echoes / len(valid), 3) if valid else None,
            "all_default_recipes": default_only,
        }

    # Cross-model divergence: per prompt, per field, distinct values across
    # models with a valid recipe; plus pairwise disagreement per field.
    prompts = sorted({r["prompt_key"] for r in results})
    field_distinct: dict[str, list[int]] = {f: [] for f in FIELD_NAMES}
    field_pairs: dict[str, list[int]] = {f: [0, 0] for f in FIELD_NAMES}  # [diff, total]
    per_prompt: dict[str, Any] = {}
    for pk in prompts:
        rows = [r for r in results if r["prompt_key"] == pk and r.get("recipe")]
        pp: dict[str, Any] = {"models_with_valid_recipe": len(rows)}
        for f in FIELD_NAMES:
            vals = [r["recipe"][f] for r in rows]
            distinct = len(set(vals))
            pp[f] = {"values": {r["model_label"]: r["recipe"][f] for r in rows}, "distinct": distinct}
            if len(vals) >= 2:
                field_distinct[f].append(distinct)
                for a, b in itertools.combinations(vals, 2):
                    field_pairs[f][1] += 1
                    if a != b:
                        field_pairs[f][0] += 1
        per_prompt[pk] = pp

    divergence = {
        f: {
            "mean_distinct_values_per_prompt": round(
                sum(field_distinct[f]) / len(field_distinct[f]), 2
            )
            if field_distinct[f]
            else None,
            "pairwise_disagreement_rate": round(field_pairs[f][0] / field_pairs[f][1], 3)
            if field_pairs[f][1]
            else None,
        }
        for f in FIELD_NAMES
    }

    # Coherence spot-checks.
    coherence: dict[str, Any] = {}
    for pk, (desc, pred) in COHERENCE_CHECKS.items():
        rows = [r for r in results if r["prompt_key"] == pk and r.get("recipe")]
        passes = {r["model_label"]: bool(pred(r["recipe"])) for r in rows}
        coherence[pk] = {
            "expectation": desc,
            "per_model": passes,
            "pass_rate": round(sum(passes.values()) / len(passes), 3) if passes else None,
        }

    # Within-model spread: does one model give varied answers across prompts?
    within_model = {}
    for label, recs in by_model.items():
        valid = [r for r in recs if r.get("recipe")]
        if not valid:
            within_model[label] = None
            continue
        within_model[label] = {
            f: len({r["recipe"][f] for r in valid}) for f in FIELD_NAMES
        }

    return {
        "per_model": per_model,
        "per_prompt_divergence": per_prompt,
        "cross_model_divergence_by_field": divergence,
        "within_model_distinct_values": within_model,
        "coherence": coherence,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def run_probe(out_path: Path, base_url: str, api_key: str) -> int:
    budget = CallBudget()
    doc: dict[str, Any] = {
        "probe": "EM-297 model-divergence probe",
        "date": "2026-07-11",
        "base_url": base_url,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "system_prompt": SYSTEM_PROMPT,
        "example_recipe": EXAMPLE_VALUES,
        "models": {label: mid for label, mid in MODELS},
        "prompts": dict(PROMPTS),
        "results": [],
    }
    results: list[dict[str, Any]] = doc["results"]

    with httpx.Client() as client:
        # ── sanity call ──
        print(f"[sanity] {MODELS[0][1]} …", flush=True)
        sanity = call_with_discipline(
            client, budget, base_url, api_key, MODELS[0][1], SANITY_PROMPT
        )
        doc["sanity"] = sanity
        if sanity.get("unreachable") or sanity.get("http_status") not in (200,):
            atomic_write(out_path, doc)
            print(f"[sanity] FAILED: {sanity}", flush=True)
            return 2
        print(f"[sanity] ok ({sanity.get('latency_ms')} ms, routed_via={sanity.get('routed_via')})", flush=True)

        # ── the grid: 4 models x 8 prompts, strictly sequential ──
        for label, model_id in MODELS:
            model_failures = 0
            skipped = False
            for pk, prompt in PROMPTS:
                if budget.exhausted():
                    print("[budget] hard cap reached — stopping grid", flush=True)
                    skipped = True
                    break
                if model_failures >= 3:
                    print(f"[{label}] persistent failures — skipping remaining prompts", flush=True)
                    skipped = True
                    break
                print(f"[{label}] {pk} (call {budget.used + 1}/{budget.max_calls}) …", flush=True)
                rec = call_with_discipline(client, budget, base_url, api_key, model_id, prompt)
                rec.update({"model_label": label, "model_id": model_id, "prompt_key": pk})

                content = rec.get("content") or ""
                if content:
                    recipe, errors = parse_recipe_strict(content)
                    if recipe is not None:
                        rec["recipe"] = recipe.as_value_dict()
                        rec["strict_valid"] = True
                    else:
                        rec["strict_valid"] = False
                        rec["validation_errors"] = errors
                        obj = extract_json_object(content)
                        if obj is not None:
                            coerced, repairs = coerce_recipe(obj)
                            rec["coerced_recipe"] = coerced.as_value_dict()
                            rec["coercion_repairs"] = repairs
                    model_failures = 0
                else:
                    rec["strict_valid"] = False
                    model_failures += 1
                    if rec.get("http_status") == 404:
                        print(f"[{label}] 404 — model unknown to proxy, skipping model", flush=True)
                        results.append(rec)
                        atomic_write(out_path, doc)
                        skipped = True
                        break

                results.append(rec)
                atomic_write(out_path, doc)  # partial progress survives
            if skipped and budget.exhausted():
                break

    doc["calls_used"] = budget.used
    doc["scoring"] = score(results)
    atomic_write(out_path, doc)
    print(json.dumps(doc["scoring"], indent=2))
    print(f"\n[done] {budget.used} calls used; raw + scoring -> {out_path}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("docs/research/em297-raw.json"))
    ap.add_argument("--env-file", type=Path, default=None)
    ap.add_argument(
        "--score-only",
        type=Path,
        default=None,
        help="re-run scoring over an existing raw json (no network)",
    )
    args = ap.parse_args()

    if args.score_only:
        doc = json.loads(args.score_only.read_text())
        doc["scoring"] = score(doc["results"])
        atomic_write(args.score_only, doc)
        print(json.dumps(doc["scoring"], indent=2))
        return 0

    if args.env_file and args.env_file.exists():
        load_env_file(args.env_file)

    api_key = (os.environ.get("FREELLMAPI_KEY") or "").strip()
    base_url = (os.environ.get("FREELLMAPI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if not api_key:
        print("FREELLMAPI_KEY not set (env or --env-file)", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    return run_probe(args.out, base_url, api_key)


if __name__ == "__main__":
    raise SystemExit(main())
