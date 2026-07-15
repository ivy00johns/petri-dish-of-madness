/**
 * useSimulation — manages WebSocket connection or mock mode.
 * Falls back to mock mode automatically if WS fails or VITE_MOCK=1.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { WorldState, WorldEvent, WSMessage, ModelProfile, SpawnSpec } from '../types';
import { buildInitialWorldState, generateTick, mockControls } from '../mock/generator';
import { inspectorApi, eventRowToWorldEvent } from '../inspector/api';

const MOCK_MODE = import.meta.env.VITE_MOCK === '1';
// EM-207 H2: catalog for mock REWILD burst species selection.
const REWILD_CATALOG = ['cat', 'dog', 'squirrel', 'raccoon', 'goat', 'fox', 'crow'] as const;
const MAX_EVENTS = 200;
// Event-history memory cap (frontend-inspector.md v1.1.0 §1). In live mode the
// history is SEEDED from GET /api/events on mount (keyset-paginated backfill)
// and then fed from the WS, deduped by seq — so after a fresh page load mid-run
// every inspector panel renders the full run. The cap bounds memory; when it
// trips, the NEWEST events are kept and `historyTruncated` surfaces a notice.
const MAX_HISTORY = 50_000;
// Page size for the /api/events keyset backfill.
const BACKFILL_CHUNK = 1000;
// WS reconnect backoff (audit C3): 2s base, doubling, capped at 30s; reset on
// a successful open.
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 30_000;

export interface SimulationState {
  world: WorldState | null;
  events: WorldEvent[];
  /**
   * Rolling history (up to MAX_HISTORY) fed from the SAME WS onmessage path as
   * `events`. The live feed stays capped at 200; the inspector consumes this
   * deeper window for replay/trace/graph/dashboard (wired at W6).
   */
  history: WorldEvent[];
  /**
   * True while the live-mode /api/events backfill is still paging in (EM-069).
   * Panels show a "history loading…" empty state instead of a blank region.
   */
  historyLoading: boolean;
  /**
   * True when the history hit the MAX_HISTORY memory cap (or the backfill
   * stopped early) — older events exist on the backend but not in memory.
   */
  historyTruncated: boolean;
  /**
   * Wave F (EM-194): the run's TOTAL event count from GET /api/events/stats,
   * fetched before the backfill starts. Drives the honest backfill progress
   * ("12,000 / 99,140 events") and the cap-honesty notice ("showing the
   * newest 50,000 of 99,140"). `null` = unknown (mock mode / no backend).
   */
  historyTotal: number | null;
  /** Latest tick observed (the inspector scrubber's right edge). */
  maxTick: number;
  connected: boolean;
  mockMode: boolean;
}

export interface SimulationControls {
  start: () => void;
  pause: () => void;
  step: () => void;
  /**
   * EM-084: start a NEW RUN. Live: POST /api/control/reset (the backend
   * rebuilds the world from config and broadcasts the fresh world_state).
   * Mock: mockControls.reset() rebuilds the generator's seed world. Both paths
   * clear the local feed/history so the new run starts clean (and anything
   * derived from them — e.g. the extinction banner — dismisses).
   */
  reset: () => void;
  setSpeed: (tickIntervalSeconds: number) => void;
  reassignModel: (agentId: string, profile: string) => void;
  injectEvent: (kind?: string) => void;
  /**
   * Ad-hoc spawn (W7 EM-063). Live: POST /api/agents with the spawn spec
   * (god=immediate 201, governance=enqueued 202). Mock: synthesize a new agent
   * locally and surface the agent_spawned event in the feed.
   */
  spawnAgent: (spec: SpawnSpec) => void;
  /**
   * EM-143: spawn an animal from the MENAGERIE god panel. Live: POST
   * /api/animals with {species, name?, location}. Mock: synthesize an
   * animal_spawned event so mock-mode works offline.
   */
  spawnAnimal: (spec: { species: string; name?: string; location: string }) => void;
  /**
   * EM-207 H2: REWILD god burst. Live: POST /api/god/rewild {count}; mock:
   * synthesizes N animal_spawned events (one per critter, random species from
   * the catalog). Returns {spawned, cap_reached} in live mode; mock always
   * succeeds up to the synthesized count.
   */
  rewild: (count?: number) => Promise<{ spawned: number; cap_reached: boolean }>;
  /**
   * EM-208 H3: ZOO ESCAPE god trigger. Live: POST /api/god/zoo_escape
   * {zoo_building_id?}. Mock: synthesizes a random_event + a couple of
   * is_chaotic animal_action escape events. Returns {escaped, zoos}.
   */
  triggerZooEscape: (zooBuildingId?: string) => Promise<{ escaped: number; zoos: number }>;
  /**
   * Wave K (EM-221): BUILDERS god console — place `count` props of `kind` at a
   * place. Live: POST /api/god/place_prop {kind, place, count?}; mock:
   * synthesize prop_placed events. Returns {placed}.
   */
  placeProp: (spec: { kind: string; place: string; count?: number }) => Promise<{ placed: number }>;
  /**
   * Wave K (EM-221): clear props at a place (or ALL when place is omitted).
   * Live: POST /api/god/clear_props {place?}; mock: synthesize prop_removed
   * events. Returns {cleared}.
   */
  clearProps: (place?: string) => Promise<{ cleared: number }>;
  /**
   * Wave K (EM-221): god-override demolish a building. Live: POST
   * /api/god/demolish {building_id}; mock: synthesize building_demolished.
   * Returns {demolished}.
   */
  godDemolish: (buildingId: string) => Promise<{ demolished: boolean }>;
  /**
   * Wave K (EM-221): set a building's color skin. Live: POST /api/god/reskin
   * {building_id, skin}; mock: synthesize building_reskinned. Returns
   * {reskinned}.
   */
  godReskin: (buildingId: string, skin: string) => Promise<{ reskinned: boolean }>;
  /**
   * W11b (EM-091d): god reply on the village billboard. Live: POST
   * /api/billboard {text, in_reply_to?} with NO optimistic echo — the backend
   * emits billboard_posted (actor_type:"god") over the WS and the feed/panel
   * render that. Mock: the generator synthesizes the same event + state.
   */
  postBillboard: (text: string, inReplyTo?: string) => void;
  getProfiles: () => ModelProfile[];
  /**
   * Inspector scrub control (frontend-inspector.md §3). In MOCK mode the
   * panels re-project from `history` at the chosen tick (this is a no-op on the
   * live feed). In LIVE mode this is where a deep `api.replay(tick)` fetch can
   * hang at W6; it pauses the loop so the projection is stable while scrubbing.
   */
  seekTick: (tick: number) => void;
}

export function useSimulation(): SimulationState & SimulationControls {
  const [world, setWorld] = useState<WorldState | null>(null);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  // Deeper rolling history for the inspector; fed alongside `events` from the
  // same sources, capped at MAX_HISTORY. Newest-first, matching `events`.
  const [history, setHistory] = useState<WorldEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [mockMode, setMockMode] = useState(MOCK_MODE);
  const [historyLoading, setHistoryLoading] = useState(!MOCK_MODE);
  const [historyTruncated, setHistoryTruncated] = useState(false);
  const [historyTotal, setHistoryTotal] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mockTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mockSpeedRef = useRef<number>(2000);
  const reconnectAttemptsRef = useRef<number>(0);
  // The pending reconnect timer (audit C3): stored so effect cleanup can cancel
  // it — otherwise a dead hook instance reconnects and sets state after unmount.
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Collision-free seq source for client-synthesized events (audit C10):
  // negative and decrementing, so it can never collide with the backend's (or
  // the mock generator's) positive monotonic seqs — EventFeed keys stay unique.
  const syntheticSeqRef = useRef(-1);
  const nextSyntheticSeq = useCallback(() => syntheticSeqRef.current--, []);
  // After this many failed reconnects, fall back to mock so the UI is never
  // dead. A recovered live socket still tears the mock loop down on open/msg.
  const MAX_RECONNECTS_BEFORE_MOCK = 3;
  // MOCK-FALLBACK PURGE: set when a WS outage actually started the mock loop.
  // The generator stamps POSITIVE monotonic seqs — the same id space as the
  // backend's DB event_ids — so on live recovery the fallback's fake events
  // must be dropped: left in place they linger in the feed/history AND their
  // seqs shadow real backend events out of the seq-dedupe (the C10 negative
  // seqs cover only client-synthesized control events, not the generator).
  const mockFallbackRanRef = useRef(false);
  // Bumped by the purge so the mount backfill effect re-runs and repopulates
  // the cleared feed/history from GET /api/events (the real run) — future WS
  // events alone would leave the pre-outage history empty.
  const [backfillNonce, setBackfillNonce] = useState(0);

  // ── Rolling history (inspector annex) ──────────────────────────────────────
  // Prepend newly-arrived events (newest-first), de-duped on seq, capped at
  // MAX_HISTORY. Same input as the live feed; does not affect feed behavior.
  // When the cap trips, the NEWEST events (by seq) are kept and the truncation
  // is surfaced so the inspector can label it (EM-069).
  const pushHistory = useCallback((incoming: WorldEvent[]) => {
    if (incoming.length === 0) return;
    setHistory(prev => {
      const seen = new Set(prev.map(e => e.seq));
      const fresh = incoming.filter(e => !seen.has(e.seq));
      if (fresh.length === 0) return prev;
      const merged = [...fresh, ...prev];
      if (merged.length <= MAX_HISTORY) return merged;
      setHistoryTruncated(true);
      // Keep the newest MAX_HISTORY by seq (backfill can interleave old pages
      // with live WS arrivals, so positional slicing isn't enough).
      merged.sort((a, b) => b.seq - a.seq);
      return merged.slice(0, MAX_HISTORY);
    });
  }, []);

  // Wave F (EM-194): APPEND older events (the tail-first backfill's background
  // pages arrive newest→oldest, each page itself newest-first). De-duped on
  // seq against WS arrivals; same cap + truncation semantics as pushHistory.
  const appendHistory = useCallback((incoming: WorldEvent[]) => {
    if (incoming.length === 0) return;
    setHistory(prev => {
      const seen = new Set(prev.map(e => e.seq));
      const fresh = incoming.filter(e => !seen.has(e.seq));
      if (fresh.length === 0) return prev;
      const merged = [...prev, ...fresh];
      if (merged.length <= MAX_HISTORY) return merged;
      setHistoryTruncated(true);
      merged.sort((a, b) => b.seq - a.seq);
      return merged.slice(0, MAX_HISTORY);
    });
  }, []);

  // ── Live-feed seeding (EM-088) ─────────────────────────────────────────────
  // A page refresh mid-run used to start the `/` feed empty (it only
  // accumulated from WS connect). The backfill below now ALSO seeds the feed:
  // merge incoming events deduped on seq against live WS arrivals, keep the
  // newest MAX_EVENTS by seq. Every kind is pushed — exactly like the live WS
  // path — because feed kind-filtering is render-time: EventFeed's category
  // filter keeps the decision-trace chain default-muted (events.schema
  // x-feed-rendering), so seeding never floods the feed with perceived/memory
  // rows. The WS path's payload.thought lift is applied here too.
  const pushFeed = useCallback((incoming: WorldEvent[]) => {
    if (incoming.length === 0) return;
    setEvents(prev => {
      const seen = new Set(prev.map(e => e.seq));
      const fresh = incoming.filter(e => !seen.has(e.seq));
      if (fresh.length === 0) return prev;
      for (const evt of fresh) {
        if (evt.thought === undefined && typeof evt.payload?.thought === 'string') {
          evt.thought = evt.payload.thought;
        }
      }
      return [...fresh, ...prev].sort((a, b) => b.seq - a.seq).slice(0, MAX_EVENTS);
    });
  }, []);

  // ── Mock-fallback purge (on live recovery) ─────────────────────────────────
  // Runs from ws.onopen and the defensive onmessage branch when a WS-loss
  // fallback previously started the mock loop: drop the same run-scoped local
  // state reset() clears (the fake feed/history and the flags derived from
  // them), then re-trigger the backfill so the REAL run repopulates. The mock
  // world snapshot stays on screen only until the next live world_state
  // broadcast replaces it. No-op unless the fallback actually ran.
  const purgeMockFallbackState = useCallback(() => {
    if (!mockFallbackRanRef.current) return;
    mockFallbackRanRef.current = false;
    setEvents([]);
    setHistory([]);
    setHistoryTruncated(false);
    setHistoryTotal(null);
    setHistoryLoading(true);
    setBackfillNonce(n => n + 1);
  }, []);

  // ── Backfill on mount (EM-069 → wave F EM-194: TAIL-FIRST) ─────────────────
  // Live mode seeds the history from GET /api/events. Wave F inverts the page
  // order so a long run renders immediately instead of paging ~50 chunks to
  // exhaustion first:
  //   1. GET /api/events/stats sizes the run (total drives the progress label
  //      and the cap-honesty notice; null-tolerant for pre-F1 backends).
  //   2. The NEWEST chunk loads first (order=desc) and renders — the annex is
  //      interactive after chunk one.
  //   3. Older chunks backfill in the BACKGROUND (before_seq keyset, newest→
  //      oldest), appended behind the newest page, until exhausted or the
  //      MAX_HISTORY memory cap (newest events win; truncation labeled).
  // Merged with the WS rolling history deduped by seq throughout. Degrades
  // silently when there is no backend (inspectorApi resolves to []), so
  // mock-fallback runs are unaffected.
  useEffect(() => {
    if (MOCK_MODE) return;
    let cancelled = false;
    (async () => {
      try {
        // 1) Size the run first — honest progress needs the real total.
        // lineage:true so a resumed/forked active run is sized to its FULL
        // timeline (ancestors' pre-fork events included), matching the backfill.
        const stats = await inspectorApi.eventStats(undefined, true);
        if (cancelled) return;
        if (stats) {
          setHistoryTotal(stats.total);
          // More events exist than the memory cap can hold: say so up front
          // (the backfill below will stop at the cap regardless).
          if (stats.total > MAX_HISTORY) setHistoryTruncated(true);
        }

        // 2) Newest chunk first → first render before any older page lands.
        let beforeSeq: number | undefined = undefined;
        let fetched = 0;
        let firstPage = true;
        for (;;) {
          const rows: Awaited<ReturnType<typeof inspectorApi.events>> =
            await inspectorApi.events({
              beforeSeq,
              order: 'desc',
              limit: BACKFILL_CHUNK,
              // EM-187: walk lineage so a resumed/forked run's feed shows the
              // pre-fork history (parent run's events), not just post-resume.
              // seq is global, so the beforeSeq keyset still pages cleanly
              // across the run boundary, newest→oldest.
              lineage: true,
            });
          if (cancelled) return;
          if (rows.length === 0) break;
          const oldestSeq = rows[rows.length - 1].seq;
          // Keyset-progress guard: a backend that ignored before_seq/desc
          // would resend the same page forever — stop instead of spinning.
          if (beforeSeq !== undefined && oldestSeq >= beforeSeq) break;
          const mapped = rows.map(eventRowToWorldEvent);
          if (firstPage) {
            // Newest page: prepend (it is newer than nothing yet; WS arrivals
            // dedupe by seq) and seed the live feed (newest 200 by seq win,
            // EM-088 — one ≥200-row newest page fully covers the feed cap).
            pushHistory(mapped);
            pushFeed(mapped);
            firstPage = false;
          } else {
            // 3) Older background pages: append behind what is already shown.
            appendHistory(mapped);
          }
          beforeSeq = oldestSeq;
          fetched += rows.length;
          if (fetched >= MAX_HISTORY) {
            // More may exist beyond the memory cap; stop and label it.
            setHistoryTruncated(true);
            break;
          }
          if (rows.length < BACKFILL_CHUNK) break;
        }
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // backfillNonce: bumped by purgeMockFallbackState so a live recovery after
    // a mock fallback re-runs this whole backfill against the real run.
  }, [pushHistory, appendHistory, pushFeed, backfillNonce]);

  // ── Mock mode ─────────────────────────────────────────────────────────────

  const startMockLoop = useCallback(() => {
    if (mockTimerRef.current) clearInterval(mockTimerRef.current);
    const initial = buildInitialWorldState();
    setWorld(initial);
    setConnected(true);

    mockTimerRef.current = setInterval(() => {
      if (!mockControls.isRunning()) return;
      const { state, events: newEvents } = generateTick();
      setWorld(state);
      setEvents(prev => {
        const combined = [...newEvents, ...prev];
        return combined.slice(0, MAX_EVENTS);
      });
      pushHistory(newEvents);
    }, mockSpeedRef.current);
  }, [pushHistory]);

  const stopMockLoop = useCallback(() => {
    if (mockTimerRef.current) {
      clearInterval(mockTimerRef.current);
      mockTimerRef.current = null;
    }
  }, []);

  // ── WebSocket mode ────────────────────────────────────────────────────────

  const connectWS = useCallback(() => {
    if (MOCK_MODE) return;

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl);
    } catch {
      // Fallback to mock
      mockFallbackRanRef.current = true;
      setMockMode(true);
      startMockLoop();
      return;
    }

    wsRef.current = ws;

    // Stale-socket guard (EM-305): every handler below is inert unless this
    // socket is STILL wsRef.current. A superseded socket (StrictMode's
    // first-mount socket, a replaced reconnect) must never touch shared
    // state, null the ref, or schedule a reconnect — one leaked close
    // otherwise orphans the live socket and the reconnect loop breeds N
    // parallel sockets, each reprocessing every message (the feed flicker).
    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      // A live socket is open: kill any running mock loop so the two
      // event sources can never push (and collide on seq) at once.
      stopMockLoop();
      // …and if a fallback DID run, drop everything it synthesized (fake
      // events would linger and shadow real seqs) — the backfill re-runs.
      purgeMockFallbackState();
      reconnectAttemptsRef.current = 0;
      setConnected(true);
      setMockMode(false);
    };

    ws.onmessage = (e: MessageEvent) => {
      if (wsRef.current !== ws) return;
      try {
        const msg: WSMessage = JSON.parse(e.data);
        // Defensive: the first live message guarantees the mock loop is dead.
        // This closes the window where a transient onerror started the mock
        // timer before onopen fired.
        if (mockTimerRef.current) {
          stopMockLoop();
          setMockMode(false);
        }
        // Same recovery contract as onopen: a live message after a fallback
        // purges the fake local state before this message is folded in (the
        // purge setter is queued first, so the event below lands post-purge).
        purgeMockFallbackState();
        if (msg.type === 'world_state') {
          // Wave I (EM-210/213): the per-tick world_state snapshot now also
          // carries `gallery` + `plaza_banner_ref`. They ride this same
          // pass-through (the whole message is the WorldState the hook exposes),
          // so the 3D notice board / PlazaBanner pick them up with no special
          // case. image_posted / image_promoted are ordinary events and flow
          // through the standard event/history path below.
          setWorld(msg);
        } else if (msg.type === 'event') {
          // Extract thought from payload if present
          const evt = msg as WorldEvent;
          if (evt.payload && 'thought' in evt.payload) {
            evt.thought = evt.payload.thought as string;
          }
          // Belt-and-suspenders: ignore a seq we already hold so a backend
          // resend or reconnect replay can't introduce a duplicate React key.
          setEvents(prev => {
            if (prev.length > 0 && prev.some(e => e.seq === evt.seq)) {
              return prev;
            }
            return [evt, ...prev].slice(0, MAX_EVENTS);
          });
          // Same source feeds the deeper inspector history (de-duped on seq).
          pushHistory([evt]);
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      setConnected(false);
      wsRef.current = null;
      reconnectAttemptsRef.current += 1;

      // If the backend is genuinely unreachable, fall back to mock after a
      // few attempts so the UI stays alive. Only start mock if one isn't
      // already running (and a live socket recovering will tear it down via
      // onopen/onmessage).
      if (reconnectAttemptsRef.current >= MAX_RECONNECTS_BEFORE_MOCK && !mockTimerRef.current) {
        // Remember the fallback ran: its fake (positive-seq) events must be
        // purged the moment a live socket recovers (onopen / first message).
        mockFallbackRanRef.current = true;
        setMockMode(true);
        startMockLoop();
      }

      // Keep trying to reconnect; a recovered socket always wins over mock.
      // Exponential backoff (audit C3): 2s, 4s, 8s… capped at 30s, reset on a
      // successful open. The handle is stored so unmount cleanup cancels it.
      const delay = Math.min(
        RECONNECT_MAX_MS,
        RECONNECT_BASE_MS * 2 ** Math.max(0, reconnectAttemptsRef.current - 1),
      );
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        if (!wsRef.current) {
          connectWS();
        }
      }, delay);
    };

    ws.onerror = () => {
      if (wsRef.current !== ws) return;
      // Do NOT permanently flip to mock on a transient error while the
      // socket may still open. If the socket is still CONNECTING, let the
      // browser resolve it (onopen or onclose will fire). onclose handles
      // reconnect; only after reconnect genuinely fails do we fall back to
      // mock — and even then, onopen/onmessage will tear the mock loop down
      // the instant a live socket recovers.
      if (ws.readyState === WebSocket.CONNECTING) {
        return;
      }
      ws.close();
    };
  }, [startMockLoop, stopMockLoop, pushHistory, purgeMockFallbackState]);

  // ── Init ──────────────────────────────────────────────────────────────────

  useEffect(() => {
    if (MOCK_MODE) {
      setMockMode(true);
      startMockLoop();
    } else {
      connectWS();
    }

    return () => {
      stopMockLoop();
      // Cancel any pending reconnect (audit C3) so a dead hook instance never
      // reconnects or sets state after unmount (the StrictMode WS warning).
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        // Deliberate teardown: detach the handlers BEFORE closing so this
        // close can never re-enter the reconnect path (the stale guard covers
        // a REPLACED socket; this covers the one being retired at unmount).
        const ws = wsRef.current;
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
        wsRef.current = null;
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Control API ───────────────────────────────────────────────────────────

  const apiPost = useCallback(async (path: string, body?: unknown) => {
    try {
      await fetch(path, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch {
      // in mock mode, ignore network errors
    }
  }, []);

  const start = useCallback(() => {
    if (mockMode) {
      mockControls.start();
      if (!mockTimerRef.current) startMockLoop();
    } else {
      // Optimistic: flip the button immediately; the next server broadcast
      // confirms (or corrects) it, instead of waiting a full tick to switch.
      setWorld(prev => (prev ? { ...prev, running: true } : prev));
      apiPost('/api/control/start');
    }
  }, [mockMode, apiPost, startMockLoop]);

  const pause = useCallback(() => {
    if (mockMode) {
      mockControls.pause();
    } else {
      setWorld(prev => (prev ? { ...prev, running: false } : prev));
      apiPost('/api/control/pause');
    }
  }, [mockMode, apiPost]);

  const step = useCallback(() => {
    if (mockMode) {
      const result = mockControls.step();
      if (result) {
        setWorld(result.state);
        setEvents(prev => [...result.events, ...prev].slice(0, MAX_EVENTS));
        pushHistory(result.events);
      }
    } else {
      apiPost('/api/control/step');
    }
  }, [mockMode, apiPost, pushHistory]);

  // EM-084: start a NEW RUN. Clears the run-scoped local state first (feed,
  // history, truncation flag) so the new run renders clean — the extinction
  // banner derives from these and dismisses immediately. Live: the backend
  // rebuilds the world from config and broadcasts the fresh world_state (the
  // old `world` stays on screen for the broadcast round-trip only). Mock: the
  // generator rebuilds its seed world synchronously.
  const reset = useCallback(() => {
    setEvents([]);
    setHistory([]);
    setHistoryTruncated(false);
    // The stats total described the OLD run; the fresh run starts unknown.
    setHistoryTotal(null);
    if (mockMode) {
      stopMockLoop();
      const fresh = mockControls.reset();
      // Mirror the backend: a reset restores the config tick interval too.
      mockSpeedRef.current = fresh.tick_interval_seconds * 1000;
      setWorld(fresh);
      // Restart the loop against the rebuilt generator state (running=true).
      startMockLoop();
    } else {
      apiPost('/api/control/reset');
    }
  }, [mockMode, apiPost, stopMockLoop, startMockLoop]);

  const setSpeed = useCallback((tickIntervalSeconds: number) => {
    if (mockMode) {
      mockSpeedRef.current = tickIntervalSeconds * 1000;
      // W10/D5: record it in the mock "server" too, so the next world_state
      // broadcast carries the new tick_interval_seconds (the control panel
      // derives its speed label from world_state — server is truth).
      mockControls.setSpeed(tickIntervalSeconds);
      // Restart loop with new speed
      stopMockLoop();
      if (mockControls.isRunning()) startMockLoop();
      // Optimistic local echo (mirrors the live broadcast) so the label
      // reflects the change immediately even while paused.
      setWorld(prev => (prev ? { ...prev, tick_interval_seconds: tickIntervalSeconds } : prev));
    } else {
      apiPost('/api/control/speed', { tick_interval_seconds: tickIntervalSeconds });
    }
  }, [mockMode, apiPost, stopMockLoop, startMockLoop]);

  const reassignModel = useCallback((agentId: string, profile: string) => {
    if (mockMode) {
      mockControls.reassign(agentId, profile);
      // Update world state immediately for optimistic UI
      setWorld(prev => {
        if (!prev) return prev;
        const profiles = prev.profiles;
        const prof = profiles.find(p => p.name === profile);
        return {
          ...prev,
          agents: prev.agents.map(a =>
            a.id === agentId
              ? { ...a, profile, profile_color: prof?.color ?? a.profile_color }
              : a
          ),
        };
      });
      // Add a reassign event to the feed
      const agent = world?.agents.find(a => a.id === agentId);
      const prof = world?.profiles.find(p => p.name === profile);
      if (agent && prof) {
        const evt: WorldEvent = {
          type: 'event',
          // Synthetic client-side event: negative decrementing seq (audit C10)
          // — can never collide with real (positive) seqs, keys stay unique.
          seq: nextSyntheticSeq(),
          tick: world?.tick ?? 0,
          kind: 'model_reassigned',
          actor_id: agentId,
          profile: profile,
          profile_color: prof.color,
          text: `${agent.name} reassigned → ${profile}`,
          ts: new Date().toISOString(),
        };
        setEvents(prev => [evt, ...prev].slice(0, MAX_EVENTS));
        pushHistory([evt]);
      }
    } else {
      apiPost(`/api/agents/${agentId}/model`, { profile });
    }
  }, [mockMode, apiPost, world, pushHistory, nextSyntheticSeq]);

  const injectEvent = useCallback((kind?: string) => {
    if (mockMode) {
      const result = generateTick();
      setWorld(result.state);
      setEvents(prev => [...result.events, ...prev].slice(0, MAX_EVENTS));
      pushHistory(result.events);
    } else {
      apiPost('/api/events/inject', kind ? { kind } : {});
    }
  }, [mockMode, apiPost, pushHistory]);

  const spawnAgent = useCallback((spec: SpawnSpec) => {
    if (mockMode) {
      const { state, events: newEvents } = mockControls.spawn(spec);
      setWorld(state);
      setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
      pushHistory(newEvents);
    } else {
      // Live: POST /api/agents (201 god / 202 governance). The backend emits the
      // agent_spawned event over the WS, which lands via onmessage like any other.
      apiPost('/api/agents', spec);
    }
  }, [mockMode, apiPost, pushHistory]);

  // EM-143: spawn an animal. Live: POST /api/animals; mock: synthesize the event.
  const spawnAnimal = useCallback((spec: { species: string; name?: string; location: string }) => {
    if (mockMode) {
      const { state, events: newEvents } = mockControls.spawnAnimal(spec);
      setWorld(state);
      setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
      pushHistory(newEvents);
    } else {
      apiPost('/api/animals', spec);
    }
  }, [mockMode, apiPost, pushHistory]);

  // EM-207 H2: REWILD burst. Live: POST /api/god/rewild {count}.
  // Mock: synthesize N animal_spawned events for random catalog species.
  const rewild = useCallback(async (count = 4): Promise<{ spawned: number; cap_reached: boolean }> => {
    if (mockMode) {
      // Mock: pick random species and synthesize events (up to count).
      let spawned = 0;
      for (let i = 0; i < count; i++) {
        const species = REWILD_CATALOG[Math.floor(Math.random() * REWILD_CATALOG.length)];
        const { state, events: newEvents } = mockControls.spawnAnimal({ species });
        setWorld(state);
        setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
        pushHistory(newEvents);
        spawned += 1;
      }
      return { spawned, cap_reached: false };
    } else {
      try {
        const res = await fetch('/api/god/rewild', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ count }),
        });
        if (res.ok) {
          return (await res.json()) as { spawned: number; cap_reached: boolean };
        }
      } catch {
        // network error — fall through
      }
      return { spawned: 0, cap_reached: false };
    }
  }, [mockMode, pushHistory]);

  // EM-208 H3: ZOO ESCAPE god trigger. Live: POST /api/god/zoo_escape.
  // Mock: synthesize a random_event (chaos) + two animal_action escape events.
  const triggerZooEscape = useCallback(async (zooBuildingId?: string): Promise<{ escaped: number; zoos: number }> => {
    if (mockMode) {
      const escaped = 2;
      const escapeEvents: WorldEvent[] = [
        {
          type: 'event',
          seq: nextSyntheticSeq(),
          tick: world?.tick ?? 0,
          kind: 'random_event',
          actor_id: 'system',
          text: `ESCAPE! ${escaped} animals break loose from the City Zoo!`,
          is_chaotic: true,
          ts: new Date().toISOString(),
          payload: { actor_type: 'system', is_chaotic: true },
        },
        ...Array.from({ length: escaped }, (_, i) => ({
          type: 'event' as const,
          seq: nextSyntheticSeq(),
          tick: world?.tick ?? 0,
          kind: 'animal_action',
          actor_id: `mock-animal-${i}`,
          text: `A zoo animal escapes and scatters into the city!`,
          is_chaotic: true,
          ts: new Date().toISOString(),
          payload: { action: 'escape', from_place: 'zoo', to_place: 'plaza', is_chaotic: true },
        })),
      ];
      setEvents(prev => [...escapeEvents, ...prev].slice(0, MAX_EVENTS));
      pushHistory(escapeEvents);
      return { escaped, zoos: 1 };
    } else {
      try {
        const res = await fetch('/api/god/zoo_escape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(zooBuildingId ? { zoo_building_id: zooBuildingId } : {}),
        });
        if (res.ok) {
          return (await res.json()) as { escaped: number; zoos: number };
        }
      } catch {
        // network error — fall through
      }
      return { escaped: 0, zoos: 0 };
    }
  }, [mockMode, world, pushHistory, nextSyntheticSeq]);

  // Wave K (EM-221): BUILDERS god console. Each mirrors the rewild/zooEscape
  // shape — mock synthesizes the contract §4 events (and mutates the mock world
  // so the 3D renderers update); live POSTs the §5 endpoint and returns its
  // JSON, degrading to a no-op result on a network error.
  const placeProp = useCallback(
    async (spec: { kind: string; place: string; count?: number }): Promise<{ placed: number }> => {
      if (mockMode) {
        const { state, events: newEvents, placed } = mockControls.placeProp(spec);
        setWorld(state);
        setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
        pushHistory(newEvents);
        return { placed };
      }
      try {
        const res = await fetch('/api/god/place_prop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            kind: spec.kind,
            place: spec.place,
            ...(spec.count !== undefined ? { count: spec.count } : {}),
          }),
        });
        if (res.ok) return (await res.json()) as { placed: number };
      } catch {
        // network error — fall through
      }
      return { placed: 0 };
    },
    [mockMode, pushHistory],
  );

  const clearProps = useCallback(
    async (place?: string): Promise<{ cleared: number }> => {
      if (mockMode) {
        const { state, events: newEvents, cleared } = mockControls.clearProps(
          place ? { place } : {},
        );
        setWorld(state);
        setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
        pushHistory(newEvents);
        return { cleared };
      }
      try {
        const res = await fetch('/api/god/clear_props', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(place ? { place } : {}),
        });
        if (res.ok) return (await res.json()) as { cleared: number };
      } catch {
        // network error — fall through
      }
      return { cleared: 0 };
    },
    [mockMode, pushHistory],
  );

  const godDemolish = useCallback(
    async (buildingId: string): Promise<{ demolished: boolean }> => {
      if (mockMode) {
        const { state, events: newEvents, demolished } = mockControls.demolish({
          building_id: buildingId,
        });
        setWorld(state);
        setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
        pushHistory(newEvents);
        return { demolished };
      }
      try {
        const res = await fetch('/api/god/demolish', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ building_id: buildingId }),
        });
        if (res.ok) return (await res.json()) as { demolished: boolean };
      } catch {
        // network error — fall through
      }
      return { demolished: false };
    },
    [mockMode, pushHistory],
  );

  const godReskin = useCallback(
    async (buildingId: string, skin: string): Promise<{ reskinned: boolean }> => {
      if (mockMode) {
        const { state, events: newEvents, reskinned } = mockControls.reskin({
          building_id: buildingId,
          skin,
        });
        setWorld(state);
        setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
        pushHistory(newEvents);
        return { reskinned };
      }
      try {
        const res = await fetch('/api/god/reskin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ building_id: buildingId, skin }),
        });
        if (res.ok) return (await res.json()) as { reskinned: boolean };
      } catch {
        // network error — fall through
      }
      return { reskinned: false };
    },
    [mockMode, pushHistory],
  );

  // W11b (EM-091d): god reply on the billboard. Live mode is optimistic-FREE
  // by contract — we wait for the WS billboard_posted event rather than
  // synthesizing a local echo (a failed POST must not leave a ghost post).
  const postBillboard = useCallback((text: string, inReplyTo?: string) => {
    const trimmed = text.trim().slice(0, 280);
    if (!trimmed) return;
    if (mockMode) {
      const { state, events: newEvents } = mockControls.postBillboard(trimmed, inReplyTo);
      setWorld(state);
      setEvents(prev => [...newEvents, ...prev].slice(0, MAX_EVENTS));
      pushHistory(newEvents);
    } else {
      apiPost('/api/billboard', { text: trimmed, ...(inReplyTo ? { in_reply_to: inReplyTo } : {}) });
    }
  }, [mockMode, apiPost, pushHistory]);

  const getProfiles = useCallback((): ModelProfile[] => {
    return world?.profiles ?? mockControls.getProfiles();
  }, [world]);

  // Latest tick observed — from the live world projection or the deepest event
  // in history (whichever is further along). Drives the inspector scrubber.
  const maxTick = useMemo(() => {
    let max = world?.tick ?? 0;
    for (const e of history) if (e.tick > max) max = e.tick;
    return max;
  }, [world, history]);

  // Inspector scrub control (frontend-inspector.md v1.1.0 §2/§3). Scrubbing
  // means "stop advancing the live edge so the projection is stable", so both
  // modes pause the loop. The deep-replay materialization itself
  // (GET /api/replay?tick=T → base snapshot + strict-left delta, folded through
  // replayStateAt) is owned by the inspector annex (useReplayMaterials), which
  // fetches against the scrub tick the annex already owns — this hook's live
  // path is the engine-side half: pause, so the run doesn't advance under the
  // scrubbed projection.
  const seekTick = useCallback((tick: number) => {
    void tick; // the annex projects at the tick; the engine just needs pausing.
    if (mockMode) {
      mockControls.pause();
      stopMockLoop();
    } else {
      apiPost('/api/control/pause');
    }
  }, [mockMode, apiPost, stopMockLoop]);

  return {
    world,
    events,
    history,
    historyLoading,
    historyTruncated,
    historyTotal,
    maxTick,
    connected,
    mockMode,
    start,
    pause,
    step,
    reset,
    setSpeed,
    reassignModel,
    injectEvent,
    spawnAgent,
    spawnAnimal,
    rewild,
    triggerZooEscape,
    placeProp,
    clearProps,
    godDemolish,
    godReskin,
    postBillboard,
    getProfiles,
    seekTick,
  };
}
