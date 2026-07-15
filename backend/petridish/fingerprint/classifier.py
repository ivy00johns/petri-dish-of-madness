"""EM-313 — deterministic behavioral-stylometry classifier.

Pure math, zero LLM, read-only over the event log. See package docstring.

Pipeline:
  turns_from_events()   — event rows  -> per-agent ordered list of AgentTurn
  features_from_turns() — a set of turns -> a fixed-length feature vector
  build_centroids()     — labeled turns grouped by model -> per-model centroid
  classify()            — a feature vector + centroids -> guess + confidence
  compute_run_fingerprints() — orchestrates the above over a repository, emitting
                               the per-agent CONVERGING guess series the ticker
                               renders (turn-by-turn confidence racing upward).

Determinism: every step is integer/float arithmetic over deterministically
ordered iteration; there is no RNG. `FEATURE_VERSION` guards the feature math so
retro-scores don't silently drift across releases.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Iterable, Mapping, Sequence

# ── Versioning ────────────────────────────────────────────────────────────────
# Bump whenever FEATURE_NAMES, the buckets below, or features_from_turns math
# changes — otherwise a run scored under v1 and re-scored under v2 would drift
# with no way to tell the scores apart. Serialized into every response.
FEATURE_VERSION = 1

# The fixed, ordered feature vocabulary. ORDER IS PART OF THE CONTRACT — a
# centroid built here is only comparable to a vector built here at the same
# FEATURE_VERSION. All features are bounded to [0, 1] so plain Euclidean
# distance treats them commensurately.
FEATURE_NAMES: tuple[str, ...] = (
    "talk_ratio",         # say/whisper share of actions
    "build_ratio",        # construction/creation share of actions
    "move_ratio",         # movement share of actions
    "econ_ratio",         # work/forage/trade/give share of actions
    "aggro_ratio",        # harm/coercion share of actions
    "verb_diversity",     # distinct verbs / total actions
    "retry_rate",         # turns needing a 2nd LLM attempt / model turns
    "parse_fail_rate",    # turns that failed JSON validation / model turns
    "sentence_len_mean",  # mean words/utterance, /40 clamped
    "sentence_len_std",   # stdev words/utterance, /40 clamped
)

_N_FEATURES = len(FEATURE_NAMES)
_WORD_NORM = 40.0  # words → [0,1] normalizer for sentence-length features

# Verb → behavioral bucket. Heuristic but FROZEN per FEATURE_VERSION. A verb in
# no bucket still counts toward the action total (so unknown/new verbs dilute the
# ratios rather than being silently dropped) and toward verb_diversity.
_TALK = frozenset({"say", "whisper"})
_BUILD = frozenset({
    "build_step", "co_build", "contribute_funds", "propose_project", "repair",
    "place_prop", "build_road", "paint_surface", "set_building_skin",
    "create_image", "post_image", "post_billboard", "answer_proclamation",
})
_MOVE = frozenset({"move_to"})
_ECON = frozenset({
    "work", "forage", "recharge", "give", "offer_trade", "accept_contract",
    "offer_cooperation", "accept_cooperation", "adopt", "feed_pet", "teach",
    "trade",
})
_AGGRO = frozenset({
    "insult", "steal", "arson", "clash", "siege", "deceive", "intimidate",
    "bribe", "vandalize", "accuse", "detain", "take_offline", "demolish",
    "remove_prop",
})


@dataclass(frozen=True)
class AgentTurn:
    """One model turn for one agent, reduced to the signals the fingerprint
    needs. `verbs` may hold several entries (EM-199 multi-action turns).
    `routed_via` is the X-Routed-Via ground-truth label for this turn (None when
    the proxy reported nothing, e.g. a cached call)."""

    actor_id: str
    run_id: int
    seq: int
    tick: int
    verbs: tuple[str, ...] = ()
    said_words: tuple[int, ...] = ()
    llm_attempts: int = 0
    parse_failed: bool = False
    routed_via: str | None = None


# ── Turn reconstruction ───────────────────────────────────────────────────────


class _TurnAcc:
    __slots__ = ("actor_id", "seq", "tick", "verbs", "said_words",
                 "llm_calls", "parse_failed", "routed_via", "resp_model",
                 "reflex", "has_action")

    def __init__(self, actor_id: str, seq: int, tick: int) -> None:
        self.actor_id = actor_id
        self.seq = seq
        self.tick = tick
        self.verbs: list[str] = []
        self.said_words: list[int] = []
        self.llm_calls = 0
        self.parse_failed = False
        self.routed_via: str | None = None
        self.resp_model: str | None = None
        self.reflex = False
        self.has_action = False


class _TurnAccumulator:
    """Incremental form of `turns_from_events`: feed seq-ordered event batches
    and reduce to per-agent turn lists on demand. Per-turn accumulators persist
    across feeds, so a turn whose events straddle two batches (a live turn still
    being written when a poll lands) still reduces to ONE AgentTurn once its
    remaining events arrive in a later delta."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self._accs: dict[tuple[str, str], _TurnAcc] = {}
        self._order: list[tuple[str, str]] = []

    def feed(self, events: Iterable[Mapping]) -> None:
        accs = self._accs
        for ev in events:
            if (ev.get("actor_type") or "human_agent") != "human_agent":
                continue
            actor_id = ev.get("actor_id")
            if not actor_id:
                continue
            seq = int(ev.get("seq") or 0)
            turn_id = ev.get("turn_id") or f"__seq{seq}"
            key = (actor_id, turn_id)
            acc = accs.get(key)
            if acc is None:
                acc = _TurnAcc(actor_id, seq, int(ev.get("tick") or 0))
                accs[key] = acc
                self._order.append(key)
            kind = ev.get("kind") or ""
            payload = ev.get("payload") or {}
            if kind == "llm_call":
                acc.llm_calls += 1
                rm = payload.get("gen_ai.response.model")
                if rm and acc.resp_model is None:
                    acc.resp_model = rm
                continue
            if kind == "parse_failure":
                acc.parse_failed = True
                rv = payload.get("routed_via")
                if rv and acc.routed_via is None:
                    acc.routed_via = rv
                continue
            action = payload.get("action")
            if action:
                acc.has_action = True
                acc.verbs.append(action)
                if payload.get("reflex"):
                    acc.reflex = True
                if action in _TALK:
                    said = payload.get("said")
                    if isinstance(said, str) and said.strip():
                        acc.said_words.append(len(said.split()))
                rv = payload.get("routed_via")
                if rv and acc.routed_via is None:
                    acc.routed_via = rv

    def turns_by_agent(self) -> dict[str, list[AgentTurn]]:
        by_agent: dict[str, list[AgentTurn]] = {}
        for key in self._order:
            acc = self._accs[key]
            # Drop reflex/instinct turns entirely — they are engine-authored,
            # not model-authored, so their verbs (and any timed-out llm_call
            # span) would only pollute the model's behavioral fingerprint.
            if acc.reflex:
                continue
            is_model_turn = acc.llm_calls > 0 or acc.has_action or acc.parse_failed
            if not is_model_turn:
                continue
            turn = AgentTurn(
                actor_id=acc.actor_id,
                run_id=self.run_id,
                seq=acc.seq,
                tick=acc.tick,
                verbs=tuple(acc.verbs),
                said_words=tuple(acc.said_words),
                llm_attempts=acc.llm_calls,
                parse_failed=acc.parse_failed,
                routed_via=acc.routed_via or acc.resp_model,
            )
            by_agent.setdefault(acc.actor_id, []).append(turn)
        # Each agent's turns are already in first-seen (seq) order via _order.
        return by_agent


def turns_from_events(
    events: Iterable[Mapping], run_id: int
) -> dict[str, list[AgentTurn]]:
    """Group one run's events into per-agent, seq-ordered lists of model turns.

    Only `human_agent` actors are fingerprinted. A group is kept as a model turn
    when the model was genuinely consulted — it has an ``llm_call``, a real
    action verb, or a ``parse_failure`` — and is dropped when it is a pure
    reflex/instinct turn (engine-authored, not model-authored)."""
    acc = _TurnAccumulator(run_id)
    acc.feed(events)
    return acc.turns_by_agent()


# ── Feature extraction ────────────────────────────────────────────────────────


def features_from_turns(turns: Sequence[AgentTurn]) -> tuple[float, ...]:
    """Aggregate a SET of turns into the fixed [0,1] feature vector. Empty →
    all-zeros. Deterministic: pure counting + arithmetic."""
    n_turns = len(turns)
    if n_turns == 0:
        return tuple(0.0 for _ in range(_N_FEATURES))

    all_verbs: list[str] = []
    words: list[int] = []
    retries = 0
    parse_fails = 0
    for t in turns:
        all_verbs.extend(t.verbs)
        words.extend(t.said_words)
        if t.llm_attempts >= 2:
            retries += 1
        if t.parse_failed:
            parse_fails += 1

    n_actions = len(all_verbs)

    def ratio(bucket: frozenset[str]) -> float:
        if not n_actions:
            return 0.0
        return sum(1 for v in all_verbs if v in bucket) / n_actions

    diversity = (len(set(all_verbs)) / n_actions) if n_actions else 0.0
    mean_w = mean(words) if words else 0.0
    std_w = pstdev(words) if len(words) >= 2 else 0.0

    return (
        ratio(_TALK),
        ratio(_BUILD),
        ratio(_MOVE),
        ratio(_ECON),
        ratio(_AGGRO),
        diversity,
        retries / n_turns,
        parse_fails / n_turns,
        min(mean_w / _WORD_NORM, 1.0),
        min(std_w / _WORD_NORM, 1.0),
    )


# ── Reference centroids + classification ──────────────────────────────────────


def build_centroids(
    turns_by_model: Mapping[str, Sequence[AgentTurn]],
    exclude_actor: str | None = None,
) -> dict[str, tuple[float, ...]]:
    """Per-model reference fingerprints. `exclude_actor` drops that agent's own
    turns so an inference is never circular (leave-one-agent-out). A model with
    no turns left after exclusion is omitted (it can't be a candidate)."""
    centroids: dict[str, tuple[float, ...]] = {}
    for model in sorted(turns_by_model):
        turns = turns_by_model[model]
        if exclude_actor is not None:
            turns = [t for t in turns if t.actor_id != exclude_actor]
        if not turns:
            continue
        centroids[model] = features_from_turns(turns)
    return centroids


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) * (x - y) for x, y in zip(a, b)))


def classify(
    vector: Sequence[float],
    centroids: Mapping[str, Sequence[float]],
    temperature: float = 0.15,
    seed: int = 0,
) -> dict:
    """Softmax over negative centroid distances → a confidence distribution.

    Returns {"top", "confidence", "distribution"}. As an agent accumulates
    turns its vector converges toward its true model's centroid, shrinking that
    distance and driving its confidence up — the racing bar. `seed` is accepted
    for a stable, replay-safe call contract; the classifier is fully
    deterministic, so ties break by model name (seed-invariant)."""
    if not centroids:
        return {"top": None, "confidence": 0.0, "distribution": {}}
    temp = temperature if temperature > 1e-9 else 1e-9
    scores = {m: -_distance(vector, c) / temp for m, c in centroids.items()}
    mx = max(scores.values())
    exps = {m: math.exp(s - mx) for m, s in scores.items()}
    z = sum(exps.values()) or 1.0
    dist = {m: exps[m] / z for m in exps}
    # argmax with a deterministic tie-break (model name ascending).
    top = sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {"top": top, "confidence": dist[top], "distribution": dist}


# ── Orchestration over a repository ───────────────────────────────────────────


@dataclass
class _Cfg:
    reference_runs: int = 25
    temperature: float = 0.15
    lock_threshold: float = 0.9
    min_turns: int = 3
    max_series_points: int = 150


def _cfg_from(ft: object) -> _Cfg:
    d = _Cfg()
    if ft is None:
        return d
    return _Cfg(
        reference_runs=int(getattr(ft, "reference_runs", d.reference_runs)),
        temperature=float(getattr(ft, "temperature", d.temperature)),
        lock_threshold=float(getattr(ft, "lock_threshold", d.lock_threshold)),
        min_turns=int(getattr(ft, "min_turns", d.min_turns)),
        max_series_points=int(getattr(ft, "max_series_points", d.max_series_points)),
    )


def _sample_indices(n: int, k: int) -> list[int]:
    """Up to `k` sorted, unique indices in [0, n-1], always including n-1 (the
    latest turn) and 0. Keeps the converging series bounded for long runs while
    preserving the full sweep from first turn to now."""
    if n <= 0:
        return []
    if k <= 0 or n <= k:
        return list(range(n))
    if k == 1:
        # A single point must be the latest turn (the live guess); the general
        # stride below would divide by k-1 == 0.
        return [n - 1]
    idxs = {0, n - 1}
    step = (n - 1) / (k - 1)
    for j in range(k):
        idxs.add(round(j * step))
    return sorted(i for i in idxs if 0 <= i < n)


def _group_by_model(
    turns_by_agent: Mapping[str, Sequence[AgentTurn]]
) -> dict[str, list[AgentTurn]]:
    """Flatten agents' turns and bucket every LABELED turn by its ground-truth
    model (routed_via). Unlabeled turns contribute to no centroid."""
    by_model: dict[str, list[AgentTurn]] = {}
    for turns in turns_by_agent.values():
        for t in turns:
            if t.routed_via:
                by_model.setdefault(t.routed_via, []).append(t)
    return by_model


# Small, bounded in-process memo for the HISTORICAL reference corpus. Keyed by
# FEATURE_VERSION + each reference run's (id, max_seq) so completed runs cache
# forever and the memo only churns when a reference run actually grows. Read-only
# and off the sim surface — purely an endpoint-cost optimization for live polling.
_REF_CACHE: dict[tuple, dict[str, list[AgentTurn]]] = {}
_REF_CACHE_MAX = 8

# Incremental memo for the TARGET run's parsed turns: (fed-up-to max_seq,
# accumulator). Each poll fetches ONLY the seq delta since the last parse
# (get_events after_seq/before_seq) and folds it into the persisted per-turn
# accumulators, so the 4s ticker poll stops re-reading the whole event log.
# _CACHE_LOCK serializes both memos: the endpoint offloads computes to worker
# threads (app.py), so concurrent polls could otherwise race the shared state.
_TURN_CACHE: dict[tuple, tuple[int, _TurnAccumulator]] = {}
_TURN_CACHE_MAX = 4
_CACHE_LOCK = threading.Lock()


def _target_turns(repo, run_id: int) -> dict[str, list[AgentTurn]]:
    """The target run's per-agent turns, parsed incrementally via _TURN_CACHE.
    Returns a fresh snapshot (immutable AgentTurns), safe to use off-lock."""
    try:
        max_seq = int(repo.get_event_stats(run_id).get("max_seq") or 0)
    except Exception:  # pragma: no cover - defensive
        return turns_from_events(repo.get_events(run_id, order="asc"), run_id)
    key = (id(repo), FEATURE_VERSION, run_id)
    entry = _TURN_CACHE.get(key)
    if entry is not None and entry[0] > max_seq:
        entry = None  # log shrank (reset/prune) — the delta contract is void
    if entry is None:
        entry = (0, _TurnAccumulator(run_id))
    seen, acc = entry
    if max_seq > seen:
        # before_seq pins the window's upper edge to the signature max_seq, so
        # events landing between the stats read and this fetch are never fed
        # twice (they re-fetch cleanly on the next poll).
        acc.feed(repo.get_events(
            run_id, order="asc",
            after_seq=seen or None, before_seq=max_seq + 1,
        ))
        seen = max_seq
    if key not in _TURN_CACHE and len(_TURN_CACHE) >= _TURN_CACHE_MAX:
        _TURN_CACHE.clear()
    _TURN_CACHE[key] = (seen, acc)
    return acc.turns_by_agent()


def _reference_corpus(repo, ref_run_ids: Sequence[int]) -> dict[str, list[AgentTurn]]:
    sig_parts = []
    for rid in ref_run_ids:
        try:
            stats = repo.get_event_stats(rid)
            max_seq = int(stats.get("max_seq") or 0)
        except Exception:  # pragma: no cover - defensive
            max_seq = 0
        sig_parts.append((rid, max_seq))
    # id(repo) guards against two distinct repositories (e.g. in-memory test DBs)
    # colliding on identical (run_id, max_seq) signatures; the live app has one
    # long-lived repo so this is a no-op there.
    sig = (id(repo), FEATURE_VERSION, tuple(sorted(sig_parts)))
    cached = _REF_CACHE.get(sig)
    if cached is not None:
        return cached
    by_model: dict[str, list[AgentTurn]] = {}
    for rid in ref_run_ids:
        turns_by_agent = turns_from_events(
            repo.get_events(rid, order="asc"), rid)
        for model, turns in _group_by_model(turns_by_agent).items():
            by_model.setdefault(model, []).extend(turns)
    if len(_REF_CACHE) >= _REF_CACHE_MAX:
        _REF_CACHE.clear()
    _REF_CACHE[sig] = by_model
    return by_model


def _round_dist(dist: Mapping[str, float]) -> dict[str, float]:
    return {m: round(dist[m], 4) for m in sorted(dist)}


def _majority_label(turns: Sequence[AgentTurn]) -> str | None:
    counts: dict[str, int] = {}
    for t in turns:
        if t.routed_via:
            counts[t.routed_via] = counts.get(t.routed_via, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def compute_run_fingerprints(repo, run_id: int, ft: object = None) -> dict:
    """Full ticker payload for one run: per-agent converging model guesses.

    Reference fingerprints come from up to `reference_runs` OTHER runs in the
    repository (the retroactive corpus, cached). On a fresh DB with no such
    history, it falls back to the current run's OTHER agents (leave-one-agent-out
    so the guess is never a self-lookup); a single-agent-per-model run with no
    history has no honest reference and reports `status: "gathering"` — the
    publishable null result. READ-ONLY; touches no sim state."""
    cfg = _cfg_from(ft)

    # Historical reference corpus (other runs, newest first).
    ref_ids: list[int] = []
    try:
        for row in repo.list_runs():
            rid = int(row.get("id"))
            if rid != run_id:
                ref_ids.append(rid)
            if len(ref_ids) >= cfg.reference_runs:
                break
    except Exception:  # pragma: no cover - defensive
        ref_ids = []
    # Both memos are shared module state and this compute may run on a worker
    # thread (the endpoint offloads it off the sim loop) — serialize access.
    with _CACHE_LOCK:
        target_turns = _target_turns(repo, run_id)
        historical = _reference_corpus(repo, ref_ids) if ref_ids else {}
    use_within_run = not any(historical.values())
    within_run = _group_by_model(target_turns) if use_within_run else {}

    agents_out: list[dict] = []
    for actor_id in sorted(target_turns):
        turns = target_turns[actor_id]
        if use_within_run:
            centroids = build_centroids(within_run, exclude_actor=actor_id)
        else:
            centroids = build_centroids(historical)

        series: list[dict] = []
        for i in _sample_indices(len(turns), cfg.max_series_points):
            vec = features_from_turns(turns[: i + 1])
            c = classify(vec, centroids, cfg.temperature)
            series.append({
                "turn": i + 1,
                "tick": turns[i].tick,
                "guess": c["top"],
                "confidence": round(c["confidence"], 4),
                "distribution": _round_dist(c["distribution"]),
            })

        final = series[-1] if series else None
        ground_truth = _majority_label(turns)
        n = len(turns)
        if n < cfg.min_turns or not centroids or final is None:
            status = "gathering"
        elif final["confidence"] >= cfg.lock_threshold:
            status = "locked"
        else:
            status = "tracking"
        guess = final["guess"] if final and status != "gathering" else None
        confidence = final["confidence"] if final and status != "gathering" else 0.0
        correct = None
        if guess is not None and ground_truth is not None:
            correct = guess == ground_truth

        agents_out.append({
            "agent_id": actor_id,
            "turns": n,
            "ground_truth": ground_truth,
            "guess": guess,
            "confidence": confidence,
            "status": status,
            "correct": correct,
            "candidates": sorted(centroids),
            "series": series,
        })

    return {
        "enabled": True,
        "feature_version": FEATURE_VERSION,
        "run_id": run_id,
        "temperature": cfg.temperature,
        "lock_threshold": cfg.lock_threshold,
        "min_turns": cfg.min_turns,
        "reference_source": "within_run" if use_within_run else "historical",
        "reference_runs_used": [] if use_within_run else ref_ids,
        "agents": agents_out,
    }
