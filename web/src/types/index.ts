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
  // Wave I (EM-210/213): the image gallery (agent-generated art) and the id of
  // the image currently promoted over the plaza. Both optional/additive so a
  // pre-Wave-I backend (or a snapshot predating the atelier) stays valid; the
  // 3D notice board textures the newest gallery image and PlazaBanner resolves
  // `plaza_banner_ref` → its gallery url (procedural fallback when absent).
  gallery?: GalleryImage[];
  plaza_banner_ref?: string;
  // EM-123 (additive): zoned-district maturity. Present ONLY once a tier has
  // diverged from the tier-1 baseline (a fresh world omits it); when absent the
  // 3D city re-derives tier-1 neighborhoods from `places` and renders identically.
  neighborhoods?: Neighborhood[];
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
  // EM-123 — a zoned district matured a tier when a megaproject completed.
  // actor_type:"system" (actor_id null), payload {neighborhood_id, zone_kind,
  // tier, building_id, reason:"megaproject_completed"}. Only emitted when
  // world.district_growth.enabled — absent histories are normal.
  | 'district_grew'
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
}

// ============================================================
// Camera focus (W11a EM-095/EM-099) — what the 3D village camera is locked
// onto. 'agent'/'animal' FOLLOW the entity until the user drags; 'place' is a
// one-shot zoom-to-place (id may be a Place id OR a W7 Building id — the
// resolver in CozyWorld checks both). null = free camera.
// ============================================================

export type FocusTarget =
  | { type: 'agent'; id: string }
  | { type: 'animal'; id: string }
  | { type: 'place'; id: string };

// ============================================================
// App state
// ============================================================

export interface AppState {
  world: WorldState | null;
  events: WorldEvent[];
  connected: boolean;
  mockMode: boolean;
}
