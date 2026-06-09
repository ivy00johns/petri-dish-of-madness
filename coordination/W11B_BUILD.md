# W11b Build — "Sim texture" (EM-079–083, 087, 091, 092, 098, 100, 101, 103)

Branch: `build/w11a-ui-batch` (continues — W11a shipped on it; one PR will carry both).
Contract deltas (orchestrator, committed before spawn): event-log.md **v1.3.0** (new
kinds billboard_posted/reflection/commitment_made/commitment_lapsed/usage_alert; EM-100
readable rule text; EM-081 no-new-calls overhearing; EM-101 fork lineage; real blackout),
api.openapi.yaml **1.4.0** (POST /api/runs/fork, GET /api/personas, RunRow lineage),
events.schema.json (+5 kinds), frontend-inspector.md **v1.3.0** (§10).

Free-scale law for the whole wave: **no item may add a standing LLM call.** Billboard
posts, reflections, and commitments ride the same single turn response (EM-066 pattern);
overhearing is context-injection + reflex only.

## File ownership (strict)

| Agent | Owns | Forbidden |
|---|---|---|
| backend-engine | `backend/petridish/engine/**`, `backend/petridish/agents/**` (if present), `config/world.yaml` | api/, persistence/, providers/, web/**, contracts |
| backend-platform | `backend/petridish/api/**`, `backend/petridish/persistence/**`, `backend/petridish/providers/**`, `backend/petridish/config/**`, `config/personas.yaml` (new), `config/profiles.yaml` | engine/, web/**, contracts |
| frontend-agent | `web/src/**` (not package.json, not tests) | backend/**, contracts |
| qe-agent (wave 2) | tests, `web/package.json` (test-only), `coordination/qa-report.json` | src |
| docs-agent (wave 2) | `README.md` | everything else |
| orchestrator | contracts, coordination, ledger | implementation |

Cross-boundary seam (contracted, both sides build to it): **`World.from_snapshot(state:
dict, *, place_overrides: list|None) -> World`** implemented by backend-engine
(classmethod on World, engine/world.py); backend-platform's `/api/runs/fork` calls it.
Engine also exposes **`world.billboard`** (list of `{tick, actor_id, actor_type, text}`,
capped 20, serialized in to_snapshot/world_state) for the frontend.

## Wave 1 (parallel ×3)

**backend-engine — cognition + governance semantics + world texture:**
- EM-079: active commitments injected into the turn prompt (compact list with ages);
  commitments parsed from the same structured response (optional `commitment` field,
  EM-066 pattern) → `commitment_made`; talk-only claims that never become tool calls
  within N turns → `commitment_lapsed{reason:"phantom"}`. Make non-talk tools salient
  in the prompt (the audit's ZERO project events finding).
- EM-080: optional `reflection` field in the same response, requested in-prompt only
  when importance threshold trips (~2–3×/day); `reflection` events; reflections enter
  the memory buffer.
- EM-081: overheard speech → ≤2 co-located listeners' next-turn perceived context
  (`overheard:true`), reflex-only immediate reactions, hard cap per tick.
- EM-087+103: governance semantics — re-proposing an identical ACTIVE effect becomes a
  RENEWAL (extends/refreshes, never stacks; `rule_passed` payload gains
  `renewed:true`), and project proposals whose name matches an active/proposed rule
  get steered: tagged `commemorative:true` + linked `rule_id` (the charm stays,
  duplicates capped at one monument per rule).
- EM-100: rule_* feed `text` leads with rule text + effect, uuid only in payload.
- EM-091 (engine half): reflex tools `post_billboard`/`read_billboard` (location-gated
  to plaza/townhall; post text rides the same turn), `world.billboard` state + events.
- EM-098: `world.procgen {enabled:false, seed, n_places, kind_weights}` → seeded town
  layout using EXISTING kinds only (work/home/social/governance/wild) so the 3D scales
  with zero new art; **housing**: per-agent cottages (`kind:home`, named "X's cottage")
  and/or a capacity-limited communal bunkhouse; recharge wired to home kinds; place
  count gated for prompt size. Off by default — the hand-authored town stays.
- EM-083 (engine half): blackout random event gets a real effect (recharge disabled at
  affected places N ticks, structure_state_changed surfaces it).

**backend-platform — fork, personas, usage alerts:**
- EM-101: `runs.forked_from`/`forked_at_tick` (idempotent migration), POST
  /api/runs/fork per api 1.4.0 (replay(T) → World.from_snapshot → new run, paused,
  lineage stamped; 404/400 paths), RunRow surfaces lineage.
- EM-092: `config/personas.yaml` (author ~10 varied cards: name, archetype,
  personality, suggested_profile from the 8-profile roster), loader + GET
  /api/personas; POST /api/agents accepts optional `persona` name (prefilled
  server-side, explicit fields still win).
- EM-083 (platform half): usage tracker emits `usage_alert` once per
  provider/metric/window on crossing 70% of configured caps (caps configurable,
  sane defaults; zero alerts when no caps configured).
- God billboard reply surface: POST /api/billboard {text, in_reply_to?} → emits
  billboard_posted with actor_type god (add to api contract as a deviation note if
  shape differs).

**frontend-agent — §10 of frontend-inspector.md v1.3.0:** billboard (3D board at
plaza + feed idiom + panel + god reply input), persona picker in spawn form,
governance ×N grouping + renewed badge, usage-alert banner, min-width gate + a11y
pass, Run Browser FORK affordance + lineage chips. Token-only; mock mode keeps
working (mock generator may emit a few billboard/reflection events for §7's
representative-data rule).

## Wave 2: qe-agent (both suites + new coverage + qa-report) ∥ docs-agent (README:
billboard/personas/fork/procgen+housing blurbs; fix the Deploy "no persistent storage"
staleness with a data/ volume note).

## Gates

1. Wave-1 gate: pytest, tsc -b + vite build, token check on diff.
2. QA gate: qa-report proceed=true.
3. Live verification (Playwright): billboard post visible, persona spawn, duplicate-law
   renewal (mock), fork run 26 → new run with lineage, usage banner (forced), min-width
   gate, procgen smoke (enable on a scratch run).
4. Ledger/BUILD-PLAN/results closeout. No merge — branch only.

## Gate log

| Date | Gate | Result |
|---|---|---|
