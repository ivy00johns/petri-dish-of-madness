/**
 * App — root shell + routing.
 *
 * The simulation hook lives here (one WS connection, shared across routes).
 * Routing chooses what renders below the header:
 *
 *   "/"          → the existing 3-column chaos lab (3D CozyWorld is the
 *                  PRIMARY view; the in-page village/map toggle is intact).
 *   "/inspector" → the 2D analysis annex (InspectorLayout) — mounts NO
 *                  <Canvas>. Because routing controls whether LiveLayout
 *                  renders, navigating to /inspector UNMOUNTS the CozyWorld
 *                  <Canvas>, releasing the WebGL/GPU context (not merely
 *                  hidden). See frontend-inspector.md §2.
 */

import { useState } from 'react';
import { Routes, Route } from 'react-router-dom';
import { useSimulation } from './hooks/useSimulation';
import type { SimulationState, SimulationControls } from './hooks/useSimulation';
import { Header } from './components/Header';
import { WorldMap } from './components/map/WorldMap';
import { CozyWorld } from './components/world3d/CozyWorld';
import { EventFeed } from './components/feed/EventFeed';
import { AgentPanels } from './components/panels/AgentPanels';
import { ControlPanel } from './components/controls/ControlPanel';
import { ModelLegend } from './components/legend/ModelLegend';
import { InspectorLayout } from './inspector/InspectorLayout';

type WorldView = 'village' | 'map';
type Sim = SimulationState & SimulationControls;

export default function App() {
  const sim = useSimulation();
  const { world, connected, mockMode } = sim;

  return (
    <div className="flex flex-col h-screen bg-lab-bg text-lab-text overflow-hidden">
      {/* ── Header (persistent across routes) ───────────────────── */}
      <Header
        tick={world?.tick ?? 0}
        day={world?.day ?? 0}
        running={world?.running ?? false}
        connected={connected}
        mockMode={mockMode}
      />

      {/* ── Routed body ─────────────────────────────────────────── */}
      <Routes>
        {/* "/" keeps the 3D village as the default live view. */}
        <Route path="/" element={<LiveLayout sim={sim} />} />
        {/*
          "/inspector" renders the 2D annex. LiveLayout (and thus CozyWorld's
          <Canvas>) is NOT rendered on this route, so React/R3F unmount the
          R3F tree and dispose the WebGL context.
        */}
        <Route
          path="/inspector"
          element={
            <InspectorLayout world={sim.world} history={sim.history} mockMode={sim.mockMode} />
          }
        />
      </Routes>
    </div>
  );
}

/**
 * LiveLayout — the existing 3-column chaos lab, unchanged, now mounted under
 * the "/" route.
 *
 * Left:   Agent panels (scrollable card stack)
 * Center: World map (CozyWorld 3D default, top ~55%) + Event feed (bottom ~45%)
 * Right:  Controls + Model legend (scrollable)
 */
function LiveLayout({ sim }: { sim: Sim }) {
  const { world, events } = sim;
  const [view, setView] = useState<WorldView>('village');

  return (
    <>
      {/* ── Three-column body ──────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* LEFT — Agent panels */}
        <aside
          className="w-52 shrink-0 border-r border-lab-border overflow-hidden flex flex-col bg-lab-surface"
          aria-label="Agent status panels"
        >
          <AgentPanels world={world} />
        </aside>

        {/* CENTER — Map + Feed */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Map */}
          <div
            className="border-b border-lab-border overflow-hidden"
            style={{ flex: '0 0 55%' }}
          >
            <div className="lab-header flex items-center justify-between gap-2">
              <span>{view === 'village' ? 'THE VILLAGE' : 'WORLD MAP'}</span>
              <div className="flex items-center gap-2">
                {world && (
                  <span className="font-mono text-[10px] text-lab-muted">
                    {world.places.length} PLACES · {world.agents.filter(a => a.alive).length} AGENTS
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setView(v => (v === 'village' ? 'map' : 'village'))}
                  className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-border-bright text-lab-text bg-lab-chrome hover:bg-lab-border hover:text-lab-acid transition-colors rounded-sm"
                  aria-label={view === 'village' ? 'Switch to 2D map' : 'Switch to 3D village'}
                  title={view === 'village' ? 'Switch to 2D map' : 'Switch to 3D village'}
                >
                  {view === 'village' ? '2D MAP' : '3D VILLAGE'}
                </button>
              </div>
            </div>
            <div style={{ height: 'calc(100% - 28px)' }}>
              {view === 'village' ? (
                <CozyWorld world={world} events={events} />
              ) : (
                <WorldMap world={world} events={events} />
              )}
            </div>
          </div>

          {/* Feed */}
          <div
            className="flex-1 overflow-hidden bg-lab-surface"
            aria-label="Live event feed"
          >
            <EventFeed events={events} />
          </div>
        </main>

        {/* RIGHT — Controls + Legend */}
        <aside
          className="w-56 shrink-0 border-l border-lab-border overflow-hidden flex flex-col bg-lab-surface"
          aria-label="Simulation controls"
        >
          <ControlPanel
            world={world}
            onStart={sim.start}
            onPause={sim.pause}
            onStep={sim.step}
            onSpeed={sim.setSpeed}
            onReassign={sim.reassignModel}
            onInject={sim.injectEvent}
            profiles={sim.getProfiles()}
          />

          {/* Model legend at the bottom */}
          <div className="border-t border-lab-border mt-auto shrink-0">
            <ModelLegend profiles={sim.getProfiles()} />
          </div>
        </aside>
      </div>
    </>
  );
}
