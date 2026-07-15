# Wave O — Culture + Religion build results

Branch: `build/wave-o-culture-religion` (worktree `/Users/johns/Projects/petri-dish-waveo`).
Builds on PR #108 (2026-07-15 fix pack) + PR #92 (EM-250 keystone / War track). Merge AFTER #108.

Baseline before build: **2475 passed, 1 skipped** (full backend suite, 65s).

Substrate ridden (all merged EM-250 keystone, verified present):
- `Meme` dataclass + `mint_meme`/`_attach_meme`/`_distort_text` (world.py 311, 9189/9219/9268)
- `_plant_belief` (world.py 2713), `_recompute_groups`/`_edge_components`/`GROUP_KIND_LABELS` (world.py 8987/9040/9046)
- stores `self.memes`/`self.culture_camps`/`self.town_motif_ref` (world.py 1676-1678); snapshot 10347; restore 11093
- `AgentState.held_memes`/`mailbox` (world.py 718/726) + coerce helpers (87/113) + serialize (889)
- `CommunicationParams` (loader.py 1056) + `_comm_param`/`_comm_enabled` (world.py 7491/7500)
- reserved round-start slots documented at world.py 2400 (recompute_factions → diffuse_culture → recompute_congregations → advance_war → age_agents)
- War verb wiring as prior-art mirror: TOOL_REGISTRY (runtime.py 553), menu gate (197/273), schema (380), dispatch (6620), governance gate (2244)

## Ship summary (2026-07-15 overnight)

**All 9 items shipped, 0 skipped/deferred.** Culture track EM-251–255 COMPLETE; Religion track EM-260–263 COMPLETE. One commit per item (9 commits, `337bd5e`→`5b659c0`), each gated green before the next.

**Final gates:**
- Backend: `.venv/bin/python -m pytest backend/tests/ -q` → **2704 passed, 1 skipped** (baseline was 2475/1 → +229 new tests across the wave).
- Typecheck: `cd web && /usr/local/bin/npx tsc -b --force` → **clean (exit 0)**.
- Frontend: `cd web && node node_modules/vitest/vitest.mjs run` → **1594 passed, 125 files** (baseline 1472 → +122).

**Both engines are behind default-OFF gates — the em161/em250/em256/em260 goldens stay byte-identical.** Every item shipped a flag-off golden test proving zero new events/menu/prompt/snapshot keys when disabled.

### How to flip live + the marquee to watch
Both blocks live in the run's `world.yaml` (config `world.comm` / `world.faith`):
```yaml
world:
  comm:
    enabled: true          # Culture: rumors, letters, memes, diffusion, camps, canonize/ban_gossip
    # diffusion_chance 0.20, dominance_threshold 6, camp_min_shared 2 … (tune in CommunicationParams)
  faith:
    enabled: true          # Religion: found_faith, proselytize, worship, congregations, schism, hostility
    conversion_chance: 0.3 # raise to see conversions faster; schism_threshold 50 / schism_grace 20 → LOWER both to force a visible schism
```
Config bakes per-run — **restart the sim to adopt** (do NOT `--reload`; see the dev-reload memory). Watch the feed + the new **Meme Lineage** and **Faith** panels (left column, beside the War panel) for:
- **A meme mutating as it spreads** — an agent paints an image (`create_image`), another `adopt_meme`s it and the drifted child repaints ("fox in a crown" → "fox in a paper crown"); the Meme Lineage panel shows the image family tree, ending in a `meme_dominant` 🦊 banner.
- **A rumor distorting per hop** — `spread_rumor`/passive `diffuse_culture` runs text through `_distort_text` ("borrowed" → "stole"); `meme_mutated` cards, generation climbs.
- **A faith founding + congregation + schism** — `found_faith` → `consecrate_faith` (70% vote anchors a temple) → `proselytize`/`worship` grow a `congregation` → after `schism_grace` rounds of divergence a child faith forks (`faith_schism`); `declare_hostility` feeds war grievance when war is also on.

### Notes / caveats for review
- Builds on **PR #108** (the 2026-07-15 fix pack) — merge this AFTER #108. Belligerence-derived-from-war_band and exiled-excluded-from-electorates idioms from the fix pack were respected (not the stale #92 idioms).
- `web/node_modules` in this worktree is a symlink to the main repo's (gitignored; the worktree lacked one). Not committed.
- New world stores added this wave (all serialize only-when-non-empty, restore-to-default): `dominant_meme_ids` (EM-253), `congregations` + `schism_pending` (EM-262). New config: `CommunicationParams` (pre-existing EM-250), `FaithParams` (EM-260) + `devotion_base`/`congregation_min_size`/`convert_trust_seed`/`hostility_grievance`. New design token `--faith-tint`.
- Round-start canonical chain is now fully live + tested: `recompute_factions → diffuse_culture → recompute_congregations → advance_war → age_agents`.
- Live visual sign-off is the USER's (ledger rows kept in-progress, not done).

## Progress log

- **EM-263 religion conflict + frontend — SHIPPED (Religion track COMPLETE).** Backend: `action_excommunicate` (founder-gated, no co-location, removes member + zeroes devotion + tears co_religionist web; `excommunicated`) + `action_declare_hostility` (founder-gated, sets `faith.hostile_to`; when war on, feeds `add_grievance` between the faiths' factions, `reason="faith_hostility"`, deterministic; `faith_hostility_declared`). +`FaithParams.hostility_grievance`. Frontend: `co_religionist` in RelationshipType, `Faith` interface + optional `Agent.faith_id/devotion` + `WorldState.faiths/congregations/schism_pending`, 15 religion EventKinds; new `FaithPanel.tsx` (faith badges ✞/☾, mean devotion, ⚔ hostility marker, congregation chips reusing camp chrome, schism/parent hint; null when faith-free) mounted beside MemeLineagePanel; new `--faith-tint` token; new 🕯 `faith` feed lane. world.py +162, runtime.py +117, loader.py +6, +frontend. New `test_em263_conflict.py` (24) + `test_em263_schema.py` (9) + `FaithPanel.test.tsx` (12) + `EventFeed.faith.test.tsx` (50). Backend 2704 passed / 1 skipped; tsc clean; vitest 1594 passed.
- **EM-262 religion emergence — SHIPPED.** `action_proselytize` (reflex, co-located, `_plant_belief` trust-positive, seeded resistance `_seed_int % 100 < conversion_chance`, converts faithless → joins members + devotion + mutual `co_religionist` edge; `proselytized`/`faith_joined`/`proselytize_resisted`). `action_worship` (reflex, clones action_work buff-at-place at `_faith_seat_here` → devotion buff + `worshipped`). `recompute_congregations()` inserted at its reserved round-start slot (**full canonical chain now live**: factions→diffuse_culture→congregations→war→age) — thin `_recompute_groups` caller (kind="congregation", cng_ ids) + per-round `devotion_decay`. Deterministic schism: `self.schism_pending` grace latch on the co_religionist graph → forks a child faith via `mint_faith(parent_id=...)` after `schism_grace` rounds (`faith_schism`). New stores `self.congregations`/`self.schism_pending`; +2 FaithParams (congregation_min_size, convert_trust_seed). world.py +375, runtime.py +74, loader.py +9; new `test_em262_emergence.py` (28) + `test_em262_schema.py` (12); round-order invariant extended in test_em252. Suite 2671 passed / 1 skipped.
- **EM-261 religion founding — SHIPPED.** `action_found_faith` (reflex: mints seeded faith + canonical `kind="faith"` Meme join, founder sole member, base devotion, `faith_founded`; rejects already-faithful). `consecrate_faith` 70% governance effect mirroring canonize_meme at all 7 sites but faith-gated (anchors faith to an operational temple via `faith.temple_id` + reused Building `commemorates`; blesses members with `temple_buff` devotion; `faith_consecrated`+`temple_consecrated`; vanished/no-temple no-op; per-faith dedup). Temple-as-seat: `_FAITH_SEAT_KINDS={temple}` + `_faith_seat_here()` + `_consecration_temple_for()` (deterministic pick, no hijack). New config `FaithParams.devotion_base`. world.py +172, runtime.py +70, loader.py +4; new `test_em261_founding.py` (22) + `test_em261_schema.py` (15). Suite 2631 passed / 1 skipped.
- **EM-260 religion plumbing — SHIPPED (Religion track begins).** `Faith` dataclass (seeded `fth_` id, INVENTED name/deity/tenets — denylist-tested against ~150 real religions, no verbs yet) in `self.faiths` + `mint_faith` seeded helper. `AgentState.faith_id`/`devotion` (serialize non-default, clamp 0..100). `co_religionist` added to RELATIONSHIP_TYPES (not declarable). New `FaithParams` config block (loader.py, `enabled` default OFF + temple_buff/conversion_chance/devotion_decay/schism_threshold/schism_grace) + `_faith_param`/`faith_enabled()`. Snapshot+restore for faiths + agent fields. world.py +225, loader.py +69; new `test_em260_schema.py` (21) + `test_em260_determinism.py` (4). Suite 2594 passed / 1 skipped. Flag-off golden byte-identical.
- **EM-255 culture frontend — SHIPPED (Culture track COMPLETE).** Pure frontend (data already rides `to_snapshot`→`world_state`). `Meme`/`CultureCamp` types + optional `Agent.held_memes`/`WorldState.memes|culture_camps|town_motif_ref|dominant_meme_ids` + 13 culture EventKinds. New `MemeLineagePanel.tsx` (the marquee: image family tree via parent_id/generation with gallery thumbnails; ⭐ dominant marker; faction-chrome camp chips; dominant-motif banner) mounted beside WarPanel in App.tsx. Feed: 13 kinds → icons/colors + new 🦊 `culture` lane. Token-only (color `var(--faction-tint)`; only tree-indent is dynamic). New `MemeLineagePanel.test.tsx` (17) + `EventFeed.culture.test.tsx` (43). tsc -b --force clean; vitest 1532 passed (123 files, +60). Culture-free golden: panel returns null. NOTE: `web/node_modules` symlinked to main repo's (gitignored) since worktree lacked it.
- **EM-254 culture governance — SHIPPED.** `canonize_meme` (town-wide 70% supermajority one-shot → sets `town_motif_ref` + `meme_canonized`; vanished-meme no-op; per-meme dedup) + `ban_gossip` (simple-majority agreement-gate cloning ban_stealing → blocks `spread_rumor` in world action + validator + menu). Zero new tally code — rides declare_war/trial 70% path + ban_stealing simple-majority path. world.py +92, runtime.py +74; `test_em251_schema.py` updated (spread_rumor gate now `ban_gossip`); new `test_em254_governance.py` (18). Suite 2569 passed / 1 skipped.
- **EM-253 culture lifecycle — SHIPPED.** `action_create_meme` (idea meme, virality 1) + `action_adopt_meme` (join carriers, virality++, image-meme adopt mints a drifted child image via free `_mint_gallery_image` → the marquee "meme mutates as it spreads"). `action_create_image` extended to auto-register a `kind="image"` meme when comm+meme_images on (payload gains `meme_id` only-when-minted → byte-identical golden). `diffuse_culture` extended: virality on infection + once-only `meme_dominant` latch at `dominance_threshold` carriers (new snapshot-safe store `self.dominant_meme_ids`) + `recompute_culture_camps()` (thin `_recompute_groups` caller, kind="culture_camp", shared-meme edge). world.py +207, runtime.py +53; new `test_em253_lifecycle.py` (24) + `test_em253_schema.py` (9). Suite 2551 passed / 1 skipped.
- **EM-252 diffuse_culture round boundary — SHIPPED.** `diffuse_culture()` inserted at its reserved slot in `_apply_round_start` (recompute_factions → **diffuse_culture** → advance_war → age_agents; recompute_congregations slot still reserved for EM-262). Three mechanics: seeded co-located passive diffusion (drifted child meme per infection, `_seed_int % 100 < diffusion_chance*100`, capped `max_diffusions`) + half-life virality `//` decay + zero-carrier decay-prune (`meme_died`). Gated on comm.enabled → `[]` no-op. world.py +140; new `test_em252_diffusion.py` (15) incl. round-order invariant + flag-off golden + image-cost guard. Suite 2518 passed / 1 skipped.
- **EM-251 transmission verbs — SHIPPED.** `action_spread_rumor` (co-located, trust-positive, no crime; distorts one hop via `_distort_text`, mints a drifted child meme parent_id/generation+1, plants distorted belief) + `action_send_letter`/`deliver_letters` (no co-location gate — write to an absent agent; mailbox FIFO cap `letter_cap`; drained once at recipient's next-turn start). Wired into TOOL_REGISTRY/ACTION_SCHEMA/menu (comm-gated, mirrors war track)/dispatch. world.py +140, runtime.py +133; new tests `test_em251_schema.py` (9) + `test_em251_transmission.py` (19). Suite 2503 passed / 1 skipped.
</content>
