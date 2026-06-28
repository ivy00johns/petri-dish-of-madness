# EM-243 (S2 — agent `build_road` verb) — Build Results

**Status: ✅ COMPLETE on branch `feat/em243-build-road-verbs`. QA gate PASS_WITH_ISSUES (`proceed=true`); the one HIGH + the MEDIUM the review surfaced are FIXED.**
Orchestrated **ultracode** build (Workflow mode): design/contracts inline (the plan), implement + verify as Workflow scripts. Not merged, no PR (no instruction).

## What shipped
Agents can now reshape the city: **`build_road`** extends the `CityGraph` one axis-aligned segment (one `BLOCK_PITCH`) from the node nearest the agent, paid in energy, bounded to a 9×9 envelope, grow-only. A diet-safe district-scoped **`nearby_layout`** perception block + menu entry let agents choose where to build. The grown graph rides the existing snapshot, so replay/fork reproduce it; the renderer re-derives live.

- **`engine/citygraph.py`** — pure `apply_build_road` / `nearest_node` / `extendable_directions` + the 9×9 envelope constants (`MAX_CITY_BLOCKS`/`MIN_IDX`/`MAX_IDX`). Deterministic `n:{i}:{j}` / `e:{a}->{b}` ids; `_ordered_edge` reproduces `classic_grid`'s a→b convention.
- **`engine/world.py`** — `action_build_road(agent, args) -> dict` (demolish dict-pattern; `_fail_event` reasons: no_location / too_tired / no_graph / blocked); energy-paid via `road_build_energy_cost` (8).
- **`agents/runtime.py`** — `build_road` in `ACTION_SCHEMA` (single + multi enums) + dispatch in `_apply_action_inner` → `road_built` event; `build_nearby_layout` + menu/perception wiring in `_assemble_context` (gated on affordability + an open direction; lot-count deferred — no backend lot derivation exists).
- **`config/loader.py` + `config/world.yaml`** — `road_build_energy_cost: 8`. (The growth envelope is a citygraph constant, NOT a config param — see the MEDIUM fix.)
- **`web/.../cityLayout.ts`** — grown roads past the frozen 5×5 now render (9×9 envelope clip); the no-graph fallback stays 5×5 (EM-239 byte-identical preserved).
- **`web/.../CityScape.tsx`** — `citySignature`/`useCityPlan` now react to the graph's node/edge counts so built roads render **live** (the HIGH fix, below).

## Commits (on `feat/em243-build-road-verbs`)

| Commit | What |
|---|---|
| `7f3efeb` | docs: the S2 implementation plan |
| `eed42ca` | feat: backend build_road verb + nearby_layout perception |
| `279df46` | feat: render grown roads past the 5×5 envelope + tessellation tests |
| `3ac39ca` | fix: live road rendering (HIGH) + remove dead max_city_blocks param (MEDIUM) |

## Gates (lead-run AND re-run by the QE agent)

| Gate | Baseline | Final | Result |
|---|---|---|---|
| Backend `pytest` | 1620 | **1638** (+18) | ✅ 0 regressions |
| `test_build_road.py` (new) + `test_citygraph.py` | — | **29** | ✅ |
| Frontend `world3d` | 561 | **564** (+3) | ✅ 24 files |
| `tsc -b --force` | exit 0 | **exit 0** | ✅ |

## Verification — adversarial (4 lenses) + QE gate

Lens verdicts: **determinism/EM-155 = clean**, **scope/regression = clean**, verb-validity = issues, diet/integration = issues. QE gate: **PASS_WITH_ISSUES, `proceed=true`, 0 blockers** (`qa-report.json`).

The adversarial pass earned its keep — it caught two real issues the green test suites missed, both now FIXED:

- **HIGH — live-render gap (FIXED in `3ac39ca`).** `useCityPlan` memoized on `citySignature(places, citySeed, neighborhoods)` and deliberately excluded `city_graph` (a correct EM-239 perf choice when the graph was *constant*). In S2 the graph *mutates*, so a built road never re-rendered live — only on reload — defeating S2's whole point ("watch streets grow"). Fix: fold the graph's node/edge **counts** (primitives) into the signature + memo deps — recomputes exactly when a road is built, stable across idle polls (no instance-buffer churn). Regression test added (grown graph churns; idle poll doesn't).
- **MEDIUM — dead config knob (FIXED in `3ac39ca`).** `max_city_blocks` was parsed but never read (the envelope is the `citygraph` constants). Removed the misleading param; documented the constants as the single source of truth (keeps backend bounds + frontend clip in lockstep — the determinism lens noted hardcoded constants are *safer* than a param that could diverge between the two sides).

**Determinism (EM-155) — proven in its strongest form.** The grown graph is a pure function of `(seed, ordered build_road actions)`; it round-trips through `to_snapshot`/`from_snapshot` byte-identical and is never re-applied on restore; `apply_build_road` and `build_nearby_layout` are pure (no RNG/clock/mutable state); the frontend envelope change is graph-branch-only with the fallback held at 5×5, so the EM-239 byte-identical golden gate still passes.

## Deviations from the plan (recorded, all sound)
- The plan's prose said the east-extension anchor "turns into a tee"; for the exact ids it actually becomes a 4-way **cross** — the test asserts the *true* classification.
- The plan's frontend snippet had a buggy `computeCityPlan({ ...TOWN })` call idiom (spread the places array into the world object); the agent mirrored the real EM-239 call instead.
- The plan assumed "no frontend code" — false: roads grown past index 12 were clipped; the minimal 9×9-envelope fix was made (the spec's "if a gap surfaces, fix it" clause).
- The golden fixture `em161_protagonist_prompt_pre_diet.txt` was regenerated — **purely additive** (+4 lines: the `NEARBY LAYOUT` block + the `build_road` menu line; zero removals/reword), verified by diff.

## Render / reality gate
This is backend logic + a graph-derived render that now reacts live. No new imagery/styling, so `nano-banana`/`design-token-guard`/`render-sanity`/`ux-review` are N/A as change gates (recorded in `MISSION_SKILLS.md`). The **acceptance eyeball** — an agent actually building a road and it appearing live in the 3-D city + the feed — is the live-walk, offered to the user (held until their say-so, along with the merge).

## Follow-ups recorded (non-blocking, deferred)
1. **Camera framing for grown cities** — `plan.extent` / `WORLD_REACH` are fixed to the 5×5; a large grown city may exceed the frame. Inert today (extent is an unused computed field); belongs to S3+ when cities routinely grow.
2. **Categorize the builder-event family in the feed** — `road_built` (like its siblings `building_demolished`/`place_prop`) isn't in `EventKind`/`CATEGORIES`, so it shows in the *default* feed view but is hidden under active category filters. Best fixed as a family (not a one-off road_built special-case).
3. **Multi-action schema direction constraint** — the `if/then` arg clause only covers single-action turns; a multi-action `build_road` with a bad direction isn't schema-rejected at parse (the runtime still rejects it cleanly with a `_fail_event`). Defense-in-depth, low priority.
4. **In-turn perception staleness** — a 2nd `build_road` in one multi-action turn re-anchors on the mutated graph (deterministic; clear `_fail_event` if blocked).

## Definition of Done
- [x] Implementation (Workflow) — backend chain (Tasks 1–4,6) ∥ frontend (Task 5), TDD
- [x] Wave gate green, 0 regressions (1638 / 564 / tsc 0)
- [x] Adversarial verify (4 lenses) + QE gate PASS (`proceed=true`); HIGH + MEDIUM findings FIXED + re-verified
- [x] Determinism (EM-155) independently proven; golden fixture additive-only
- [x] Mission skill manifest closed (`MISSION_SKILLS.md`); end-state report (this file)
- [ ] Live-walk acceptance eyeball + merge — held for the user
