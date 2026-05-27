/**
 * ControlPanel — start/pause/step, speed, inject-event,
 * and the marquee per-agent model reassign feature.
 */

import { useState, useCallback } from 'react';
import type { WorldState, ModelProfile } from '../../types';

interface ControlPanelProps {
  world: WorldState | null;
  onStart: () => void;
  onPause: () => void;
  onStep: () => void;
  onSpeed: (seconds: number) => void;
  onReassign: (agentId: string, profile: string) => void;
  onInject: (kind?: string) => void;
  profiles: ModelProfile[];
}

const INJECT_KINDS = ['windfall', 'famine', 'blackout', 'festival'] as const;

function SpeedSlider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  // Tick interval: 0.5s → 10s mapped to slider 0→100
  const toSlider = (v: number) => {
    const logMin = Math.log(0.5);
    const logMax = Math.log(10);
    return ((Math.log(v) - logMin) / (logMax - logMin)) * 100;
  };
  const fromSlider = (s: number) => {
    const logMin = Math.log(0.5);
    const logMax = Math.log(10);
    return Math.exp(logMin + (s / 100) * (logMax - logMin));
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-lab-muted uppercase tracking-wider">Speed</span>
        <span className="font-mono text-[10px] text-lab-acid tabular-nums">
          {value.toFixed(1)}s / tick
        </span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-[9px] text-lab-dim">FAST</span>
        <input
          type="range"
          min={0}
          max={100}
          value={toSlider(value)}
          onChange={e => onChange(parseFloat(fromSlider(Number(e.target.value)).toFixed(1)))}
          className="flex-1 h-1 appearance-none bg-lab-chrome rounded cursor-pointer
                     [&::-webkit-slider-thumb]:appearance-none
                     [&::-webkit-slider-thumb]:w-3
                     [&::-webkit-slider-thumb]:h-3
                     [&::-webkit-slider-thumb]:rounded-full
                     [&::-webkit-slider-thumb]:bg-lab-acid
                     [&::-webkit-slider-thumb]:cursor-pointer"
          aria-label="Tick interval in seconds"
        />
        <span className="font-mono text-[9px] text-lab-dim">SLOW</span>
      </div>
    </div>
  );
}

interface ReassignRowProps {
  agentId: string;
  agentName: string;
  currentProfile: string;
  currentColor: string;
  profiles: ModelProfile[];
  onReassign: (agentId: string, profile: string) => void;
}

function ReassignRow({
  agentId,
  agentName,
  currentProfile,
  currentColor,
  profiles,
  onReassign,
}: ReassignRowProps) {
  const [selected, setSelected] = useState(currentProfile);
  const [flashing, setFlashing] = useState(false);

  const handleChange = useCallback(
    (profile: string) => {
      setSelected(profile);
      onReassign(agentId, profile);
      setFlashing(true);
      setTimeout(() => setFlashing(false), 400);
    },
    [agentId, onReassign],
  );

  const selectedProfile = profiles.find(p => p.name === selected);
  const displayColor = selectedProfile?.color ?? currentColor;

  return (
    <div
      className={`flex items-center gap-2 py-1.5 px-2 border-b border-lab-border/30
                  transition-colors duration-300
                  ${flashing ? 'bg-lab-acid/10' : ''}`}
    >
      {/* Agent indicator */}
      <div
        className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 font-mono text-[9px] font-bold"
        style={{
          backgroundColor: displayColor + '30',
          border: `1.5px solid ${displayColor}`,
          color: displayColor,
        }}
      >
        {agentName.slice(0, 2).toUpperCase()}
      </div>

      {/* Agent name */}
      <span className="font-mono text-[10px] text-lab-text font-semibold w-10 shrink-0">
        {agentName}
      </span>

      {/* Model dropdown */}
      <div className="relative flex-1 min-w-0">
        <select
          value={selected}
          onChange={e => handleChange(e.target.value)}
          className="lab-select w-full pr-5 text-[10px]"
          style={{ color: displayColor }}
          aria-label={`Assign model to ${agentName}`}
        >
          {profiles.map(p => (
            <option key={p.name} value={p.name} style={{ color: p.color }}>
              {p.name}
              {!p.available ? ' (unavail)' : ''}
            </option>
          ))}
        </select>
        {/* Arrow indicator */}
        <div
          className="absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none font-mono text-[8px]"
          style={{ color: displayColor }}
        >
          ▼
        </div>
      </div>
    </div>
  );
}

export function ControlPanel({
  world,
  onStart,
  onPause,
  onStep,
  onSpeed,
  onReassign,
  onInject,
  profiles,
}: ControlPanelProps) {
  const [speed, setSpeed] = useState(world?.tick_interval_seconds ?? 2);
  const [injectKind, setInjectKind] = useState<string>('');

  const handleSpeed = (v: number) => {
    setSpeed(v);
    onSpeed(v);
  };

  const running = world?.running ?? false;
  const liveAgents = world?.agents.filter(a => a.alive) ?? [];

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* ── Playback Controls ───────────────────────────────────── */}
      <div className="lab-header">PLAYBACK</div>
      <div className="p-2 space-y-2">
        <div className="flex gap-1.5">
          <button
            className={`lab-btn flex-1 ${running ? 'lab-btn-secondary' : 'lab-btn-primary'}`}
            onClick={onStart}
            disabled={running}
            aria-label="Start simulation"
          >
            ▶ START
          </button>
          <button
            className={`lab-btn flex-1 ${!running ? 'lab-btn-secondary' : 'lab-btn-secondary'}`}
            onClick={onPause}
            disabled={!running}
            aria-label="Pause simulation"
          >
            ⏸ PAUSE
          </button>
        </div>
        <button
          className="lab-btn lab-btn-secondary w-full"
          onClick={onStep}
          aria-label="Step one tick"
        >
          ⏭ STEP ONE TICK
        </button>

        {/* Speed */}
        <div className="pt-1">
          <SpeedSlider value={speed} onChange={handleSpeed} />
        </div>
      </div>

      {/* ── Model Reassign — THE MARQUEE FEATURE ─────────────── */}
      <div
        className="lab-header mt-0.5 flex items-center justify-between"
        style={{ borderColor: '#c8ff00', borderTopWidth: '2px' }}
      >
        <span style={{ color: '#c8ff00' }}>⇄ MODEL REASSIGN</span>
        <span className="font-mono text-[9px] text-lab-acid opacity-70">LIVE SWAP</span>
      </div>

      {/* Prominent section — acid green border accent */}
      <div className="border border-lab-acid/20 mx-1 mb-1">
        {liveAgents.length === 0 ? (
          <div className="font-mono text-xs text-lab-dim py-3 text-center">
            NO LIVE AGENTS
          </div>
        ) : (
          liveAgents.map(agent => (
            <ReassignRow
              key={agent.id}
              agentId={agent.id}
              agentName={agent.name}
              currentProfile={agent.profile}
              currentColor={agent.profile_color ?? '#888888'}
              profiles={profiles}
              onReassign={onReassign}
            />
          ))
        )}
      </div>

      {/* ── Inject Event ────────────────────────────────────────── */}
      <div className="lab-header mt-0.5">CHAOS KNOB</div>
      <div className="p-2 space-y-1.5">
        <div className="flex gap-1.5">
          <select
            value={injectKind}
            onChange={e => setInjectKind(e.target.value)}
            className="lab-select flex-1 text-[10px]"
            aria-label="Event type to inject"
          >
            <option value="">Random event</option>
            {INJECT_KINDS.map(k => (
              <option key={k} value={k}>{k.charAt(0).toUpperCase() + k.slice(1)}</option>
            ))}
          </select>
          <button
            className="lab-btn lab-btn-danger px-2"
            onClick={() => onInject(injectKind || undefined)}
            aria-label="Inject random event"
            title="Inject a world event"
          >
            ⊕
          </button>
        </div>
        <button
          className="lab-btn lab-btn-danger w-full"
          onClick={() => onInject(injectKind || undefined)}
        >
          INJECT EVENT
        </button>
      </div>

      {/* ── Status ──────────────────────────────────────────────── */}
      {world && (
        <>
          <div className="lab-header mt-0.5">STATUS</div>
          <div className="p-2 space-y-1">
            {[
              ['TICK',  String(world.tick)],
              ['DAY',   String(world.day)],
              ['STATE', world.running ? 'RUNNING' : 'PAUSED'],
              ['ALIVE', `${liveAgents.length}/${world.agents.length}`],
              ['RULES', `${world.rules.filter(r => r.status === 'active').length} ACTIVE`],
            ].map(([label, value]) => (
              <div key={label} className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-lab-muted">{label}</span>
                <span
                  className="font-mono text-[10px] tabular-nums"
                  style={{
                    color:
                      label === 'STATE'
                        ? world.running ? '#27ae60' : '#ff9900'
                        : '#e8e8f0',
                  }}
                >
                  {value}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── Active Rules ────────────────────────────────────────── */}
      {world && world.rules.length > 0 && (
        <>
          <div className="lab-header mt-0.5">ACTIVE RULES</div>
          <div className="p-2 space-y-1">
            {world.rules.filter(r => r.status === 'active').map(rule => (
              <div
                key={rule.id}
                className="font-mono text-[10px] text-lab-acid border-l-2 border-lab-acid pl-2 py-0.5"
              >
                {rule.effect.toUpperCase().replace('_', ' ')}
              </div>
            ))}
            {world.rules.filter(r => r.status === 'proposed').map(rule => (
              <div
                key={rule.id}
                className="font-mono text-[10px] text-lab-warn border-l-2 border-lab-warn pl-2 py-0.5"
              >
                PROPOSED: {rule.effect.replace('_', ' ')}
                <br />
                <span className="text-lab-muted">
                  {Object.values(rule.votes).filter(Boolean).length} yes / {Object.values(rule.votes).filter(v => !v).length} no
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
