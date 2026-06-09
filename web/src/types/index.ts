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
}

export type RelationshipType = 'ally' | 'rival' | 'neutral' | 'friend' | 'enemy';

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
  beliefs: string[];
  relationships: Record<string, Relationship>;
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
}

// ============================================================
// Animal (W8) — match contracts/world-model.md §W8. Animals are a DISTINCT
// entity type (actor_type:"animal"), NOT human agents: own persona, looser
// action set, slow cadence, own logging channel. They share the world
// mechanically (places, can damage buildings) but have NO credits account
// (invariant 7). They live in world.animals; world_state gains `animals: [Animal]`.
// Rendered as a roaming cat + dog in the 3D village (species-shaped, tinted).
// ============================================================

export type AnimalSpecies = 'cat' | 'dog';

export interface Animal {
  id: string;
  species: AnimalSpecies;
  name: string;
  location: string;             // place id
  energy: number;               // 0..100
  mood: string;                 // short free text
  alive: boolean;
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
  | 'rule_proposed'
  | 'rule_vote'
  | 'rule_passed'
  | 'rule_rejected'
  | 'memory'
  | 'parse_failure'
  | 'model_reassigned'
  | 'random_event'
  | 'control'
  // Animal chaos layer (W8 / EM-064-065). Distinct actor_type:"animal" events;
  // surfaced MAGENTA in the Animal Chaos Feed + the main feed + replay markers.
  | 'animal_spawned'
  | 'animal_action'
  | 'animal_died'
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
}

// ============================================================
// App state
// ============================================================

export interface AppState {
  world: WorldState | null;
  events: WorldEvent[];
  connected: boolean;
  mockMode: boolean;
}
