/**
 * useSimulation — manages WebSocket connection or mock mode.
 * Falls back to mock mode automatically if WS fails or VITE_MOCK=1.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { WorldState, WorldEvent, WSMessage, ModelProfile, SpawnSpec } from '../types';
import { buildInitialWorldState, generateTick, mockControls } from '../mock/generator';
import { inspectorApi, eventRowToWorldEvent } from '../inspector/api';

const MOCK_MODE = import.meta.env.VITE_MOCK === '1';
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
  /** Latest tick observed (the inspector scrubber's right edge). */
  maxTick: number;
  connected: boolean;
  mockMode: boolean;
}

export interface SimulationControls {
  start: () => void;
  pause: () => void;
  step: () => void;
  setSpeed: (tickIntervalSeconds: number) => void;
  reassignModel: (agentId: string, profile: string) => void;
  injectEvent: (kind?: string) => void;
  /**
   * Ad-hoc spawn (W7 EM-063). Live: POST /api/agents with the spawn spec
   * (god=immediate 201, governance=enqueued 202). Mock: synthesize a new agent
   * locally and surface the agent_spawned event in the feed.
   */
  spawnAgent: (spec: SpawnSpec) => void;
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

  // ── Backfill on mount (EM-069 / frontend-inspector.md v1.1.0 §1) ───────────
  // Live mode seeds the history from GET /api/events, keyset-paginated via
  // after_seq ascending until exhausted (or the memory cap), merged with the WS
  // rolling history deduped by seq. Degrades silently when there is no backend
  // (inspectorApi resolves to []), so mock-fallback runs are unaffected.
  useEffect(() => {
    if (MOCK_MODE) return;
    let cancelled = false;
    (async () => {
      try {
        let afterSeq = 0;
        let fetched = 0;
        for (;;) {
          const rows = await inspectorApi.events({
            afterSeq,
            order: 'asc',
            limit: BACKFILL_CHUNK,
          });
          if (cancelled) return;
          if (rows.length === 0) break;
          pushHistory(rows.map(eventRowToWorldEvent));
          afterSeq = rows[rows.length - 1].seq;
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
  }, [pushHistory]);

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
      setMockMode(true);
      startMockLoop();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      // A live socket is open: kill any running mock loop so the two
      // event sources can never push (and collide on seq) at once.
      stopMockLoop();
      reconnectAttemptsRef.current = 0;
      setConnected(true);
      setMockMode(false);
    };

    ws.onmessage = (e: MessageEvent) => {
      try {
        const msg: WSMessage = JSON.parse(e.data);
        // Defensive: the first live message guarantees the mock loop is dead.
        // This closes the window where a transient onerror started the mock
        // timer before onopen fired.
        if (mockTimerRef.current) {
          stopMockLoop();
          setMockMode(false);
        }
        if (msg.type === 'world_state') {
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
      setConnected(false);
      wsRef.current = null;
      reconnectAttemptsRef.current += 1;

      // If the backend is genuinely unreachable, fall back to mock after a
      // few attempts so the UI stays alive. Only start mock if one isn't
      // already running (and a live socket recovering will tear it down via
      // onopen/onmessage).
      if (reconnectAttemptsRef.current >= MAX_RECONNECTS_BEFORE_MOCK && !mockTimerRef.current) {
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
  }, [startMockLoop, stopMockLoop, pushHistory]);

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
        wsRef.current.close();
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

  const setSpeed = useCallback((tickIntervalSeconds: number) => {
    if (mockMode) {
      mockSpeedRef.current = tickIntervalSeconds * 1000;
      // Restart loop with new speed
      stopMockLoop();
      if (mockControls.isRunning()) startMockLoop();
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
    maxTick,
    connected,
    mockMode,
    start,
    pause,
    step,
    setSpeed,
    reassignModel,
    injectEvent,
    spawnAgent,
    getProfiles,
    seekTick,
  };
}
