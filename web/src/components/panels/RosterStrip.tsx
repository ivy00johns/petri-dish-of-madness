/**
 * RosterStrip (EM-096/EM-099) — the horizontally-scrollable card strip along
 * the bottom edge of the world view. Replaces the old left-column AgentPanels
 * in the live layout with NO information loss: every agent card keeps name,
 * model badge (profile + color), energy bar, credits, mood, location,
 * dying/dead state AND the top-3 relationship tags.
 *
 * EM-099 adds the CRITTERS group: per animal — species emoji, name, mood,
 * model chip (the same EM-089 chip idiom Critter.tsx/WorldMap use, derived
 * from the latest animal llm_call since world_state animals carry no
 * profile), location, and a chaos count (is_chaotic events in the rolling
 * history).
 *
 * Clicking a card focuses/FOLLOWS that entity in the 3D village (EM-095);
 * clicking the selected card again releases it. Selection is surfaced with
 * the acid ring + aria-pressed.
 *
 * Dynamic colors (model profile colors, relationship registers) follow the
 * established data-driven inline-color idiom (AgentPanels/EventFeed/W10);
 * every static color is a lab-* token.
 */

import { useMemo } from 'react';
import type { Agent, Animal, FocusTarget, WorldEvent, WorldState } from '../../types';
import type { AnimalModelId } from '../../lib/animalIdentity';
// Declares the --rel-* relationship registers (plus reuses the shared :root
// tokens WorldMap/inspector already declare) — token-only colors, no literals.
import './roster-tokens.css';

interface RosterStripProps {
  world: WorldState | null;
  /** Deep rolling history (newest-first) — source of the critter chaos count. */
  history: WorldEvent[];
  /** EM-089 map: animalId → model identity (absent ⇒ chip omitted). */
  animalModels: Map<string, AnimalModelId>;
  /** Currently focused/followed entity (EM-095), or null. */
  selected: FocusTarget | null;
  /** Select (focus+follow) or deselect (null) an entity. */
  onSelect: (target: FocusTarget | null) => void;
}

const ENERGY_WARN_THRESHOLD = 25;

const REL_COLOR: Record<string, string> = {
  ally: 'var(--rel-ally)',
  friend: 'var(--rel-friend)',
  neutral: 'var(--rel-neutral)',
  rival: 'var(--rel-rival)',
  enemy: 'var(--rel-enemy)',
};

function EnergyBar({ value, color }: { value: number; color: string }) {
  const pct = Math.max(0, Math.min(100, value));
  const barColor =
    pct > 60 ? color : pct > ENERGY_WARN_THRESHOLD ? 'var(--lab-warn)' : 'var(--lab-danger)';
  const critical = pct <= ENERGY_WARN_THRESHOLD;
  return (
    <div className="flex items-center gap-1.5 min-w-0 flex-1">
      <div className="energy-bar-track flex-1 h-1.5">
        <div
          className={`h-full rounded-full transition-all duration-500 ${critical ? 'animate-pulse' : ''}`}
          style={{ width: `${pct}%`, backgroundColor: barColor }}
        />
      </div>
      <span
        className={`font-mono text-[10px] tabular-nums w-6 text-right shrink-0 ${pct <= 0 ? 'animate-pulse font-bold' : ''}`}
        style={{ color: barColor }}
      >
        {Math.round(pct)}
      </span>
    </div>
  );
}

/** Shared clickable card chrome: selection ring + focus affordance. */
function StripCard({
  selected,
  onClick,
  title,
  borderColor,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  borderColor: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      title={title}
      className={`lab-panel relative shrink-0 w-60 text-left px-2.5 py-1.5 cursor-pointer
                  transition-colors duration-150 snap-start
                  hover:border-lab-border-bright
                  ${selected ? 'ring-1 ring-lab-acid border-lab-acid' : ''}`}
      style={{ borderLeft: `3px solid ${borderColor}` }}
    >
      {children}
    </button>
  );
}

function AgentCard({
  agent,
  world,
  selected,
  onSelect,
}: {
  agent: Agent;
  world: WorldState;
  selected: boolean;
  onSelect: (t: FocusTarget | null) => void;
}) {
  const color = agent.profile_color ?? 'var(--inspector-node-neutral)';
  const turnsLeft = agent.turns_until_death;
  const dying =
    agent.alive && agent.energy <= 0 && typeof turnsLeft === 'number' && turnsLeft >= 0;
  const placeName = world.places.find((p) => p.id === agent.location)?.name ?? agent.location;

  const topRels = Object.entries(agent.relationships)
    .sort((a, b) => Math.abs(b[1].trust) - Math.abs(a[1].trust))
    .slice(0, 3);
  const nameOf = (id: string) => world.agents.find((a) => a.id === id)?.name ?? id;

  return (
    <StripCard
      selected={selected}
      onClick={() => onSelect(selected ? null : { type: 'agent', id: agent.id })}
      title={
        selected
          ? `Following ${agent.name} — click to release`
          : `Click to follow ${agent.name} in the village`
      }
      borderColor={color}
    >
      <div className={!agent.alive ? 'opacity-40' : ''}>
        {/* Row 1: identity + model badge */}
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 font-mono text-[9px] font-bold"
              style={{
                backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)`,
                border: `1.5px solid ${color}`,
                color,
              }}
            >
              {agent.name.slice(0, 2).toUpperCase()}
            </span>
            <span className="font-mono text-[11px] font-semibold text-lab-text truncate">
              {agent.name}
            </span>
            {!agent.alive && (
              <span className="font-mono text-[8px] text-lab-danger border border-lab-danger px-1 shrink-0">
                DEAD
              </span>
            )}
            {dying && (
              <span
                className="font-mono text-[8px] font-bold text-lab-danger border border-lab-danger bg-lab-danger/15 px-1 animate-pulse whitespace-nowrap shrink-0"
                title="Energy is 0 — this villager dies unless they recharge in time."
              >
                DYING — {turnsLeft}T
              </span>
            )}
          </div>
          <span
            className="font-mono text-[8px] font-semibold px-1 py-px border rounded-sm tracking-wider truncate max-w-[5.5rem] shrink-0"
            style={{
              backgroundColor: `color-mix(in srgb, ${color} 13%, transparent)`,
              borderColor: `color-mix(in srgb, ${color} 50%, transparent)`,
              color,
            }}
            title={agent.profile}
          >
            {agent.profile}
          </span>
        </div>

        {/* Row 2: energy + credits + mood */}
        <div className="flex items-center gap-2 mt-1">
          <EnergyBar value={agent.energy} color={color} />
          <span className="font-mono text-[10px] text-lab-acid font-semibold tabular-nums shrink-0">
            ¢{agent.credits}
          </span>
          <span className="font-mono text-[10px] text-lab-muted truncate max-w-[4.5rem]" title={`mood: ${agent.mood}`}>
            {agent.mood}
          </span>
        </div>

        {/* Row 3: location + top relationships */}
        <div className="flex items-center gap-1.5 mt-1 min-w-0">
          <span className="font-mono text-[9px] text-lab-muted truncate shrink-0" title={`at ${placeName}`}>
            ▸ {placeName}
          </span>
          <span className="flex items-center gap-1 min-w-0 overflow-hidden">
            {topRels.map(([targetId, rel]) => {
              const c = REL_COLOR[rel.type] ?? REL_COLOR.neutral;
              return (
                <span
                  key={targetId}
                  className="font-mono text-[8px] px-1 py-px border rounded-sm whitespace-nowrap"
                  style={{
                    color: c,
                    borderColor: `color-mix(in srgb, ${c} 38%, transparent)`,
                    backgroundColor: `color-mix(in srgb, ${c} 9%, transparent)`,
                  }}
                  title={`${nameOf(targetId)}: ${rel.type} (trust ${rel.trust})`}
                >
                  {nameOf(targetId).slice(0, 4)} {rel.trust > 0 ? `+${rel.trust}` : rel.trust}
                </span>
              );
            })}
          </span>
        </div>
      </div>
    </StripCard>
  );
}

function CritterCard({
  animal,
  world,
  chaosCount,
  model,
  selected,
  onSelect,
}: {
  animal: Animal;
  world: WorldState;
  chaosCount: number;
  model: AnimalModelId | undefined;
  selected: boolean;
  onSelect: (t: FocusTarget | null) => void;
}) {
  const placeName = world.places.find((p) => p.id === animal.location)?.name ?? animal.location;
  const emoji = animal.species === 'cat' ? '🐱' : '🐶';

  return (
    <StripCard
      selected={selected}
      onClick={() => onSelect(selected ? null : { type: 'animal', id: animal.id })}
      title={
        selected
          ? `Following ${animal.name} — click to release`
          : `Click to follow ${animal.name} in the village`
      }
      borderColor="var(--marker-animal)"
    >
      <div className={!animal.alive ? 'opacity-40' : ''}>
        {/* Row 1: species + name + chaos count */}
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-sm leading-none shrink-0" aria-hidden="true">{emoji}</span>
            <span className="font-mono text-[11px] font-semibold text-lab-text truncate">
              {animal.name}
            </span>
            {!animal.alive && (
              <span className="font-mono text-[8px] text-lab-danger border border-lab-danger px-1 shrink-0">
                GONE
              </span>
            )}
          </div>
          <span
            className="font-mono text-[8px] font-semibold px-1 py-px border rounded-sm whitespace-nowrap shrink-0"
            style={{
              color: 'var(--chaos-chaotic)',
              borderColor: 'var(--chaos-border)',
              backgroundColor: 'var(--chaos-surface)',
            }}
            title={`${chaosCount} chaotic event${chaosCount === 1 ? '' : 's'} in the loaded history`}
          >
            CHAOS ×{chaosCount}
          </span>
        </div>

        {/* Row 2: mood + model chip (EM-089 idiom: omitted until an llm_call). */}
        <div className="flex items-center gap-2 mt-1 min-w-0">
          <span className="font-mono text-[10px] text-lab-muted truncate" title={`mood: ${animal.mood}`}>
            {animal.mood}
          </span>
          {model ? (
            <span
              className="font-mono text-[8px] font-semibold px-1 py-px border rounded-sm truncate max-w-[7rem]"
              style={{
                color: model.color ?? 'var(--lab-text)',
                borderColor: model.color
                  ? `color-mix(in srgb, ${model.color} 50%, transparent)`
                  : 'var(--lab-border-bright)',
              }}
              title={`LLM decisions route to ${model.profile}`}
            >
              🧠 {model.profile}
            </span>
          ) : (
            <span className="font-mono text-[8px] text-lab-dim shrink-0" title="No LLM decision yet — reflex-only so far">
              reflex-only
            </span>
          )}
        </div>

        {/* Row 3: location */}
        <div className="mt-1">
          <span className="font-mono text-[9px] text-lab-muted truncate block" title={`at ${placeName}`}>
            ▸ {placeName}
          </span>
        </div>
      </div>
    </StripCard>
  );
}

/** Vertical group label between strip sections. */
function GroupLabel({ text }: { text: string }) {
  return (
    <div className="shrink-0 self-stretch flex items-center px-1 border-r border-lab-border/60">
      <span className="font-mono text-[9px] font-semibold tracking-widest text-lab-muted uppercase [writing-mode:vertical-rl]">
        {text}
      </span>
    </div>
  );
}

export function RosterStrip({ world, history, animalModels, selected, onSelect }: RosterStripProps) {
  // EM-099: chaos count per animal — is_chaotic events in the rolling history.
  const chaosCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of history) {
      if (e.is_chaotic && e.actor_id) {
        m.set(e.actor_id, (m.get(e.actor_id) ?? 0) + 1);
      }
    }
    return m;
  }, [history]);

  if (!world) {
    return (
      <div className="flex items-center px-3 py-2" aria-label="Agent and critter roster">
        <span className="font-mono text-xs text-lab-dim">ROSTER — NO DATA</span>
      </div>
    );
  }

  const agents = [...world.agents].sort((a, b) => {
    if (a.alive !== b.alive) return a.alive ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  const animals = world.animals ?? [];

  return (
    <div
      className="flex items-stretch gap-1.5 px-2 py-1.5 overflow-x-auto overflow-y-hidden snap-x"
      role="toolbar"
      aria-label="Agent and critter roster — click a card to follow it in the village"
    >
      <GroupLabel text={`Agents ${agents.filter((a) => a.alive).length}/${agents.length}`} />
      {agents.length === 0 ? (
        <span className="font-mono text-xs text-lab-dim self-center px-2">no agents yet</span>
      ) : (
        agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            world={world}
            selected={selected?.type === 'agent' && selected.id === agent.id}
            onSelect={onSelect}
          />
        ))
      )}

      <GroupLabel text="Critters" />
      {animals.length === 0 ? (
        <span className="font-mono text-xs text-lab-dim self-center px-2 whitespace-nowrap">
          no critters in this world
        </span>
      ) : (
        animals.map((animal) => (
          <CritterCard
            key={animal.id}
            animal={animal}
            world={world}
            chaosCount={chaosCounts.get(animal.id) ?? 0}
            model={animalModels.get(animal.id)}
            selected={selected?.type === 'animal' && selected.id === animal.id}
            onSelect={onSelect}
          />
        ))
      )}
    </div>
  );
}
