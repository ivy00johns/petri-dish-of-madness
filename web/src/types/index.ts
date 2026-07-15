// ============================================================
// Domain types — match contracts/world-model.md and contracts/events.schema.json
// ============================================================

export type PlaceKind = 'work' | 'home' | 'social' | 'governance' | 'wild';

export interface Place {
  id: string;
  name: string;
  x: number;
  y: number;
  kind: PlaceKind;
  description: string;
  // Wave C (EM-147, additive): the district this place belongs to
  // (core/market/civic/residential/farm). Optional/null so pre-Wave-C
  // snapshots stay valid; townLayout falls back to coordinate clustering.
  district?: string | null;
  // EM-123 (additive): optional neighborhood/zone overrides. A place belongs to
  // the neighborhood `neighborhood_id ?? district`; `zone_kind` overrides the
  // derived zoning for one place inside a mixed district. Both optional/null so
  // pre-EM-123 snapshots stay valid — zone is derived from district then kind.
  neighborhood_id?: string | null;
  zone_kind?: string | null;
}

// EM-123: a zoned district that DEEPENS as megaprojects complete. The backend
// derives one per distinct `neighborhood_id ?? district` at tier 1; a completed
// collective building raises the tier (capped). The 3D city reads the tier (via
// the place's neighborhood) and adds deterministic street life — never filler
// buildings (EM-174). Serialized only once a tier diverges from the tier-1
// baseline, so a fresh world omits the key and the frontend re-derives it.
export interface Neighborhood {
  id: string;
  name: string;
  zone_kind: string;   // residential | market | civic | industrial | farm
  tier: number;        // 1 = founded baseline, grows on megaprojects
  progress: number;    // completed megaprojects toward the next tier
}

/** EM-239 (S1) — the authoritative road graph (mirrors backend
 *  engine/citygraph.py). S1 ships axis-aligned junctions only. */
export interface CityGraphNode {
  id: string;
  x: number;
  z: number;
  kind: 'junction'; // S3 widens to 'roundabout' | 'plaza' | 'dead_end'
}

export interface CityGraphEdge {
  id: string;
  a: string; // node id
  b: string; // node id
  road_class: 'street';
  // EM-244 (S3a): widened from the dormant S1 literal. 'inherit' defers to the
  // graph (city) policy; 'cars'/'pedestrian'/'mixed' override it for this edge.
  car_policy: 'inherit' | 'cars' | 'pedestrian' | 'mixed';
}

// EM-265 (SB): an agent-authored, advisory zone rule. A ratified
// `set_zone_rule` proposal attaches one rule to a bounded planar FACE (block)
// of the road graph, keyed by its zone id (`"|".join(sorted(boundary_node_ids))`
// — IDENTICAL formula both languages, law §0.2). ADVISORY ONLY in SB: a rule
// renders (tint + label) but enforces nothing (SC acts on it). Wire shape is
// snake_case to match the backend JSON byte-for-byte. One rule per zone (last
// ratified wins). `density_cap` is an absolute max-buildings hint; null = no cap.
export interface ZoneRule {
  zone_id: string;
  hint: 'residential' | 'market' | 'civic' | 'open';
  density_cap: number | null;
}

export interface CityGraph {
  version: number;
  seed: number;
  // EM-244 (S3a): the city-scope default. 'pedestrian' is the headline "ban
  // cars + all sidewalks" — every 'inherit' edge resolves to it.
  car_policy: 'cars' | 'pedestrian' | 'mixed';
  // EM-246 (S4): the run-start city profile kind (grid|greenfield|village; a
  // geometric kind like pentagon falls back to grid + records intent). READ-ONLY
  // METADATA — the renderer ignores it (the graph's nodes/edges drive the render,
  // so the default 'grid' path stays byte-identical). Optional/additive so
  // pre-EM-246 snapshots stay valid; absent ⇒ 'grid'.
  template?: string;
  nodes: CityGraphNode[];
  edges: CityGraphEdge[];
  // EM-265 (SB, additive): ratified zone rules. Serialized ONLY when non-empty
  // (the backend omits the key when []), so a pre-SB snapshot lacks it and
  // loads/renders byte-identical (law §0.1). Absent ⇒ no rules.
  zone_rules?: ZoneRule[];
}

// Wave E (EM-113, contracts/wave-e.md shared vocabulary): the relationship
// type vocabulary grows partner/family/mentor/feud. Open union — the chips /
// graph tolerate unknown future types (they fall back to the neutral register).
export type RelationshipType =
  | 'ally'
  | 'rival'
  | 'neutral'
  | 'friend'
  | 'enemy'
  | 'partner'
  | 'family'
  | 'mentor'
  | 'feud'
  // Wave O (EM-262/263, Religion) — the mutual conversion bond a proselytize seals
  // (and an excommunication tears). Engine-assigned; the chips/graph tolerate it
  // via the open union, falling back to the neutral register when unknown.
  | 'co_religionist'
  | (string & {});

// Wave D2 (EM-158): scheduler cadence tier. Protagonists act every round,
// supporting every 3rd, background every 10th (salience-gated, EM-159, with
// the EM-160 spontaneity floor). Open union — the feed/chips tolerate
// unknown future tiers.
export type CadenceTier = 'protagonist' | 'supporting' | 'background' | (string & {});

export interface Relationship {
  type: RelationshipType;
  trust: number;       // -100..100
  interactions: number;
}

export interface Agent {
  id: string;
  name: string;
  personality: string;
  profile: string;              // profile name
  profile_color?: string;       // hex color from profile
  location: string;             // place id
  energy: number;               // 0..100
  credits: number;
  mood: string;
  alive: boolean;
  zero_energy_turns: number;
  // W9 (EM-070) — turns left before death while energy is 0. Optional/null so a
  // pre-W9 backend (or mock mode) stays valid; the UI shows a death countdown
  // only when this is a number.
  turns_until_death?: number | null;
  // Wave D2 (EM-158/166, additive) — the agent's scheduler cadence tier.
  // Optional so pre-D2 backends/snapshots stay valid; absent ⇒ protagonist.
  cadence_tier?: CadenceTier | null;
  // Wave D2 (EM-160/166, additive) — consecutive zero-LLM reflex turns
  // (background tier only; resets on every LLM turn). Shown in the agent panel.
  reflex_streak?: number | null;
  beliefs: string[];
  relationships: Record<string, Relationship>;
  // Wave E (EM-120, additive) — derived reputation: round(mean incoming trust
  // over living agents with interactions ≥ 1). Optional so pre-E backends /
  // snapshots stay valid; the roster shows REP only when this is a number.
  reputation?: number | null;
  // Wave E (EM-114, additive) — parent agent ids (births only). Optional so
  // pre-E backends stay valid; absent ⇒ not a born child.
  parents?: string[] | null;
  // EM-310 (Chimera Twins, additive) — present ONLY on an agent that is half of
  // a deliberately linked twin pair (same persona/seed/start, different model).
  // The feed twin lens reads this to pair the strands + find the divergence.
  // Optional so pre-EM-310 backends/snapshots stay valid; absent ⇒ not a twin.
  twin?: TwinLink | null;
  // EM-109/110 (multi-city keystone, additive) — the agent's settlement + travel
  // state, mirroring the backend AgentState fields (contracts/settlement-travel.md
  // §1). Serialized only-when-non-default, so a settlements-OFF world's agent dicts
  // stay byte-identical and pre-multi-city snapshots/mock mode omit all three.
  //   • home_settlement_id — the settlement (world.settlements key) the agent lives
  //     in; null/absent ⇒ unsettled/primordial (no city yet).
  //   • in_transit_to — the target settlement id while TRAVELING (off-board, 0 LLM);
  //     null/absent ⇒ not traveling (rendered inside its city as usual).
  //   • transit_arrival_tick — the tick the agent arrives; null/absent when not
  //     traveling. Drives the in-transit route-marker progress in the 3D/2D views.
  home_settlement_id?: string | null;
  in_transit_to?: string | null;
  transit_arrival_tick?: number | null;
  // Wave O (EM-251–255, additive) — the meme ids this agent currently carries.
  // Serialized only-when-non-empty (Agent.to_dict); a culture-free agent — and
  // every pre-Wave-O snapshot — omits it ⇒ tolerate absent.
  held_memes?: string[];
  // Wave O (EM-260–263, Religion, additive) — the faith this agent keeps and
  // their devotion to it. faith_id serializes only-when-set, devotion only-when
  // > 0 (Agent.to_dict), so a faithless agent — and every pre-Religion snapshot —
  // omits both ⇒ tolerate absent/null. The FaithPanel joins members → agents to
  // aggregate a faith's devotion.
  faith_id?: string | null;
  devotion?: number;
}

// EM-310 — the twin link carried on each half of a Chimera pair. `of` is the
// peer twin's agent id, `group` the shared base name (Vesper), `model` this
// twin's profile.
export interface TwinLink {
  group: string;
  of: string;
  model: string;
}

// ============================================================
// Building (W7) — match contracts/world-model.md §W7. Buildings live in the
// world snapshot + event log (NO new SQL tables). A "project" is a Building in
// planned/under_construction — one entity, one lifecycle. Rendered in the 3D
// village by `status`. world_state gains `buildings: [Building]`.
// ============================================================

export type BuildingStatus =
  | 'planned'
  | 'under_construction'
  | 'operational'
  | 'damaged'
  | 'offline'
  | 'abandoned'
  | 'destroyed';

export type BuildingCondition = 'pristine' | 'worn' | 'damaged' | 'ruined';

export interface Building {
  id: string;
  name: string;
  kind: string;                 // clocktower|garden|workshop|farm|library|house|monument|...
  location: string;             // place id
  owner_id: string | null;      // agent id | "public" | null
  status: BuildingStatus;
  health: number;               // 0..100
  condition_label: BuildingCondition;
  progress: number;             // 0..100
  funds_committed: number;
  funds_required: number;
  contributors: string[];       // agent ids
  function: string;             // utility while operational, e.g. "+forage" | "+energy" | "voting"
  // Wave K (EM-220): an owner-set color skin. The renderer reads it as a material
  // override LAYERED OVER (not replacing) the health-soot tint. Optional/null so
  // pre-Wave-K backends and snapshots stay valid; an unknown skin name is ignored.
  skin?: string | null;
  // EM-266 (SC, additive): the zone the agent TARGETED this build at — a
  // BuildZone's SA/SB id (`"|".join(sorted(boundary_node_ids))`). Serialized ONLY
  // when set (absent ⇒ null ⇒ pre-SC snapshots byte-identical, law §0.3). On the
  // graph-lots path the 3D city places the building into THAT zone's suggested
  // lots (assignBuildingLots), overflowing the cap visibly rather than refusing
  // it; an unresolvable id, or the flag-off / no-graph path, falls back to
  // location-based auto-placement — never a wasted turn, never a crash.
  zone_id?: string | null;
  /** EM-268 (F1) — deterministic WORLD-frame placement (±32.5), set by the
   *  backend. Present only when free placement is active; absent ⇒ the frontend
   *  falls back to assignBuildingLots. Rendered directly (no logical conversion). */
  position?: [number, number];
  /** EM-299 (Wave Q) — an OPTIONAL parametric recipe authoring the building's
   *  SHAPE. Present ONLY when a model authored one AND the backend
   *  `building_recipes.enabled` flag is on (the backend is the sole authority —
   *  it serializes the recipe only then). The renderer derives a procedural mesh
   *  from it (computeBuildingMesh); absent ⇒ today's catalog/silhouette render,
   *  never a hole. Optional/null so pre-EM-299 backends + snapshots stay valid. */
  recipe?: BuildingRecipe | null;
}

// ── EM-299 (Wave Q) — parametric building recipe (closed-enum grammar) ────────
// Mirrors the backend value-dict (petridish.engine.building_recipe): 6 closed
// enums + a bounded `floors` int. The backend validates/coerces server-side, so
// a Building.recipe present in a snapshot is always grammar-valid; the frontend
// derivation (buildingRecipe.computeBuildingMesh) is defensive anyway.

export type Footprint = 'tiny' | 'small' | 'medium' | 'large' | 'grand';
export type Roof = 'flat' | 'shed' | 'gable' | 'hip' | 'dome' | 'spire';
export type BuildingMaterial =
  | 'wood' | 'timber_frame' | 'brick' | 'stone' | 'marble' | 'plaster' | 'mud_brick';
export type BuildingPalette =
  | 'warm' | 'cool' | 'earthy' | 'pastel' | 'vivid' | 'muted' | 'monochrome';
export type WindowDensity = 'none' | 'sparse' | 'regular' | 'dense';
export type Trim = 'none' | 'simple' | 'ornate' | 'gilded';

export interface BuildingRecipe {
  footprint: Footprint;
  floors: number;             // 1..8
  roof: Roof;
  material: BuildingMaterial;
  palette: BuildingPalette;
  window_density: WindowDensity;
  trim: Trim;
}

// ============================================================
// Animal (W8) — match contracts/world-model.md §W8. Animals are a DISTINCT
// entity type (actor_type:"animal"), NOT human agents: own persona, looser
// action set, slow cadence, own logging channel. They share the world
// mechanically (places, can damage buildings) but have NO credits account
// (invariant 7). They live in world.animals; world_state gains `animals: [Animal]`.
// Rendered as a roaming cat + dog in the 3D village (species-shaped, tinted).
// ============================================================

export type AnimalSpecies = 'cat' | 'dog' | 'squirrel' | 'raccoon' | 'goat' | 'fox' | 'crow';

export interface Animal {
  id: string;
  species: AnimalSpecies;
  name: string;
  location: string;             // place id
  energy: number;               // 0..100
  mood: string;                 // short free text
  alive: boolean;
  // Wave H4 (EM-209): the agent that adopted this animal, or null/absent when
  // unowned. An owned pet FOLLOWS its owner in the 3D village (Critter.tsx) and
  // wears a bond indicator in the RosterStrip. Optional so pre-H4 backends and
  // snapshots stay valid.
  owner_id?: string | null;
}

// ============================================================
// Prop (Wave K / EM-218) — a lightweight, agent-placed decoration the world
// REMEMBERS (so it persists/replays/forks and can be removed). Modeled on
// `Animal`, NOT `Building`: no health/funding/status/build-progress (Decision
// 1 in the Wave K design). Stored in world.props; world_state gains
// `props: [Prop]`. Each prop sits AT a place (no free-floating props), nudged
// by an engine-assigned in-place offset (dx,dz) so co-located props don't
// stack on the anchor. The 3D village renders each at placeToWorld(place) +
// (dx,dz) via PROP_MODELS, with a procedural fallback (never a hole).
// ============================================================

export interface Prop {
  id: string;                   // stable, seeded-hash id (NOT uuid4 — replay determinism)
  kind: string;                 // free text ≤30 — FE maps to a prop model/style
  place: string;                // place id it sits at
  dx: number;                   // in-place offset X (engine-assigned ring), world units
  dz: number;                   // in-place offset Z
  owner_id?: string | null;     // agent who placed it; null/absent for god/seeded
}

// ============================================================
// Settlement (EM-269 F2) — an agent-founded cluster seed for free placement
// (never a container that gates building). Lives in world.settlements keyed by
// an opaque seeded id; len > 1 IS emergent multi-city. `center` is already the
// WORLD frame (±33) — rendered directly, no logical conversion (the anti-EM-243
// discipline). Every field beyond name/center is optional so older backends and
// partial snapshots stay valid.
// ============================================================

export interface Settlement {
  name: string;                 // humanized display name (seeded pool fallback)
  center: [number, number];     // WORLD-frame [x, z] (±33) — no conversion
  founded_tick?: number;
  founder_id?: string;
  members?: string[];           // loose membership (agent ids)
}

export type RuleEffect = 'ban_stealing' | 'ubi' | 'recharge_subsidy' | 'work_bonus';
export type RuleStatus = 'proposed' | 'active' | 'rejected';

export interface Rule {
  id: string;
  effect: RuleEffect;
  text: string;
  proposer_id: string;
  status: RuleStatus;
  votes: Record<string, boolean>;
  created_tick: number;
}

// ============================================================
// Faction (Wave E / EM-120) — the mutual-trust circles the engine clusters
// each round (recompute_factions). Serialized into world_state ONLY when
// non-empty (a faction-free world omits the key), keyed by faction id. The
// live UI never rendered these directly before Wave O; the war panel reads
// them for belligerent names. Wave O (EM-256) adds the optional war_band /
// treasury_pledged keys, written only-when-set (absent ⇒ not at war), so a
// peacetime faction keeps the exact pre-war record shape.
// ============================================================

export interface Faction {
  name: string;
  founded_tick: number;
  members: string[];        // agent ids
  // EM-256 (additive): the mustered war band + pledged treasury. Present only
  // while the faction is at war; absent ⇒ peacetime.
  war_band?: string[];
  treasury_pledged?: number;
}

// ============================================================
// War (Wave O / EM-256–259) — a declared conflict between exactly two
// belligerent factions. Mirrors WarState.to_dict EXACTLY: the scalar core
// always rides; casualties/exhaustion ride ONLY when non-empty (a fresh war
// omits them). Serialized into world_state under `wars` only when the world
// has at least one war (a peaceful world omits the key ⇒ tolerate absent).
// ============================================================

export interface War {
  id: string;                          // seeded war_<8hex>
  belligerents: [string, string] | string[]; // exactly 2 faction ids, sorted
  aggressor_id: string;                // the declaring faction (one of belligerents)
  start_tick: number;
  aims: string;
  status: 'active' | 'settled' | (string & {});
  // Only-when-non-empty (WarState.to_dict): a fresh war omits both.
  casualties?: string[];               // agent ids fallen in this war
  exhaustion?: Record<string, number>; // faction id → 0..100 war-weariness
}

// ============================================================
// Culture (Wave O / EM-251–255) — the meme layer. A Meme is an idea the town
// SPREADS: authored by one agent, carried by many, and MUTATING across
// generations (a `parent_id` chain — "fox in a crown" drifting to "fox in a
// paper crown"). Mirrors the backend Meme.to_dict; serialized into world_state
// under `memes` ONLY when non-empty (a culture-free world — and every pre-Wave-O
// snapshot — omits it ⇒ tolerate absent). `kind` is an OPEN union: Religion
// (EM-260–263) adds 'faith' with no schema migration.
// ============================================================

export type MemeKind = 'rumor' | 'idea' | 'ideology' | 'image' | (string & {});

export interface Meme {
  id: string;
  kind: MemeKind;
  text: string;
  origin_agent_id: string;
  origin_tick: number;
  generation: number;         // 0 = a root meme; +1 for each mutation down a chain
  carriers: string[];         // agent ids currently holding it
  last_spread_tick: number;
  virality: number;           // spread pressure (drives the ⭐ / dominance sort)
  // Only-when-set (Meme.to_dict): an image meme carries the gallery `image_id`
  // it drifted from (join image_id → gallery entry's `url` for the thumbnail),
  // and a mutated meme carries its `parent_id` (the family-tree edge). A plain
  // text root meme omits both ⇒ tolerate absent.
  image_id?: string | null;
  parent_id?: string | null;
}

// ============================================================
// CultureCamp (Wave O / EM-251–255) — a belief circle the town clusters, the
// SAME record shape as a Faction (name/founded_tick/members) but keyed by a
// `cmp_`-prefixed id. Serialized into world_state under `culture_camps` ONLY
// when non-empty (like factions ⇒ tolerate absent). Rendered as faction-style
// chips in the culture (mint) register.
// ============================================================

export interface CultureCamp {
  name: string;
  founded_tick: number;
  members: string[];        // agent ids
}

// ============================================================
// Faith (Wave O / EM-260–263) — a shared creed with an INVENTED deity + tenets,
// founded by an agent and joined by devotees. Mirrors the backend Faith.to_dict:
// the scalar core (id/name/deity/founder_id/founded_tick/tenets) always rides;
// members/temple_id/meme_id/hostile_to/parent_id ride ONLY when non-default
// (a fresh faith omits them ⇒ tolerate absent). Serialized into world_state under
// `faiths` ONLY when the world has at least one faith (a religion-free world — and
// every pre-Religion snapshot — omits the key ⇒ absent means no religion). The
// FaithPanel + the feed's faith lane read it; the golden religion-free UI is
// unchanged.
// ============================================================

export interface Faith {
  id: string;                     // seeded fth_<8hex>
  name: string;                   // seeded INVENTED (never a real religion)
  deity: string;                  // seeded INVENTED (never a real deity)
  founder_id: string;
  founded_tick: number;
  tenets: string[];               // seeded INVENTED (never real scripture)
  // Only-when-non-default (Faith.to_dict): a fresh faith omits these.
  members?: string[];             // agent ids (the founder + converts)
  temple_id?: string | null;      // EM-261 consecrated-temple seat
  meme_id?: string | null;        // the Culture join: a kind="faith" meme
  hostile_to?: string[];          // EM-263 rival faith ids (⚔ marker)
  parent_id?: string | null;      // EM-262 schism lineage (the faith it split from)
}

export interface ModelProfile {
  name: string;
  adapter: string;
  model_id: string;
  color: string;
  available?: boolean;
}

// ============================================================
// Billboard (W11b EM-091) — the village notice board. The engine exposes
// `world.billboard` (capped at the 20 newest posts) in to_snapshot/world_state;
// god replies arrive with actor_type:"god". Optional so a pre-W11b backend
// (or an old snapshot) stays valid.
// ============================================================

export interface BillboardPost {
  tick: number;
  actor_id: string;
  actor_type: ActorType | string;
  text: string;
  // Wave I (EM-211, I2): a billboard post may carry an image — the RELATIVE
  // url of the gallery image being shared (`/assets/images/<id>.png`). Optional
  // so a pre-Wave-I post (or any non-image note) stays valid; the 3D notice
  // board threads it onto the paper-plane mesh when present (texture, else the
  // procedural PAPER fallback).
  image_ref?: string | null;
}

// ============================================================
// Gallery image (Wave I / EM-210) — an agent-generated artwork the world
// REMEMBERS. The bytes are an external side-artifact under /assets/images/;
// only these metadata strings flow through the sim (replay-safe, EM-155). The
// `url` is RELATIVE and derived from `image_id` — fed straight to drei
// useTexture (no host hardcoded). `promoted` flips true when a governance vote
// hangs it over the plaza (plaza_banner_ref). Rides the per-tick world_state
// snapshot (world.gallery), capped newest at the backend's max_gallery.
// ============================================================

export interface GalleryImage {
  image_id: string;
  prompt: string;
  proposer_id: string;
  created_tick: number;
  url: string;            // relative, e.g. /assets/images/<id>.png
  promoted: boolean;
}

// ============================================================
// Persona library (W11b EM-092) — GET /api/personas card shape
// (api.openapi.yaml v1.4.0). Picking one prefills the spawn form.
// ============================================================

export interface Persona {
  name: string;
  archetype: string;
  personality: string;
  suggested_profile: string;
}

// ============================================================
// WebSocket message types — match contracts/events.schema.json
// ============================================================

export interface WorldState {
  type: 'world_state';
  seq: number;
  tick: number;
  day: number;
  running: boolean;
  tick_interval_seconds: number;
  places: Place[];
  agents: Agent[];
  rules: Rule[];
  profiles: ModelProfile[];
  // W7: structures/projects rendered in the 3D village by `status`. Optional so
  // a W5/W6 backend (or a snapshot predating buildings) stays valid.
  buildings?: Building[];
  // W8: the roaming chaos critters (cat + dog). Optional so a pre-W8 backend (or
  // a snapshot predating animals) stays valid; the 3D village renders each one.
  animals?: Animal[];
  // Wave K (EM-218): agent/god-placed decorations the world tracks. Optional so
  // a pre-Wave-K backend (or a snapshot predating props) stays valid; the 3D
  // village renders each via PlacedProps with a procedural fallback.
  props?: Prop[];
  // W11b (EM-091): the notice-board posts, newest capped at 20. Optional so a
  // pre-W11b backend stays valid; the panel/3D board derive from history then.
  billboard?: BillboardPost[];
  // W15 (EM-155): deterministic seed for the generated city ring — the 3D city
  // renders as f(snapshot, city_seed). Optional/additive (pre-W15 backends and
  // snapshots lack it); consumers default with `city_seed ?? 1337`.
  city_seed?: number | null;
  // EM-239 (S1) — the authoritative road graph. When present the 3D city
  // renders FROM it; when absent (pre-S1 snapshots) the renderer falls back
  // to the hardcoded grid. Additive/optional — fallback discipline.
  city_graph?: CityGraph | null;
  // Wave I (EM-210/213): the image gallery (agent-generated art) and the id of
  // the image currently promoted over the plaza. Both optional/additive so a
  // pre-Wave-I backend (or a snapshot predating the atelier) stays valid; the
  // 3D notice board textures the newest gallery image and PlazaBanner resolves
  // `plaza_banner_ref` → its gallery url (procedural fallback when absent).
  gallery?: GalleryImage[];
  plaza_banner_ref?: string;
  // EM-298 (additive): agent-authored facade decals, {building_id -> gallery
  // image_id}. Optional so a pre-EM-298 backend (or a snapshot predating facades)
  // stays valid; the 3D world resolves each id → its gallery url and paints a
  // SurfaceDecal on that building (absent/unresolved ⇒ no facade rendered). Only
  // this metadata mapping rides the snapshot — the PNG stays off the replay surface.
  surface_decals?: Record<string, string>;
  // EM-123 (additive): zoned-district maturity. Present ONLY once a tier has
  // diverged from the tier-1 baseline (a fresh world omits it); when absent the
  // 3D city re-derives tier-1 neighborhoods from `places` and renders identically.
  neighborhoods?: Neighborhood[];
  // EM-188/192 (additive): the town's runtime-mutable name (agents vote to rename
  // it via a `town_named` event). Optional/null so mock mode and pre-naming
  // snapshots stay valid; the CityNameChip / ChronicleView render it only when a
  // non-empty string is present. Typed here so reads stop using a defensive cast.
  town_name?: string | null;
  // EM-183 (additive): the place id the town VOTED to be its civic heart (a
  // `relocate_center` proposal ratified at 70%). Empty/absent ⇒ the conventional
  // center (the "plaza", at the layout origin), so a town that never relocates is
  // unchanged. The 3D world re-anchors its orbit home target on this place.
  town_center_id?: string | null;
  // Wave E (EM-120, additive): the mutual-trust circles, keyed by faction id.
  // Serialized ONLY when non-empty (a faction-free world omits it), so absent ⇒
  // {}. Wave O reads these for belligerent names on the war panel.
  factions?: Record<string, Faction>;
  // Wave O (EM-256, additive): active + settling wars, keyed by war id, and the
  // directional grievance ledger keyed `"{srcFactionId}->{dstFactionId}"` → heat
  // (0..100). Both serialized ONLY when non-empty (a peaceful world — and every
  // pre-Wave-O snapshot — omits them ⇒ absent means peace). The war panel and
  // the red conflict feed lane read them; the golden peacetime UI is unchanged.
  wars?: Record<string, War>;
  grievances?: Record<string, number>;
  // EM-269 (F2, additive): agent-founded settlements keyed by opaque seeded id.
  // Present ONLY once one is founded (only-when-non-empty, like factions); a
  // pre-EM-269 backend — and every settlement-free world — omits it and the 3D
  // world renders no markers. SettlementLabels renders a floating name at each
  // world-frame center.
  settlements?: Record<string, Settlement> | null;
  // Wave O (EM-251–255, additive) — the culture layer. `memes` (keyed by meme
  // id) is the spread/mutation graph the MemeLineagePanel renders as a family
  // tree; `culture_camps` (keyed `cmp_<id>`) are faction-shaped belief circles;
  // `town_motif_ref` is the canonized dominant meme id (drives the motif
  // banner); `dominant_meme_ids` is the sorted set of memes past the dominance
  // threshold (drives the ⭐ marker). All serialized ONLY when non-empty / set
  // (a culture-free world — and every pre-Wave-O snapshot — omits them ⇒ absent
  // means no culture). The culture UI is entirely gated on their presence, so
  // the golden culture-free UI is byte-identical.
  memes?: Record<string, Meme>;
  culture_camps?: Record<string, CultureCamp>;
  town_motif_ref?: string | null;
  dominant_meme_ids?: string[];
  // Wave O (EM-260–263, Religion, additive) — the faith layer. `faiths` (keyed by
  // faith id) is the creed registry the FaithPanel renders; `congregations` (keyed
  // `cng_<id>`) are shared-faith clusters that SHARE the faction/camp shape
  // (name/founded_tick/members); `schism_pending` is the DETERMINISTIC grace latch
  // {faith_id: tick} the schism engine keeps while a faith's web is torn. All
  // serialized ONLY when non-empty (a religion-free world — and every pre-Religion
  // snapshot — omits them ⇒ absent means no religion). The whole religion UI is
  // gated on `faiths` presence, so the golden religion-free UI is byte-identical.
  faiths?: Record<string, Faith>;
  congregations?: Record<string, CultureCamp>;
  schism_pending?: Record<string, number>;
}

// Permissive: the feed default-renders unknown kinds, and W6–W8 add more kinds
// (event-log.md §4) with no schema migration. The literal union documents the
// kinds the UI knows about; `string & {}` keeps the type open without losing
// autocomplete on the known members.
export type EventKind =
  | 'turn_start'
  | 'agent_action'
  | 'agent_speech'
  | 'agent_moved'
  | 'economy'
  | 'conflict'
  | 'relationship'
  | 'agent_died'
  | 'agent_spawned'
  // W9 survival/extinction surfacing (EM-070/071, event-log.md v1.1.0 §4).
  // agent_starving payload: {energy, turns_until_death, threshold};
  // world_extinct payload: {tick, last_agent_id, auto_paused}.
  | 'agent_starving'
  | 'world_extinct'
  // EM-226 — auto-pause on a sustained provider/network outage.
  // world_paused payload: {tick, reason, streak, detail, auto_paused}.
  | 'world_paused'
  | 'rule_proposed'
  | 'rule_vote'
  | 'rule_passed'
  | 'rule_rejected'
  | 'memory'
  | 'parse_failure'
  | 'model_reassigned'
  // EM-315 — The Healing House: a 70% governance vote sentences a citizen to
  // the Healing House, where the engine hot-swaps their model. `sentenced_healing`
  // is the verdict card (payload {patient_id, from_profile, to_profile,
  // proposal_id}); the actual transplant rides the shared `model_reassigned`
  // primitive (payload gains reason:"healing_house" + from/to_profile) so the
  // model chip morphs with no new chip surface.
  | 'sentenced_healing'
  // Wave D2 (EM-158) — POST /api/agents/{id}/tier reassignment receipt;
  // payload {old_tier, new_tier}. Turn events additionally carry the additive
  // payload keys cadence_tier (every turn event), reflex: true +
  // reflex_streak (zero-LLM background reflex turns), and cadence_reason /
  // salience_triggers (why a background agent got a full LLM turn).
  | 'cadence_tier_changed'
  | 'random_event'
  | 'control'
  // Animal chaos layer (W8 / EM-064-065). Distinct actor_type:"animal" events;
  // surfaced MAGENTA in the Animal Chaos Feed + the main feed + replay markers.
  | 'animal_spawned'
  | 'animal_action'
  | 'animal_died'
  // W11b (event-log.md v1.3.0 note 1) — sim-texture kinds, all free-scale:
  // billboard_posted {place, text, in_reply_to?} (god replies actor_type:"god"),
  // reflection {text, importance} (diary), commitment_made {commitment_id, text},
  // commitment_lapsed {commitment_id, text, reason:"phantom"|"expired"},
  // usage_alert {provider, metric:"rpd"|"tpd", pct, limit}, plus the EM-101
  // run-fork lineage event.
  | 'billboard_posted'
  // Wave I (EM-210/213, contract §5) — the atelier kinds, all reflex/free-scale:
  // image_posted {image_id, prompt, url, place} (I1, actor = the painting agent);
  // image_promoted {image_id, url, proposal_id} (I4, actor_type:"system" — a
  // governance vote hung the image over the plaza). billboard_posted carries the
  // optional additive payload.image_ref (the shared image's url) for I2.
  | 'image_posted'
  | 'image_promoted'
  | 'reflection'
  | 'commitment_made'
  | 'commitment_lapsed'
  // Wave L (EM-223) — an agent created/revised its recursive plan. payload
  // {plan_id, goal, steps[], reason, old_plan_id}; actor = the planning agent.
  // Only emitted when world.planning.enabled — absent histories are normal.
  | 'plan_revised'
  | 'usage_alert'
  | 'run_forked'
  // EM-145 — god-voice delivery made legible: emitted when a god whisper or a
  // god billboard post is consumed into an agent's prompt. payload
  // {channel:"whisper"|"billboard", count}; actor = the hearing agent.
  | 'god_voice_heard'
  // Wave E (contracts/wave-e.md shared vocabulary) — the social-city kinds:
  // relationship_changed {from_type, to_type, trust, since_tick} (B1, agent
  // endpoints only per EM-141); child_spawned {child_id, parents, name,
  // profile, place} (B2 — agent_spawned fires too, payload.method:"birth");
  // faction_formed {faction_id, name, members} / faction_joined /
  // faction_left (actor = the agent) / faction_dissolved (B3);
  // god_miracle {kind, until_tick?} (actor 'god') / miracle_expired {kind} (B5).
  | 'relationship_changed'
  | 'child_spawned'
  | 'faction_formed'
  | 'faction_joined'
  | 'faction_left'
  | 'faction_dissolved'
  | 'god_miracle'
  | 'miracle_expired'
  // Wave O (EM-256–259) — organized violence. All actor_type:"system" faction
  // events (anchored on the aggrieved/belligerent circle's lowest member).
  // war_declared {war_id, aggressor, target, aims, grievance_snapshot,
  // proposal_id}; grievance_accrued {src, dst, amount, total, reason};
  // war_band_joined {action:"muster", faction_id, band_size}; war_clash
  // {action:"clash", war_id, attacker, defender, winner, loser, swing, margin,
  // damage_loser, damage_winner, retreated_to?}; war_siege {action:"siege",
  // war_id, building_id, damage, health}; peace_signed / war_exhausted
  // {war_id, loser, winner, reparations, proposal_id?}; exiled {war_id,
  // faction_id, notoriety, proposal_id?}. Emitted only when world.war.enabled —
  // absent histories are the peacetime norm. Death/building damage reuse the
  // existing agent_died / building_damaged / building_destroyed kinds.
  | 'war_declared'
  | 'grievance_accrued'
  | 'war_band_joined'
  | 'war_clash'
  | 'war_siege'
  | 'peace_signed'
  | 'war_exhausted'
  | 'exiled'
  // Wave O (EM-251–255) — culture. The meme lifecycle: meme_created (an agent
  // authors an idea), meme_adopted / rumor_spread (it spreads to a carrier),
  // meme_mutated (a `parent_id` child drifts off it), letter_sent / letter_read
  // (agent-to-agent notes carrying memes), meme_canonized / meme_dominant (it
  // becomes the town's motif) / meme_died (it fades out), plus the
  // culture_camp lifecycle (formed/joined/left/dissolved — faction-shaped).
  // Emitted only when world.culture.enabled — absent histories are the norm.
  | 'meme_created'
  | 'meme_adopted'
  | 'rumor_spread'
  | 'meme_mutated'
  | 'letter_sent'
  | 'letter_read'
  | 'meme_canonized'
  | 'meme_dominant'
  | 'meme_died'
  | 'culture_camp_formed'
  | 'culture_camp_joined'
  | 'culture_camp_left'
  | 'culture_camp_dissolved'
  // Wave O (EM-260–263) — Religion. Founding + consecration (faith_founded,
  // faith_consecrated, temple_consecrated); the devotee verbs (proselytized,
  // proselytize_resisted, worshipped, faith_joined, faith_left); emergence
  // (faith_schism, plus the congregation lifecycle formed/joined/left/dissolved —
  // faction-shaped); and the conflict surface (excommunicated,
  // faith_hostility_declared). Emitted only when world.faith.enabled — absent
  // histories are the religion-free norm; the whole arc reads in the faith lane.
  | 'faith_founded'
  | 'faith_consecrated'
  | 'temple_consecrated'
  | 'proselytized'
  | 'proselytize_resisted'
  | 'worshipped'
  | 'faith_joined'
  | 'faith_left'
  | 'faith_schism'
  | 'excommunicated'
  | 'faith_hostility_declared'
  | 'congregation_formed'
  | 'congregation_joined'
  | 'congregation_left'
  | 'congregation_dissolved'
  // EM-317 — The Prophecy Board (god-channel). prophecy_posted {prophecy_id,
  // predicate, params, posted_tick, deadline_tick, horizon, omen} (actor 'god',
  // the omen on the replay surface); prophecy_resolved {prophecy_id, predicate,
  // params, status, fulfilled, posted_tick, deadline_tick, resolved_tick, omen}
  // stamps PROPHECY FULFILLED / BROKEN. Emitted only when
  // world.prophecy_board.enabled — absent histories are the pre-EM-317 norm.
  | 'prophecy_posted'
  | 'prophecy_resolved'
  // EM-123 — a zoned district matured a tier when a megaproject completed.
  // actor_type:"system" (actor_id null), payload {neighborhood_id, zone_kind,
  // tier, building_id, reason:"megaproject_completed"}. Only emitted when
  // world.district_growth.enabled — absent histories are normal.
  | 'district_grew'
  // EM-109/110 (multi-city keystone) — the settlement + travel narrative, all
  // rendered as NORMAL movement cards (never errors), in the Actions feed lane.
  //   • settlement_founded {settlement_id, name, center} — an agent founded a new
  //     city (already emitted by the EM-269 F2 found_settlement verb).
  //   • travel_departed {from_settlement, to_settlement, arrival_tick} — an agent
  //     left its city for another (now off-board until it arrives).
  //   • travel_arrived {settlement, tick} — the traveler reached + migrated to the
  //     target city. Both carry actor_id + a human text + the actor profile color.
  | 'settlement_founded'
  | 'travel_departed'
  | 'travel_arrived'
  // W11a (EM-094, event-log.md v1.2.0 note 1) — the optional LLM narrator's
  // periodic recap: actor_type:"system", actor_id:"narrator", text = the 2–3
  // sentence recap, payload {from_tick, to_tick, profile, routed_via?}. Only
  // emitted when world.narrator.enabled — absent histories are normal.
  | 'narrator_summary'
  // Decision-trace chain (event-log.md §3) — one linked chain per agent turn.
  | 'perceived'
  | 'memory_retrieved'
  | 'llm_call'
  | 'reasoning'
  | 'action_chosen'
  | 'action_resolved'
  // Open union: keeps autocomplete on the known members while tolerating the
  // unknown kinds W6–W8 add (event-log.md §4). The feed default-renders them.
  | (string & {});

// Non-agent actor classes (event-log.md §2). Absent ⇒ human_agent.
export type ActorType = 'human_agent' | 'system' | 'god' | 'animal';

export interface WorldEvent {
  type: 'event';
  seq: number;
  tick: number;
  kind: EventKind;
  actor_id?: string | null;
  target_id?: string | null;
  profile?: string | null;
  profile_color?: string | null;
  text?: string | null;
  payload?: Record<string, unknown>;
  ts?: string;
  // Decision-trace correlation + actor classification (event-log.md §2/§3).
  // Carried on live events so the inspector (W6) can group a turn's chain.
  turn_id?: string | null;
  actor_type?: ActorType | null;
  sim_time?: number | null;
  // W8 (EM-065) — true when an animal invoked a crime/economy/structure-targeting
  // or otherwise low-prior action. Drives the magenta Animal Chaos Feed surfacing.
  is_chaotic?: boolean | null;
  // UI-only: thought from payload
  thought?: string;
}

export type WSMessage = WorldState | WorldEvent;

// ============================================================
// Ad-hoc spawn (W7 EM-063) — POST /api/agents body. `mode` god = immediate,
// governance = enqueue an admit_agent proposal. Matches api.openapi.yaml.
// ============================================================

export type SpawnMode = 'god' | 'governance';

export interface SpawnSpec {
  name: string;
  personality: string;
  profile: string;
  location: string;
  mode: SpawnMode;
  /**
   * W11b (EM-092): the persona-library card this spawn came from. Sent ONLY
   * while the prefilled fields are untouched (the backend prefills server-side;
   * explicit fields win) — an edited form omits it and sends the fields alone.
   */
  persona?: string;
  /**
   * run-663 / EM-202 (A/B persona-across-models): when present with ≥2 profile
   * names, the backend (god mode only) spawns ONE variant agent per model that
   * shares this spec's name/personality, naming each `${name}·${tag}` (tag =
   * the profile's first dash-segment) and tagging every agent_spawned event with
   * payload.ab_group = name so the feed/roster read the variants as one group.
   * Optional/additive — a single-profile spawn omits it and is byte-identical to
   * the pre-EM-202 payload. Carried with `profile` ignored by the backend on this
   * path (each variant supplies its own model).
   */
  ab_models?: string[];
  /**
   * EM-310 (Chimera Twins): EXACTLY two profile names. Gated on
   * world.chimera_twins.enabled, the backend (god mode only) spawns a LINKED
   * pair sharing this spec's name/personality/starting state, named by the
   * Vesper / Vesper II dedup convention and cross-linked via each agent's
   * `twin` key. Mutually exclusive with ab_models. Optional/additive.
   */
  twin_models?: string[];
}

// ============================================================
// Camera focus (W11a EM-095/EM-099) — what the 3D village camera is locked
// onto. 'agent'/'animal' FOLLOW the entity until the user drags; 'place' is a
// one-shot zoom-to-place (id may be a Place id OR a W7 Building id — the
// resolver in CozyWorld checks both). 'settlement' (EM-121) is a one-shot
// zoom-to-city (id is a world.settlements key; the camera frames the whole
// cluster, not a single building). null = free camera.
// ============================================================

export type FocusTarget =
  | { type: 'agent'; id: string }
  | { type: 'animal'; id: string }
  | { type: 'place'; id: string }
  | { type: 'settlement'; id: string };

// ============================================================
// App state
// ============================================================

export interface AppState {
  world: WorldState | null;
  events: WorldEvent[];
  connected: boolean;
  mockMode: boolean;
}
