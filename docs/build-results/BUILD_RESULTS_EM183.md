# Build Results — EM-183 Town-Center Vote

> Branch `feat/town-center-vote` · shipped 2026-06-27 · standalone backlog item (not a wave).

## Headline

Agents can now **vote to move the town's civic heart**. A new `relocate_center`
governance proposal, ratified at a **70% supermajority** (the `demolish` bar), re-anchors
the town center on a place the agents choose — the "they grow the city as they see fit"
end-goal — and the **3-D world glides its orbit home** to that chosen heart.

## What shipped

**Backend (engine + runtime):**
- `World.town_center_id` — additive state, default `""` (the conventional plaza center).
  Serialized in `to_snapshot()` **only when set**, restored defensively in `from_snapshot`
  (a dangling id is tolerated and re-emitted verbatim) ⇒ an un-relocated world round-trips
  **byte-identically** (EM-155).
- `World.civic_center_id()` — pure resolver: voted center → `plaza` → first social → first
  place → `""`. The one place both the engine and the prompt agree on.
- `relocate_center` governance effect (R5, modelled on `demolish`): carries the target
  place id; validated at propose time (real place + no-op-to-current-center guard);
  per-target duplicate guard (two distinct "new heart" votes may be open at once); one-shot
  ACT (excluded from EM-087 renewal tagging); 70% supermajority in `_evaluate_rule`; on
  ratification sets `town_center_id`, parks a `center_relocated` event, and replenishes the
  proposer's influence (the EM-229 governance-win hook). A vanished target is a silent no-op.
- Runtime gate (`_validate_world`) + prompt menu (`propose_rule`, offered only when a
  non-center place exists) + the resolve path (the generic `target` arg already plumbs through).
- `center_relocated` added to `contracts/events.schema.json` `x-known-kinds`.

**Frontend (the 3-D payoff):**
- `resolveCivicCenterId(places, town_center_id)` in `worldSpace.ts` — mirrors the backend
  fallback chain exactly so the camera and the engine pick the same place.
- `CozyWorld` computes the orbit **home target** from the voted center; `CameraDirector`
  eases reset/recenter to it (framing preserved about the new home) and **glides home when
  the center changes** — the visible "the city re-centers" moment. Default (unset/plaza)
  resolves to the layout origin ⇒ framing is unchanged for an un-relocated world.
- `town_center_id` typed on the `WorldState`.

**Drive-by correctness fix:** EM-236 `amend_constitution` was missing from the runtime
gate's `valid_effects` — the exact **FINDING-1** bug class the code comments warn about
(the effect was un-proposable through the agent's only path; the EM-236 tests passed only by
calling `action_propose_rule` directly). Added it to the gate and pinned it with a regression
test driving a full agent turn.

## Verification

- **Backend** `pytest -q` → **1582 passed, 1 skipped** (+22): `tests/test_em183_town_center.py`
  covers propose/validate/ratify/reject, the event + influence side effects, per-target
  duplicate + no-renewal, vanished-target no-op, snapshot round-trip (byte-identical + dangling
  id), the prompt menu (present/omitted), the agent gate (incl. the amend_constitution fix),
  and a **full `run_turn` end-to-end** through the real gate → resolve → world path.
- **em161 golden + EM-155 snapshots** byte-identical (the protagonist isn't at a governance
  place, so the menu addition can't touch the golden; `town_center_id` serializes only-when-set).
- **Frontend** `tsc -b` clean + `vitest` → **1039 passed (89 files)** on node v22.22.3 (+6 in
  `worldSpace.test.ts` for `resolveCivicCenterId`).
- **Integration smoke** `run.py --ticks 300 --profile mock` → clean, all invariants PASS.

## Scope notes / deferred

- The **2-D minimap** stays plaza-anchored — re-centering it is a fixed-projection viewBox
  shift, deliberately out of scope (the 3-D world is the redesign focus).
- The `center_relocated` feed event renders with default styling, consistent with its peer
  governance/system events (`town_named`, `building_demolished`, `constitution_amended` — none
  carry a special feed icon).
- A live-LLM run to watch agents actually campaign for and pass a relocation is the natural
  next observation (the verb is deterministic + mock-smoke proven).
