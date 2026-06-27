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
 * whisper on one living agent), and VOICE (the billboard reply + the LOUD
 * proclamation — a decree that rides every agent's next prompt).
 */

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import type { WorldState, ModelProfile, Rule, SpawnSpec, SpawnMode, Agent } from '../../types';
import { PersonaPicker, usePersonaLibrary } from './PersonaPicker';
import { inspectorApi } from '../../inspector/api';
import type { PersonaRow, GodMiracleKind } from '../../inspector/api';
import { AnimalSpawnForm } from './AnimalSpawnForm';
import type { AnimalSpawnSpec } from './AnimalSpawnForm';
// Wave K (EM-221): the named building-skin palette (Wave 1) drives the reskin
// picker's options. SKIN_PALETTES keys are the canonical skin names.
import { SKIN_PALETTES } from '../world3d/worldSpace';
// Token sources for the dynamic inline colors below (STATE row reads
// --rel-ally / --lab-warn / --lab-text; the reassign swatch falls back to the
// neutral). Imported here so these vars resolve no matter the mount order —
// design-token-guard stays clean (no hardcoded hex in this module).
import '../../inspector/inspector-tokens.css';
import '../panels/roster-tokens.css';

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
  /** EM-143: spawn an animal from the MENAGERIE god panel. */
  onSpawnAnimal: (spec: AnimalSpawnSpec) => void;
  /**
   * EM-207 H2: REWILD burst — spawn count random catalog critters. Returns
   * {spawned, cap_reached} so the panel can flash a confirmation.
   */
  onRewild: (count?: number) => Promise<{ spawned: number; cap_reached: boolean }>;
  /**
   * EM-208 H3: ZOO ESCAPE — triggers an escape from the operational zoo.
   * Returns {escaped, zoos} so the panel can flash a confirmation.
   */
  onZooEscape: (zooBuildingId?: string) => Promise<{ escaped: number; zoos: number }>;
  /**
   * Wave K (EM-221): BUILDERS god console. Each mirrors the rewild/zoo
   * flash-confirmation pattern. Optional so callers/tests that predate Wave K
   * stay valid — the BUILDERS group only renders when onPlaceProp is wired.
   */
  onPlaceProp?: (spec: { kind: string; place: string; count?: number }) => Promise<{ placed: number }>;
  onClearProps?: (place?: string) => Promise<{ cleared: number }>;
  onDemolish?: (buildingId: string) => Promise<{ demolished: boolean }>;
  onReskin?: (buildingId: string, skin: string) => Promise<{ reskinned: boolean }>;
  /** W11b (EM-091d): god reply on the billboard (≤280 chars, no local echo). */
  onBillboardReply: (text: string) => void;
  /** W11b (EM-092): mock mode renders the persona picker's no-backend state. */
  mockMode: boolean;
  profiles: ModelProfile[];
}

const INJECT_KINDS = ['windfall', 'famine', 'blackout', 'festival'] as const;

/**
 * Read a declared CSS custom property (mirrors the inspector's `cssVar`).
 * Returns '' when there is no DOM (SSR / jsdom tests), so callers fall through
 * to a token-referencing default rather than a hardcoded hex.
 */
function cssVar(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * The neutral swatch color for an agent with no model color yet. Resolves the
 * declared `--inspector-node-neutral` token at runtime (token-only — no
 * hardcoded hex in this module). Falls back to the var() reference itself when
 * unresolved, which is a valid CSS color for the `border` / `color` slots.
 */
function neutralColor(): string {
  return cssVar('--inspector-node-neutral') || 'var(--inspector-node-neutral)';
}

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
  // The 8-digit-hex alpha trick only applies to a 6-digit hex profile color; a
  // var()-resolved neutral fallback is left opaque (no corrupting suffix).
  const swatchBg = /^#[0-9a-fA-F]{6}$/.test(displayColor)
    ? displayColor + '30'
    : displayColor;

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
          backgroundColor: swatchBg,
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

  // ── EM-202 (A/B persona-across-models) ──────────────────────────────────
  // "A/B test" toggle reveals a model multi-select. With ≥2 models picked the
  // spawn fires the A/B group (backend god-mode only): one variant per model,
  // sharing this form's name/personality. Off ⇒ the single-profile spawn is
  // unchanged. The toggle is god-mode-only (the backend 400s ab_models under
  // governance), so flipping to GOV clears it.
  const [abEnabled, setAbEnabled] = useState(false);
  const [abModels, setAbModels] = useState<ReadonlySet<string>>(new Set());
  const toggleAbModel = useCallback((profileName: string) => {
    setAbModels((cur) => {
      const next = new Set(cur);
      if (next.has(profileName)) next.delete(profileName);
      else next.add(profileName);
      return next;
    });
  }, []);

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
  const sendPersona = picked !== null && !editedSincePick;
  // EM-202: the A/B group fires only in god mode with ≥2 models picked. When
  // it's armed the single profile is irrelevant (each variant supplies its own).
  const abActive = abEnabled && mode === 'god';
  const abPicked = useMemo(
    () => profiles.filter((p) => abModels.has(p.name)),
    [profiles, abModels],
  );
  const abReady = abActive && abPicked.length >= 2;
  const canSpawn =
    name.trim().length > 0 && !!location && (abActive ? abReady : !!profile);

  // GOV doesn't support ab_models (the backend 400s it) — drop the A/B arm when
  // the operator switches to governance so a stale group can't leak through.
  const setModeSafe = useCallback((m: SpawnMode) => {
    setMode(m);
    if (m !== 'god') setAbEnabled(false);
  }, []);

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
        // EM-202: the A/B group — one variant per model. Only when ≥2 picked
        // in god mode; otherwise omitted entirely (single-profile spawn).
        ...(abReady ? { ab_models: abPicked.map((p) => p.name) } : {}),
      });
      setJustSpawned(name.trim());
      setName('');
      setPersonality('');
      setPicked(null);
      setEditedSincePick(false);
      window.setTimeout(() => setJustSpawned(null), 2200);
    },
    [canSpawn, name, personality, profile, location, mode, onSpawn, sendPersona, picked, abReady, abPicked],
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
            className={`lab-select flex-1 min-w-0 text-[10px] ${swatch ? '' : 'text-lab-text'}`}
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
              onClick={() => setModeSafe(m)}
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

      {/* EM-202: A/B persona-across-models — spawn the SAME persona on N models
          at once ("which model plays Vesper better?"). God mode only; the
          backend 400s ab_models under governance, so the toggle disables there.
          With ≥2 models picked the single Model-profile select above is ignored
          (each variant supplies its own). lab-* tokens only; the data-driven
          chip colors mirror the established ReassignRow swatch idiom. */}
      <div className="space-y-1 border-t border-lab-border/40 pt-2">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={abEnabled}
            disabled={mode !== 'god'}
            onChange={(e) => setAbEnabled(e.target.checked)}
            className="accent-lab-acid"
            aria-label="A/B test this persona across multiple models"
          />
          <span className="font-mono text-[10px] text-lab-muted uppercase tracking-wider">
            ⚗ A/B test across models
          </span>
        </label>
        {mode !== 'god' ? (
          <p className="font-mono text-[9px] text-lab-dim leading-snug">
            A/B groups spawn immediately — switch to ⚡ GOD to use them.
          </p>
        ) : abEnabled ? (
          <div className="space-y-1">
            <div className="flex flex-wrap gap-1" role="group" aria-label="A/B models">
              {profiles.map((p) => {
                const on = abModels.has(p.name);
                return (
                  <button
                    key={p.name}
                    type="button"
                    onClick={() => toggleAbModel(p.name)}
                    aria-pressed={on}
                    aria-label={`Toggle ${p.name} in the A/B group`}
                    title={p.available === false ? `${p.name} (unavailable)` : p.name}
                    className={`font-mono text-[9px] px-1 py-px border rounded-sm cursor-pointer
                                transition-colors duration-100 whitespace-nowrap
                                ${on ? '' : 'border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid'}`}
                    style={on ? { color: p.color, borderColor: p.color, backgroundColor: `color-mix(in srgb, ${p.color} 13%, transparent)` } : undefined}
                  >
                    {on ? '✓ ' : ''}{p.name}{p.available === false ? ' (unavail)' : ''}
                  </button>
                );
              })}
            </div>
            <p
              className={`font-mono text-[9px] leading-snug ${abReady ? 'text-lab-acid' : 'text-lab-dim'}`}
              role="status"
            >
              {abReady
                ? `${abPicked.length} models — spawns ${abPicked.length} variants sharing the name “${name.trim() || '…'}”.`
                : 'Pick at least 2 models to fire an A/B group.'}
            </p>
          </div>
        ) : null}
      </div>

      {/* Submit */}
      <button
        type="submit"
        className="lab-btn lab-btn-primary w-full"
        disabled={!canSpawn}
        aria-label={abReady ? 'Spawn A/B group' : 'Spawn agent'}
      >
        {abReady ? `⚗ SPAWN A/B ×${abPicked.length}` : '✚ SPAWN AGENT'}
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
 * Proclaim (Wave A.2 EM-137 sibling) — the GOD CONSOLE's LOUD voice. Unlike the
 * billboard reply (opt-in — an agent only sees it if it reads the board), the
 * active proclamation rides EVERY agent's next prompt, so the god's word is
 * guaranteed to reach the whole town (the "I asked them to name the town and
 * nobody heard" fix). Self-contained like GodIntervene — calls
 * `inspectorApi.proclaim` directly and is OPTIMISTIC-FREE: no local echo, the
 * proclamation_posted event arrives via the WS feed. ≤280 (the backend
 * ProclaimBody cap); failures render inline via the labeled-result idiom
 * (proclaim never throws).
 */
function Proclaim() {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
  }, []);

  const trimmed = text.trim();
  const canSend = trimmed.length > 0 && !busy;

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!canSend) return;
      setBusy(true);
      setError(null);
      setSent(false);
      const result = await inspectorApi.proclaim(trimmed);
      setBusy(false);
      if (result.ok) {
        setText('');
        setSent(true);
        if (sentTimerRef.current) clearTimeout(sentTimerRef.current);
        sentTimerRef.current = setTimeout(() => setSent(false), 3000);
      } else {
        setError(result.message);
      }
    },
    [canSend, trimmed],
  );

  return (
    <form className="p-2 space-y-1.5" onSubmit={handleSubmit} aria-label="Send a god proclamation">
      <div className="flex items-baseline justify-between">
        <label
          htmlFor="god-proclaim"
          className="font-mono text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--lab-god-bright)' }}
        >
          📣 Proclaim
        </label>
        <span className="font-mono text-[9px] text-lab-dim tabular-nums" aria-hidden="true">
          {text.length}/280
        </span>
      </div>
      <textarea
        id="god-proclaim"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="A decree the whole town hears…"
        maxLength={280}
        rows={2}
        className="lab-input w-full text-[11px] resize-none leading-snug"
      />
      <button
        type="submit"
        className="lab-btn lab-btn-secondary w-full"
        disabled={!canSend}
        aria-label="Proclaim to the whole town"
      >
        {busy ? '…' : '📣 PROCLAIM'}
      </button>
      {error ? (
        <p role="alert" className="m-0 font-mono text-[9px] text-lab-warn leading-snug">
          ⚠ {error}
        </p>
      ) : sent ? (
        <p className="m-0 font-mono text-[9px] text-lab-acid leading-snug" role="status" aria-live="polite">
          proclaimed — every agent hears it next turn (no local echo).
        </p>
      ) : (
        <p className="m-0 font-mono text-[9px] text-lab-dim leading-snug">
          Heard by the whole town — louder than the opt-in billboard.
        </p>
      )}
    </form>
  );
}

/**
 * RewildButton (EM-207 H2) — the MENAGERIE "Rewild" god burst. One click
 * seeds up to `count` random catalog critters; flashes "N critters rewilded"
 * (or a cap-reached note). lab-* tokens only.
 */
function RewildButton({
  onRewild,
}: {
  onRewild: (count?: number) => Promise<{ spawned: number; cap_reached: boolean }>;
}) {
  const [count, setCount] = useState(4);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
  }, []);

  const handleRewild = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setFlash(null);
    const result = await onRewild(count);
    setBusy(false);
    const msg = result.cap_reached
      ? `${result.spawned} critter${result.spawned === 1 ? '' : 's'} rewilded — cap reached.`
      : `${result.spawned} critter${result.spawned === 1 ? '' : 's'} rewilded.`;
    setFlash(msg);
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => setFlash(null), 2400);
  }, [busy, count, onRewild]);

  return (
    <div className="p-2 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          min={1}
          max={20}
          value={count}
          onChange={(e) => setCount(Math.max(1, Math.min(20, Number(e.target.value))))}
          className="lab-input w-12 text-[11px] text-center tabular-nums"
          aria-label="Rewild count"
          title="Number of critters to spawn (1–20)"
        />
        <button
          type="button"
          className="lab-btn flex-1"
          style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
          onClick={() => void handleRewild()}
          disabled={busy}
          aria-label={`Rewild — spawn ${count} random critter${count === 1 ? '' : 's'}`}
          title="Seeds a burst of random catalog species (up to the population cap)"
        >
          {busy ? '…' : '🌿 REWILD'}
        </button>
      </div>
      {flash && (
        <p
          className="font-mono text-[10px] text-center animate-flash"
          style={{ color: 'var(--lab-god-bright)' }}
          role="status"
          aria-live="polite"
        >
          {flash}
        </p>
      )}
    </div>
  );
}

/**
 * ZooEscapeButton (EM-208 H3) — the MENAGERIE "Zoo escape" god trigger. One
 * click causes zoo animals to scatter into the city; flashes "N animals
 * escaped!" (or "No zoo to escape from." if there are none). lab-* tokens
 * only; no hardcoded hex.
 */
function ZooEscapeButton({
  onZooEscape,
}: {
  onZooEscape: (zooBuildingId?: string) => Promise<{ escaped: number; zoos: number }>;
}) {
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
  }, []);

  const handleEscape = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setFlash(null);
    const result = await onZooEscape();
    setBusy(false);
    const msg =
      result.zoos === 0
        ? 'No zoo to escape from.'
        : result.escaped === 0
          ? 'No animals to escape.'
          : `${result.escaped} animal${result.escaped === 1 ? '' : 's'} escaped!`;
    setFlash(msg);
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => setFlash(null), 2400);
  }, [busy, onZooEscape]);

  return (
    <div className="p-2 space-y-1.5">
      <button
        type="button"
        className="lab-btn w-full"
        style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
        onClick={() => void handleEscape()}
        disabled={busy}
        aria-label="Trigger zoo escape — scatter zoo animals into the city"
        title="Relocates all zoo animals to random city places (chaos!)"
      >
        {busy ? '…' : '🦁 ZOO ESCAPE'}
      </button>
      {flash && (
        <p
          className="font-mono text-[10px] text-center animate-flash"
          style={{ color: 'var(--lab-god-bright)' }}
          role="status"
          aria-live="polite"
        >
          {flash}
        </p>
      )}
    </div>
  );
}

/**
 * BuildersGroup (Wave K / EM-221) — the GOD CONSOLE "BUILDERS" group. Four
 * controls, each mirroring the rewild/zoo flash-confirmation UX (lab-* tokens
 * only — the god buttons wear the --lab-god-* ink, no hardcoded hex):
 *   • PLACE PROP   — kind input + place picker + optional count → onPlaceProp
 *   • CLEAR PROPS  — place picker (or All) → onClearProps
 *   • DEMOLISH     — building picker → onDemolish
 *   • RESKIN       — building picker + skin picker → onReskin
 *
 * Pickers read world.places / world.buildings; the skin names come from the
 * Wave-1 SKIN_PALETTES map. Each flashes a brief, role="status" confirmation.
 */
function BuildersGroup({
  world,
  onPlaceProp,
  onClearProps,
  onDemolish,
  onReskin,
}: {
  world: WorldState | null;
  onPlaceProp: (spec: { kind: string; place: string; count?: number }) => Promise<{ placed: number }>;
  onClearProps: (place?: string) => Promise<{ cleared: number }>;
  onDemolish: (buildingId: string) => Promise<{ demolished: boolean }>;
  onReskin: (buildingId: string, skin: string) => Promise<{ reskinned: boolean }>;
}) {
  const places = world?.places ?? [];
  const buildings = world?.buildings ?? [];
  const skinNames = useMemo(() => Object.keys(SKIN_PALETTES), []);

  // PLACE PROP state.
  const [propKind, setPropKind] = useState('bench');
  const [propPlace, setPropPlace] = useState('');
  const [propCount, setPropCount] = useState(1);
  // CLEAR PROPS state ('' = all places).
  const [clearPlace, setClearPlace] = useState('');
  // DEMOLISH / RESKIN building selection.
  const [demolishId, setDemolishId] = useState('');
  const [reskinId, setReskinId] = useState('');
  const [skin, setSkin] = useState(skinNames[0] ?? '');

  const [busy, setBusy] = useState<null | 'place' | 'clear' | 'demolish' | 'reskin'>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
  }, []);

  // Keep the pickers valid once the world arrives after first render.
  const defaultPlace = places[0]?.id ?? '';
  const defaultBuilding = buildings[0]?.id ?? '';
  if (!propPlace && defaultPlace) setPropPlace(defaultPlace);
  if (!demolishId && defaultBuilding) setDemolishId(defaultBuilding);
  if (!reskinId && defaultBuilding) setReskinId(defaultBuilding);

  const showFlash = useCallback((msg: string) => {
    setFlash(msg);
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => setFlash(null), 2400);
  }, []);

  const handlePlace = useCallback(async () => {
    const kind = propKind.trim();
    if (busy || !kind || !propPlace) return;
    setBusy('place');
    setFlash(null);
    const result = await onPlaceProp({ kind, place: propPlace, count: propCount });
    setBusy(null);
    const placeName = places.find(p => p.id === propPlace)?.name ?? propPlace;
    showFlash(
      `${result.placed} ${kind}${result.placed === 1 ? '' : 's'} placed at ${placeName}.`,
    );
  }, [busy, propKind, propPlace, propCount, onPlaceProp, places, showFlash]);

  const handleClear = useCallback(async () => {
    if (busy) return;
    setBusy('clear');
    setFlash(null);
    const result = await onClearProps(clearPlace || undefined);
    setBusy(null);
    const where = clearPlace
      ? (places.find(p => p.id === clearPlace)?.name ?? clearPlace)
      : 'every place';
    showFlash(
      `${result.cleared} prop${result.cleared === 1 ? '' : 's'} cleared from ${where}.`,
    );
  }, [busy, clearPlace, onClearProps, places, showFlash]);

  const handleDemolish = useCallback(async () => {
    if (busy || !demolishId) return;
    setBusy('demolish');
    setFlash(null);
    const result = await onDemolish(demolishId);
    setBusy(null);
    const name = buildings.find(b => b.id === demolishId)?.name ?? demolishId;
    showFlash(result.demolished ? `${name} demolished.` : `Nothing to demolish.`);
  }, [busy, demolishId, onDemolish, buildings, showFlash]);

  const handleReskin = useCallback(async () => {
    if (busy || !reskinId || !skin) return;
    setBusy('reskin');
    setFlash(null);
    const result = await onReskin(reskinId, skin);
    setBusy(null);
    const name = buildings.find(b => b.id === reskinId)?.name ?? reskinId;
    showFlash(result.reskinned ? `${name} reskinned ${skin}.` : `Reskin had no effect.`);
  }, [busy, reskinId, skin, onReskin, buildings, showFlash]);

  const noBuildings = buildings.length === 0;

  return (
    <div className="p-2 space-y-2">
      {/* ── PLACE PROP ───────────────────────────────────────────── */}
      <div className="space-y-1">
        <label
          htmlFor="builders-prop-kind"
          className="block font-mono text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--lab-god-bright)' }}
        >
          🪑 Place prop
        </label>
        <div className="flex items-center gap-1.5">
          <input
            id="builders-prop-kind"
            type="text"
            value={propKind}
            onChange={(e) => setPropKind(e.target.value)}
            placeholder="e.g. bench"
            maxLength={30}
            className="lab-input flex-1 min-w-0 text-[11px]"
            autoComplete="off"
            aria-label="Prop kind"
          />
          <input
            type="number"
            min={1}
            max={8}
            value={propCount}
            onChange={(e) => setPropCount(Math.max(1, Math.min(8, Number(e.target.value))))}
            className="lab-input w-12 text-[11px] text-center tabular-nums"
            aria-label="Prop count"
            title="How many to place (1–8)"
          />
        </div>
        <select
          value={propPlace}
          onChange={(e) => setPropPlace(e.target.value)}
          className="lab-select w-full text-[10px]"
          aria-label="Prop place"
        >
          {places.length === 0 && <option value="">—</option>}
          {places.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <button
          type="button"
          className="lab-btn w-full"
          style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
          onClick={() => void handlePlace()}
          disabled={busy !== null || !propKind.trim() || !propPlace}
          aria-label={`Place ${propCount} ${propKind || 'prop'}`}
        >
          {busy === 'place' ? '…' : '🪑 PLACE PROP'}
        </button>
      </div>

      {/* ── CLEAR PROPS ──────────────────────────────────────────── */}
      <div className="space-y-1 border-t border-lab-border/40 pt-2">
        <label
          htmlFor="builders-clear-place"
          className="block font-mono text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--lab-god-bright)' }}
        >
          🧹 Clear props
        </label>
        <div className="flex items-center gap-1.5">
          <select
            id="builders-clear-place"
            value={clearPlace}
            onChange={(e) => setClearPlace(e.target.value)}
            className="lab-select flex-1 min-w-0 text-[10px]"
            aria-label="Clear props at place"
          >
            <option value="">All places</option>
            {places.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <button
            type="button"
            className="lab-btn lab-btn-danger px-2"
            onClick={() => void handleClear()}
            disabled={busy !== null}
            aria-label={clearPlace ? 'Clear props at the chosen place' : 'Clear props everywhere'}
          >
            {busy === 'clear' ? '…' : '🧹 CLEAR'}
          </button>
        </div>
      </div>

      {/* ── DEMOLISH ─────────────────────────────────────────────── */}
      <div className="space-y-1 border-t border-lab-border/40 pt-2">
        <label
          htmlFor="builders-demolish"
          className="block font-mono text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--lab-god-bright)' }}
        >
          🧨 Demolish building
        </label>
        {noBuildings ? (
          <p className="m-0 font-mono text-[9px] text-lab-dim leading-snug">No buildings yet.</p>
        ) : (
          <div className="flex items-center gap-1.5">
            <select
              id="builders-demolish"
              value={demolishId}
              onChange={(e) => setDemolishId(e.target.value)}
              className="lab-select flex-1 min-w-0 text-[10px]"
              aria-label="Building to demolish"
            >
              {buildings.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
            <button
              type="button"
              className="lab-btn lab-btn-danger px-2"
              onClick={() => void handleDemolish()}
              disabled={busy !== null || !demolishId}
              aria-label="Demolish the chosen building"
            >
              {busy === 'demolish' ? '…' : '🧨 RAZE'}
            </button>
          </div>
        )}
      </div>

      {/* ── RESKIN ───────────────────────────────────────────────── */}
      <div className="space-y-1 border-t border-lab-border/40 pt-2">
        <label
          htmlFor="builders-reskin"
          className="block font-mono text-[10px] uppercase tracking-wider"
          style={{ color: 'var(--lab-god-bright)' }}
        >
          🎨 Reskin building
        </label>
        {noBuildings ? (
          <p className="m-0 font-mono text-[9px] text-lab-dim leading-snug">No buildings yet.</p>
        ) : (
          <>
            <select
              id="builders-reskin"
              value={reskinId}
              onChange={(e) => setReskinId(e.target.value)}
              className="lab-select w-full text-[10px]"
              aria-label="Building to reskin"
            >
              {buildings.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
            <div className="flex items-center gap-1.5">
              <select
                value={skin}
                onChange={(e) => setSkin(e.target.value)}
                className="lab-select flex-1 min-w-0 text-[10px]"
                aria-label="Skin"
              >
                {skinNames.map((name) => (
                  <option key={name} value={name}>
                    {name.charAt(0).toUpperCase() + name.slice(1)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="lab-btn px-2"
                style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
                onClick={() => void handleReskin()}
                disabled={busy !== null || !reskinId || !skin}
                aria-label="Reskin the chosen building"
              >
                {busy === 'reskin' ? '…' : '🎨 RESKIN'}
              </button>
            </div>
          </>
        )}
      </div>

      {flash && (
        <p
          className="font-mono text-[10px] text-center animate-flash"
          style={{ color: 'var(--lab-god-bright)' }}
          role="status"
          aria-live="polite"
        >
          {flash}
        </p>
      )}
    </div>
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
          className="lab-select flex-1 min-w-0 text-[10px]"
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

/**
 * StatusStrip — the compact, always-visible live readout pinned under PLAYBACK
 * (replaces the old scroll-away STATUS section). The active-rule DETAIL lives in
 * the ACTIVE RULES section; this is the at-a-glance line. Token-only colors —
 * the STATE chip reads --rel-ally (running) / --lab-warn (paused).
 */
function StatusStrip({ world, liveCount }: { world: WorldState; liveCount: number }) {
  const activeRules = world.rules.filter((r) => r.status === 'active').length;
  const running = world.running;
  return (
    <div className="px-3 py-1.5 font-mono text-[10px] tabular-nums border-t border-lab-border/40 space-y-0.5">
      <div className="flex items-center gap-x-2.5">
        <span className="flex items-baseline gap-1">
          <span className="text-lab-muted">TICK</span>
          <span className="text-lab-text">{world.tick}</span>
        </span>
        <span className="flex items-baseline gap-1">
          <span className="text-lab-muted">DAY</span>
          <span className="text-lab-text">{world.day}</span>
        </span>
        <span
          className="ml-auto font-semibold"
          style={{ color: running ? 'var(--rel-ally)' : 'var(--lab-warn)' }}
        >
          {running ? '▶ RUNNING' : '⏸ PAUSED'}
        </span>
      </div>
      <div className="flex items-center gap-x-2.5">
        <span className="flex items-baseline gap-1">
          <span className="text-lab-muted">ALIVE</span>
          <span className="text-lab-text">{liveCount}/{world.agents.length}</span>
        </span>
        <span className="flex items-baseline gap-1">
          <span className="text-lab-muted">RULES</span>
          <span className="text-lab-text">{activeRules}</span>
        </span>
      </div>
    </div>
  );
}

/** Per-section disclosure state, persisted so the operator's layout sticks. */
function loadSectionOpen(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v === '1';
  } catch {
    return fallback;
  }
}

type SectionAccent = 'acid' | 'god' | 'neutral';

const SECTION_TITLE_COLOR: Record<SectionAccent, string> = {
  acid: 'text-lab-acid',
  god: 'text-lab-god-bright',
  neutral: 'text-lab-text',
};

const SECTION_STRIPE: Record<SectionAccent, string> = {
  acid: 'border-l-2 border-lab-acid',
  god: 'border-l-2 border-lab-god',
  neutral: 'border-l-2 border-transparent',
};

/**
 * Section — one collapsible god-control group. A single disclosure header
 * (chevron + accent title + muted hint) is wrapped in an <h2> so the heading
 * semantics the tests assert survive; the chevron/hint are aria-hidden, so the
 * accessible name is exactly the title (e.g. "✦ GOD CONSOLE"). Open/closed
 * persists to localStorage per id; collapsed bodies unmount (lazy + light DOM,
 * matching ModelLegend). This ONE disclosure header replaces the old grab-bag
 * of colored top-borders — the consistent separator the panel was missing.
 */
function Section({
  id,
  title,
  tag,
  accent = 'neutral',
  defaultOpen = false,
  children,
}: {
  id: string;
  title: string;
  tag?: string;
  accent?: SectionAccent;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const storageKey = `em.controls.${id}.open`;
  const [open, setOpen] = useState(() => loadSectionOpen(storageKey, defaultOpen));
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, open ? '1' : '0');
    } catch {
      /* ignore — private mode / no storage */
    }
  }, [storageKey, open]);

  const panelId = `controls-section-${id}`;

  return (
    <section>
      <h2 className="m-0">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          className={`lab-header ${SECTION_STRIPE[accent]} w-full flex items-center justify-between gap-2
                      cursor-pointer text-left transition-colors duration-100
                      hover:bg-lab-chrome/40
                      focus:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-lab-acid`}
        >
          {/* Title never shrinks (it's the point); the decorative hint yields
              and truncates first — critical in the 224px-wide controls aside. */}
          <span className="flex items-center gap-1.5 shrink-0">
            <span aria-hidden="true" className="shrink-0 text-[10px] text-lab-muted">
              {open ? '▾' : '▸'}
            </span>
            <span className={SECTION_TITLE_COLOR[accent]}>{title}</span>
          </span>
          {tag && (
            <span
              aria-hidden="true"
              className="min-w-0 truncate text-right font-mono text-[9px] normal-case tracking-normal text-lab-muted opacity-70"
            >
              {tag}
            </span>
          )}
        </button>
      </h2>
      {open && <div id={panelId}>{children}</div>}
    </section>
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
  onSpawnAnimal,
  onRewild,
  onZooEscape,
  onPlaceProp,
  onClearProps,
  onDemolish,
  onReskin,
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
      {/* ── Pinned operator strip: transport + live status. Sticky on scroll,
          so START/PAUSE and the tick readout never leave view even when the
          sections below are expanded. ─────────────────────────────────────── */}
      <div className="sticky top-0 z-20 bg-lab-surface border-b border-lab-border shadow-lg">
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

        {/* Live status — compact, always visible (the rule DETAIL lives in the
            ACTIVE RULES section below). */}
        {world && <StatusStrip world={world} liveCount={liveAgents.length} />}
      </div>

      {/* ── Collapsible sections — ONE consistent disclosure header each;
          open/closed persists per section (em.controls.<id>.open). Ordered by
          operator intent: agents → god powers → world → laws. ──────────────── */}

      {/* MODEL REASSIGN — the marquee live-swap; open by default. */}
      <Section id="reassign" title="⇄ MODEL REASSIGN" tag="LIVE SWAP" accent="acid" defaultOpen>
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
              currentColor={agent.profile_color ?? neutralColor()}
              profiles={profiles}
              onReassign={onReassign}
            />
          ))
        )}
      </Section>

      {/* GOD CONSOLE (Wave A.2 EM-138): WORLD EVENTS / INTERVENE / VOICE. */}
      <Section id="god-console" title="✦ GOD CONSOLE" tag="EVENTS·ACT·VOICE" accent="god">
        {/* Group 1 — WORLD EVENTS: the inject controls, unchanged behavior. */}
        <GodGroupLabel>WORLD EVENTS</GodGroupLabel>
        <div className="p-2 space-y-1.5">
          <div className="flex gap-1.5">
            <select
              value={injectKind}
              onChange={e => setInjectKind(e.target.value)}
              className="lab-select flex-1 min-w-0 text-[10px]"
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

        {/* Group 3 — VOICE: the billboard reply (W11b EM-091d, opt-in) plus the
            LOUD proclamation (EM-137 sibling) — a decree that rides every agent's
            next prompt, guaranteed to reach the whole town. */}
        <div className="border-t border-lab-border/60 mx-1" aria-hidden="true" />
        <GodGroupLabel>VOICE</GodGroupLabel>
        <BillboardReply onPost={onBillboardReply} />
        <Proclaim />
      </Section>

      {/* GOD PANEL — spawn a villager (W7 EM-063). */}
      <Section id="god-panel" title="✦ GOD PANEL" tag="SPAWN" accent="god">
        <SpawnForm world={world} profiles={profiles} mockMode={mockMode} onSpawn={onSpawn} />
      </Section>

      {/* MENAGERIE — add an animal (EM-143) + rewild burst (EM-207). */}
      <Section id="menagerie" title="🐾 MENAGERIE" tag="ANIMALS" accent="god">
        {/* EM-207 H2: REWILD burst — above the manual spawn form */}
        <div className="border-b border-lab-border/40 mx-1 pb-1">
          <RewildButton onRewild={onRewild} />
          {/* EM-208 H3: ZOO ESCAPE — scatter housed animals into the city */}
          <ZooEscapeButton onZooEscape={onZooEscape} />
        </div>
        <AnimalSpawnForm world={world} onSpawn={onSpawnAnimal} />
      </Section>

      {/* BUILDERS (Wave K EM-221): place/clear props · demolish · reskin.
          Only rendered when the build callbacks are wired. */}
      {onPlaceProp && onClearProps && onDemolish && onReskin && (
        <Section id="builders" title="🛠 BUILDERS" tag="PROPS·RAZE·SKIN" accent="god">
          <BuildersGroup
            world={world}
            onPlaceProp={onPlaceProp}
            onClearProps={onClearProps}
            onDemolish={onDemolish}
            onReskin={onReskin}
          />
        </Section>
      )}

      {/* ACTIVE RULES — identical-effect laws group into ×N (EM-087). */}
      {world && world.rules.length > 0 && (
        <Section
          id="rules"
          title="ACTIVE RULES"
          tag={`${world.rules.filter(r => r.status === 'active').length} ACTIVE`}
          accent="neutral"
        >
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
        </Section>
      )}
    </div>
  );
}
