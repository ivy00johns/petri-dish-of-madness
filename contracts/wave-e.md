# Wave E contract — "the social city" (characters & the social world)

> Version: 1.0 · Date: 2026-06-11 · Branch: `build/wave-e-social-world`
> Items: **EM-113** (B1), **EM-114** (B2), **EM-120** (B3), **EM-125** (B4),
> **EM-184** (B5), **EM-185 + social-graph UI** (B6).
> Mission: recreate the Emergence-World experience — its magic was *social*
> texture (683-crimes-vs-zero-crimes cultures). That needs typed relationships,
> factions, family lines, and a closed petition→miracle loop.
> Deferred this wave (written reasons): **EM-126** generations (P3 — the v3
> report itself stages it "depth later"; deps EM-114 which lands here; the
> `parents` field shipped in B2 is its hook); **EM-125's migration half**
> (reflection-driven *migration* is multi-city surface — single-city scope is
> the bond-upgrade path only; multi-city stays deferred per the user's
> "deepen the first city first" direction); **EM-182/183** (city-agency, not
> social — pairs with generator work, separate wave).

## Global rules (all batches)

- **Free-scale law: no change may add a standing LLM call.**
  - Children are NEW agents → they spawn at `background` tier and only into
    *vacancies* under `world.children.max_population` (default 25 — the
    measured v4 budget). Births never grow the call budget past today's.
  - EM-125 bond declarations ride the EXISTING reflection request (same JSON,
    same single turn call). Never a separate call.
  - Relationship transitions, factions, reputation, miracles: pure reflex /
    derived state. Zero calls.
- Verification on MockProvider / unit tests only — never real paid keys.
- Agents do NOT commit — the orchestrator commits at batch gates.
- Full backend suite stays green: `cd backend && source ../.venv/bin/activate
  && python -m pytest -q` (566 at wave start). Tests import
  `petridish.engine.world` BEFORE `petridish.agents.runtime`.
- **No `Math.random()`/`random` without a seed derived from world state**
  (city_seed/tick/agent ids) — determinism is an EM-155 invariant.
- Config params follow EM-155: yaml → loader dataclass → engine reads via
  `_block_get` with identical defaults → `EMBEDDED_WORLD_YAML` mirror kept in
  sync → snapshot keys ADDITIVE (absent ⇒ byte-identical pre-E behavior, prove
  with a test each batch).
- New event kinds get a row in `contracts/event-log.md` §registry (the batch
  that introduces the kind updates the doc).
- Backend batches are SEQUENTIAL (B1→B5 all touch `world.py`). B6 is frontend
  (`web/` only) and runs after B5.
- Never touch `README.md`, `START-HERE.md`.

## Shared vocabulary (all batches build against this)

Relationship `type` vocabulary becomes:
`neutral | ally | friend | rival | enemy | partner | family | mentor | feud`
(first five exist today — never break them in snapshots or prompts).

New event kinds this wave:
`relationship_changed` (B1) · `child_spawned` (B2) ·
`faction_formed | faction_joined | faction_left | faction_dissolved` (B3) ·
`god_miracle | miracle_expired` (B5).
All relationship/faction events carry ONLY agent ids in actor_id/target_id
(EM-141: the social-graph selector silently drops non-agent endpoints).

---

## B1 — EM-113: relationship depth (P1, foundation)

**Owner:** backend-agent-B1.
**Files owned:** `backend/petridish/engine/world.py`,
`backend/petridish/agents/runtime.py`, `backend/petridish/config/loader.py`,
`config/world.yaml`, `contracts/event-log.md`,
`backend/tests/test_wave_e_relationships.py` (new).

### Behavior spec

1. **Schema (additive):** `RelationshipState` (world.py:51) gains
   `since_tick: int = 0` — the tick of the last TYPE change. `trust` stays the
   single scalar (strength = |trust|, valence = sign; do NOT add redundant
   floats). Serialize in `to_dict`/`from_snapshot`/`relationships_json`
   additively (absent ⇒ 0).
2. **Type vocabulary** extends to the shared list above. `set_relationship`
   accepts the new types with guards: `partner` requires the declarer's trust
   toward the target ≥ `partner_trust_threshold` (default 40) — below it the
   action fails with guidance ("you barely know them"); `family` is
   engine-assigned only (births, B2) — agent attempts are rejected with
   guidance; `feud`/`mentor` are declarable.
3. **Reflex transitions** — ONE seam: after `_update_trust` (world.py:2022)
   clamps, evaluate transitions (helper `_maybe_shift_relationship(from_agent,
   to_agent, tick)`):
   - `neutral|ally` → `friend` when trust ≥ `friend_trust` (default 30) AND
     interactions ≥ `friend_interactions` (default 5).
   - `rival|enemy` → `feud` when trust ≤ `feud_trust` (default -40).
   - Existing steal escalation (rival/enemy at -20) is UNCHANGED beneath these.
   - Types never auto-downgrade this wave (drama persists; explicit
     `set_relationship` can still overwrite, subject to guards).
4. **Mutual-partner predicate** `World.are_partners(a_id, b_id) -> bool`:
   BOTH directions typed `partner` AND both trusts ≥ threshold. (B2 consumes;
   reciprocity is the consent mechanic.)
5. **Event:** emit `relationship_changed` ONLY on type transitions (reflex or
   accepted set_relationship), payload `{from_type, to_type, trust,
   since_tick}`, text e.g. `"Ada and Bram are now friends"` /
   `"the rivalry between Mox and Vesper has hardened into a feud"`. Routed
   through the existing action `_multi` chain (reflex transitions triggered by
   an action ride that action's turn events).
6. **Prompt:** the EM-161 relationship line format (`name: type (trust=N)`) is
   UNCHANGED (new types just appear as words). Protagonist fixture guard
   (`em161_protagonist_prompt_pre_diet.txt`) must stay byte-identical — new
   types only show when relationships actually shift.
7. **Config** `world.relationships` (EM-155 conventions):
   ```yaml
   relationships:
     friend_trust: 30
     friend_interactions: 5
     feud_trust: -40
     partner_trust_threshold: 40
   ```
   No `enabled` flag — thresholds only fire on NEW trust mutations, so
   pre-E snapshots restore byte-identical.

### Acceptance (minimum)

- since_tick round-trips snapshot + repository json; absent key ⇒ 0.
- give×5 to trust 30 flips neutral→friend exactly once, one event, since_tick
  stamped; further gives don't re-emit.
- steal-driven trust ≤ -40 flips rival→feud; -39 doesn't.
- set_relationship partner below threshold rejected with guidance; at
  threshold accepted; family always rejected for agents.
- are_partners true only when mutual + both ≥ threshold.
- relationship_changed events carry agent ids only (both endpoints).
- Protagonist prompt fixture byte-identical; full suite green.

---

## B2 — EM-114: lightweight children (P1)

**Owner:** backend-agent-B2 (after B1 gate).
**Files owned:** `backend/petridish/engine/world.py`,
`backend/petridish/engine/loop.py` (hook only),
`backend/petridish/config/loader.py`, `config/world.yaml`,
`contracts/event-log.md`, `backend/tests/test_wave_e_children.py` (new).

### Behavior spec

1. **Birth check** `World.check_births(personas) -> list[dict]` (events),
   called once per ROUND boundary (hook beside the existing per-round effects
   in `_start_new_round`, events parked in the proven `pending_spawn_events`
   outbox → drained at top of `next_agent` like EM-168). Conditions, ALL
   required, evaluated deterministically (stable pair order by sorted ids):
   - pair `are_partners` (B1) and co-located at a `home`-kind place;
   - living human population < `max_population` (default 25) AND < total home
     capacity (cottage = 1 bed each, bunkhouse = its `capacity`);
   - both parents' credits ≥ `birth_cost_credits` (default 6) — both pay
     (credits sink), and both energy ≥ 30;
   - pair cooldown: no prior child of this pair within `pair_cooldown_ticks`
     (default 600); world cooldown: at most ONE birth per round;
   - seeded chance gate `birth_chance` (default 0.25) via
     `hash((city_seed, tick, a_id, b_id))`-derived unit float — no `random`.
2. **The child:** spawned via the existing `spawn_agent` machinery at
   `cadence_tier="background"`; `AgentState` gains additive
   `parents: list[str] = []` (snapshot/repository round-trip; absent ⇒ []).
   Name+personality: first UNUSED persona-library card (EM-092 casting pool),
   personality prefixed `"Child of {p1} and {p2}. "` + a deterministic
   blend (first clause of each parent's personality appended); library
   exhausted ⇒ name `"Kit-{n}"`. Profile: the non-mock profile with the
   FEWEST living assigned agents (tie → stable profile order) — load-spread,
   never mock. Location: the birth home. Starting energy 70, credits 0.
   Relationship seeds: child↔each parent `family`, trust +40, both directions,
   since_tick = birth tick; memory line "born in {town_name}".
3. **Events:** `child_spawned` narrative event (payload `{child_id, parents,
   name, profile, place}`, text `"👶 {name} is born to {p1} and {p2}"`) PLUS
   the standard `agent_spawned` (frontend roster contract) — both via the
   outbox.
4. **Config** `world.children`:
   ```yaml
   children:
     enabled: true
     max_population: 25
     birth_cost_credits: 6
     birth_chance: 0.25
     pair_cooldown_ticks: 600
   ```
   `enabled: false` ⇒ no birth checks, byte-identical pre-E (prove).
5. Free-scale proof obligation (test): with population AT cap, no birth ever
   fires regardless of conditions.

### Acceptance (minimum)

- Happy path: mutual partners co-located at home with credits/energy →
  child appears, parents debited, both events emitted, child at background
  tier with family ties both ways, parents field set.
- Cap gates: population cap, housing capacity, credits, energy, cooldowns,
  chance gate (seed-pinned both ways), one-birth-per-round.
- Persona casting: unused card consumed; collision with living names skipped;
  exhausted library → Kit-N.
- Snapshot round-trip: parents + new config; resumed world doesn't re-birth
  (cooldown state derivable — pair cooldown keyed off the CHILD's existence:
  youngest shared child's spawn tick, no new clock state).
- enabled:false byte-identical; full suite green.

---

## B3 — EM-120: factions, feuds & reputation (P2)

**Owner:** backend-agent-B3 (after B2 gate).
**Files owned:** `backend/petridish/engine/world.py`,
`backend/petridish/config/loader.py`, `config/world.yaml`,
`contracts/event-log.md`, `backend/tests/test_wave_e_factions.py` (new).

### Behavior spec

1. **Reputation (derived, zero storage):** `World.reputation(agent_id) -> int`
   = round(mean incoming trust over living agents with interactions ≥ 1
   toward this agent); no relationships toward them ⇒ 0. Exposed additively in
   `AgentState.to_dict()` as `"reputation"` (computed at serialization via a
   world backref — if to_dict can't reach world, compute in `to_snapshot` and
   the loop's agent payload path; B3 picks the cleanest seam and documents it).
2. **Factions (stored, diffed):** `World.factions: dict[str, dict]` —
   `{id: {name, founded_tick, members: list[str]}}`. Recompute candidate
   clusters at each ROUND boundary (same hook pattern as B2, order: births
   then factions): connected components over MUTUAL warm edges (both
   directions type ∈ {ally, friend, partner, family} AND both trusts ≥
   `faction_trust` default 25) among living agents; components of size ≥
   `faction_min_size` (default 3) are factions.
3. **Identity continuity:** match each new component to an existing faction by
   max member overlap (≥ 50% of the OLD membership) — keeps id/name; else new
   faction `id=fct_{8hex of sorted founding members + tick}`, name
   `"{oldest founding member's name}'s circle"` (oldest = lowest agent id for
   determinism). Unmatched old factions dissolve.
4. **Events on edges only:** `faction_formed` (payload {faction_id, name,
   members}), `faction_joined`/`faction_left` (actor_id = the agent,
   payload {faction_id, name}), `faction_dissolved`. Emitted via the same
   outbox; no per-round spam when membership is stable (diff-driven).
5. **Snapshot:** `factions` key ADDITIVE (absent ⇒ {}), round-trips.
6. **Prompt (cheap, optional but specified):** agents in a faction get ONE
   line in their context (`"Your circle: {name} ({k} members)"`) — additive,
   protagonist fixture guard must still pass for the fixture world (no
   factions there).
7. **Config** `world.factions {enabled: true, faction_trust: 25,
   faction_min_size: 3}`; `enabled: false` ⇒ byte-identical pre-E (prove).

### Acceptance (minimum)

- 3 mutually-warm agents form a faction (one formed event, named/deterministic);
  4th warm agent joins (one joined event); trust drop below threshold →
  left event; shrink under min_size → dissolved.
- Identity continuity across membership churn (≥50% overlap keeps id).
- Reputation math (incl. zero-relationship default); surfaces in to_dict.
- Determinism: same world state ⇒ identical faction ids/names across two
  recomputes; snapshot round-trip preserves factions.
- enabled:false byte-identical; events carry agent ids only; full suite green.

---

## B4 — EM-125: reflection-driven bonds (P2)

**Owner:** backend-agent-B4 (after B3 gate).
**Files owned:** `backend/petridish/agents/runtime.py`,
`backend/petridish/engine/world.py` (one helper:
`apply_bond(agent, target_id, type, tick)`), `contracts/event-log.md`,
`backend/tests/test_wave_e_bonds.py` (new).

### Behavior spec

1. When a reflection is requested (the EXISTING EM-080 threshold path,
   runtime.py:2218 + prompt injection :1362), the SAME injected instruction
   additionally offers an optional `"bond"` field:
   `{"target": "<name>", "type": "friend|partner|mentor|feud"}` — "if these
   events changed how you see someone". Rides the SAME single turn call;
   ACTION_SCHEMA gains the optional `bond` object (additive, maxLengths
   consistent with EM-142 caps).
2. **Validation & application** (reflex, after parse): target resolved via the
   existing `_normalize_args` name→id machinery; type must be in the allowed
   set (`family` engine-only, B1 rule); B1 guards apply (partner threshold).
   Valid bond ⇒ `world.apply_bond(...)` = set_relationship semantics +
   `relationship_changed` event (B1's) attributed to the agent's turn chain.
   Invalid/unknown target ⇒ silently dropped (logged in trace payload
   `bond_rejected: reason` — never fails the turn).
3. **Throttle:** at most ONE bond per reflection (which is already
   importance-throttled ~2-3×/day) — no new cadence, no new calls. MockProvider
   scenario tests drive it deterministically.
4. The reflection event payload gains additive `bond_applied:
   {target_id, type}` when one landed (observability — EM-166 spirit).

### Acceptance (minimum)

- MockProvider turn with reflection+valid bond → relationship type set, one
  relationship_changed event in the SAME turn chain (shared turn_id),
  reflection payload carries bond_applied.
- partner bond below trust threshold rejected (trace reason), turn succeeds.
- family bond rejected; unknown target dropped; malformed bond object ignored.
- No bond instruction when reflection not requested (prompt byte-identical to
  pre-E for the non-reflection path; protagonist fixture guard passes).
- Zero llm_call delta proven: turn emits exactly the same llm_call rows as a
  reflection turn today. Full suite green.

---

## B5 — EM-184: world-scale miracles (P1)

**Owner:** backend-agent-B5 (after B4 gate).
**Files owned:** `backend/petridish/engine/world.py`,
`backend/petridish/api/app.py`, `backend/petridish/config/loader.py`,
`config/world.yaml`, `contracts/event-log.md`,
`backend/tests/test_wave_e_miracles.py` (new).

### Behavior spec

1. **Timed world modifiers:** `World.active_miracles: list[dict]` —
   `[{kind, until_tick, payload…}]` (snapshot ADDITIVE, absent ⇒ []).
   Expiry swept in the existing per-tick path next to `expire_blackouts()`
   (world.py:1995 pattern): emits `miracle_expired` ("the rains pass…").
2. **Kinds** (extend `god_intervene`, world.py:1890 — `agent_id` becomes
   optional; world kinds REJECT an agent_id, targeted kinds still require it):
   - `send_rain`: while active, `action_forage` yield +`rain_forage_bonus`
     (default 2) on top of base+garden bonuses. Duration
     `rain_days` (default 2) in-world days (`days × turns_per_day` ticks).
   - `bountiful_harvest`: while active, `apply_energy_decay` uses
     `decay × harvest_decay_factor` (default 0.5). Duration `harvest_days`
     (default 2).
   - `calm_spirits`: ONE-TIME — every living agent's mood set to `"hopeful"`,
     and every existing relationship with interactions ≥ 1 gets
     `_update_trust(+calm_trust_bonus, default 3)` (clamped as usual; B1
     transitions may fire — that's the point). No duration entry.
   - Re-invoking an active kind REFRESHES until_tick (no stacking).
3. **Event all agents perceive:** `god_miracle` (actor_id='god',
   actor_type='god', target_id=None, payload `{kind, until_tick?}`,
   text e.g. `"🌧 Rain falls on the gardens — forage flourishes"`). Add
   `god_miracle` to the runtime importance weights at 2.0 AND to the global
   witness kinds (alongside random_event) so the whole town can react —
   this closes the ask→answer→belief loop.
4. **API:** `POST /api/god/intervene` — `InterveneBody.agent_id` becomes
   `str | None`; validation: world kinds (the three above) require agent_id
   None/absent (422 otherwise), targeted kinds (bless_energy/grant_credits)
   require it (existing behavior byte-identical). Response includes
   `until_tick` for timed kinds.
5. **Config** `world.miracles {enabled: true, rain_forage_bonus: 2,
   rain_days: 2, harvest_decay_factor: 0.5, harvest_days: 2,
   calm_trust_bonus: 3}`; `enabled:false` ⇒ world kinds 409/ValueError,
   targeted kinds untouched, byte-identical pre-E (prove).
6. Free-scale: pure state modifiers; zero LLM calls; importance weight may
   make a background agent's next due turn salient — that is EXISTING EM-159
   machinery, not a new standing call.

### Acceptance (minimum)

- send_rain: forage yield boosted while active, normal after expiry;
  miracle_expired emitted exactly once; refresh-not-stack proven.
- bountiful_harvest halves decay only while active.
- calm_spirits: moods set, trust nudged + clamped, B1 transition can fire,
  no duration entry left behind.
- API matrix: world kind + agent_id ⇒ 422; targeted kind without agent_id ⇒
  422; existing bless/grant behavior unchanged (regression).
- Snapshot round-trip mid-rain: buff survives resume, expires on schedule.
- enabled:false inert; full suite green.

---

## B6 — EM-185 + social-graph UI (P1, frontend)

**Owner:** frontend-agent-B6 (after B5 gate; `web/` ONLY).
**Files owned:** `web/src/**` (components/feed/EventFeed.tsx,
components/controls/ControlPanel.tsx, components/panels/RosterStrip.tsx,
inspector/SocialGraph.tsx, inspector/selectors.ts, types/index.ts, api client,
matching `*.test.ts(x)`), NOTHING outside `web/`.

### Behavior spec

1. **Event-kind registration (mandatory):** add all 8 new kinds to
   `KIND_ICON`, `KIND_FALLBACK_COLOR`, and `CATEGORIES` (every kind maps to
   exactly ONE category): relationship_changed + faction_* + child_spawned →
   `social`; god_miracle/miracle_expired → the god/system category that holds
   god_intervention today. Icons: ♥ relationship_changed, 👶 child_spawned,
   ⚑ faction_*, 🌧/☀ miracles (or tasteful equivalents). New colors as CSS
   token vars (declared in the tokens css, never hex-in-JS —
   design-token-guard).
2. **GRANT-a-petition (EM-185):** feed entries for petition-shaped events —
   `billboard_posted` and `proclamation_answered` with actor_type ≠ 'god' —
   render a small `GRANT` affordance. Click opens a compact picker (inline
   popover in the feed entry or god-console handoff — B6's call, document it):
   the three EM-184 miracles + the two targeted interventions, pre-filled
   with the petition text. Granting: (a) calls the intervene API
   (world kind ⇒ no agent_id), (b) auto-posts a god billboard reply quoting
   the petition (existing `in_reply_to` mechanism). Optimistic-free like the
   rest of the god console (WS event is the echo).
3. **God console:** the EM-138 INTERVENE group gains a `MIRACLES` row —
   kind picker (3 world kinds) + CAST button; api client gains
   `godMiracle(kind)` (POST /api/god/intervene without agent_id).
4. **Social graph:** edge colors keyed by relationship TYPE (partner/family
   warm-distinct, feud darker than enemy; REL_COLOR-style map extended via
   CSS tokens); `relationship_changed` events update the selector fold
   (`socialGraph()` consumes payload.to_type/trust; agent-endpoint filter
   EM-141 preserved); faction hulls: nodes carry faction_id from faction_*
   event fold, rendered as a soft convex-hull tint behind member nodes
   (canvas pass under nodes; skip if perf < 60fps and fall back to per-node
   faction ring — document the choice).
5. **Roster:** REL_COLOR map extended for the 4 new types (chips already
   render type+trust); add `REP` mini-stat reading `agent.reputation`
   (backend additive field) next to credits/mood.
6. **child_spawned** rides the existing agent_spawned roster path (backend
   emits both) — B6 only needs the feed narrative row + social category.
7. **Tests:** every registry addition + GRANT flow (petition detect, API call
   shape, reply call) + selectors relationship_changed fold + reputation
   render. Suite stays green (501 at wave start).

### Acceptance (minimum)

- All 8 kinds registered in all three registries (a test enumerates them).
- GRANT shows on agent billboard posts, NOT on god posts; flow fires both API
  calls with the right payloads (mocked client).
- SocialGraph: typed edge colors; relationship_changed updates an edge;
  building-endpoint filter still passes EM-141 tests.
- Reputation renders when present, absent-safe when not.
- vitest suite green; `npm run build` green; no hex literals in JS
  (token vars only).

---

## Gates

After each batch: full backend pytest (B6: vitest + tsc/build) run by the
ORCHESTRATOR, then orchestrator commit. Wave QE after B6: adversarial
verification per the green-gate-≠-real-fix rule — verify a birth actually
debits BOTH parents and the child takes real scheduled turns (next_agent
order), verify a miracle actually changes forage/decay math (not just flags),
verify the bond path adds ZERO llm_call rows, verify factions diff (no event
spam on stable rounds). QE writes `coordination/qa-report.json` (wave-E,
schema 1.1). Build blocked on standard QA rules. Closeout: ledger statuses,
BUILD-PLAN closure log, `docs/build-results/BUILD_RESULTS_WAVEE.md`.
