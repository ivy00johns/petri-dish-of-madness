# BUILD RESULTS — EM-240 Crime & Justice engine

> **Status: COMPLETE on branch `feat/em240-crime-justice`** (not merged).
> Backend engine subsystem. No UI in scope (that is the deferred EM-242).
> Built via the orchestrator in ultracode/Workflow mode: 4 sequential gated waves,
> each task implemented test-first by one agent and independently adversarially
> verified, with a full-suite wave gate between waves.

## Headline

The full **crime↔justice loop** is implemented and proven by deterministic tests
that exercise the **real engine methods** (no mocks): a witnessed crime accrues
notoriety → an enforcer escalates to a town-hall **trial** (reusing the existing
governance vote) → a guilty verdict **jails** the defendant, **fines** them, and pays
**restitution** to victims → `advance_crime()` **releases** them at sentence expiry.
Conspiracy (`recruit` → `accept_contract`) forms a real **criminal-ring faction**.

**Final gate:** `1142 passed, 1 skipped` (the lone skip is pre-existing —
`test_em222_live.py` needs the live embed proxy). **76 EM-240 tests**, all green.

## What shipped (13 commits, `8538a6b`…`20fd967`)

### Persona schema (the shared contract for EM-241/EM-242)
- `AgentState.disposition` (`lawful`|`opportunist`|`criminal`) and `role`
  (`citizen`|`enforcer`) — additive, serialized only when non-default, restored in
  `from_snapshot`. **Byte-stable**: a lawful citizen's `to_dict()` is unchanged, so
  every pre-EM-240 snapshot round-trips identically.
- Crime status scalars: `notoriety` (0–100), `crime_status`
  (`wanted`|`detained`|`jailed`|`exiled`), `crime_status_until_tick`, `rap_sheet`.
- Loaded from `personas.yaml` (`load_personas`) and threaded through the spawn API
  (`SpawnBody`, `_resolve_spawn_fields`, `spawn_agent`).

### Crime verbs (all reflex-tier — zero extra LLM calls per action)
- `heist` (big-score theft), `extort`, `vandalize` (building blackout short of arson),
  `bribe` (corruption — a witnessed bribe dirties the *enforcer*), `launder` (cool
  notoriety for a cut), `recruit` + `accept_contract` (two-turn conspiracy → ring).
- `steal` and `arson` folded into the taxonomy (now also accrue notoriety + rap sheet).
- **Notoriety** accrues only from **third-party** witnesses (the victim doesn't count —
  the pickpocket rule), decays while lying low, flips `wanted` at threshold.

### Justice loop
- Enforcer-only verbs `investigate` (confirms unwitnessed crimes when a witness is
  present), `accuse`, `detain` (jails a wanted/high-notoriety suspect on the spot).
- **Jail** is a real `civic` place + a `_validate_world` gate: jailed agents may only
  `say`/`whisper`/`idle`/`remember` (the cell makes feed drama, not dead air).
- **Town-hall trial**: a new `propose_rule` effect `trial` reusing the unchanged
  `action_vote`/`_evaluate_rule` machinery — guilty → jail + fine + restitution;
  acquittal → notoriety relief + an accuser standing penalty (frivolous accusations
  cost enforcers). Defendant resolvable by **name or id** so an enforcer can actually
  name them in a live run (the Wave-3 verifier caught this; fixed in Task 12a).

### Integration & config
- Prompt: a gated `crime_block` in `_assemble_context` (criminal nudge / enforcer duty
  / WANTED+JAIL status / open-pact offer) — **empty for lawful citizens**, so the
  em161 golden prompt fixture is unchanged.
- Menu: crime verbs offered only to `opportunist`/`criminal`, enforcer verbs only to
  `enforcer` — but the **validator still allows crime for everyone** (the emergent
  "lawful agent snaps"). New verbs added to `ACTION_SCHEMA` so they pass the JSON gate.
- `crime:` config block + a real `CrimeParams` dataclass (all tunables defaulted →
  existing worlds unchanged). New event kinds registered in `events.schema.json`.
- Seed cast: **6 new personas** (Roop/Sledge/Wisp criminals; Sheriff Cobb/Reyes
  enforcers; Pip opportunist) + **Brick promoted** to `enforcer`.

## Definition of Done

| # | Item | State |
|---|---|---|
| 1 | Every task passed its validation checklist | ✅ 12 plan tasks + 1 polish, each adversarially verified |
| 2 | Contract conformance | ✅ build-contract A–E followed; deviations disclosed in commit bodies |
| 4 | **Reality gate** | ✅ *at the engine level* — the capstone test drives the **real** `World` methods end-to-end (no mocks); the LLM-driven live run is the recommended next observation (see Handoff) |
| 5 | End-to-end validation | ✅ `test_crime_to_conviction_end_to_end` + `test_conspiracy_forms_a_faction` |
| 6 | Integration issues fixed & re-validated | ✅ jail-place town-shape invariants, trial name-resolution, ACTION_SCHEMA gate |
| 7 | Plan acceptance criteria | ✅ all 12 plan tasks closed |
| 13 | Changelog/spec clean | ✅ spec + plan + contract committed |
| 14 | **QA gate** | ✅ 76 EM-240 tests written & passing; full suite `1142 passed, 1 skipped`; no skipped/weakened tests (verifiers confirmed no gate-cheating) |
| 16 | End-state report | ✅ this file |

UI-specific DoD items (3, 9–12, 15, 17 ports) — **N/A**: no UI in this build.

## Backward-compat & determinism

- All new `AgentState`/persona/config fields additive and default-omitted from
  serialization → pre-EM-240 snapshots byte-identical (verified by the existing
  snapshot/round-trip suite staying green).
- No `random`/wall-clock in any new engine path (EM-155 replay/fork safety preserved).

## Handoff / next steps

1. **Live smoke (recommended, not run here):** bring up the FreeLLMAPI proxy + the
   sim, spawn `Sheriff Cobb` + `Roop`, and watch the feed for
   `crime_committed → accusation → trial_verdict → jailed → released`. This is the only
   thing the deterministic suite can't prove — that LLM agents *spontaneously* pick
   these verbs in a live run. (The menu/prompt wiring that makes them able to is tested.)
2. **EM-241 (persona content expansion)** and **EM-242 (persona management UI)** are the
   documented follow-on specs — they consume the schema this build introduced. File
   them into the ledger via the `plan-intake` skill when ready.
3. **Tuning:** the `crime:` config defaults (notoriety thresholds, jail sentences,
   payoffs, fines) are first-pass numbers — tune against the live run.
4. Branch is ready for review; **not merged** (per build policy). Spec, plan, and
   build-contract travel with it.
