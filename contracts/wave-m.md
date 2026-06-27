# Contract — Wave M: Cooperation Economy (EM-227–237) + W23 build

> Integration contract for the orchestrated Wave M build (cooperation economy)
> plus the cognition/correctness items that ship alongside it. Source items:
> `docs/REMAINING-WORK.md` EM-227–237, EM-224, EM-203/206, EM-189/190, EM-186,
> EM-167, EM-126. Research: `docs/research/deep-research-v1.md` (EW gap analysis).
>
> **This contract is the shared integration layer. Every build agent reads §1
> (Invariants) and §2 (Recipes) before touching code, then their feature's §3
> spec.** The agents share `world.py` / `runtime.py` / `loop.py` / `loader.py`,
> so backend features are built **sequentially**, each on the prior's committed
> state. Do not restructure existing code; add additively.

---

## §1 — Load-bearing invariants (DO NOT BREAK)

These are gated by existing tests. A red gate here blocks the wave.

1. **EM-155 byte-identical snapshots.** A world with no new-feature state must
   serialize (`World.to_dict` / `AgentState.to_dict`) to the **exact pre-change
   dict**, and `World.from_snapshot` must round-trip it byte-identically. New
   `AgentState` / `World` fields are **additive**: non-feature default value,
   serialized in `to_dict` **only when non-default**, restored defensively in
   `from_snapshot` (unknown/absent → default, fail-safe). Reference: the EM-240
   crime fields (`world.py:187-256`, `5084-5097`) and EM-223 `plan`.
   Test that pins this: `backend/tests/test_wave_k_integration.py::
   test_full_snapshot_round_trip_is_byte_identical_after_protocol_mutations`
   and the EM-155 city-seed round-trip. **Run these after every feature.**

2. **em161 prompt golden fixture.** The turn prompt for a **lawful citizen
   with no new state** (default disposition, no plan, no commitments, no
   overheard, no new needs pressure) must be **byte-identical** to today. Any
   new `_assemble_context` block MUST be **empty/absent under default
   conditions** — exactly how the crime block is empty for lawful citizens
   (`runtime.py:2240-2285`). Tests: `test_em240_prompt.py`, the em161 golden.
   **A feature that changes the prompt for ALL agents unconditionally (e.g.
   universalization, a new always-on needs line) MUST be gated behind a config
   flag defaulting OFF, OR carry an explicit golden-fixture update with a
   written justification in the build log.** Default is: preserve the golden.

3. **Determinism / replay-fork safety (EM-155).** No `random.*`, no
   `Math.random`, no wall-clock (`time.*`, `datetime.now`) in any new engine
   path. Seed any choice from `world.tick` + ids + `city_seed` (see the EM-240
   `_seeded_*` and `rng_for` patterns, `world.py:4220`). Child/entity ids that
   must align across same-seed runs derive from a seeded hash (this is EM-189's
   whole point — see §3).

4. **Backward-compat config.** A `world.yaml` WITHOUT a new block must behave
   identically to before (the `CrimeParams` / `_crime_param` convention:
   defaults live in the dataclass AND the engine accessor, so an absent block
   is a no-op). Both `config/world.yaml` and the `EMBEDDED_WORLD_YAML` mirror
   in `config/loader.py` get the new block.

5. **Full suite stays green.** Baseline: **1142 passed, 1 skipped** (the skip
   needs the live embed proxy). Command:
   `cd backend && .venv/bin/python -m pytest -q` (hermetic; conftest pins
   `EM_DB_PATH=:memory:`, `EM_EMBED_MOCK=1`, `EM_IMAGEGEN_MOCK=1`).
   Every feature ADDS tests; none may subtract or weaken existing ones.

6. **North-star alignment.** Features ADD agent activity / LLM-call surface,
   never throttle. No cap-governor, no decision-cache re-enable, no muting
   agents. Reflex-tier verbs (zero extra LLM calls, ride the existing turn)
   are preferred for new actions; psychology/prompt changes enrich the single
   existing call. See memory `no-throttling-bounce-models-instead`,
   `session-189-rate-is-the-target`.

---

## §2 — Recipes (follow these exactly; they encode the invariants)

### R1 — Add an additive `AgentState` field
- Declare in the dataclass (`world.py:144-198`) with a neutral default.
- `to_dict` (`world.py:200-257`): emit the key **only when non-default**
  (`if self.x != DEFAULT: d["x"] = ...`). List/dict fields: `if self.x:`.
- `from_snapshot` (`world.py:5040-5098`): read defensively
  (`x=_coerce(d.get("x"))`), unknown/absent → default.
- If observability is wanted, add to the `to_dict` observability keys (always
  emitted) — but that **changes world_state shape**; prefer only-when-set
  unless a panel needs it live.

### R2 — Add a config param block `world.<name>`
- `@dataclass <Name>Params` in `loader.py` (model on `CrimeParams`, `:616`),
  fields with defaults. **No `enabled` flag** unless the feature changes
  default behavior for existing worlds (verb-only additions need none; an
  always-on prompt/decay change needs one defaulting to preserve old behavior).
- `def _parse_<name>(raw)` (model on `_parse_crime`, `:1426`): absent/malformed
  → defaults, per-key fallback.
- Add `<name>: <Name>Params = field(default_factory=<Name>Params)` to
  `WorldParams` (`:810-928`), and wire `<name>=_parse_<name>(w.get("<name>"))`
  in the WorldParams construction (`:1663` area).
- Add a `_<name>_param(key, default)` defensive accessor on `World` (model on
  `_crime_param`) so engine reads never KeyError.
- Add the `<name>:` block to BOTH `config/world.yaml` (after the `crime:` block)
  AND `EMBEDDED_WORLD_YAML` in `loader.py` (`:50-207`), with comments.

### R3 — Add a new agent action verb (reflex-tier preferred)
- Add the string to the `ACTION_SCHEMA` enum in BOTH the single-`action` enum
  and the `actions[]` items enum (`runtime.py:110-191`).
- Add a `TOOL_REGISTRY` entry (`runtime.py:301-383`):
  `{"tier": "reflex"|"llm", "location_gate": None|"@place"|"@building",
  "agreement_gate": None|"<rule_id>"}`.
- If the verb takes new arg aliases or name→id targets, extend `_normalize_args`
  (`runtime.py:1107-1177`).
- Gate it in `_validate_world` (`runtime.py:1261-1448`): role/location/tier/
  co-location checks, with a **clear rejection reason** (agents see it).
- Dispatch in `_apply_action_inner` (`runtime.py:4378-4700`): call a
  `world.action_<verb>(...)` method, return an event dict
  `{**base, "kind": "<event>", "text": "...", "payload": {...}}` (model on
  `action_heist`, `:4465`). The world method holds the state mutation + returns
  `(ok, reason, amount)` or an event dict via `_emit_world_result`.
- Surface in the prompt **valid-actions menu** (`runtime.py:1807-2039`),
  **conditionally** so the em161 golden stays byte-identical (offer only when
  the agent meets the precondition — e.g. has the skill, is co-located, etc.).
- Add the event kind to `contracts/events.schema.json` x-known-kinds (`:38`).

### R4 — Add a new two-turn negotiated action (offer → accept)
Model on EM-240 conspiracy (`recruit` → `accept_contract`,
`world.py:1660-1675`, dispatch `runtime.py:4530-4547`): the offer parks a
pending record keyed by target id on the World (a transient outbox dict);
the prompt surfaces "X has offered you …"; `accept_contract`-style verb
consumes it. **Transient pending dicts MUST be serialized or asserted-empty at
snapshot time (EM-190) — see §3 EM-190.**

### R5 — Add a governance rule effect
Model on EM-240 `trial` and EM-212 `promote_image`
(`world.py:2229-2568`):
- Add the effect string to `valid_effects` in `action_propose_rule` (`:2251`).
- Route its payload (`:2259-2320`).
- Scope its duplicate-guard if multiple instances can contend (`:2321-2345`).
- Exclude one-shot effects from EM-087 renewal tagging (`:2346-2357`).
- Set the threshold in `_evaluate_rule` (`:2657-2699`) — strict majority, or
  70% supermajority like `demolish`.
- Implement the activation in `_on_rule_activated` (`:2419-2568`) + emit an
  event kind. If it has an acquittal/rejection branch, hook
  `action_vote`'s reject path (`:2413`).
- Surface a concrete proposable id in the propose_rule menu (`:1888-1924`).

### R6 — Add a conditional prompt context block
`_assemble_context` (`runtime.py:1686-2500`). Add the block AFTER the relevant
existing block, **gated** so it is empty/absent under em161-golden conditions.
Diet-aware: background tier gets a trimmed or dropped version (see the EM-161
prompt-diet pattern + the crime block's tier handling).

### R7 — Tests
`backend/tests/test_em<NNN>_<topic>.py`. Construct `World(params, places,
agents)` directly (see `test_em240_*.py`). Cover: the happy path, the snapshot
round-trip with the new state set (byte-identical when unset), the em161 golden
(unchanged for a default agent), config-absent = default behavior, and the
determinism/replay property where relevant. Run the targeted file, then the
full suite.

---

## §3 — Per-feature specs

> Build order respects deps + shared-file serialization. Each feature: TDD,
> commit `feat: <desc> (EM-XXX)` when its targeted tests + full suite are green.

### Wave M1 — psychology & prompt foundations

**EM-229 — Three-needs psychology.** Add decaying `knowledge` and `influence`
needs (floats 0..100) alongside `energy`. EW drives: energy ~30h, influence
~24h, knowledge ~36h → scale to our tick cadence (slower decay than energy;
config). R1 fields (default 100.0, serialized when `< 100`), R2 block
`world.needs` (`knowledge_decay_per_turn`, `influence_decay_per_turn`, salience
thresholds; **the decay is new always-on behavior → these default to small
non-zero, but the PROMPT surfacing must keep em161 byte-identical**: only add a
needs line when a need is below a salience threshold, exactly like the energy
starvation line is conditional). Decay hook beside `apply_energy_decay`
(`world.py:1369`). Needs do NOT kill (only energy does) — low knowledge/
influence bias behavior via the prompt (drives curiosity/teaching, politics/
campaigning). Knowledge replenished by learning (teach/skill-gain, EM-227/228);
influence by governance/social wins. Wire those replenishments minimally now or
leave hooks documented for M2. Tests: decay math, conditional prompt line,
snapshot, golden-unchanged-when-full.

**EM-234 — Universalization prompting.** Inject the GovSim scaffold ("before
acting on the commons, ask: what if *every* agent did this?") as a prompt block
(R6). This is **always-on for all agents → would break em161 golden**, so gate
it behind `world.universalization.enabled` (R2) **default OFF** — exactly how
EM-223 planning shipped (default off ⇒ prompt golden + snapshot byte-identical).
The feature ships complete; flip `enabled:true` for live runs to get the cheap
cooperation lift. Add a test asserting the block IS present when enabled and
ABSENT (golden byte-identical) when off. **Do NOT regenerate the em161 golden**
— the off-default keeps it intact. One block, no new systems.

**EM-233 — Memory consolidation + soul entries.** (a) **Soul entries**: a tiny
immutable `soul: list[str]` on AgentState (R1; seeded from persona at spawn,
≤3 entries, never summarized, injected into every prompt as identity anchors —
conditional block, empty if no soul → golden-safe since default agents get
seeded soul only if configured; default empty list preserves golden). (b)
**Consolidation ("sleep")**: at a beliefs token/count ceiling, batch-summarize
oldest `beliefs` into one digest line (deterministic, no LLM in v1 — a
structured rollup; an optional cheap-LLM summary can be a documented hook).
Hook at round boundary (`_start_new_round`). R2 block `world.memory`
(`consolidate_at`, `soul_cap`). Tests: consolidation triggers at ceiling,
soul injected, golden-safe, snapshot.

### Wave M2 — skills keystone + cooperation

**EM-227 — Skills & emergent professions (KEYSTONE).** Add `skills: dict[str,
int]` to AgentState (R1; skill→level, default `{}` → golden/snapshot safe).
A **skill library** (config `world.skills`, R2): named skills (e.g. farming,
crafting, medicine, art, rhetoric, building) each with a list of **gated
actions** that require ≥ a min level. Gate in `_validate_world` (R3): an agent
attempting a gated high-value action WITHOUT the skill gets a clear rejection
("you lack the <skill> skill"). Skills are GAINED by doing (successful gated
action → +xp, threshold → level up) and by teaching (EM-228). Seed initial
skills per persona (config / persona library) so identical agents start
differentiated OR start blank and diverge — **default: seed a small random-free
spread by persona archetype** so specialization has a starting gradient. Surface
the agent's skills + what's gated in the prompt (R6, conditional/diet-aware).
Which actions to gate: pick a few existing high-value ones (e.g.
`propose_project`/`build_step` → building skill; `create_image` → art skill;
`propose_rule` → rhetoric/influence) — gate **softly** (still allowed for
protagonists? no — gate for real, that's the point) but keep the world livable
(don't gate survival: move/work/forage/say/recharge always open). Tie to
EM-229 knowledge need (gaining a skill replenishes knowledge). Closes the
dangling `skills` payload EM-110 already migrates. Tests: gate rejects,
xp/level-up, seed spread deterministic, snapshot, prompt.

**EM-228 — teach_skill / request_skill.** Two reflex verbs (R3): co-located
`teach_skill(target, skill)` transfers/raises the target's level (teacher must
have it at a higher level; bounded gain), `request_skill(target, skill)` is the
ask (parks a pending request, R4). THE explicit cooperation lever. Teaching
replenishes BOTH agents' knowledge need (EM-229) and raises trust. Event kind
`skill_taught`. Deps EM-227. Tests: transfer math, co-location gate, pending
request, snapshot.

**EM-230 — Real trade / offer_trade.** Two-turn negotiated exchange (R4):
`offer_trade(target, give={credits?, skill?, item?}, get={...})` parks an
offer; `accept_trade` / `decline_trade` resolves it (atomic two-sided swap of
credits and/or skill-teach and/or resource). Beyond one-way `give` + `steal`.
Event kinds `trade_offered`, `trade_settled`, `trade_declined`. Deps EM-227
(enables skill-for-credit / skill-for-skill). Tests: atomic swap, insufficient
funds rejected, pending offer snapshot (EM-190), decline path.

**EM-231 — Cooperation-gated tools.** A class of high-value actions unlocked
**only when both partners have agreed to cooperate** (EW's hard mechanic).
Model: a co-located pair forms a `cooperation` handshake (one offers, the other
accepts — reuse the R4 pending pattern or a relationship flag), and a gated
action (e.g. a joint project bonus, a co-build, a partnership trade discount)
requires the active handshake. Make it a designed affordance, not an accident.
Deps EM-230. Keep it small: one concrete cooperation-gated action + the
handshake. Tests: gate blocks solo, unlocks paired, snapshot.

### Wave M3 — economy, governance, harm

**EM-232 — Peer-judged credit economy (Victory Arch).** A periodic
pitch→peer-judge→award cycle (EW ~2-day cadence → config `world.victory_arch`,
R2: `every_n_ticks`, `award`). At the cycle boundary (`_start_new_round` /
tick check): agents who `pitch_contribution` (a reflex verb, R3, parks a pitch)
are peer-judged (deterministic v1: rank by a contribution score derived from
recent events — buildings funded, skills taught, trades settled — NOT random),
top pitch(es) get a credit award + a reputation bump + an event `arch_award`.
Adds reputation-through-contribution + the inequality story (feeds a Gini/
AWI-M8 read). Reflex/deterministic, zero new LLM calls. Tests: cycle fires on
cadence, deterministic ranking, award applied, snapshot of pending pitches.

**EM-235 — Boost queue.** Let agents spend credits for extra turns/airtime
(EW ComputeCredits). Reflex verb `buy_turn` (R3): deduct `boost_cost` credits,
grant the agent an extra scheduled turn this/next round. Hook the scheduler
(`next_agent`/`_rebuild_turn_order`, `world.py:1111-1162`) to honor a per-agent
boost counter (additive AgentState field, R1, default 0). Agents literally buy
influence over the shared timeline — pure emergence + MORE calls (north-star).
Config `world.boost` (R2: `cost`, `max_per_round`). Deterministic. Tests:
credits deducted, extra turn granted, cap respected, snapshot, scheduler stays
deterministic.

**EM-236 — Living constitution.** An amendable articled foundational document
vs today's flat rule list. A `World.constitution: list[dict]` (articles:
{id, text, ratified_tick}); a governance effect `amend_constitution` (R5) that
adds/edits/removes an article on a 70% supermajority (like demolish); surface
the constitution in the prompt (R6, conditional — empty list → golden-safe).
Adds the constitutional-growth signal (AWI M9). Builds on EM-015/108 governance.
Backend + a minimal frontend read (the frontend surfacing can be deferred to
Wave F / EM-225-adjacent — backend ships the artifact + effect + event
`constitution_amended`). Tests: amend adds article, 70% threshold, snapshot,
golden-safe-when-empty.

**EM-237 — Harm finishers (intimidate / deceive).** Two reflex verbs (R3)
into the existing crime-verb path: `intimidate(target)` (threaten without
contact — coerce credits/compliance via fear, raises target fear/lowers trust,
adds notoriety like extort but no contact required) and `deceive(target, about)`
(lying as a first-class act — plants a false belief / manipulates a trade or
vote, reputation-gaming axis). Slot into `_apply_action_inner` beside the EM-240
crime verbs; reuse notoriety/witness machinery (`world.py:4097` rap_sheet,
witness scaling). Event kinds `intimidate`, `deceive`. Config: add
`intimidate_notoriety`, `deceive_notoriety` to `CrimeParams` (R2 extend).
Small add, not new infra (EM-240 path exists). Tests: notoriety accrual,
witness scaling, target effect, snapshot.

### Wave M4 — cognition + correctness

**EM-224 — PIANO coherence for multi-action turns (spike+build).** Open Q:
structure a "bottleneck → single decision → broadcast" so speech and action
stay aligned across `actions[]` (EM-199), preventing "says 'sure!' while doing
something else." Take ONLY the coherence idea (reject PIANO's parallelize-to-
cut-latency motive). v1 approach: in `_normalize_steps` / multi-action
resolution, derive a single `intent` from the turn's `thought`/first speech act
and **validate later steps for contradiction** (a `say` that promises X then an
action ¬X → reorder, annotate, or drop with a coherence note), OR require the
speech act to reference the chosen actions. Keep it deterministic + cheap.
Write the resolved approach into a short
`docs/superpowers/specs/2026-06-26-em224-piano-coherence-design.md` first, then
build behind `world.coherence.enabled` (default preserving current behavior +
golden). Tests: contradictory pair handled, coherent pair unchanged, golden.

**EM-203 + EM-206 — Governance renewal cooldown + settled-naming signal.**
(203) An unchanged ACTIVE rule can't be renewed for N ticks (`world.governance`
config: `renewal_cooldown_ticks`), OR surface "already active (settled)"
in-prompt so agents legislate something new. (206) `world.town_name` surfaced
as **decided/settled** in agent context, and a no-op rename returns "already
named X (settled)" so agents stop campaigning for the current name. Same class
(no settled-signal → re-doing decided things) — fold together. Touch
`action_propose_rule` renewal tagging (`world.py:2346`), `name_town` no-op
guard (already partly in EM-200 — verify), prompt context (R6). Tests:
renewal blocked within cooldown, settled signal present, no-op rename rejected.

**EM-189 — Deterministic child ids.** Child agent ids use `uuid4` → same-seed
runs produce identical births with different ids. Derive child id from a seeded
birth hash (parents' ids + birth tick + ordinal), like the EM-210 `_image_id`
seed. Find the child-spawn path (EM-114, `world.py` birth logic, search
`child_spawned`/`parents`). Tests: same-seed → identical child ids; fork/replay
identity preserved.

**EM-190 — Serialize transient outboxes.** `pending_relationship_events` /
`pending_spawn_events` (and any new Wave-M pending dicts: trade offers, skill
requests, pitches, recruit offers) are not serialized → a snapshot taken
between park and drain drops them on fork/resume. Either serialize them in
`World.to_dict`/`from_snapshot` OR assert-empty at snapshot time (round-boundary
parks drain within the same `next_agent` call today, so assert-empty is valid
IF snapshots only happen at round boundaries — verify). **All new Wave-M pending
state must follow whichever rule this establishes.** Tests: park → snapshot →
restore preserves (or asserts-empty correctly).

**EM-186 — Headless run.py D3 wiring.** `run.py` builds `Router(cfg.profiles)`
without `world.lane_failover`, never wires lane-event/usage-alert sinks or the
usage-window probe → EM-177 failover + EM-168 governor only work via the API
server. Thread the params + sinks through `run.py` (and the W7
`world.cache`→Router gap noted in the same finding). Compare `api/app.py`'s
wiring as the reference. Defaults coincide with shipped yaml → default headless
behavior identical. Tests: run.py constructs Router with failover params;
behavior parity.

**EM-167 — Ollama overflow lane (providers).** Enable the scaffolded Ollama
profile (`profiles.yaml`), route background/supporting tiers there as
off-critical-path background tasks (animal-task pattern). ~40% of background
calls off FreeLLMAPI. **Live-verify needs Ollama running — if unavailable in
this env, ship the wiring + a test with a mock Ollama adapter and record
"code-complete, live-verify pending Ollama" in the build log.** Deps EM-158
(✅), EM-164 (✅).

**EM-126 — Generational depth (STRETCH).** Life stages (child→adult→elder
cadence + tool unlocks), inheritance of credits/relationships/grudges on death,
lineage tree data. Deps EM-114 (✅ children). Large — build only after M1–M3
land green; if the budget/quality bar can't hold it, defer with a written
reason. R1 fields (`life_stage`, `age_ticks`), inheritance hook on death,
event `inherited`. Tests: aging cadence, inheritance on death, snapshot.

---

## §4 — Frontend (Wave F) — see per-item specs in the build log

EM-202 (A/B persona UI), EM-215 (the Diary), EM-204 (inspector IA cleanup),
EM-195 (inspector scrub residuals), EM-180 (funds-as-marker), EM-191 (GRANT
typographic distinction), EM-192 (frontend follow-ups), EM-193 (token-discipline
burndown), EM-225 (chronicle deep-dive). Area-owner serialization: inspector
(195→204), world3d (180→192), controls/feed (202→191), nav seam (Diary tab +
inspector tabs share App.tsx/Header — integrate centrally). EM-193 runs LAST,
solo. Frontend gate: `cd web && npm run typecheck && npm test` + design-token-
guard + class-extraction-guard on touched UI.

---

## §5 — Definition of Done (Wave M)

- All EM-227–237 + M4 items shipped or deferred-with-reason; tests added.
- Full backend suite green (≥1142 + new tests, 1 skip).
- EM-155 byte-identical + em161 golden invariants hold (or golden updated with
  a logged justification for EM-234/EM-236 prompt enrichments).
- Ledger (`docs/REMAINING-WORK.md`) + closure log (`BUILD-PLAN.md`) updated.
- `docs/build-results/BUILD_RESULTS_WAVE_M.md` written.
- No deployment (excluded by user).
