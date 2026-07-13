/**
 * App — root shell + routing.
 *
 * The simulation hook lives here (one WS connection, shared across routes).
 * Routing chooses what renders below the header:
 *
 *   "/"          → the live chaos lab (W11a layout: feed+digest left, the 3D
 *                  CozyWorld PRIMARY view center with the roster strip on its
 *                  bottom edge, controls right; village/map toggle intact).
 *   "/inspector" → the 2D analysis annex (InspectorLayout) — mounts NO
 *                  <Canvas>. Because routing controls whether LiveLayout
 *                  renders, navigating to /inspector UNMOUNTS the CozyWorld
 *                  <Canvas>, releasing the WebGL/GPU context (not merely
 *                  hidden). See frontend-inspector.md §2.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import { useSimulation } from './hooks/useSimulation';
import { animalModelMap } from './lib/animalIdentity';
import type { SimulationState, SimulationControls } from './hooks/useSimulation';
import { useRoutingHealth } from './hooks/useRoutingHealth';
import type { FocusTarget } from './types';
import { Header } from './components/Header';
import { ExtinctionBanner } from './components/ExtinctionBanner';
import { MinWidthGate, useViewportWide } from './components/MinWidthGate';
import { TopBannerLayer } from './components/BannerFade';
import { WorldMap } from './components/map/WorldMap';
import { CozyWorld } from './components/world3d/CozyWorld';
import { EventFeed } from './components/feed/EventFeed';
import { DramaWire } from './components/feed/DramaWire';
import { StorySoFar } from './components/feed/StorySoFar';
import { BillboardPanel } from './components/feed/BillboardPanel';
import { GalleryPanel } from './components/feed/GalleryPanel';
import { WarPanel } from './components/panels/WarPanel';
import { TwinLens } from './components/panels/TwinLens';
import FingerprintTicker from './components/panels/FingerprintTicker';
import { RosterStrip } from './components/panels/RosterStrip';
import { ControlPanel } from './components/controls/ControlPanel';
import { ModelLegend } from './components/legend/ModelLegend';
import { BlindLineupProvider } from './components/blind/BlindLineupContext';
import { BlindLineupPanel } from './components/blind/BlindLineupPanel';
import { InspectorLayout } from './inspector/InspectorLayout';
import { ChronicleView } from './components/chronicle/ChronicleView';
import { DiaryView } from './components/diary/DiaryView';

type WorldView = 'village' | 'map';
type Sim = SimulationState & SimulationControls;

// ── EM-105: user-resizable feed column ───────────────────────────────────────
// The chat/feed is the product's centerpiece (contract §9 priority
// clarification), so the default is a GENEROUS reading width; the drag handle
// lets the user trade feed↔village balance at runtime. Width persists.
const FEED_W_KEY = 'em.layout.feedWidth';
const FEED_W_DEFAULT = 432;
const FEED_W_MIN = 280;
/** Max: half the viewport — the village never collapses. */
function feedWidthMax(): number {
  return Math.max(FEED_W_MIN, Math.round(window.innerWidth * 0.5));
}
function clampFeedWidth(w: number): number {
  return Math.min(Math.max(Math.round(w), FEED_W_MIN), feedWidthMax());
}
function loadFeedWidth(): number {
  try {
    const raw = Number(localStorage.getItem(FEED_W_KEY));
    if (Number.isFinite(raw) && raw > 0) return clampFeedWidth(raw);
  } catch { /* ignore */ }
  return FEED_W_DEFAULT;
}

export default function App() {
  const sim = useSimulation();
  const { world, connected, mockMode } = sim;
  // EM-072: routing health for the inspector's quiet status chip. (The noisy
  // top banner that used to surface this was removed — see below.)
  const routingHealth = useRoutingHealth(world, sim.history);
  // EM-082: below 1024px both routes render the labeled full-screen gate
  // instead of a broken layout. The simulation hook stays mounted, so the
  // run keeps streaming and nothing is lost while the user resizes.
  const wide = useViewportWide();
  // EM-107: the extinction banner stays live-route-only. (The routing-degraded
  // and usage-alert top banners were removed — too noisy, and under the
  // bounce-don't-throttle direction cap pressure self-heals; the inspector
  // still shows routing health in its compact status chip.)
  const onLive = useLocation().pathname === '/';

  if (!wide) {
    return <MinWidthGate />;
  }

  return (
    // Wave G (EM-197): h-dvh (not h-screen/100vh) so the frame tracks the
    // DYNAMIC viewport — the inspector annex is viewport-fit and must never
    // gain a page scrollbar from browser-chrome height changes.
    <div className="flex flex-col h-dvh bg-lab-bg text-lab-text overflow-hidden">
      {/* ── Header (persistent across routes) ───────────────────── */}
      <Header
        tick={world?.tick ?? 0}
        day={world?.day ?? 0}
        running={world?.running ?? false}
        connected={connected}
        mockMode={mockMode}
      />

      {/* ── Body: routed content + the layout-stable banner overlay ─
          EM-107: every top banner renders in TopBannerLayer — absolutely
          positioned over the routed body, so banner appearance/clearing
          moves ZERO content pixels (the old in-flow mounts reflowed the
          whole app: the "zoom" feeling). Banners fade opacity only and
          stack vertically; each stays individually dismissible. */}
      <div className="relative flex flex-col flex-1 min-h-0">
        <TopBannerLayer>
          {/* EM-071/084: extinction headline + end-of-run summary + NEW RUN.
              Computed from the deeper history so deaths/rules/crimes survive
              the 200-cap feed; its CTA restarts via /api/control/reset. */}
          {onLive && <ExtinctionBanner world={world} events={sim.history} onReset={sim.reset} />}
        </TopBannerLayer>

        {/* ── Routed body ───────────────────────────────────────── */}
        <Routes>
          {/* "/" keeps the 3D village as the default live view. */}
          <Route path="/" element={<LiveLayout sim={sim} />} />
          {/* EM-201 — the Chronicle: a full-width reading view of the saga.
              Like /inspector, it does NOT mount LiveLayout/CozyWorld. */}
          <Route
            path="/chronicle"
            element={<ChronicleView world={sim.world} history={sim.history} />}
          />
          {/* EM-215 — the Diary: a per-agent inner-life reading room (the
              individual cousin to the Chronicle). Like /inspector + /chronicle
              it does NOT mount LiveLayout/CozyWorld, so the WebGL context is
              released on this route. */}
          <Route
            path="/diary"
            element={<DiaryView world={sim.world} history={sim.history} />}
          />
          {/*
            "/inspector" renders the 2D annex. LiveLayout (and thus CozyWorld's
            <Canvas>) is NOT rendered on this route, so React/R3F unmount the
            R3F tree and dispose the WebGL context.
          */}
          <Route
            path="/inspector"
            element={
              <InspectorLayout
                world={sim.world}
                history={sim.history}
                historyLoading={sim.historyLoading}
                historyTruncated={sim.historyTruncated}
                historyTotal={sim.historyTotal}
                mockMode={sim.mockMode}
                onSeekTick={sim.seekTick}
                routingHealth={routingHealth}
              />
            }
          />
        </Routes>
      </div>
    </div>
  );
}

/**
 * LiveLayout — the W11a redesign (EM-096, contract §9 — the user's sketch):
 *
 * Left:   Story-so-far digest (EM-094) on top + full-height event feed.
 * Center: The 3D village (CozyWorld default; 2D WorldMap via the toggle)
 *         getting roughly twice the pixels it used to, with the agent +
 *         critter roster as a horizontally-scrollable card strip along the
 *         BOTTOM edge of the world view (EM-096/EM-099).
 * Right:  Controls + collapsible model legend (EM-104).
 *
 * Desktop-first (~1280px+). No information was lost vs the old layout: every
 * old AgentPanels datum (name, model badge, energy, credits, mood, dying/dead,
 * top relationships) lives on the strip cards, plus location.
 */
function LiveLayout({ sim }: { sim: Sim }) {
  const { world, events } = sim;
  const [view, setView] = useState<WorldView>('village');
  // EM-095: camera focus (follow/zoom target) + the reset-view signal.
  const [focus, setFocus] = useState<FocusTarget | null>(null);
  const [resetNonce, setResetNonce] = useState(0);

  // EM-105: feed-column width — persisted, drag-handle driven.
  const [feedWidth, setFeedWidth] = useState<number>(loadFeedWidth);
  const [resizing, setResizing] = useState(false);
  const dragStateRef = useRef<{ startX: number; startW: number } | null>(null);

  useEffect(() => {
    try { localStorage.setItem(FEED_W_KEY, String(feedWidth)); } catch { /* ignore */ }
  }, [feedWidth]);

  const handleResizeDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    // Pointer capture keeps the drag alive when the cursor outruns the thin
    // handle. It's an enhancement only — jsdom (vitest) and synthetic events
    // have no active pointer, so a failure must not kill the drag.
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ignore */ }
    dragStateRef.current = { startX: e.clientX, startW: feedWidth };
    setResizing(true);
  }, [feedWidth]);

  const handleResizeMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const d = dragStateRef.current;
    if (!d) return;
    setFeedWidth(clampFeedWidth(d.startW + (e.clientX - d.startX)));
  }, []);

  const handleResizeEnd = useCallback(() => {
    dragStateRef.current = null;
    setResizing(false);
  }, []);

  // EM-089: which model each critter consults. world_state animals do NOT
  // carry the profile (backend Animal.to_dict omits it), so it's derived from
  // the latest animal llm_call in the DEEP history (the 200-cap feed would
  // lose it between slow animal cadences). Empty until an animal has consulted
  // the LLM — the labels omit the chip until then (graceful degradation).
  // EM-313: id → name for the fingerprint ticker's spotlighted agent.
  const agentNames = useMemo<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    for (const a of world?.agents ?? []) m[a.id] = a.name;
    return m;
  }, [world?.agents]);

  const animalModels = useMemo(
    () => animalModelMap(sim.history, world?.animals ?? [], world?.profiles ?? []),
    [sim.history, world],
  );

  // Selecting from the strip (or clicking in the scene) focuses the 3D view —
  // if the 2D map is up, switch back to the village so the follow is visible.
  const handleFocus = useCallback((target: FocusTarget | null) => {
    setFocus(target);
    if (target) setView('village');
  }, []);

  const handleResetView = useCallback(() => {
    setFocus(null);
    setResetNonce((n) => n + 1);
  }, []);

  // Name of the followed entity for the header chip.
  const followingName = useMemo(() => {
    if (!focus || !world) return null;
    if (focus.type === 'agent') return world.agents.find((a) => a.id === focus.id)?.name ?? null;
    if (focus.type === 'animal') return world.animals?.find((a) => a.id === focus.id)?.name ?? null;
    return null; // place focus is a one-shot zoom, not a follow
  }, [focus, world]);

  return (
    // EM-309 (Blind Lineup): the provider owns the reveal state; it masks
    // NOTHING unless the blind_lineup.enabled flag is on, so with the flag off
    // this wrapper is inert and the live view is byte-identical to before.
    <BlindLineupProvider>
      {/* EM-107: the routing-degraded + extinction banners moved to App's
          TopBannerLayer overlay — they no longer mount in flow here, so
          their appearance/clearing can't reflow this layout. */}

      {/* ── Three-region body (EM-096) ─────────────────────────── */}
      <div
        className={`flex flex-1 min-h-0 overflow-hidden ${resizing ? 'select-none cursor-col-resize' : ''}`}
        style={{ '--feed-w': `${feedWidth}px` } as React.CSSProperties}
      >
        {/* LEFT — story so far + full-height feed. The chat/feed is the
            centerpiece (contract §9 priority clarification): generous default
            reading width, user-resizable via the handle (EM-105). */}
        <aside
          className="w-[var(--feed-w)] shrink-0 overflow-hidden flex flex-col bg-lab-surface"
          aria-label="Story digest and live event feed"
        >
          <StorySoFar world={world} history={sim.history} />
          {/* EM-309 (Blind Lineup): the spectator guess card. Renders NOTHING
              unless the blind_lineup.enabled flag is on. */}
          <BlindLineupPanel world={world} />
          {/* W11b (EM-091c): the notice-board panel rides under the digest —
              collapsible so the feed keeps its vertical budget. */}
          <BillboardPanel world={world} history={sim.history} />
          {/* Atelier (EM-210): the read-only artwork viewer — browse the art the
              villagers paint + vote onto the plaza. Collapsible so the feed keeps
              its vertical budget. */}
          <GalleryPanel world={world} history={sim.history} />
          {/* Wave O (EM-256–259): the war panel — belligerent factions + the
              grievances driving them. Renders NOTHING in peacetime (no wars,
              no grievances ⇒ null), so it adds zero chrome until war fires. */}
          <WarPanel world={world} />
          {/* EM-310 (Chimera Twins): the twin lens — a synchronized dual-strand
              thread + an auto-pinned divergence-point card for a linked
              same-persona/different-model pair. Renders NOTHING until such a
              pair is spawned behind world.chimera_twins.enabled, so it adds zero
              chrome to every ordinary run. Feed-only chrome (off replay). */}
          <TwinLens world={world} history={sim.history} />
          {/* EM-313: the fingerprint ticker — a converging live model guess vs
              the X-Routed-Via ground truth. Renders NOTHING unless the backend
              has fingerprint_ticker.enabled (default OFF), so it adds zero
              chrome until switched on. */}
          <FingerprintTicker
            tick={world?.tick}
            activeAgentId={focus?.type === 'agent' ? focus.id : null}
            names={agentNames}
          />
          {/* EM-316: the Drama Wire — a derived, zero-sim-feedback rail that
              scores typed events and breaks its own news into rate-capped red
              cards; clicking one flies the shipped zoom-to-place camera. Gated
              behind VITE_DRAMA_WIRE (default OFF ⇒ renders null, feed unchanged). */}
          <DramaWire world={world} history={sim.history} onFocus={handleFocus} />
          <div className="flex-1 min-h-0" aria-label="Live event feed">
            {/* Wave E (EM-185): the GRANT affordance replies through the SAME
                optimistic-free billboard path the god console's VOICE uses. */}
            <EventFeed events={events} onGrantReply={sim.postBillboard} />
          </div>
        </aside>

        {/* EM-105: the feed↔village drag handle. Pointer-drag resizes (hand-
            rolled, no deps); double-click restores the default; arrow keys
            nudge for keyboard users. Width persists to localStorage. */}
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the feed column (drag, arrow keys; double-click to reset)"
          aria-valuenow={feedWidth}
          aria-valuemin={FEED_W_MIN}
          tabIndex={0}
          title="Drag to resize the feed — double-click to reset"
          onPointerDown={handleResizeDown}
          onPointerMove={handleResizeMove}
          onPointerUp={handleResizeEnd}
          onPointerCancel={handleResizeEnd}
          onDoubleClick={() => setFeedWidth(FEED_W_DEFAULT)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') setFeedWidth((w) => clampFeedWidth(w - 16));
            if (e.key === 'ArrowRight') setFeedWidth((w) => clampFeedWidth(w + 16));
          }}
          className={`group shrink-0 w-1.5 cursor-col-resize relative z-10
                      border-l border-lab-border
                      ${resizing ? 'bg-lab-acid/60' : 'bg-lab-chrome hover:bg-lab-acid/40'}
                      transition-colors duration-100
                      focus-visible:bg-lab-acid/40`}
        >
          {/* grip dots — the visible affordance */}
          <span
            aria-hidden="true"
            className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                        font-mono text-[8px] leading-[5px] tracking-tighter pointer-events-none
                        ${resizing ? 'text-lab-bg' : 'text-lab-muted group-hover:text-lab-acid'}`}
          >
            ⋮
          </span>
        </div>

        {/* CENTER — the world view (~2× the old pixels) + bottom roster strip */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <div className="lab-header flex items-center justify-between gap-2 shrink-0">
            <span>{view === 'village' ? 'THE VILLAGE' : 'WORLD MAP'}</span>
            <div className="flex items-center gap-2">
              {followingName && (
                <button
                  type="button"
                  onClick={() => setFocus(null)}
                  className="font-mono text-[10px] px-2 py-0.5 border border-lab-acid text-lab-acid rounded-sm hover:bg-lab-acid/15 transition-colors cursor-pointer"
                  title="Camera is following — click (or drag the view) to release"
                >
                  ◉ FOLLOWING {followingName.toUpperCase()} ✕
                </button>
              )}
              {world && (
                <span className="font-mono text-[10px] text-lab-muted">
                  {world.places.length} PLACES · {world.agents.filter(a => a.alive).length} AGENTS
                </span>
              )}
              {view === 'village' && (
                <button
                  type="button"
                  onClick={handleResetView}
                  className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-border-bright text-lab-text bg-lab-chrome hover:bg-lab-border hover:text-lab-acid transition-colors rounded-sm cursor-pointer"
                  aria-label="Reset the camera to the default framing"
                  title="Reset the camera to the default framing"
                >
                  ⌂ RESET VIEW
                </button>
              )}
              <button
                type="button"
                onClick={() => setView(v => (v === 'village' ? 'map' : 'village'))}
                className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-border-bright text-lab-text bg-lab-chrome hover:bg-lab-border hover:text-lab-acid transition-colors rounded-sm cursor-pointer"
                aria-label={view === 'village' ? 'Switch to 2D map' : 'Switch to 3D village'}
                title={view === 'village' ? 'Switch to 2D map' : 'Switch to 3D village'}
              >
                {view === 'village' ? '2D MAP' : '3D VILLAGE'}
              </button>
            </div>
          </div>

          {/* World view — fills everything below the header; the roster strip
              rides its bottom edge as an overlay so the village keeps the full
              pixel area (contract §9: "~2× today's pixels"). */}
          <div className="relative flex-1 min-h-0">
            <div className="absolute inset-0">
              {view === 'village' ? (
                <CozyWorld
                  world={world}
                  events={events}
                  animalModels={animalModels}
                  focus={focus}
                  resetNonce={resetNonce}
                  onPick={handleFocus}
                  onFocusBreak={() => setFocus(null)}
                />
              ) : (
                <WorldMap world={world} events={events} animalModels={animalModels} />
              )}
            </div>

            {/* Bottom roster strip (EM-096/EM-099) — agents + CRITTERS. */}
            <div className="absolute inset-x-0 bottom-0 border-t border-lab-border bg-lab-surface/90 backdrop-blur-sm">
              <RosterStrip
                world={world}
                history={sim.history}
                animalModels={animalModels}
                selected={focus}
                onSelect={handleFocus}
              />
            </div>
          </div>
        </main>

        {/* RIGHT — Controls + Legend (same width as before; legend collapses) */}
        <aside
          className="w-56 shrink-0 border-l border-lab-border overflow-hidden flex flex-col bg-lab-surface"
          aria-label="Simulation controls"
        >
          <ControlPanel
            world={world}
            onStart={sim.start}
            onPause={sim.pause}
            onStep={sim.step}
            onReset={sim.reset}
            onSpeed={sim.setSpeed}
            onReassign={sim.reassignModel}
            onInject={sim.injectEvent}
            onSpawn={sim.spawnAgent}
            onSpawnAnimal={sim.spawnAnimal}
            onRewild={sim.rewild}
            onZooEscape={sim.triggerZooEscape}
            onPlaceProp={sim.placeProp}
            onClearProps={sim.clearProps}
            onDemolish={sim.godDemolish}
            onReskin={sim.godReskin}
            onBillboardReply={sim.postBillboard}
            mockMode={sim.mockMode}
            profiles={sim.getProfiles()}
          />

          {/* Model legend at the bottom (EM-104: collapsible) */}
          <div className="border-t border-lab-border mt-auto shrink-0">
            <ModelLegend profiles={sim.getProfiles()} />
          </div>
        </aside>
      </div>
    </BlindLineupProvider>
  );
}
