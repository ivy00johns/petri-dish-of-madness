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
import { speciesEmoji } from '../world3d/worldSpace';
import { useBlindLineup } from '../blind/BlindLineupContext';
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
  // Wave E (EM-113/B6) — the four new typed-bond registers (roster-tokens.css):
  // partner/family warm-distinct, mentor sky, feud darker than enemy.
  partner: 'var(--rel-partner)',
  family: 'var(--rel-family)',
  mentor: 'var(--rel-mentor)',
  feud: 'var(--rel-feud)',
};

// Wave D2 (EM-158/166) — the cadence tier chip (matches the model-chip idiom,
// token-only colors). Protagonists read brightest; background reads dimmest.
const TIER_ABBR: Record<string, string> = {
  protagonist: 'PRO',
  supporting: 'SUP',
  background: 'BG',
};
const TIER_CLASS: Record<string, string> = {
  protagonist: 'text-lab-acid border-lab-acid/50',
  supporting: 'text-lab-muted border-lab-border-bright',
  background: 'text-lab-dim border-lab-border',
};
const TIER_TITLE: Record<string, string> = {
  protagonist: 'Protagonist — acts every round, always a full LLM turn',
  supporting: 'Supporting — acts every 3rd round, always a full LLM turn when due',
  background:
    'Background — acts every 10th round; quiet turns resolve a zero-LLM reflex routine ' +
    '(salience, a seeded wildcard, or the reflex-streak floor brings the LLM back)',
};

/** Wave D2 (EM-166) — the small cadence-tier chip shown beside the model chip. */
export function TierChip({ tier, reflexStreak }: { tier?: string | null; reflexStreak?: number | null }) {
  if (!tier) return null; // pre-D2 backend — no chip, no layout shift
  const streak = typeof reflexStreak === 'number' && reflexStreak > 0 ? ` · reflex ×${reflexStreak}` : '';
  return (
    <span
      className={`font-mono text-[8px] font-semibold px-1 py-px border rounded-sm tracking-wider whitespace-nowrap shrink-0 ${
        TIER_CLASS[tier] ?? TIER_CLASS.supporting
      }`}
      title={`${TIER_TITLE[tier] ?? `Cadence tier: ${tier}`}${streak}`}
    >
      {TIER_ABBR[tier] ?? tier.slice(0, 3).toUpperCase()}
    </span>
  );
}

// ── EM-202 (A/B persona-across-models) ────────────────────────────────────────
// A/B variants share a base name; the backend names each `${base}·${tag}` (the
// `·` separator is the canonical signal). The roster correlates them by that
// base: when ≥2 living-or-dead agents share a base, every variant in the group
// wears an "A/B · {base}" chip and its `·tag` reads distinctly from the base, so
// "Vesper·mistral" and "Vesper·groq" obviously belong to one model-vs-model
// experiment (model chip already names WHICH model). Derived purely from the
// snapshot — no new Agent field needed (the ab_group payload only rides the
// agent_spawned event; the roster reads world.agents).

/** Split a `${base}·${tag}` variant name; null when there's no `·` separator. */
export function parseAbName(name: string): { base: string; tag: string } | null {
  const i = name.indexOf('·');
  if (i <= 0 || i >= name.length - 1) return null; // no separator, or empty side
  return { base: name.slice(0, i), tag: name.slice(i + 1) };
}

/**
 * Map base-name → count of `·`-tagged variants sharing it. A base with ≥2
 * variants is an A/B group; lone `·` names (an agent that merely has a dot)
 * are NOT a group and read normally.
 */
export function abGroupCounts(agents: Agent[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const a of agents) {
    const parsed = parseAbName(a.name);
    if (parsed) m.set(parsed.base, (m.get(parsed.base) ?? 0) + 1);
  }
  return m;
}

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
  abGroupSize,
  selected,
  onSelect,
}: {
  agent: Agent;
  world: WorldState;
  /** EM-202: # of `·`-tagged variants sharing this agent's base name (≥2 ⇒ A/B). */
  abGroupSize: number;
  selected: boolean;
  onSelect: (t: FocusTarget | null) => void;
}) {
  // EM-309 (Blind Lineup): mask the model NAME behind ??? while a round is
  // live. The card's left-border + avatar COLOR stays — the viewer still sees
  // the slot, just not its model until reveal.
  const { maskName } = useBlindLineup();
  const color = agent.profile_color ?? 'var(--inspector-node-neutral)';
  const turnsLeft = agent.turns_until_death;
  const dying =
    agent.alive && agent.energy <= 0 && typeof turnsLeft === 'number' && turnsLeft >= 0;
  const placeName = world.places.find((p) => p.id === agent.location)?.name ?? agent.location;
  // EM-202: render this card as an A/B variant only when ≥2 variants share its
  // base (a lone `·` name is just a name, not a group).
  const ab = abGroupSize >= 2 ? parseAbName(agent.name) : null;

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
            {ab ? (
              // EM-202: the base reads as the persona, the `·tag` as the variant
              // distinction — so the A/B siblings scan as one group.
              <span
                className="font-mono text-[11px] font-semibold text-lab-text truncate"
                title={`A/B variant of "${ab.base}" — running ${maskName(agent.profile)}`}
              >
                {ab.base}
                <span className="text-lab-muted">·{ab.tag}</span>
              </span>
            ) : (
              <span className="font-mono text-[11px] font-semibold text-lab-text truncate">
                {agent.name}
              </span>
            )}
            {ab && (
              <span
                className="font-mono text-[8px] font-bold text-lab-acid border border-lab-acid/50 bg-lab-acid/10 px-1 rounded-sm shrink-0 uppercase tracking-wider"
                title={`A/B group "${ab.base}" — ${abGroupSize} variants compared across models`}
              >
                A/B
              </span>
            )}
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
          <span className="flex items-center gap-1 shrink-0">
            {/* Wave D2 (EM-166) — cadence tier chip beside the model chip. */}
            <TierChip tier={agent.cadence_tier} reflexStreak={agent.reflex_streak} />
            <span
              className="font-mono text-[8px] font-semibold px-1 py-px border rounded-sm tracking-wider truncate max-w-[5.5rem] shrink-0"
              style={{
                backgroundColor: `color-mix(in srgb, ${color} 13%, transparent)`,
                borderColor: `color-mix(in srgb, ${color} 50%, transparent)`,
                color,
              }}
              title={maskName(agent.profile)}
            >
              {maskName(agent.profile)}
            </span>
          </span>
        </div>

        {/* Row 2: energy + credits + REP + mood */}
        <div className="flex items-center gap-2 mt-1">
          <EnergyBar value={agent.energy} color={color} />
          <span className="font-mono text-[10px] text-lab-acid font-semibold tabular-nums shrink-0">
            ¢{agent.credits}
          </span>
          {/* Wave E (EM-120): derived reputation — rendered ONLY when the
              backend sends it (absent-safe for pre-E backends/snapshots). */}
          {typeof agent.reputation === 'number' && (
            <span
              className="font-mono text-[10px] text-lab-muted tabular-nums shrink-0"
              title={`reputation ${agent.reputation} — mean incoming trust from villagers who know them`}
            >
              REP {agent.reputation > 0 ? `+${agent.reputation}` : agent.reputation}
            </span>
          )}
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
  // EM-309 (Blind Lineup): a critter's model chip is also part of the lineup —
  // mask its name while a round is live.
  const { maskName } = useBlindLineup();
  const placeName = world.places.find((p) => p.id === animal.location)?.name ?? animal.location;
  const emoji = speciesEmoji(animal.species);
  // Wave H4 (EM-209): resolve the owner name when this pet is owned by a
  // living agent. Absent owner_id or a dead/missing owner ⇒ no bond line.
  const ownerAgent = animal.owner_id
    ? world.agents.find((a) => a.id === animal.owner_id && a.alive)
    : undefined;

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
              title={`LLM decisions route to ${maskName(model.profile)}`}
            >
              🧠 {maskName(model.profile)}
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

        {/* Row 4 (Wave H4 EM-209): bond indicator — only when owned by a
            living agent. Uses lab-* tokens only (token-guard compliant). */}
        {ownerAgent && (
          <div className="mt-1">
            <span
              className="font-mono text-[9px] text-lab-muted truncate block"
              title={`Adopted by ${ownerAgent.name}`}
            >
              🔗 {ownerAgent.name}{"'"}s pet
            </span>
          </div>
        )}
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
  // EM-202: how many `·`-tagged variants share each base name (≥2 ⇒ A/B group).
  const abCounts = abGroupCounts(world.agents);

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
        agents.map((agent) => {
          const parsed = parseAbName(agent.name);
          return (
            <AgentCard
              key={agent.id}
              agent={agent}
              world={world}
              abGroupSize={parsed ? (abCounts.get(parsed.base) ?? 0) : 0}
              selected={selected?.type === 'agent' && selected.id === agent.id}
              onSelect={onSelect}
            />
          );
        })
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
