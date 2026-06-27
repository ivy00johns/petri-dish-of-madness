# EM-224 — PIANO coherence for multi-action turns (design spike)

> Status: resolved → build. Author: backend build agent (Wave M4).
> Contract: `contracts/wave-m.md` §3 (Wave M4, EM-224). Open Q resolved below.

## 1. Problem

EM-199 made a turn carry an ORDERED `actions[]` sequence resolved from one LLM
call (`_normalize_steps` → `_apply_steps` in `backend/petridish/agents/runtime.py`).
A single response can now say one thing and *do* the opposite in the same turn:

> `say "Sure, here — take these credits, friend!"` → then `steal {target: Bram}`
> `say "Welcome, I'd love to help you build."` → then `attack {target: Bram}`

The feed shows the friendly line and the hostile act side by side, with no
reconciliation. This is the "PIANO incoherence" failure: speech and action drift
because nothing enforces a single intent across the multi-step turn.

## 2. What we take from PIANO — and what we reject

PIANO (Project Sid / AI Town's "concurrency + a coherence bottleneck") has two
ideas bundled together:

1. **Parallelize cognitive modules to cut latency** — many modules run at once,
   a *bottleneck* serializes them into one coherent output.
2. **A single bottleneck "decision" that the other modules must agree with** —
   the coherence guarantee.

We take ONLY idea (2), the coherence bottleneck. We explicitly **REJECT** idea
(1): PetriDish's north star is MORE LLM calls, never fewer-blocking (memory
`session-189-rate-is-the-target`, `no-throttling-bounce-models-instead`).
We do not parallelize, we do not cut calls, we do not add calls. The coherence
check is a **deterministic, zero-LLM post-processing pass** over the already-
resolved `actions[]` list — it rides the existing single turn (EM-066 ethos).

## 3. Where the bottleneck lives in the EXISTING flow

The single-LLM-turn → multi-action flow today is:

```
run_turn → _call_and_parse (the ONE LLM call, the "module outputs")
         → _normalize_steps  (flatten actions[] → ordered steps)
         → _apply_steps      (per-step normalize → gate → dispatch, in order)
```

The bottleneck is a new pass **between `_normalize_steps` and `_apply_steps`**:

```
_normalize_steps → _coherence_resolve(steps, ...) → _apply_steps
```

`_coherence_resolve` is the PIANO "single decision → broadcast": it derives ONE
intent from the turn (the bottleneck), then reconciles every later step against
it (the broadcast). It is a pure function of `(steps, thought)` — deterministic,
no `random.*`, no clock, seedless (it makes no *choices*, only structural ones).

## 4. The intent and the contradiction rule (v1)

**Intent derivation (the single decision).** The turn's intent toward a *target*
is read from its FIRST speech act — the first `say`/`whisper` step's `args.text`
(falling back to the turn `thought` if there is no speech act). v1 classifies the
speech's **stance toward a named target** as `friendly`, `hostile`, or `neutral`
via a small deterministic keyword lexicon (a frozenset of cooperative cues —
"help", "give", "gift", "welcome", "friend", "thank", "trust", "share", "for you",
"take these", … — and hostile cues — "hate", "kill", "destroy", "fool", "trick",
"rob", …). No target named / neutral stance ⇒ no intent ⇒ no-op (golden-safe).

**Contradiction.** A later **action** step contradicts the intent when:

- the speech stance toward target T is **friendly**, AND
- a later step is a **hostile verb** (`steal`, `attack`, `insult`, `intimidate`,
  `deceive`, `extort`, `vandalize`, `heist`) targeting that **same** T.

(The mirror case — hostile speech then a `give`/`teach_skill`/`feed_pet` to the
same target — is recognized symmetrically but is far rarer; v1 handles the
friendly-then-harm case as the primary, with the hostile-then-help case behind
the same machinery.)

**Resolution — one configurable strategy, deterministic.** When a contradiction
is found, `world.coherence.strategy` picks the handling:

- `annotate` (default-when-enabled): keep both steps, but append a deterministic
  **coherence note** to the contradicting action's event text and stamp
  `payload.coherence = {"intent": ..., "contradicted": true}`. The world still
  changes; the feed is now *honest* about the dissonance ("…— belying their warm
  words"). This is the lowest-risk, most-emergent option: it never silently drops
  an agent's chosen act, it just makes the hypocrisy legible.
- `drop`: remove the contradicting step before `_apply_steps` and emit a single
  `coherence_note` event in its place (the speech "wins"; the act is suppressed).
- `reorder`: not implemented in v1 — documented as a future option (would need to
  re-validate gating against the reordered state; deferred to avoid the
  re-gate-cost). Falls back to `annotate`.

All three are pure structural transforms of the steps list. None calls the LLM.

## 5. Config — `world.coherence` (R2), DEFAULT OFF

```yaml
coherence:
  enabled: false        # master toggle — OFF ⇒ byte-identical to pre-EM-224
  strategy: annotate    # annotate | drop  (reorder reserved → annotate)
```

`CoherenceParams(enabled=False, strategy="annotate")` in `loader.py`, parsed by
`_parse_coherence` (absent/malformed → defaults), wired into `WorldParams`, and a
defensive `_coherence_enabled(params)` accessor in `runtime.py` (mirrors
`_planning_enabled` / `_universalization_enabled`). The block is added to BOTH
`config/world.yaml` and the `EMBEDDED_WORLD_YAML` mirror.

**Default OFF is the load-bearing invariant.** With `enabled=False`,
`_coherence_resolve` returns the steps untouched and emits nothing, so:

- the em161 prompt golden is **byte-identical** (EM-224 adds NO prompt block at
  all — it is post-resolution only, the prompt never changes either way);
- EM-155 snapshots are **byte-identical** (EM-224 carries NO `AgentState`/`World`
  state — it is a pure per-turn structural pass, nothing to serialize);
- a coherent multi-action turn is unchanged even when ENABLED (no contradiction
  found ⇒ steps pass through verbatim).

This mirrors exactly how EM-223 planning and EM-234 universalization shipped
(complete feature, gated, default-off, golden+snapshot intact).

## 6. Determinism

`_coherence_resolve` makes no random/clock/uuid calls. The lexicon match and the
target-equality test are pure string ops; the note text is fixed. Same input
steps ⇒ same output, so replay/fork identity holds (EM-155). The contradiction
scan is O(n²) worst case over ≤ `max_actions_per_turn` (default 4) steps —
negligible, zero extra calls.

## 7. Tests (TDD, `tests/test_em224_coherence.py`)

1. `enabled + annotate`: friendly `say` then `steal` same target → the steal event
   carries `payload.coherence.contradicted` and a note in its text; both still
   resolve (the world mutated).
2. `enabled + drop`: same turn, `strategy: drop` → the steal is suppressed (no
   credit moves), a `coherence_note` event replaces it, the `say` still lands.
3. `coherent multi-action unchanged`: friendly `say` + `give` same target (no
   contradiction) → events identical to the no-coherence path even when enabled.
4. `disabled = byte-identical`: the contradictory turn with `enabled=False`
   produces exactly the pre-EM-224 chain (steal applies, no coherence payload).
5. `no target / neutral speech`: a `say` with no target reference + a `steal` →
   no contradiction flagged (intent un-derivable) even when enabled.
6. em161 golden unchanged (config absent) — covered by the existing golden test
   staying green; assert no `coherence` key appears on a default turn.
7. determinism: same steps twice → identical resolution.

Full suite gate: `cd backend && .venv/bin/python -m pytest -q` must stay green
(≥ baseline + these new tests, exactly 1 skipped).
