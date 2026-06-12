/**
 * ControlPanel — start/pause/step, speed, inject-event,
 * and the marquee per-agent model reassign feature.
 *
 * W11b additions: the spawn form gains the persona-library picker (EM-092),
 * the god panel gains REPLY ON BILLBOARD (EM-091d, optimistic-free — the post
 * appears when the WS broadcasts it), and the ACTIVE RULES strip groups
 * identical-effect laws into one ×N row, expandable to instances (EM-087).
 *
 * Wave A.2 (EM-138): the god section reorganizes into the GOD CONSOLE — three
 * labeled groups: WORLD EVENTS (the inject controls), INTERVENE (bless/grant/
 * whisper on one living agent), and VOICE (the billboard reply).
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import type { WorldState, ModelProfile, Rule, SpawnSpec, SpawnMode, Agent } from '../../types';
import { PersonaPicker, usePersonaLibrary } from './PersonaPicker';
import { inspectorApi } from '../../inspector/api';
import type { PersonaRow, GodMiracleKind } from '../../inspector/api';

interface ControlPanelProps {
  world: WorldState | null;
  onStart: () => void;
  onPause: () => void;
  onStep: () => void;
  /** EM-084: destructive — rebuilds the world from config (a NEW RUN). */
  onReset: () => void;
  onSpeed: (seconds: number) => void;
  onReassign: (agentId: string, profile: string) => void;
  onInject: (kind?: string) => void;
  /** Ad-hoc spawn (W7 EM-063): god (immediate) or governance (proposal). */
  onSpawn: (spec: SpawnSpec) => void;
  /** W11b (EM-091d): god reply on the billboard (≤280 chars, no local echo). */
  onBillboardReply: (text: string) => void;
  /** W11b (EM-092): mock mode renders the persona picker's no-backend state. */
  mockMode: boolean;
  profiles: ModelProfile[];
}

const INJECT_KINDS = ['windfall', 'famine', 'blackout', 'festival'] as const;

function SpeedSlider({
  value,
  onChange,
  onDragStart,
  onDragEnd,
}: {
  value: number;
  onChange: (v: number) => void;
  /** D5: the parent suspends server re-sync while the user is mid-drag. */
  onDragStart?: () => void;
  onDragEnd?: () => void;
}) {
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
          onPointerDown={onDragStart}
          onPointerUp={onDragEnd}
          onPointerCancel={onDragEnd}
          onBlur={onDragEnd}
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

/**
 * SpawnForm (W7 EM-063) — the God-panel "conjure a villager" control.
 *
 * Fields: name, personality, profile (model), location (place), and mode
 * (god = appears now · governance = petitions for admission). Token-only
 * styling (lab-* utilities); the only inline styles are data-driven profile
 * colors on the swatch + select (mirrors the existing ReassignRow pattern, so
 * design-token-guard stays clean). On submit it calls onSpawn and flashes a
 * brief confirmation, then clears the name (ready for the next spawn).
 */
function SpawnForm({
  world,
  profiles,
  mockMode,
  onSpawn,
}: {
  world: WorldState | null;
  profiles: ModelProfile[];
  mockMode: boolean;
  onSpawn: (spec: SpawnSpec) => void;
}) {
  const places = world?.places ?? [];
  const availableProfiles = profiles.filter((p) => p.available !== false);
  const defaultProfile = availableProfiles[0]?.name ?? profiles[0]?.name ?? '';
  const defaultLocation = places[0]?.id ?? '';

  const [name, setName] = useState('');
  const [personality, setPersonality] = useState('');
  const [profile, setProfile] = useState(defaultProfile);
  const [location, setLocation] = useState(defaultLocation);
  const [mode, setMode] = useState<SpawnMode>('god');
  const [justSpawned, setJustSpawned] = useState<string | null>(null);

  // ── W11b (EM-092): persona picker state ─────────────────────────────────
  // Picking a card prefills name/personality/profile (still editable). The
  // spawn sends `persona` ONLY while the prefilled fields are untouched —
  // any edit flips to explicit fields (the backend honors explicit over
  // persona anyway; we just don't send a stale persona name).
  const personaState = usePersonaLibrary(mockMode);
  const [picked, setPicked] = useState<PersonaRow | null>(null);
  const [editedSincePick, setEditedSincePick] = useState(false);

  const handlePickPersona = useCallback((p: PersonaRow | null) => {
    setPicked(p);
    setEditedSincePick(false);
    if (p) {
      setName(p.name);
      setPersonality(p.personality);
      // Preselect the suggested profile only when this run actually has it.
      if (p.suggested_profile && profiles.some((m) => m.name === p.suggested_profile)) {
        setProfile(p.suggested_profile);
      }
    }
  }, [profiles]);

  /** Wraps a prefilled-field setter so edits invalidate the persona send. */
  const touch = useCallback(() => setEditedSincePick(true), []);

  // Keep the dropdowns valid if the world arrives after first render.
  if (!profile && defaultProfile) setProfile(defaultProfile);
  if (!location && defaultLocation) setLocation(defaultLocation);

  const selectedProfile = profiles.find((p) => p.name === profile);
  // Data-driven model color when known; null falls back to a lab token class
  // (no hardcoded hex literal — design-token-guard clean).
  const swatch = selectedProfile?.color ?? null;
  const canSpawn = name.trim().length > 0 && !!profile && !!location;
  const sendPersona = picked !== null && !editedSincePick;

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!canSpawn) return;
      onSpawn({
        name: name.trim(),
        personality: personality.trim(),
        profile,
        location,
        mode,
        // EM-092: persona name rides along only while untouched.
        ...(sendPersona && picked ? { persona: picked.name } : {}),
      });
      setJustSpawned(name.trim());
      setName('');
      setPersonality('');
      setPicked(null);
      setEditedSincePick(false);
      window.setTimeout(() => setJustSpawned(null), 2200);
    },
    [canSpawn, name, personality, profile, location, mode, onSpawn, sendPersona, picked],
  );

  return (
    <form className="p-2 space-y-2" onSubmit={handleSubmit} aria-label="Spawn a new agent">
      {/* W11b (EM-092): persona library cards — prefill, stay editable. */}
      <PersonaPicker
        state={personaState}
        selected={picked?.name ?? null}
        profiles={profiles}
        onPick={handlePickPersona}
      />
      {picked && (
        <p className="m-0 font-mono text-[9px] leading-snug" role="status">
          {sendPersona ? (
            <span className="text-lab-acid">
              spawning as persona “{picked.name}” — edit any field to go freeform
            </span>
          ) : (
            <span className="text-lab-muted">
              edited since picking “{picked.name}” — explicit fields will be sent
            </span>
          )}
        </p>
      )}

      {/* Name */}
      <div className="space-y-1">
        <label htmlFor="spawn-name" className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider">
          Name <span className="text-lab-acid">*</span>
        </label>
        <input
          id="spawn-name"
          type="text"
          value={name}
          onChange={(e) => { setName(e.target.value); touch(); }}
          placeholder="e.g. Fenn"
          maxLength={24}
          className="lab-input w-full text-[11px]"
          autoComplete="off"
        />
      </div>

      {/* Personality */}
      <div className="space-y-1">
        <label htmlFor="spawn-personality" className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider">
          Personality
        </label>
        <textarea
          id="spawn-personality"
          value={personality}
          onChange={(e) => { setPersonality(e.target.value); touch(); }}
          placeholder="Short persona (≤280 chars)…"
          maxLength={280}
          rows={2}
          className="lab-input w-full text-[11px] resize-none leading-snug"
        />
      </div>

      {/* Profile (model) */}
      <div className="space-y-1">
        <label htmlFor="spawn-profile" className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider">
          Model profile <span className="text-lab-acid">*</span>
        </label>
        <div className="flex items-center gap-1.5">
          <span
            className={`w-3 h-3 rounded-full shrink-0 border ${swatch ? '' : 'bg-lab-muted border-lab-muted'}`}
            style={swatch ? { backgroundColor: swatch, borderColor: swatch } : undefined}
            aria-hidden="true"
          />
          <select
            id="spawn-profile"
            value={profile}
            onChange={(e) => { setProfile(e.target.value); touch(); }}
            className={`lab-select flex-1 text-[10px] ${swatch ? '' : 'text-lab-text'}`}
            style={swatch ? { color: swatch } : undefined}
          >
            {profiles.map((p) => (
              <option key={p.name} value={p.name} style={{ color: p.color }}>
                {p.name}
                {p.available === false ? ' (unavail)' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Location */}
      <div className="space-y-1">
        <label htmlFor="spawn-location" className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider">
          Spawn at <span className="text-lab-acid">*</span>
        </label>
        <select
          id="spawn-location"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className="lab-select w-full text-[10px]"
        >
          {places.length === 0 && <option value="">—</option>}
          {places.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      {/* Mode toggle */}
      <div className="space-y-1">
        <span className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider">Mode</span>
        <div className="grid grid-cols-2 gap-1" role="radiogroup" aria-label="Spawn mode">
          {(['god', 'governance'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              role="radio"
              aria-checked={mode === m}
              className={
                mode === m
                  ? 'font-mono text-[10px] uppercase tracking-wide px-2 py-1 border border-lab-acid text-lab-acid bg-lab-acid/10 rounded-sm transition-colors'
                  : 'font-mono text-[10px] uppercase tracking-wide px-2 py-1 border border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid rounded-sm transition-colors'
              }
              title={m === 'god' ? 'Appears immediately' : 'Petitions for admission (vote)'}
            >
              {m === 'god' ? '⚡ GOD' : '⚖ GOV'}
            </button>
          ))}
        </div>
        <p className="font-mono text-[9px] text-lab-dim leading-snug">
          {mode === 'god'
            ? 'Appears now at the chosen place.'
            : 'Enqueues an admit_agent proposal; admitted iff the vote passes.'}
        </p>
      </div>

      {/* Submit */}
      <button
        type="submit"
        className="lab-btn lab-btn-primary w-full"
        disabled={!canSpawn}
        aria-label="Spawn agent"
      >
        ✚ SPAWN AGENT
      </button>
      {justSpawned && (
        <p
          className="font-mono text-[10px] text-lab-acid text-center animate-flash"
          role="status"
          aria-live="polite"
        >
          {mode === 'governance'
            ? `${justSpawned} petitions to join…`
            : `${justSpawned} joined the village.`}
        </p>
      )}
    </form>
  );
}

/**
 * BillboardReply (W11b EM-091d) — "REPLY ON BILLBOARD": the god affordance
 * that answers agent petitions on the notice board. ≤280 chars; the send is
 * OPTIMISTIC-FREE by contract — no local echo, the post appears when the
 * backend broadcasts the billboard_posted (actor_type:"god") WS event.
 */
function BillboardReply({ onPost }: { onPost: (text: string) => void }) {
  const [text, setText] = useState('');
  const [sent, setSent] = useState(false);
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
  }, []);

  const trimmed = text.trim();
  const canSend = trimmed.length > 0;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSend) return;
    onPost(trimmed);
    setText('');
    setSent(true);
    if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
    sentTimerRef.current = setTimeout(() => setSent(false), 3000);
  };

  return (
    <form className="p-2 space-y-1.5" onSubmit={handleSubmit} aria-label="Reply on the village billboard">
      <div className="flex items-baseline justify-between">
        <label
          htmlFor="billboard-reply"
          className="font-mono text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--lab-god-bright)' }}
        >
          📌 Reply on billboard
        </label>
        <span className="font-mono text-[9px] text-lab-dim tabular-nums" aria-hidden="true">
          {text.length}/280
        </span>
      </div>
      <textarea
        id="billboard-reply"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Answer the village's petitions…"
        maxLength={280}
        rows={2}
        className="lab-input w-full text-[11px] resize-none leading-snug"
      />
      <button
        type="submit"
        className="lab-btn lab-btn-secondary w-full"
        disabled={!canSend}
        aria-label="Post the god reply to the billboard"
      >
        ✦ POST TO BOARD
      </button>
      {sent ? (
        <p className="m-0 font-mono text-[9px] text-lab-acid leading-snug" role="status" aria-live="polite">
          sent — it appears on the board when the world broadcasts it (no local echo).
        </p>
      ) : (
        <p className="m-0 font-mono text-[9px] text-lab-dim leading-snug">
          Agents read the board at the plaza &amp; town hall; your ink shows as ✦ god.
        </p>
      )}
    </form>
  );
}

/**
 * GodGroupLabel (Wave A.2 EM-138) — one GOD CONSOLE group heading, in the
 * established god ink (the --lab-god-* tokens BillboardReply already wears).
 */
function GodGroupLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="px-2 pt-2 font-mono text-[9px] font-semibold uppercase tracking-widest"
      style={{ color: 'var(--lab-god-bright)' }}
      role="heading"
      aria-level={3}
    >
      {children}
    </div>
  );
}

/**
 * GodIntervene (Wave A.2 EM-136/137/138) — the GOD CONSOLE's INTERVENE group:
 * pick a LIVING agent, then BLESS (+25 energy), GRANT (+10 credits), or
 * WHISPER a one-shot line (≤280) into their next context. OPTIMISTIC-FREE
 * like the billboard reply — no local echo; the god_intervention /
 * whisper_posted event arrives via the WS feed. Buttons disable while a
 * request is in flight; failures render inline via the labeled-result idiom
 * (godIntervene/godWhisper never throw).
 */
function GodIntervene({ agents }: { agents: Agent[] }) {
  const [agentId, setAgentId] = useState('');
  const [whisper, setWhisper] = useState('');
  const [busy, setBusy] = useState<null | 'bless' | 'grant' | 'whisper'>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
  }, []);

  // Living-agents only by contract; a death (or world arriving late) falls
  // back to the first living agent rather than holding a stale selection.
  const selectedId = agents.some((a) => a.id === agentId) ? agentId : (agents[0]?.id ?? '');
  const selected = agents.find((a) => a.id === selectedId);
  const canWhisper = whisper.trim().length > 0;

  const runAction = useCallback(
    async (action: 'bless' | 'grant' | 'whisper') => {
      if (!selectedId || busy) return;
      setBusy(action);
      setError(null);
      setSent(null);
      const result =
        action === 'whisper'
          ? await inspectorApi.godWhisper(selectedId, whisper)
          : await inspectorApi.godIntervene(
              action === 'bless' ? 'bless_energy' : 'grant_credits',
              selectedId,
            );
      setBusy(null);
      if (result.ok) {
        if (action === 'whisper') setWhisper('');
        setSent(
          action === 'whisper'
            ? 'whispered — it rides their next turn (no local echo).'
            : 'done — the ✦ god event arrives via the feed (no local echo).',
        );
        if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
        sentTimerRef.current = setTimeout(() => setSent(null), 3000);
      } else {
        setError(result.message);
      }
    },
    [selectedId, busy, whisper],
  );

  if (agents.length === 0) {
    return (
      <div className="p-2 font-mono text-xs text-lab-dim text-center">
        NO LIVE AGENTS
      </div>
    );
  }

  return (
    <div className="p-2 space-y-1.5">
      {/* Target agent — living only. */}
      <select
        value={selectedId}
        onChange={(e) => setAgentId(e.target.value)}
        className="lab-select w-full text-[10px]"
        aria-label="Agent to intervene on"
      >
        {agents.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} · ⚡{Math.round(a.energy)} · ₡{a.credits}
          </option>
        ))}
      </select>

      {/* BLESS / GRANT — amounts are the backend defaults (+25 / +10). */}
      <div className="grid grid-cols-2 gap-1.5">
        <button
          type="button"
          className="lab-btn lab-btn-secondary"
          onClick={() => void runAction('bless')}
          disabled={busy !== null}
          aria-label={`Bless ${selected?.name ?? 'the agent'} with +25 energy`}
        >
          {busy === 'bless' ? '…' : '☀ BLESS +25⚡'}
        </button>
        <button
          type="button"
          className="lab-btn lab-btn-secondary"
          onClick={() => void runAction('grant')}
          disabled={busy !== null}
          aria-label={`Grant ${selected?.name ?? 'the agent'} +10 credits`}
        >
          {busy === 'grant' ? '…' : '✦ GRANT +10₡'}
        </button>
      </div>

      {/* WHISPER — one-shot context injection, billboard-capped at 280. */}
      <div className="flex items-baseline justify-between">
        <label
          htmlFor="god-whisper"
          className="font-mono text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--lab-god-bright)' }}
        >
          🜁 Whisper
        </label>
        <span className="font-mono text-[9px] text-lab-dim tabular-nums" aria-hidden="true">
          {whisper.length}/280
        </span>
      </div>
      <textarea
        id="god-whisper"
        value={whisper}
        onChange={(e) => setWhisper(e.target.value)}
        placeholder="A voice only they can hear…"
        maxLength={280}
        rows={2}
        className="lab-input w-full text-[11px] resize-none leading-snug"
      />
      <button
        type="button"
        className="lab-btn lab-btn-secondary w-full"
        onClick={() => void runAction('whisper')}
        disabled={busy !== null || !canWhisper}
        aria-label={`Whisper to ${selected?.name ?? 'the agent'}`}
      >
        {busy === 'whisper' ? '…' : '🜁 WHISPER'}
      </button>

      {error && (
        <p role="alert" className="m-0 font-mono text-[9px] text-lab-warn leading-snug">
          ⚠ {error}
        </p>
      )}
      {sent && (
        <p className="m-0 font-mono text-[9px] text-lab-acid leading-snug" role="status" aria-live="polite">
          {sent}
        </p>
      )}
    </div>
  );
}

/**
 * GodMiracles (Wave E EM-184/185) — the INTERVENE group's MIRACLES row:
 * pick one of the three WORLD-scale miracle kinds and CAST it. World kinds
 * take no target — the api client posts {kind} with NO agent_id key (the
 * backend 422s a world kind carrying one). OPTIMISTIC-FREE like the rest of
 * the console: the god_miracle event (actor 'god', whole town perceives it)
 * arrives via the WS feed; failures render inline via the labeled-result
 * idiom (godMiracle never throws).
 */
const MIRACLE_KINDS: Array<{ kind: GodMiracleKind; label: string }> = [
  { kind: 'send_rain', label: '🌧 Send rain — forage flourishes' },
  { kind: 'bountiful_harvest', label: '🌾 Bountiful harvest — decay halves' },
  { kind: 'calm_spirits', label: '🕊 Calm spirits — hope + trust' },
];

function GodMiracles() {
  const [kind, setKind] = useState<GodMiracleKind>('send_rain');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
  }, []);

  const cast = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    setSent(false);
    const result = await inspectorApi.godMiracle(kind);
    setBusy(false);
    if (result.ok) {
      setSent(true);
      if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
      sentTimerRef.current = setTimeout(() => setSent(false), 3000);
    } else {
      setError(result.message);
    }
  }, [busy, kind]);

  return (
    <div className="px-2 pb-2 space-y-1.5">
      <span
        className="block font-mono text-[10px] uppercase tracking-wider"
        style={{ color: 'var(--lab-god-bright)' }}
      >
        🌧 Miracles
      </span>
      <div className="flex gap-1.5">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as GodMiracleKind)}
          className="lab-select flex-1 text-[10px]"
          aria-label="Miracle to cast"
        >
          {MIRACLE_KINDS.map((m) => (
            <option key={m.kind} value={m.kind}>{m.label}</option>
          ))}
        </select>
        <button
          type="button"
          className="lab-btn lab-btn-secondary px-2"
          onClick={() => void cast()}
          disabled={busy}
          aria-label="Cast the miracle"
          title="World-scale — the whole town perceives the god_miracle event"
        >
          {busy ? '…' : 'CAST'}
        </button>
      </div>
      {error && (
        <p role="alert" className="m-0 font-mono text-[9px] text-lab-warn leading-snug">
          ⚠ {error}
        </p>
      )}
      {sent && (
        <p className="m-0 font-mono text-[9px] text-lab-acid leading-snug" role="status" aria-live="polite">
          cast — the whole town perceives it via the feed (no local echo).
        </p>
      )}
    </div>
  );
}

/**
 * GroupedActiveRules (W11b EM-087) — the live rules strip. Identical-effect
 * ACTIVE rules collapse into ONE row with a ×N stack badge; expanding it
 * lists the instances (tick + proposer). Pairs with the backend's
 * renewal-not-stacking semantics — and renders historical stacks (the 3×UBI
 * runs) sanely too.
 */
function GroupedActiveRules({ rules, world }: { rules: Rule[]; world: WorldState | null }) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  const nameOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of world?.agents ?? []) m.set(a.id, a.name);
    return m;
  }, [world]);

  const groups = useMemo(() => {
    const byEffect = new Map<string, Rule[]>();
    for (const r of rules) {
      const list = byEffect.get(r.effect) ?? [];
      list.push(r);
      byEffect.set(r.effect, list);
    }
    return [...byEffect.entries()];
  }, [rules]);

  const toggle = (effect: string) =>
    setExpanded((cur) => {
      const next = new Set(cur);
      if (next.has(effect)) next.delete(effect);
      else next.add(effect);
      return next;
    });

  return (
    <>
      {groups.map(([effect, instances]) => {
        const label = effect.toUpperCase().replace(/_/g, ' ');
        const stacked = instances.length > 1;
        const open = expanded.has(effect);
        return (
          <div key={effect} className="border-l-2 border-lab-acid pl-2 py-0.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[10px] text-lab-acid">{label}</span>
              {stacked && (
                <button
                  type="button"
                  onClick={() => toggle(effect)}
                  aria-expanded={open}
                  aria-label={`${label}: ${instances.length} identical active rules — ${open ? 'collapse' : 'expand'} the instances`}
                  title={`${instances.length} identical-effect rules are active (renewals extend, they shouldn't stack) — click for instances`}
                  className="font-mono text-[9px] font-bold px-1 py-px border border-lab-acid text-lab-acid
                             bg-lab-acid/10 rounded-sm cursor-pointer hover:bg-lab-acid/20 transition-colors"
                >
                  ×{instances.length} {open ? '▾' : '▸'}
                </button>
              )}
            </div>
            {stacked && open && (
              <ul className="m-0 mt-0.5 p-0 list-none space-y-0.5">
                {instances.map((r) => (
                  <li key={r.id} className="font-mono text-[9px] text-lab-muted leading-snug">
                    <span className="text-lab-dim">└─</span> T{r.created_tick} ·{' '}
                    {nameOf.get(r.proposer_id) ?? r.proposer_id}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </>
  );
}

export function ControlPanel({
  world,
  onStart,
  onPause,
  onStep,
  onReset,
  onSpeed,
  onReassign,
  onInject,
  onSpawn,
  onBillboardReply,
  mockMode,
  profiles,
}: ControlPanelProps) {
  const [speed, setSpeed] = useState(world?.tick_interval_seconds ?? 2);
  const [injectKind, setInjectKind] = useState<string>('');

  // EM-084: two-click destructive confirm for RESET WORLD (no browser
  // confirm()): the first click arms it ("⚠ CONFIRM RESET"), a second click
  // within the window fires onReset, and the arm auto-cancels after 3s.
  const [confirmingReset, setConfirmingReset] = useState(false);
  const confirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleReset = useCallback(() => {
    if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
    if (!confirmingReset) {
      setConfirmingReset(true);
      confirmTimerRef.current = setTimeout(() => setConfirmingReset(false), 3000);
      return;
    }
    confirmTimerRef.current = null;
    setConfirmingReset(false);
    onReset();
  }, [confirmingReset, onReset]);
  useEffect(() => () => {
    if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
  }, []);

  // D5: the speed label/slider DERIVE from the server's tick_interval_seconds
  // (the world_state broadcast is the source of truth) — they re-sync whenever
  // a fresh world_state changes it (another client, auto-throttle, a reset).
  // While the user is actively dragging, local intent wins; on release the
  // next server broadcast (the ack) is truth again.
  const serverInterval = world?.tick_interval_seconds;
  const draggingRef = useRef(false);
  useEffect(() => {
    if (serverInterval !== undefined && !draggingRef.current) {
      setSpeed(serverInterval);
    }
  }, [serverInterval]);

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
          <SpeedSlider
            value={speed}
            onChange={handleSpeed}
            onDragStart={() => { draggingRef.current = true; }}
            onDragEnd={() => { draggingRef.current = false; }}
          />
        </div>

        {/* EM-084: NEW RUN — destructive, two-click confirm (auto-cancels). */}
        <button
          className={`lab-btn lab-btn-danger w-full ${confirmingReset ? 'bg-lab-danger/20' : ''}`}
          onClick={handleReset}
          aria-label={confirmingReset ? 'Confirm: reset the world' : 'Reset the world (new run)'}
          title="Rebuild the world from config — current run ends. Click twice to confirm."
        >
          {confirmingReset ? '⚠ CONFIRM RESET' : '⟲ RESET WORLD'}
        </button>
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

      {/* ── GOD CONSOLE (Wave A.2 EM-138): three labeled groups ──── */}
      <div className="lab-header mt-0.5 flex items-center justify-between border-t-2 border-t-lab-god">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase text-lab-god-bright">✦ GOD CONSOLE</h2>
        <span className="font-mono text-[9px] text-lab-muted opacity-70">WORLD · INTERVENE · VOICE</span>
      </div>

      {/* Group 1 — WORLD EVENTS: the inject controls, unchanged behavior. */}
      <GodGroupLabel>WORLD EVENTS</GodGroupLabel>
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

      {/* Group 2 — INTERVENE: bless/grant/whisper one living agent (EM-136/137),
          plus the Wave-E MIRACLES row (EM-184: world-scale, no target). */}
      <div className="border-t border-lab-border/60 mx-1" aria-hidden="true" />
      <GodGroupLabel>INTERVENE</GodGroupLabel>
      <GodIntervene agents={liveAgents} />
      <GodMiracles />

      {/* Group 3 — VOICE: the billboard reply (W11b EM-091d), behavior unchanged. */}
      <div className="border-t border-lab-border/60 mx-1" aria-hidden="true" />
      <GodGroupLabel>VOICE</GodGroupLabel>
      <BillboardReply onPost={onBillboardReply} />

      {/* ── God Panel: spawn a villager (W7 EM-063) ──────────────── */}
      <div className="lab-header mt-0.5 flex items-center justify-between border-t-2 border-t-lab-god">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase text-lab-god-bright">✦ GOD PANEL</h2>
        <span className="font-mono text-[9px] text-lab-muted opacity-70">SPAWN</span>
      </div>
      <SpawnForm world={world} profiles={profiles} mockMode={mockMode} onSpawn={onSpawn} />

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

      {/* ── Active Rules — identical-effect laws group into ×N (EM-087) ── */}
      {world && world.rules.length > 0 && (
        <>
          <div className="lab-header mt-0.5">ACTIVE RULES</div>
          <div className="p-2 space-y-1">
            <GroupedActiveRules
              rules={world.rules.filter(r => r.status === 'active')}
              world={world}
            />
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
