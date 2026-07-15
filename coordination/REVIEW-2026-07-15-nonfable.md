# Fresh-context review — all changes built without Fable (2026-07-15, overnight)

**Method:** 6 fresh-context finders over disjoint targets, one adversarial skeptic per finding
(ultracode workflow, 31 agents). **Result: 21 confirmed (1 critical / 8 major / 12 minor), 4 refuted.**
Full machine output: session workflow `nonfable-review` (wf_0b36e12b-1a1).

**Targets:** `build/multi-city-expansion` (unmerged branch, backend + frontend) · PR #92 Wave O
keystone + war (merged with no independent review) · PR #106 routing/chat bundle (live) ·
W31 zero-LLM feed features (#96/#97/#98/#99/#100) · W31 sim-surface features (#101/#102/#103/#104).

## Confirmed findings (fix pack dispatched same night)

### Multi-city branch (fixed on `build/multi-city-expansion`)
| # | Sev | Finding |
|---|-----|---------|
| C1 | **CRITICAL** | **All-agents-in-transit permanently freezes the sim** — tick only advances inside an executed turn, arrivals need tick to advance; all-in-transit ⇒ empty due set forever, tick pinned, round counter inflates ~2 Hz re-running round subsystems. **Reproduced live** (3 agents / 2 cities / 3× travel_to). Fix: deterministic tick fast-forward to the min arrival when due set empty + all travelers; bound round inflation. |
| C2 | major | Travel marker uses fixed 8-tick nominal window vs backend's 3..~23 real `travel_ticks` — long trips park the marker inside the home city (contract §3 violation), short trips teleport 62% down-route. Fix: mirror the backend distance formula. |
| C10 | minor | Join-on-build moves loose settlement membership without moving `home_settlement_id` (breaks the documented lock-step invariant). |
| C11 | minor | `shadow-radius={3}` is a no-op under PCFSoftShadowMap; commit comments claim it carries the softness (and still mention PCSS). Comments corrected, dead prop dropped. |
| C12 | minor | Arriving traveler pops in at its OLD city (stale animMap/posRef) and glides across the open map; camera-follow on a traveler tracks the stale spot. |

### Wave O — PR #92 (fixed on `fix/nonfable-review-pack`)
| # | Sev | Finding |
|---|-----|---------|
| C3 | major | `crime_status='belligerent'` suppresses the wanted flip + freezes notoriety decay — justice pipeline silently disabled for war-band members in the 40–59 band. |
| C4 | major | Permanent exile + faction-scoped 70% electorate mathematically wedges min-size factions (3 yes needed from 2 eligible); zombie peace proposal then blocks that war's peace forever via the duplicate guard. |
| C13 | minor | Clash-kill `agent_died`/inherited events wear the ATTACKER's profile color (same class as the fixed travel_arrived bug). |
| C14 | minor | `siege` is strictly cost-free (damage + enemy exhaustion, no cost/limit) — dominates the clash centerpiece. Conservative cost added. |

### Routing — PR #106 (fixed on `fix/nonfable-review-pack`)
| # | Sev | Finding |
|---|-----|---------|
| C5 | major | Dead model id `deepseek-ai/deepseek-v4-pro` (404; catalog id is `deepseek-v4-pro`) sits at priority 9 in the "probe-verified clean" bounce pool — burns an attempt per storm walk. |
| C15 | minor | The `*` sweep re-includes `command-a-2` — the exact truncator EM-324 was written to eliminate. |
| C16 | minor | Stale ops docs: lanes.yaml "48s worst case" (now 60s), test docstring claims the pre-EM-319 terminal. |

### W31 features (fixed on `fix/nonfable-review-pack`)
| # | Sev | Finding |
|---|-----|---------|
| C6 | major | **DramaWire runs 3× full 50k-event scans on every update with the flag OFF** (compute-then-gate; mounted unconditionally) — recurring main-thread work against the R3F canvas on the default build. |
| C7 | major | `/api/fingerprints` re-reads the ENTIRE run event log + recomputes all series each 4s poll, synchronously on the sim's asyncio loop (blocks TickLoop + WS). Fix: (run_id, max_seq) delta cache + thread executor; same treatment for `/api/babel-matrix`. |
| C8 | major | Healing House: unvalidated `target_profiles` can swap a patient onto an unknown lane → router reassign fails at debug level, chip/snapshot lie, fork degrades the agent to mock (= silence). |
| C9 | major | Charters: configured `max_ambitions`/`creed_cap` ignored by the whole write path (module constants) but honored on restore — non-default caps break snapshot byte-stability (EM-155). |
| C17 | minor | Selected storyline snapshot captured at click time goes stale while the thread evolves (feed filter + tether use old principals). |
| C18 | minor | `BabelMatrix.tsx` contains literal NUL bytes — git treats the source as binary (unreviewable diffs, git-grep skips it). |
| C19 | minor | `_sample_indices` ZeroDivisionError at `max_series_points: 1` → every /api/fingerprints request 500s. |
| C20 | minor | `fingerprint_ticker: true` (non-dict config) crashes `load_config` → sim fails to boot over viewer-only chrome. |
| C21 | minor | TwinLens dual-strand rows misalign twins' answer indexes once stream lengths drift — the marquee comparison quietly lies. |

**Plus (ledger directive, not a finding):** EM-318 feed-silence REMOVED from EventFeed.tsx
(fix-don't-hide; EM-324 fixed the root; lanes.yaml rationale reworded to match).

## Refuted (verified non-issues)
- `GRAPH_ZONES_ENABLED` compile-time flip — pre-approved Wave-P sign-off riding the organic-world commit, not stealth multi-city work.
- `held_meme_cap` clamp asymmetry — claimed truncation can't occur.
- Feed-silence "swallows actionable errors" — real behavior but already tracked as the EM-318 removal above.
- Chimera twin uuid4 ids — the seeded-ID requirement doesn't govern that spawn path (explicit code contract).

## Review verdicts on what was checked and held
- Multi-city: settlements-OFF byte-identity, genesis seeding init+reset, scheduler exclusion across all
  paths, prompt flatness (Voronoi place partition), reset re-seed/re-home (9843330) — all clean. The QA
  report's open travel_arrived color issue was already fixed by 4848f63 (report stale, not wrong).
- Wave O #92: extractions byte-identical for flag-off worlds; seeded ids everywhere; only-when-non-default
  serialization + defensive restores; round order as specced; 52 PR tests pass locally.
- Routing #106: EM-324 detour bounded; demerits attribute to serving lane; reserved terminal `auto`
  survived EM-319; all changed pins resolve against the live catalog (1-token probes); max_tokens 1024
  with #77 out_hint clamp intact; EM-322 state off the snapshot surface.
- W31: nothing writes events/snapshot keys when OFF (fingerprint WorldParams field enters config_json but
  the resume guard ignores it); .venv symlink already untracked; TICK tell untouched; hysteresis/rate caps
  correctly bound feed spam; 51 new determinism/feature tests pass.
