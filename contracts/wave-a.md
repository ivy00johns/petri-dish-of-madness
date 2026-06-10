# Wave A — live-run correctness batch (contract v1.0)

> Build branch: `build/wave-a-live-run-fixes` · Date: 2026-06-10
> Items: EM-129, EM-132, EM-133, EM-134, EM-108 (backend-world) · EM-135 (backend-router)
> · EM-130, EM-131 (frontend) · EM-106 (infra)
> Source of truth for root causes: `docs/REMAINING-WORK.md` rows + run 102/126 diagnosis.

## Global rules (all agents)

- **Free-scale law:** no change may add a standing LLM call. Everything here is
  deterministic/reflex or moves an existing budget.
- **File ownership is exclusive** (see per-agent sections). If your fix seems to
  need a file you don't own, STOP and report a blocker instead of editing it.
- **No git commits.** The orchestrator commits after the wave gate.
- **Tests are part of the item.** Every EM lands with tests in YOUR test file;
  run your file plus the full backend suite (`cd backend && source
  ../.venv/bin/activate && python -m pytest -q`) or web suite (`cd web && npm
  run test`) before reporting done.
- Existing event/snapshot contracts (`contracts/events.schema.json`,
  `world-model.md`) are additive-only: new optional fields OK, no renames, no
  removals, no changes to existing `to_dict()` keys.

## Agent W — backend-world

Owns: `backend/petridish/engine/world.py`, NEW `backend/tests/test_wave_a_world.py`.

### EM-129 — humanize agent-built building names
In `action_propose_project` (~line 912): `name` arrives as model-authored text,
often `snake_case_identifier` (live: `prepare_beds`, `village_fair`).
- Derive a display name: replace `_`/`-` with spaces, collapse whitespace; if the
  result is all-lowercase identifier-ish, Title Case it; cap at 60 (existing cap).
- Empty / punctuation-only / single-character names → fallback `f"{agent.name}'s {kind}"`
  (kind humanized the same way; if kind also junk → `f"{agent.name}'s Project"`).
- `Building.name` stores the DISPLAY name. The raw arg is preserved in the
  returned event payload as `raw_name` (additive).
- Same humanization helper applied to `kind` for DISPLAY purposes is NOT done
  here — `kind` stays a raw key (frontend maps it, EM-130).

### EM-132 — build_step on a damaged building redirects to repair
In `action_build_step` (~line 1057, guard ~1082): when the target's status is
`damaged`, do NOT fail the turn — execute the existing repair semantics for that
building instead (reuse the repair code path; do not duplicate logic) and return
an event whose text makes the redirect legible (e.g. "...switched to repairing...").
Other invalid statuses (operational/destroyed/abandoned/offline) keep failing
with the current message.

### EM-133 — clamp contribute_funds at the remaining gap
In `action_contribute_funds` (~line 984): clamp `amount` to
`max(0, funds_required - funds_committed)`. Deduct ONLY the clamped amount from
the agent. If the gap is already 0 → fail softly with guidance ("already fully
funded — it needs build_step now"), costing nothing. Event payload carries
`amount_requested` and `amount_applied` (additive). funds_committed must never
exceed funds_required after this lands.

### EM-134 — animal-damage cooldown per building
In `animal_damage_building` (~line 1510): add an internal cooldown — a building
damaged by an animal within the last `ANIMAL_DAMAGE_COOLDOWN_TICKS = 6` ticks
(class constant on World, comment why) cannot lose health to an animal again;
the attempt resolves as a harmless no-state-change outcome whose feed text stays
in-character ("...gets shooed away from..."). Track via a non-contract field
(e.g. `Building.last_animal_damage_tick`, default sentinel, NOT added to
`to_dict()`). Human arson / non-animal damage paths are unaffected. Keep the
chaos: the FIRST hit always lands.

### EM-108 — governance location gate at resolution time
`action_propose_rule` (~line 692) and `action_vote` (~line 733) currently trust
the prompt. Mirror the billboard gate pattern (`billboard_here`, ~line 1304):
both actions fail at resolution unless the agent's location is a governance
place (the procgen invariant says the first governance place is ALWAYS id
`"townhall"`; gate on `kind == "governance"` of the agent's current place, not
on the hardcoded id). Failure message must guide: "civic actions happen at the
town hall — move there first". GOD-actor paths (if any call these) must remain
ungated — only `AgentState` actors are location-bound.

### Tests (minimum)
Name humanization (snake→Title, junk→fallback, raw_name in payload); redirect
build_step-on-damaged actually repairs + event text; clamp (overshoot clamped,
exact fit, zero gap soft-fail, never exceeds required); cooldown (hit, blocked
within 6 ticks, allowed after, first hit always lands); governance gate
(propose/vote fail away from townhall, succeed at townhall).

## Agent R — backend-router

Owns: `backend/petridish/providers/router.py`,
`backend/petridish/agents/runtime.py`, `backend/petridish/animals/runtime.py`,
NEW `backend/tests/test_lane_health.py`.

### EM-135 — reroute-aware lane health (first-attempt budget bump)
The proxy silently reroutes profiles to models that truncate (reasoning CoT
eats budget; mistral-medium cuts at 'stop' — runs 102/126). The retry boost
already rescues those turns; this item stops the FIRST attempt failing
repeatedly once a lane is known-bad.

Router additions (in-memory only, cleared by `clear_cache()`):
- Track per-PROFILE outcome window: deque of the last 6 parse outcomes,
  reported by the runtimes via `note_parse_outcome(profile_name, *, parsed:
  bool, truncated: bool)`. Also record the `routed_via` seen, for introspection.
- `first_attempt_max_tokens(profile_name, base: int) -> int`: when ≥2 of the
  window's outcomes are truncations, return the SAME boost formula the retry
  uses (`max(base * 4, 2048)`); otherwise `base`. Recovers automatically: 6
  consecutive clean outcomes flush the flag (deque does this naturally).
- `lane_health() -> dict` introspection (profile → {window, boosted,
  last_routed_via}) for a future UI; no API/event changes in this wave.

Runtime wiring (both `agents/runtime.py` `run_turn` and `animals/runtime.py`
`_decide_via_llm`):
- Attempt 1 budget = `router.first_attempt_max_tokens(profile, max_tokens)`
  via guarded `getattr` (duck-typed test routers don't implement it).
- After each parse attempt, report `note_parse_outcome(...)` (guarded). A
  successful parse of a REPAIRED truncation still reports `truncated=True`
  (the lane is still cutting output; salvage hides it from the feed, not from
  health tracking) — derive from `_looks_truncated` / existing meta.
- ZERO new LLM calls; only the attempt-1 cap moves, and only after evidence.

### Tests (minimum)
Boost engages after 2 truncations in window; disengages after clean runs; base
unchanged for healthy lanes; guarded getattr keeps duck-typed routers working
(existing test_json_mode routers must still pass untouched); end-to-end: a
runtime turn against a fake router records outcomes and gets the bumped
attempt-1 budget on the NEXT turn.

## Agent F — frontend

Owns: `web/src/components/world3d/worldSpace.ts`,
`web/src/components/world3d/CozyWorld.tsx`, may ADD pure-function modules +
tests under `web/src/components/world3d/`. Do not touch 2-D inspector files.

### EM-130 — unknown building kinds stop rendering as "Monument"
`buildingStyle()` (~worldSpace.ts:117) falls back to `BUILDING_STYLES.monument`.
- Add a NEUTRAL `building` fallback style (its own palette/shape config —
  generic structure, visually distinct from monument).
- Keyword-map common emergent kinds onto existing palettes before falling back:
  garden/farm/orchard/grove/bed(s)→garden|farm; market/stall/shop/booth/
  bazaar→workshop; hall/civic/center/fair/pavilion→clocktower; library/school/
  archive→library; house/home/inn/shelter/den→house; monument/statue/arch→
  monument. Case-insensitive substring match on the raw kind.
- The label subtitle must show the HUMANIZED kind (snake_case → Title Case),
  never the style's name — "Bram's Market Stall · Market Stall", not "· Monument".

### EM-131 — building placement overlap (render-side slots)
Buildings spawn at `agent.location`, so meshes pile onto the place anchor.
Fix entirely render-side (zero backend change):
- Deterministic slot layout: all buildings sharing a place are sorted by id and
  placed on offset slots around the place anchor (ring/grid; radius grows with
  count) so no two building meshes share a position, and none sits on the
  place's own mesh.
- Same world → same layout every frame/session (pure function of the building
  id list; no Math.random()).
- Label declutter: in dense clusters reuse/extend the EM-102 declutter approach
  so building labels don't stack unreadably at default zoom.

### Tests (minimum)
Vitest, pure functions: kind→style mapping table incl. fallback + live
offenders (`prepare_beds`, `village_fair`, `community`); humanized kind labels;
slot layout (distinct positions, deterministic, stable under reordering input,
no slot at the anchor itself). `npm run test` and `npm run build` must pass.

## Agent I — infra

Owns: `docker-compose.yml` (+ compose docs section of README.md if one exists).

### EM-106 — named volume for data/
The backend service must ship a named volume for its `data/` directory by
default so run history survives container recreation. Match the existing
compose file's style; document the volume name in the compose file comments.

## Report format (every agent)

Return JSON: `{agent, items: [{id, status: "done"|"blocked", summary,
files_touched, tests_added}], test_command, full_suite_pass: bool, blockers:
[], notes}` — `full_suite_pass` means YOUR stack's whole suite, not just your file.
