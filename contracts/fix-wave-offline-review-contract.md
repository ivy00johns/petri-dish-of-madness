# Fix-wave contract — offline-window review remediation (v1.0)

Source: deep review of PRs #49–#69 (workflow `wf_d2408257-d5a`, 2026-07-01).
Scope: the 7 CONFIRMED findings + 2 test-hygiene items. Branch: `fix/offline-review-wave`.
Verified findings still arriving from the resumed verify pass are OUT of this wave (follow-up).

## Global constraints (all lanes)

- **EM-155 is law.** Replay is event-sourced: these fixes change *future* behavior, never
  the interpretation of recorded events. New/changed state must serialize additively.
  If the em161 golden prompt fixture changes because the Nearby-layout perception line is
  now correct, regenerating it is EXPECTED — do it deliberately and say so in your report.
- **TDD:** every fix lands with a regression test that FAILS before the fix (run it pre-fix
  to prove it). Never weaken/delete an assertion to get green.
- Toolchain: `.venv/bin/python -m pytest` (never bare `python`), `/usr/local/bin/npx`,
  `tsc -b --force` (never `--noEmit`).
- **NEVER `git add -A` / `git add .`** — `docs/superpowers/specs/2026-06-30-agent-invented-ideologies-design.md`
  is another session's untracked file and must stay out. The orchestrator does all commits.
- Do not touch files owned by another lane.

## Shared contract: the logical→world frame (Lane A introduces, others consume nothing)

Backend gains the conversion the frontend has had all along
(`web/src/components/world3d/worldSpace.ts`: `SIZE = 66`, `toWorldX(x) = (x/1000 − 0.5) * SIZE`):

```python
# backend/petridish/engine/citygraph.py
WORLD_SIZE: float = 66.0   # MUST equal web worldSpace.ts SIZE

def logical_to_world(x: float, y: float) -> tuple[float, float]:
    """Place logical coords (0..1000) → world (x, z). Mirrors web/worldSpace.ts."""
    return ((x / 1000.0 - 0.5) * WORLD_SIZE, (y / 1000.0 - 0.5) * WORLD_SIZE)
```

Pinned conversions (assert exactly in tests): `(500,500) → (0.0, 0.0)`;
`(106,894) → (-26.004, 26.004)`; `(0,1000) → (-33.0, 33.0)`.

---

## Lane A — backend city engine (owner: backend-agent A)

**Files:** `backend/petridish/engine/world.py`, `backend/petridish/engine/citygraph.py`,
`backend/petridish/agents/runtime.py`, `backend/tests/**`.

### A1 (HIGH) — coordinate-frame fix
Every backend `nearest_node` / face-centroid-distance call currently feeds logical
0..1000 place coords into the ±32.5 world-frame graph, so ALL places anchor to `n:12:12`.
- Call sites to fix via `logical_to_world`: `world.py:3489` (`action_build_road`),
  `runtime.py:993` (`build_nearby_layout`), `runtime.py:1027` (EM-265 nearby-zones centroid
  sort — px/pz must be world-frame).
- Fix the false comment at `world.py:3488` ("place.x/place.y are the world (x, z)").
- Tests: plaza (500,500) anchors to an interior node (assert NOT `n:12:12`); two places in
  different town quadrants anchor to DIFFERENT nodes; the pinned conversions above.
- **Rewrite the fixtures that embrace the bug:** `backend/tests/test_build_road.py` builds a
  single place at (500,500) and its docstring celebrates the corner anchoring — update to the
  corrected frame (roads must now grow near the town center, multiple agents at different
  places must get different anchors).

### A2 (HIGH) — zones perception decoupled from road-buildability
`runtime.py:996–999` early-returns `None` when no direction is `open`, killing the EM-265
zones block below it (zones go dark on geometric cities and interior nodes; `set_zone_rule`
un-bootstrappable).
- Restructure `build_nearby_layout`: road-extension sentence only when `openable` is
  non-empty; zones block (flag-gated) computed INDEPENDENTLY; return `None` only when both
  are absent. The road-build energy gate at the `runtime.py:2875` call site must gate only
  the road sentence, not zone perception.
- Tests (with `GRAPH_ZONES_ENABLED` monkeypatched True): pentagon-template city → zones block
  present with real face ids while no road sentence appears; classic-grid interior node
  (all 4 dirs road) → same; flag False → byte-identical to today's output (golden).

### A3 (HIGH) — `zone=` → `zone_id`
`runtime.py:1074` instructs `pass zone=<id> on propose_project`, but schema (`:253`) and
dispatch (`:6138`) read only `zone_id` — SC targeting can never fire.
- Fix the perception text to `zone_id=<id>`; ALSO alias `args["zone"] → args["zone_id"]`
  (when `zone_id` absent) at dispatch for robustness against replayed/old-styled emissions.
- Tests: dispatching `propose_project` with `zone=` places into the zone (alias works);
  perception text contains `zone_id=`.

### A4 (HIGH/MED) — zone rules reconciled after non-morph graph mutations
Reconcile only runs inside `step_master_plan_morph`; a passed `demolish_road` vote
(`world.py:4381`) or a face-reshaping `action_build_road` (`world.py:3494`) silently
orphans ratified rules (no `zone_rule_dropped` event, orphan persisted forever).
- Extract the morph path's keep/re-point/drop into `_reconcile_zone_rules(pre_centroids, reason)`;
  capture pre-mutation centroids ONLY when `zone_rules` is non-empty (perf); call it after both
  non-morph mutation sites. Event text must attribute honestly ("after a road change", not
  "after the master plan").
- Tests: rule on face A + demolish shared edge → rule re-pointed to the merged face (centroid
  match) or dropped WITH a `zone_rule_dropped` event; build_road splitting a ruled face behaves
  per the same policy; morph path behavior unchanged (existing tests stay green).

### A5 (MED) — honest geometric-city build_road failure
`apply_build_road` on `n:pent:*`-style ids fails with "the anchor node id is malformed".
- When `_parse_node` fails on an otherwise-real node id, return
  `(False, "this city's road plan has no lattice grid to extend", None)`. No snapping (out of
  scope). Note the EM-243↔EM-245/246 exclusivity in the module docstring.
- Test: pentagon graph → that exact reason; menu suppression (existing behavior) untouched.

---

## Lane B — image provider chain (owner: backend-agent B)

**Files:** `backend/petridish/imagegen/provider.py`, its tests.

### B1 (HIGH, billing) — free-first chain order
`build_provider()` currently chains FreeLLMAPI → **Gemini (paid)** → Cloudflare → Pollinations.
House law: paid Gemini is the LAST backstop; cost is cut via ordering.
- New order: FreeLLMAPI → Pollinations → Cloudflare → Gemini. Pollinations stays
  always-present (keyless); update the factory docstring (it currently promises
  "Pollinations is always the keyless final member" — now it's "always present, ahead of
  paid backstops").
- Tests: with all env keys set, assert chain type order exactly
  `[Freellmapi, Pollinations, Cloudflare, Gemini]`; with no keys, bare `PollinationsProvider`
  (unchanged single-member behavior).

---

## Lane C — frontend render signatures + test hygiene (owner: frontend-agent)

**Files:** `web/src/components/world3d/CityScape.tsx`, `web/src/components/world3d/RoadMesh.tsx`,
`web/src/components/world3d/CityScape.test.tsx`, related test files.

### C1 (HIGH) — content-keyed graph signatures (4th recurrence of the content-key class)
`citySignature` (`CityScape.tsx:312`) and RoadMesh's `graphSig` (`RoadMesh.tsx:~178`) fold
node/edge COUNTS only → equal-count mutations (demolish+build within one poll, balanced morph
ticks) render stale — on the DEFAULT renderer since #65.
- Replace the count fold with a content key: sorted edge ids joined (+ node count +
  car_policy + the existing rules hash). Keep it cheap (string join at ≤ a few hundred edges,
  computed per snapshot poll, never serialized). Keep `citySignature` arity/shape guards
  (EM-243 tests) intact.
- Tests (fails-pre-fix): two graphs with equal counts but different edges → different
  signature in BOTH files; flag-off render path byte-identical.

### C2 (test hygiene) — retire the 3 stale flag assertions
`CityScape.test.tsx` has 3 failures on main asserting `ROAD_MESH_ENABLED === false`; PR #65
flipped the default true. Update the 3 tests to assert the CURRENT contract (mesh default,
tile path reachable as fallback). Also fix the contradictory 10-line docstring above
`export const ROAD_MESH_ENABLED = true` (`CityScape.tsx:~659`) — it still says
"Default **false**".
- Gate: full `world3d` suite green afterward (no other assertions weakened).

---

## Wave gate (orchestrator runs, all lanes must pass integrated)

1. `.venv/bin/python -m pytest backend/tests -q` — 0 failures.
2. `cd web && /usr/local/bin/npx tsc -b --force` — clean.
3. `cd web && /usr/local/bin/npx vitest run src/components/world3d src/inspector` — 0 failures
   (the 3 pre-existing stale-flag failures must be GONE via C2, not skipped).
4. Byte-identical spot-check: with all dormant flags at defaults, the em161 golden +
   cityLayout golden tests pass (regenerations declared, never silent).

## Report contract (each lane returns)

`{ lane, items: [{id, status: fixed|blocked, files_touched, tests_added, fails_pre_fix_proven: bool, notes}], suite_results }`
