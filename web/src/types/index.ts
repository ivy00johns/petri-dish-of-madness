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
  beliefs: string[];
  relationships: Record<string, Relationship>;
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
  | 'rule_proposed'
  | 'rule_vote'
  | 'rule_passed'
  | 'rule_rejected'
  | 'memory'
  | 'parse_failure'
  | 'model_reassigned'
  | 'random_event'
  | 'control'
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
  // UI-only: thought from payload
  thought?: string;
}

export type WSMessage = WorldState | WorldEvent;

// ============================================================
// App state
// ============================================================

export interface AppState {
  world: WorldState | null;
  events: WorldEvent[];
  connected: boolean;
  mockMode: boolean;
}
