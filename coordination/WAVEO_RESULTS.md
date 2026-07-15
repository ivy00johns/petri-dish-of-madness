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

## Progress log

- **EM-253 culture lifecycle — SHIPPED.** `action_create_meme` (idea meme, virality 1) + `action_adopt_meme` (join carriers, virality++, image-meme adopt mints a drifted child image via free `_mint_gallery_image` → the marquee "meme mutates as it spreads"). `action_create_image` extended to auto-register a `kind="image"` meme when comm+meme_images on (payload gains `meme_id` only-when-minted → byte-identical golden). `diffuse_culture` extended: virality on infection + once-only `meme_dominant` latch at `dominance_threshold` carriers (new snapshot-safe store `self.dominant_meme_ids`) + `recompute_culture_camps()` (thin `_recompute_groups` caller, kind="culture_camp", shared-meme edge). world.py +207, runtime.py +53; new `test_em253_lifecycle.py` (24) + `test_em253_schema.py` (9). Suite 2551 passed / 1 skipped.
- **EM-252 diffuse_culture round boundary — SHIPPED.** `diffuse_culture()` inserted at its reserved slot in `_apply_round_start` (recompute_factions → **diffuse_culture** → advance_war → age_agents; recompute_congregations slot still reserved for EM-262). Three mechanics: seeded co-located passive diffusion (drifted child meme per infection, `_seed_int % 100 < diffusion_chance*100`, capped `max_diffusions`) + half-life virality `//` decay + zero-carrier decay-prune (`meme_died`). Gated on comm.enabled → `[]` no-op. world.py +140; new `test_em252_diffusion.py` (15) incl. round-order invariant + flag-off golden + image-cost guard. Suite 2518 passed / 1 skipped.
- **EM-251 transmission verbs — SHIPPED.** `action_spread_rumor` (co-located, trust-positive, no crime; distorts one hop via `_distort_text`, mints a drifted child meme parent_id/generation+1, plants distorted belief) + `action_send_letter`/`deliver_letters` (no co-location gate — write to an absent agent; mailbox FIFO cap `letter_cap`; drained once at recipient's next-turn start). Wired into TOOL_REGISTRY/ACTION_SCHEMA/menu (comm-gated, mirrors war track)/dispatch. world.py +140, runtime.py +133; new tests `test_em251_schema.py` (9) + `test_em251_transmission.py` (19). Suite 2503 passed / 1 skipped.
</content>
