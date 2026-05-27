/**
 * useSimulation — manages WebSocket connection or mock mode.
 * Falls back to mock mode automatically if WS fails or VITE_MOCK=1.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { WorldState, WorldEvent, WSMessage, ModelProfile } from '../types';
import { buildInitialWorldState, generateTick, mockControls } from '../mock/generator';

const MOCK_MODE = import.meta.env.VITE_MOCK === '1';
const MAX_EVENTS = 200;

export interface SimulationState {
  world: WorldState | null;
  events: WorldEvent[];
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
  getProfiles: () => ModelProfile[];
}

export function useSimulation(): SimulationState & SimulationControls {
  const [world, setWorld] = useState<WorldState | null>(null);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [mockMode, setMockMode] = useState(MOCK_MODE);
  const wsRef = useRef<WebSocket | null>(null);
  const mockTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mockSpeedRef = useRef<number>(2000);

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
    }, mockSpeedRef.current);
  }, []);

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
      setConnected(true);
      setMockMode(false);
    };

    ws.onmessage = (e: MessageEvent) => {
      try {
        const msg: WSMessage = JSON.parse(e.data);
        if (msg.type === 'world_state') {
          setWorld(msg);
        } else if (msg.type === 'event') {
          // Extract thought from payload if present
          const evt = msg as WorldEvent;
          if (evt.payload && 'thought' in evt.payload) {
            evt.thought = evt.payload.thought as string;
          }
          setEvents(prev => [evt, ...prev].slice(0, MAX_EVENTS));
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Reconnect after 2s; fall back to mock if can't connect
      setTimeout(() => {
        if (!wsRef.current) {
          connectWS();
        }
      }, 2000);
    };

    ws.onerror = () => {
      ws.close();
      // Fallback to mock mode
      setMockMode(true);
      startMockLoop();
    };
  }, [startMockLoop]);

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
      apiPost('/api/control/start');
    }
  }, [mockMode, apiPost, startMockLoop]);

  const pause = useCallback(() => {
    if (mockMode) {
      mockControls.pause();
    } else {
      apiPost('/api/control/pause');
    }
  }, [mockMode, apiPost]);

  const step = useCallback(() => {
    if (mockMode) {
      const result = mockControls.step();
      if (result) {
        setWorld(result.state);
        setEvents(prev => [...result.events, ...prev].slice(0, MAX_EVENTS));
      }
    } else {
      apiPost('/api/control/step');
    }
  }, [mockMode, apiPost]);

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
          seq: Date.now(),
          tick: world?.tick ?? 0,
          kind: 'model_reassigned',
          actor_id: agentId,
          profile: profile,
          profile_color: prof.color,
          text: `${agent.name} reassigned → ${profile}`,
          ts: new Date().toISOString(),
        };
        setEvents(prev => [evt, ...prev].slice(0, MAX_EVENTS));
      }
    } else {
      apiPost(`/api/agents/${agentId}/model`, { profile });
    }
  }, [mockMode, apiPost, world]);

  const injectEvent = useCallback((kind?: string) => {
    if (mockMode) {
      const result = generateTick();
      setWorld(result.state);
      setEvents(prev => [...result.events, ...prev].slice(0, MAX_EVENTS));
    } else {
      apiPost('/api/events/inject', kind ? { kind } : {});
    }
  }, [mockMode, apiPost]);

  const getProfiles = useCallback((): ModelProfile[] => {
    return world?.profiles ?? mockControls.getProfiles();
  }, [world]);

  return {
    world,
    events,
    connected,
    mockMode,
    start,
    pause,
    step,
    setSpeed,
    reassignModel,
    injectEvent,
    getProfiles,
  };
}
