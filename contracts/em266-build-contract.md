# EM-266 (SC) — Zone-Targeted Emergent Building · Build Contract

> **Spec:** `docs/superpowers/specs/2026-06-29-agent-building-layout-sC-emergent-build-design.md`
> **Depends on:** SA (EM-264, merged — `BuildZone`/`planarFaces`, `assignBuildingLots`),
> SB (EM-265, merged — `ZoneRule` + `zone_rules` on the graph, `zone_id_for`/`planar_faces`,
> `GRAPH_ZONES_ENABLED`, the `nearby_zones` perception that already surfaces the raw `zone_id`
> + built-count + cap).
> **Branch:** `build/em266-emergent-build`. **The payoff slice.**

## 0. The law (non-negotiable acceptance bar)

1. **The build ALWAYS succeeds — honor / ignore / break (pillars 3+4).** Targeting a
   zone never blocks or alters a build. Building a wrong-kind structure in a zone,
   building past `density_cap`, or piling into the pentagon **core** — ALL succeed.
   Defiance is a **finding, not a bug**. SC records; it NEVER enforces or penalizes.
2. **"Build nothing" stays valid.** A zone may sit empty the whole run.
3. **Byte-identical / additive (EM-155).** `Building.zone_id` is additive, serialized
   ONLY when set (absent ⇒ `None` ⇒ pre-SC snapshots byte-identical). With no `zone_id`
   on a build, OR with `GRAPH_ZONES_ENABLED` (backend) / `GRAPH_LOTS_ENABLED` (frontend)
   off, behavior is byte-identical to today. All goldens pass unchanged.
4. **Deterministic (EM-155).** `zone_id` is data on the build event; replay/fork
   re-applies it. Placement is a pure function of (plan, buildings, zones). No
   clock/random; the `zone_violation` record (if emitted) is deterministic.
5. **No new standing LLM calls / no new geometry / no new assets / no road changes.**
   Choosing a zone is a field on the EXISTING build turn.

## 1. File ownership (strict)

| Lane | Owns (modify/create) | May read |
|---|---|---|
| **1 — backend** | `backend/petridish/engine/world.py` (MODIFY), `backend/petridish/agents/runtime.py` (MODIFY), `backend/tests/test_zone_targeted_build.py` (CREATE) | everything |
| **2 — frontend** | `web/src/components/world3d/cityLayout.ts` (MODIFY), `web/src/components/world3d/CozyWorld.tsx` (MODIFY), `web/src/types/index.ts` (MODIFY), the matching `*.test.ts(x)` (MODIFY/CREATE) | the wire shape below |
| **QE** | `coordination/em266-qa-report.json` (CREATE) | everything; runs tests; edits no source |

Lanes are independent (backend attaches `zone_id`; frontend consumes it) — both build
against the wire shape in §2 and run in parallel.

## 2. The wire shape — `Building.zone_id`

```python
# backend — engine/world.py, the Building dataclass (additive):
#   zone_id: str | None = None
#   to_dict(): include "zone_id" ONLY when set (like commemorates/skin) -> byte-identical
#   from_snapshot(): zone_id = d.get("zone_id")   (absent ⇒ None)
```
```ts
// frontend — types/index.ts, the Building type (additive):
//   zone_id?: string | null;
```
`zone_id` is a zone's SB/SA id (`"|".join(sorted(boundary_node_ids))`). Absent ⇒ today's
auto-placement (by `location` place). The value is loose: an unresolvable id falls back to
auto-placement — never a wasted turn, never a crash (chaos-loose, mirrors `propose_project`'s
unknown-`place` fallback at world.py:~4727).

## 3. Lane 1 — backend (build gains a zone target + records defiance)

**`world.py action_propose_project`** (~4676, where the `Building` is created ~4732):
- Add an optional `zone_id` param (dispatched from the agent args by Lane 1's runtime change).
- **Gate on `GRAPH_ZONES_ENABLED`** (runtime.py const, imported): when off, ignore `zone_id`
  entirely ⇒ byte-identical. When on: if `zone_id` resolves to a **current** face
  (`zone_id in {zone_id_for(f.boundary) for f in planar_faces(self.city_graph)}`), store it on
  the `Building`; else drop it (auto-placement fallback — the build still succeeds).
- **The build proceeds UNCONDITIONALLY** regardless of the zone's rule. No cap enforcement,
  no kind coercion, no block.
- **`zone_violation` (observation only, §5 of the spec):** when a stored-`zone_id` build's
  `kind` ≠ the zone's `ZoneRule.hint`, OR the zone's built-count (buildings whose `zone_id`
  equals this zone) **exceeds** its `density_cap`, park a `zone_violation` event
  `{zone_id, building_id, kind, rule_hint, over_cap: bool, tick}` (same outbox pattern as
  `zone_rule_set`). NO penalty, NO block. An honored build emits nothing. Only emit under
  `GRAPH_ZONES_ENABLED` (keeps the event stream byte-identical when dormant).

**`runtime.py`:**
- Thread `zone_id` from the `propose_project` agent args through to
  `world.action_propose_project` (the dispatch at ~6120). Accept an optional `args.zone_id`
  in the `propose_project` schema/gate; an absent/loose id is fine (no rejection — the build
  is free).
- Extend the SB `nearby_zones` perception framing (only under `GRAPH_ZONES_ENABLED`): make
  explicit that an agent MAY target one of these zones when it builds (e.g. "build here with
  zone=<id>"). Reuse SB's existing per-zone line (name + raw `zone_id` + hint + `~N lots` +
  `cap C — B built`) — add NO new per-zone lines beyond SB's (prompt-diet). Absent when the
  district has no faces.

## 4. Lane 2 — frontend (place into the targeted zone; show the mess honestly)

**`cityLayout.ts assignBuildingLots`** (~1047; today `(plan, buildings, placeCenters)`):
- Buildings gain an optional `zone_id`. Give `assignBuildingLots` access to the plan's
  `zones` (`Pick<CityPlan, 'realLots' | 'landmarks' | 'blockLots' | 'zones'>` — `zones` is
  the SA-optional field, present only on the graph-lots path).
- For a building whose `zone_id` matches a `zone.id` (only when `plan.zones` exists):
  place it in THAT zone's `suggestedLots`, claiming lots in order and **overflowing** past
  them via the existing `slotLayout` ring around the zone centroid when the zone is over-cap
  (SA already allows overflow) — a violated cap you can SEE, buildings not refused.
- **Wrong-type buildings render with their own kind** (no coercion). Choked core → a dense
  pile at the centroid — the headline emergent picture.
- Buildings with no `zone_id`, or when `plan.zones` is absent (flag off / no graph), use the
  EXISTING place-based path UNCHANGED — byte-identical. Keep the round-robin + `slotLayout`
  ring fallback intact.

**`CozyWorld.tsx`** (~524): include each building's `zone_id` in the `list` passed to
`assignBuildingLots` (today `{id, location}` → `{id, location, zone_id}`).

**`types/index.ts`:** `Building` gains `zone_id?: string | null` (additive).

**Optional (defer unless cheap):** a violations count in the AWI/feed. Spec §5 marks it
optional / off if it risks budget — **defer** to a follow-up; SC's behavior does not depend
on it.

## 5. Toolchain (project memory)
Backend `.venv/bin/python -m pytest backend/tests/...` ; frontend `cd web &&
/usr/local/bin/npx vitest run …` + `tsc -b --force` ; use `/usr/local/bin/...`.

## 6. Testing & gate sequence

**Lane 1 (`test_zone_targeted_build.py`):** with `GRAPH_ZONES_ENABLED` on — a build naming a
valid `zone_id` stores it on the Building; honor (kind==hint, under cap) emits NO violation;
break (kind≠hint) emits `zone_violation`; over-cap build emits `zone_violation{over_cap:true}`
AND still succeeds; choke-the-core (many builds into one zone) all succeed, no crash;
unresolvable `zone_id` → auto-placement fallback, build succeeds; "build nothing" valid.
Flag OFF ⇒ `zone_id` ignored, no violation events, byte-identical. `Building.zone_id`
serialized only when set; snapshot/replay/fork round-trips; pre-SC snapshot (no key) loads
unchanged. Determinism: fixed action sequence ⇒ byte-identical placement/events.

**Lane 2 (frontend tests):** a building with a `zone_id` lands in that zone's lots; over-cap
zone overflows (ring) without crashing or dropping a building; wrong-kind renders its own
kind; empty zone renders empty; no-`zone_id` / no-`zones` path byte-identical (existing
`assignBuildingLots` goldens unchanged); determinism (same inputs ⇒ same spots, input-order
independent).

**Gate sequence:** Lane 1 ‖ Lane 2 self-verify → **wave gate** (lead: full `pytest` +
`tsc -b --force` + `vitest`, goldens unchanged) → **adversarial verify** (QE + lenses:
byte-identical/replay, build-always-succeeds (honor/ignore/break + choke-core, no
enforcement leak), over-cap overflow render, `zone_violation` correctness + determinism,
flag-off dormancy) → **QA gate** (`coordination/em266-qa-report.json`, `proceed=true`, no
CRITICAL, contract ≥3, security ≥3). Ships dormant behind the SA+SB flags — no new user gate.
