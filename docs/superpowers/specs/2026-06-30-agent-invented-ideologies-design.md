# Agent-Invented Ideologies — the Government Bridge

> **Status:** design (approved 2026-06-30) · **Wave:** standalone (ships on shipped governance substrate; orthogonal to Wave O) · **Area:** backend + frontend · **Flag:** `ideology.enabled` (default `false`)

## Problem

The simulation has a working **government** — agents propose rules, vote, amend a living
constitution, run trials, set car policy — but no concept of a *political/economic
ideology*. There is no communism, socialism, capitalism, monarchy, etc. anywhere in code
(confirmed: zero hits across `.py/.ts/.tsx/.json/.yaml` for any named system; no
`government_type`/`regime_type` field). Government is modeled purely as emergent
rules+votes+constitution; the *kind* of government is never named or categorized.

The project's standing philosophy is **emergent and invented, not real-world-labelled**
(e.g. Wave O's religion spec mandates "seeded **invented** name/deity/tenets — no real
religions"). So the goal is **not** to add a `government_type = "communism"` enum. It is to
give agents the **tools to invent and name their own ideology**, have it spread, and have itRevi
**shape how they govern** — emergently.

## Decisions (locked via brainstorming 2026-06-30)

1. **What an ideology does → bridge to governance.** An ideology is a *named banner* that
   *also records stances on existing law-effects* (favors/opposes). Adherents are nudged
   toward voting/proposing consistently — but can defect. This is what makes an ideology a
   **government concept** rather than a cultural vibe. (Rejected: "named banner only" with no
   governance link; "hard auto-policy" that auto-toggles laws — cuts against the emergent /
   freedom-to-make-mistakes ethos.)
2. **Nudge mechanism → perception-only, agent decides.** The agent's held ideology + its
   favored/opposed effects are injected into that agent's turn context. The LLM agent then
   votes/proposes **freely** — usually with its ideology, but defection is allowed and
   visible. Zero new vote-tally code, zero extra LLM calls, fully emergent. (Rejected:
   deterministic vote-weighting that overrides agency; a separate engine-computed bloc/
   alignment tally.)
3. **Scope → standalone governance core, ships now.** Built on the **existing shipped**
   governance substrate (rules/votes/constitution + reflex verbs + the 0.7 supermajority
   lane + perception injection + group-by camps). Blocks on nothing. The viral/meme layer
   (passive diffusion, text drift, lineage, image-memes) is **deferred** to ride Wave O's
   `Meme` primitive (EM-250) when it lands — at which point ideology auto-registers a
   `kind="ideology"` meme to gain drift "for free." (Rejected: gating on the unbuilt EM-250/
   253/254 chain; building a throwaway mini-meme engine now.)

### Smaller calls (made during design; open to revision)

- **One ideology per agent** — mutually exclusive, like `faith_id`. Switching = converting.
- **`favors`/`opposes` drawn from the existing law-effect vocabulary** (`world.py:3661`) so
  the bridge is machine-precise — *plus* free-text `tenets` for flavor/manifesto.
- **Founding and adopting are free** (no influence cost). Founding spam is a *finding*, not a
  bug (MAX-call-rate / freedom ethos).
- **Official ideology is perception-only** — it never auto-toggles a law.

## How it maps to existing patterns

This is the **governance-flavored sibling of Wave O's Faith**: where `Faith` is an
institution anchored to a `temple`, an `Ideology` is an institution anchored to the **rule
machine**. It reuses the same shipped idioms the crime engine (EM-240) and constitution
(EM-236) used:

| Need | Reused shipped mechanism | Anchor |
|------|--------------------------|--------|
| New collective decision | governance `effect` + existing vote tally | `world.py:3661`, `4370` |
| Supermajority (0.7) act | add string to the demolish-grade lane tuple | `world.py:4370` |
| Conditional prompt block | `constitution_block` pattern (empty → nothing) | `runtime.py:3265`, `3409` |
| Serialize-when-non-default | `crime_status`/`influence` to_dict gating | `world.py:475`, `484` |
| World collection snapshot | `self.factions` clone-when-non-empty | `world.py:7383` |
| Reflex verb | append to `ACTION_SCHEMA` + `TOOL_REGISTRY` | `runtime.py` registry |

## Data model

All new fields **serialize only when non-default** and restore to default when absent, so the
em161 golden snapshot stays byte-identical with the feature inert.

### `Ideology` dataclass (beside `RuleState`, ~`world.py:653`)

```python
@dataclass
class Ideology:
    id: str                       # seeded "ide_<hex>" from _seed_int(tick, founder_id, name)
    name: str                     # agent-authored, e.g. "Sharebound"
    founder_id: str
    founded_tick: int
    tenets: list[str]             # free-text manifesto lines (cap = ideology.max_tenets, 5)
    favors: list[str]             # subset of valid law-effects (cap = max_stances, 6)
    opposes: list[str]            # subset of valid law-effects (cap = max_stances, 6)
    adherents: list[str]          # agent ids; founder auto-included
```

- `favors`/`opposes` entries are validated against the existing `valid_effects` set
  (`world.py:3661`). **Unrestricted within that set** — an agent may hold weird stances
  (e.g. pro-`demolish`); that is chaos, not an error. Unknown effects are dropped on
  `found_ideology` with a soft note.

### World collections (beside `self.factions`, `world.py:1189`)

```python
self.ideologies: dict[str, Ideology] = {}
self.ideology_camps: dict[str, dict] = {}     # mirrors self.factions shape
self.official_ideology_id: str | None = None
```

Snapshot/restore: clone the `self.factions` block at `world.py:7383` (serialize only when
non-empty); `official_ideology_id` emitted only when set.

### AgentState (`world.py:264`)

```python
ideology_id: str | None = None   # emit only when set (mirror crime_status, world.py:475)
```

One ideology per agent. `to_dict` emits the key only when non-None; restore defaults to
`None` when absent.

### Config — `ideology:` block on `WorldParams` (clone `CrimeParams`)

```yaml
ideology:
  enabled: false          # master flag — fully inert when false (no verbs/prompt/events)
  camp_min_size: 3        # min adherents for an ideology_camp to exist
  max_tenets: 5
  max_stances: 6          # cap on favors + on opposes (each)
  name_max_len: 48
```

Accessor `_ideology_param` clones `_crime_param` (`world.py:5670`).

## Verbs & governance

### Reflex verbs (zero extra LLM calls, append to `ACTION_SCHEMA` + `TOOL_REGISTRY`)

- **`found_ideology(name, tenets, favors, opposes)`** — ungated (a conviction can strike
  anywhere). Validates/clamps inputs against config caps + the law-effect vocabulary; seeds
  an `ide_` id; founder auto-adheres (sets `founder.ideology_id`). Emits `ideology_founded`.
- **`adopt_ideology(id)`** — ungated. Sets the caller's `ideology_id` (switches if already
  held). Emits `ideology_joined` (+ `ideology_left` for the prior, if any).
- **`abandon_ideology()`** — ungated, optional. Clears `ideology_id`; emits `ideology_left`.

These are **reflex** (no `location_gate`, like voting post-EM-199) — personal belief is free
and location-independent. Collective adoption is the governed act, below.

### Governance effect (the collective act)

- **`ratify_ideology`** — a new `effect` value. Proposed at Town Hall
  (`propose_rule effect=ratify_ideology, payload={ideology_id}`), passes on the **0.7
  supermajority lane** (add `"ratify_ideology"` to the tuple at `world.py:4370` — **no new
  tally code**, exactly how `trial`/`amend_constitution` work). On activation
  (`_on_rule_activated`) sets `world.official_ideology_id`. Re-ratifying a different ideology
  **replaces** the current one (emit `ideology_disavowed` for the outgoing,
  `ideology_ratified` for the incoming). Added to `valid_effects` (`world.py:3661`) and given
  a validation branch (payload must reference a real `ideology_id`).

## The bridge: perception injection

A conditional **`ideology_block`** assembled like `constitution_block` (`runtime.py:3265`)
and dropped into the prompt immediately after it (`runtime.py:3409`). **Empty when the agent
holds no ideology AND the town has no official ideology → prints nothing → em161 golden
byte-identical.** When present:

```
=== 🏛 IDEOLOGY ===
  You hold Sharebound. Its tenets: "all credits pooled"; "no landlords".
  It favors laws: ubi, work_bonus.   It opposes: ban_stealing.
  The town's official ideology is The Ledger Creed (favors: recharge_subsidy).
  Vote and propose as your convictions move you — or break with them.
```

- The "you hold …" lines appear only when the agent has an `ideology_id`.
- The "town's official ideology …" line appears only when `official_ideology_id` is set, and
  rides **every** agent's prompt (adherent or not) — it is town-wide perception.
- The agent (an LLM) then votes/proposes **freely**. Defection is observable in the normal
  vote feed. **No engine-side alignment tally** (perception-only decision).
- Background tier gets the same compact block (it is short), consistent with how
  `constitution_block` is handled.

## Camps (round-boundary, deterministic)

`recompute_ideology_camps()` runs at round start (in `_apply_round_start`, after
`recompute_factions`): a **deterministic group-by `ideology_id`** over living agents, keeping
groups with `>= camp_min_size` adherents. Emits `ideology_camp_formed` /
`ideology_camp_dissolved` on membership diffs (diff-only, like `recompute_factions`). This is
a partition on a field — simpler than the faction mutual-edge clusterer. When EM-250 lands,
this can be swapped to the shared `_recompute_groups` for free.

## Determinism keystone

- Ideology ids seeded via `_seed_int` on `tick` + sorted inputs; **no `random`, no
  wall-clock** anywhere in engine paths.
- Every new field serializes only when non-default; restores to default when absent.
- New event kinds are open strings.
- With `ideology.enabled = false`: no verb appears in any menu, no prompt block is emitted,
  no event is produced, no collection is serialized → the em161 golden is byte-identical.

## Event kinds (open union)

`ideology_founded`, `ideology_joined`, `ideology_left`, `ideology_ratified`,
`ideology_disavowed`, `ideology_camp_formed`, `ideology_camp_dissolved`.

## Frontend (`web/src/types/index.ts` + inspector)

- Types: `Ideology` + `IdeologyCamp` interfaces; optional `Agent.ideology_id`; optional
  `WorldState.ideologies` / `ideology_camps` / `official_ideology_id`; new EventKinds (open
  union, additive).
- UI:
  - **Ideology badge** on agents (reuse faith/faction badge chrome).
  - **Camp chips** (reuse faction chrome).
  - **Official-ideology banner** (reuse `plaza_banner_ref`).
  - **Ideology panel** listing each ideology: name / tenets / favors–opposes / adherent
    count / founder.
  - Vote rows show the **voter's ideology badge** so a human *sees* alignment/defection —
    without the engine computing an alignment tally (honors the perception-only decision).
- **Live-render discipline:** any memoized component that reads ideology state must key on
  ideology **content** (counts + `official_ideology_id`), not object identity — the
  thrice-shipped CityScape live-render bug (EM-243/244/247).

## Tests (mirror `test_em240_*`)

- **Schema / serialize-when-non-default:** new fields absent from a default world's snapshot;
  round-trip restore is byte-identical.
- **Verbs:** `found_ideology` (validation, caps, effect-vocabulary filtering, founder
  auto-adheres); `adopt_ideology` (join, switch, prior `ideology_left`); `abandon_ideology`.
- **Governance:** `ratify_ideology` passes on 0.7, sets `official_ideology_id`; re-ratify
  replaces + emits disavow; payload validation rejects a non-existent ideology id.
- **Camps:** group-by ≥ `camp_min_size`; diff-only formed/dissolved events.
- **Perception:** block present when held / when town-official; **absent (empty string) when
  neither** → byte-identical prompt for a default agent.
- **Determinism golden:** default world byte-identical with the feature inert AND with it
  enabled but unused; a live run with ideologies replays byte-identical from a snapshot.

## Scope boundary — deferred to Wave O

Explicitly **out** of this pass, arriving when EM-250 (`Meme` primitive) lands:

- Passive viral **diffusion** of an ideology (one-hop seeded spread).
- Per-hop **text drift / mutation** of tenets.
- Meme **lineage** (parent_id/generation family trees).
- **Image-memes** for ideologies.

v1 spread is **explicit `adopt_ideology` only** — sufficient for a movement to grow to a 70%
ratification. When EM-250 ships, `found_ideology` additionally registers a `kind="ideology"`
`Meme`, and `recompute_ideology_camps` swaps to the shared `_recompute_groups` — a thin
follow-up, not a rewrite.

## Verification (per the petridish toolchain)

- Backend: `.venv/bin/python -m pytest backend/tests/test_em<new>_*.py`.
- Determinism gate: em161 golden round-trips byte-identical with the feature inert; a live
  run replays byte-identical from a snapshot.
- Typecheck: `tsc -b --force` (NOT `--noEmit`) for the frontend type additions; tooling via
  `/usr/local/bin/npx`.
- Live smoke: start the sim, hard-reload (watch the mock-fallback gotcha — check the TICK
  number), enable `ideology`, and watch the feed: an agent founds an ideology, others adopt
  it, a camp forms, a `ratify_ideology` proposal passes at Town Hall, and the official banner
  appears — with at least one adherent visibly voting *against* a favored law (the defection
  that proves perception-only, not coercion).

## Filing

After spec approval: run `plan-intake` to file this as a real `EM-###` row (next free is
**EM-267**) in `docs/REMAINING-WORK.md` (P2, standalone — orthogonal to Wave O), then drive it
into a full implementation plan via `writing-plans`.
