/**
 * LaneHealthPanel (EM-300 P5) — "see the lanes" observability.
 *
 * Consumes the router's OWN health accounting, verbatim — never a client-side
 * re-derivation:
 *   GET /api/lanes          — the profile-keyed EM-135 lane_health() map:
 *                             {window, boosted, timeouts, errors,
 *                              last_routed_via, sick, detours_routed_here,
 *                              cooldown?}. The window entries are the router's
 *                             raw per-outcome records {parsed, truncated,
 *                             timed_out?, error?} — the panel renders them
 *                             cell-for-cell so what the router "believes" is
 *                             exactly what the user sees (the EM-325 lesson:
 *                             lane-health accounting must be inspectable).
 *   GET /api/lanes/registry — the EM-300 P2 discovery view: the lane registry
 *                             in priority order + discovery meta.
 *
 * The panel answers the questions EM-325 left open in the open loop:
 *   • which lanes are sick (≥3 demerits in the 6-window) and therefore
 *     pre-emptively skipped this run?
 *   • which lanes are inside a 429 cooldown window (routing to auto, resets in
 *     Ns, N strikes)?
 *   • what does the router's own window actually say — an `error` cell? a
 *     `timed_out` cell? a truncated-but-parsed cell? a plain parsed hit?
 *
 * Graceful degradation: backend unreachable (mock mode / backend down) →
 * labeled "no backend" strip; zero lanes → labeled empty. Never throws.
 *
 * Token-only styling (lab-* classes / inspector tokens). The only inline styles
 * are the DATA-DRIVEN per-cell window colors (computed values a static class
 * cannot express), via cssVar — the sanctioned escape hatch the AWI/SocialGraph
 * panels use. No `any`.
 */
import { useEffect, useMemo, useState } from 'react';
import { inspectorApi } from './api';
import type {
  LaneHealthMap,
  LaneHealthRow,
  LaneRegistryRow,
  LaneRegistryView,
  LaneWindowEntry,
} from './api';
import './inspector-tokens.css';

/** Poll interval: the lane-health window is turn-paced; 2s keeps it fresh. */
const POLL_MS = 2000;

/** Window outcome → token class + glyph. `parsed` is the default (a served
 *  turn with a parseable result is a healthy outcome); the three fault
 *  registers are all explicitly distinguished. */
function windowCellClass(e: LaneWindowEntry): string {
  if (e.error) return 'bg-lab-danger/80 text-lab-bg';
  if (e.timed_out) return 'bg-lab-warn text-lab-bg';
  if (e.truncated && e.parsed) return 'bg-lab-warn/45 text-lab-bg';
  if (!e.parsed) return 'bg-lab-muted/60 text-lab-bg';
  return 'bg-lab-acid/70 text-lab-bg';
}

function windowCellGlyph(e: LaneWindowEntry): string {
  if (e.error) return '✕';
  if (e.timed_out) return '⧖';
  if (e.truncated && e.parsed) return '✂';
  if (!e.parsed) return '?';
  return '✓';
}

function windowCellTitle(e: LaneWindowEntry, i: number, n: number): string {
  const parts = [
    `slot ${n - i} of ${n}`,
    e.parsed ? 'parsed' : 'unparseable',
    e.truncated ? 'truncated' : '',
    e.timed_out ? 'turn-budget timeout' : '',
    e.error ? 'provider error' : '',
  ].filter(Boolean);
  return parts.join(' · ');
}

function cooldownLabel(cd: { expires_in_s: number; strikes: number; platform?: string }): string {
  // Platform-resume parking (EM-300 P3 finish) names the culprit platform —
  // "huggingface · auto 38s" reads as the proxy's own reset clock, not a
  // lane-own 429 streak (strikes is 0 there by construction).
  const head = cd.platform ? `${cd.platform} · auto` : 'cooling — auto';
  const tail = cd.platform ? `${Math.ceil(cd.expires_in_s)}s` : `${Math.ceil(cd.expires_in_s)}s · ×${cd.strikes}`;
  return `${head} ${tail}`;
}

/** Model color for a lane's chip — from the live legend when present. */
function modelColor(model: string, profiles: Array<{ name: string; color?: string | null }>): string {
  const p = profiles.find((x) => x.name === model);
  return p?.color || 'var(--lab-muted)';
}

interface LaneHealthPanelProps {
  /** Live profile legend, for config-sourced model-chip colors. */
  profiles: Array<{ name: string; color?: string | null }>;
}

export default function LaneHealthPanel({ profiles }: LaneHealthPanelProps) {
  const [health, setHealth] = useState<LaneHealthMap | null>(null);
  const [registry, setRegistry] = useState<LaneRegistryView | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let live = true;
    const tick = async () => {
      const [h, r] = await Promise.all([
        inspectorApi.lanes(),
        inspectorApi.lanesRegistry(),
      ]);
      if (!live) return;
      setHealth(h);
      setRegistry(r);
      setLoaded(true);
    };
    void tick();
    const timer = setInterval(tick, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  // ── Merge the two payloads (hoisted above the early returns so the hook
  //    order is stable): registry order drives the table; the health map
  //    supplies the window + cooldown verbatim. Lanes with health data but no
  //    registry row (profiles that served this run outside the registry) append
  //    at the bottom so nothing the router records is hidden.
  const merged = useMemo(() => {
    const rows = registry?.lanes ?? [];
    const known = rows.filter((r) => health?.[r.profile] !== undefined);
    const unknown = Object.entries(health ?? {})
      .filter(([p]) => !rows.some((r) => r.profile === p))
      .map(([p, h]): LaneRegistryRow => ({
        id: p,
        source: 'live',
        model_id: '',
        profile: p,
        priority: 999,
        enabled: true,
        health: h.sick ? 'sick' : 'ok',
        cooldown: h.cooldown ?? null,
        cap_state: h.sick ? 'sick' : 'ok',
        discovered: false,
        free: false,
        out_hint: null,
        last_refresh_counter: 0,
      }));
    return [...known, ...unknown];
  }, [registry, health]);

  // ── Labeled states ──────────────────────────────────────────────────────────
  if (!loaded) {
    return (
      <div className="h-full flex items-center justify-center font-mono text-[11px] text-lab-muted">
        loading lane health…
      </div>
    );
  }
  if (health === null || registry === null) {
    return (
      <div className="h-full flex items-center justify-center font-mono text-[11px] text-lab-muted">
        no backend — lane health lives on the router (live runs only)
      </div>
    );
  }

  const byProfile = (p: string): LaneHealthRow | undefined => health[p];

  const sickCount = merged.filter((r) => r.health === 'sick').length;
  const coolingCount = merged.filter((r) => r.cooldown).length;
  const servedProfiles = Object.keys(health).length;

  return (
    <div className="h-full flex flex-col min-h-0 gap-2 p-2 overflow-y-auto">
      {/* ── Summary strip ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 shrink-0 lab-panel px-2 py-1.5">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-lab-muted">
          lanes
        </span>
        <span className="font-mono text-[11px] tabular-nums text-lab-text">
          {merged.length}
        </span>
        <span className="font-mono text-[10px] text-lab-muted">/</span>
        <span className="font-mono text-[11px] tabular-nums text-lab-text" title="lanes with ≥1 recorded outcome this run">
          {servedProfiles}
        </span>
        <span className="font-mono text-[10px] text-lab-muted">served</span>
        <span
          className={`font-mono text-[10px] font-bold tabular-nums px-1.5 py-px border rounded-sm ${
            sickCount > 0
              ? 'border-lab-danger text-lab-danger bg-lab-danger/10'
              : 'border-lab-border text-lab-muted'
          }`}
          title="lanes the router is pre-emptively skipping this run (≥3 demerits in the window)"
        >
          {sickCount} SICK
        </span>
        {coolingCount > 0 && (
          <span
            className="font-mono text-[10px] font-bold tabular-nums px-1.5 py-px border border-lab-warn text-lab-warn bg-lab-warn/10 rounded-sm"
            title="lanes inside a 429 cooldown window — routing to auto until the reset"
          >
            {coolingCount} COOLING
          </span>
        )}
        <span
          className={`ml-auto font-mono text-[10px] ${
            registry.discovery.enabled ? 'text-lab-acid' : 'text-lab-dim'
          }`}
          title={
            registry.discovery.enabled
              ? `discovery on — every ${registry.discovery.every_turns ?? '?'} turns (${registry.discovery.served_turns} served so far)`
              : 'discovery off — the registry is the static P1 sorting list'
          }
        >
          {registry.discovery.enabled ? `DISCOVERY ON · ${registry.discovery.served_turns} runs` : 'DISCOVERY OFF'}
        </span>
      </div>

      {/* ── The table ─────────────────────────────────────────────────── */}
      {merged.length === 0 ? (
        <div className="flex-1 flex items-center justify-center font-mono text-[11px] text-lab-muted">
          no lane outcomes recorded yet — the first LLM calls will populate this
        </div>
      ) : (
        <div className="flex flex-col gap-1 min-h-0">
          {merged.map((row) => {
            const h = byProfile(row.profile);
            if (!h) return null;
            return (
              <div
                key={row.profile}
                className="lab-panel px-2 py-1.5 flex items-center gap-2"
                title={`${row.profile} — ${row.model_id || row.id} · priority ${row.priority}`}
              >
                {/* status */}
                <span
                  className={`font-mono text-[10px] font-bold uppercase tracking-wider w-9 shrink-0 text-center ${
                    row.health === 'sick'
                      ? 'text-lab-danger'
                      : row.cooldown
                        ? 'text-lab-warn'
                        : 'text-lab-muted'
                  }`}
                >
                  {row.health === 'sick' ? 'SKIP' : row.cooldown ? 'AUTO' : 'OK'}
                </span>

                {/* model chip */}
                <span
                  className="font-mono text-[10px] shrink-0 rounded-sm px-1.5 py-px"
                  style={{ backgroundColor: modelColor(row.profile, profiles), color: '#0a0a0b' }}
                >
                  {row.profile}
                </span>

                {/* router's own window — verbatim, slot-for-slot */}
                <span className="flex items-center gap-[2px] shrink-0" title={h.window.length === 0 ? 'no outcomes in the 6-window yet' : undefined}>
                  {h.window.map((e, i) => (
                    <span
                      key={i}
                      className={`w-[10px] h-[10px] rounded-[2px] flex items-center justify-center font-mono text-[7px] leading-none ${windowCellClass(e)}`}
                      title={windowCellTitle(e, i, h.window.length)}
                    >
                      {windowCellGlyph(e)}
                    </span>
                  ))}
                </span>

                {/* cooldown */}
                {row.cooldown ? (
                  <span
                    className="font-mono text-[9px] tabular-nums shrink-0 px-1.5 py-px border border-lab-warn/60 text-lab-warn rounded-sm"
                    title="429 cooldown window (EM-300 P3) — pinned calls route to auto until this expires"
                  >
                    {cooldownLabel(row.cooldown)}
                  </span>
                ) : (
                  <span className="font-mono text-[9px] text-lab-dim shrink-0 w-0" aria-hidden="true" />
                )}

                {/* counters */}
                <span className="ml-auto flex items-center gap-2 shrink-0 font-mono text-[9px] tabular-nums text-lab-muted">
                  <span title="turn-budget timeouts in the window">⧖{h.timeouts}</span>
                  <span title="provider errors in the window" className={h.errors > 0 ? 'text-lab-danger' : ''}>
                    ✕{h.errors}
                  </span>
                  <span title="detoured calls this lane absorbed this run">⇄{h.detours_routed_here}</span>
                </span>

                {/* last routed_via — dash ≠ absent, a mark is a fact */}
                <span
                  className="font-mono text-[9px] text-lab-dim shrink-0 max-w-[10rem] truncate text-right"
                  title="the upstream model id the lane last actually answered with"
                >
                  {h.last_routed_via ?? '—'}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
