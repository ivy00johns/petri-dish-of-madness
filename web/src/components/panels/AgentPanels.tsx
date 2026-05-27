/**
 * AgentPanels — vertical stack of per-agent cards.
 * Each card: name, model badge (profile + color), energy bar,
 * credits, mood, top 3 relationships.
 */

import type { Agent, WorldState } from '../../types';

interface AgentPanelsProps {
  world: WorldState | null;
}

interface AgentCardProps {
  agent: Agent;
  world: WorldState;
}

function EnergyBar({ value, color }: { value: number; color: string }) {
  const pct = Math.max(0, Math.min(100, value));
  const barColor = pct > 60 ? color : pct > 25 ? '#ff9900' : '#ff3333';

  return (
    <div className="flex items-center gap-1.5">
      <div className="energy-bar-track flex-1 h-1.5">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: barColor }}
        />
      </div>
      <span
        className="font-mono text-[10px] tabular-nums w-7 text-right"
        style={{ color: barColor }}
      >
        {Math.round(pct)}
      </span>
    </div>
  );
}

function RelationshipTag({
  type,
  trust,
}: {
  type: string;
  trust: number;
}) {
  const COLOR: Record<string, string> = {
    ally:    '#27ae60',
    friend:  '#3498db',
    neutral: '#5a5a72',
    rival:   '#ff9900',
    enemy:   '#ff3333',
  };
  const c = COLOR[type] ?? '#5a5a72';
  return (
    <span
      className="font-mono text-[9px] px-1 py-px border rounded-sm"
      style={{ color: c, borderColor: c + '60', backgroundColor: c + '18' }}
    >
      {type.toUpperCase()} {trust > 0 ? `+${trust}` : trust}
    </span>
  );
}

function AgentCard({ agent, world }: AgentCardProps) {
  const color = agent.profile_color ?? '#888888';
  const isAlive = agent.alive;

  // Top 3 relationships sorted by |trust| desc
  const topRels = Object.entries(agent.relationships)
    .sort((a, b) => Math.abs(b[1].trust) - Math.abs(a[1].trust))
    .slice(0, 3);

  const getAgentName = (id: string) =>
    world.agents.find(a => a.id === id)?.name ?? id;

  return (
    <div
      className={`lab-panel relative transition-all duration-300 ${!isAlive ? 'opacity-40' : ''}`}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between px-3 pt-2 pb-1">
        <div className="flex items-center gap-2 min-w-0">
          {/* Colored initial circle */}
          <div
            className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 font-mono text-[10px] font-bold"
            style={{
              backgroundColor: color + '30',
              border: `1.5px solid ${color}`,
              color,
            }}
          >
            {agent.name.slice(0, 2).toUpperCase()}
          </div>
          <span className="font-mono text-xs font-semibold text-lab-text truncate">
            {agent.name}
          </span>
          {!isAlive && (
            <span className="font-mono text-[9px] text-lab-danger border border-lab-danger px-1">
              DEAD
            </span>
          )}
        </div>

        {/* Model badge — the key identity signal */}
        <div
          className="flex-none font-mono text-[9px] font-semibold px-1.5 py-0.5 border rounded-sm tracking-wider"
          style={{
            backgroundColor: color + '22',
            borderColor: color + '80',
            color,
          }}
          title={agent.profile}
        >
          {agent.profile}
        </div>
      </div>

      {/* Stats */}
      <div className="px-3 pb-1 space-y-1">
        {/* Energy */}
        <div className="flex items-center gap-1">
          <span className="font-mono text-[9px] text-lab-muted w-12 shrink-0">ENERGY</span>
          <EnergyBar value={agent.energy} color={color} />
        </div>

        {/* Credits + Mood */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <span className="font-mono text-[9px] text-lab-muted">¢</span>
            <span className="font-mono text-[10px] text-lab-acid font-semibold tabular-nums">
              {agent.credits}
            </span>
          </div>
          <div className="flex items-center gap-1 min-w-0">
            <span className="font-mono text-[9px] text-lab-muted shrink-0">MOOD</span>
            <span className="font-mono text-[10px] text-lab-text truncate" style={{ color: color + 'cc' }}>
              {agent.mood}
            </span>
          </div>
        </div>
      </div>

      {/* Relationships */}
      {topRels.length > 0 && (
        <div className="px-3 pb-2 flex flex-wrap gap-1">
          {topRels.map(([targetId, rel]) => (
            <div key={targetId} className="flex items-center gap-1">
              <span className="font-mono text-[9px] text-lab-muted">{getAgentName(targetId)}:</span>
              <RelationshipTag type={rel.type} trust={rel.trust} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AgentPanels({ world }: AgentPanelsProps) {
  if (!world) {
    return (
      <div className="flex flex-col h-full">
        <div className="lab-header">AGENTS</div>
        <div className="flex-1 flex items-center justify-center font-mono text-xs text-lab-dim">
          NO DATA
        </div>
      </div>
    );
  }

  const sorted = [...world.agents].sort((a, b) => {
    // Alive first, then by name
    if (a.alive !== b.alive) return a.alive ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div className="flex flex-col h-full">
      <div className="lab-header flex items-center justify-between">
        <span>AGENTS</span>
        <span className="text-lab-muted text-[10px]">
          {world.agents.filter(a => a.alive).length}/{world.agents.length} ALIVE
        </span>
      </div>
      <div className="flex-1 overflow-y-auto space-y-0.5 p-1">
        {sorted.map(agent => (
          <AgentCard key={agent.id} agent={agent} world={world} />
        ))}
      </div>
    </div>
  );
}
