/**
 * GovernanceHistory (EM-057) — the legislative record made visible.
 *
 * A vertical legislative timeline of every rule the world ever debated. For
 * each rule_id it renders the full lifecycle (proposed → vote(s) →
 * active/rejected), the proposer, the rule's effect, the vote tally
 * (for / against) against the passing threshold, and — crucially — the
 * DOWNSTREAM CONSEQUENCES the enacted rule actually caused (a UBI
 * distribution, an agent_died after a ban, …).
 *
 * The headline failure mode this panel exists to surface: a rule that PASSED
 * but produced NO downstream events — the "clock tower" that the assembly
 * funded and voted up yet which never actually got built. A green checkmark on
 * the books, nothing in the world. We flag it loudly.
 *
 * Data: PURE projection of `props.events` via `governanceTimeline(events)` →
 * GovTimelineEntry[] (selectors.ts + types.ts). No backend required; renders
 * identically in mock and live mode. Re-projected at `props.currentTick` so the
 * timeline reflects exactly what had happened by the shared scrub position.
 *
 * Styling: token-only (lab-* Tailwind classes). Governance accent is BLUE,
 * pulled from the contract's color-code token (--marker-governance, declared in
 * inspector-tokens.css) — the SAME token the ReplayScrubber legend uses, never
 * a hardcoded hex. Dynamic `var(--token)` references in inline style are
 * design-token-guard clean (the established pattern in ReplayScrubber).
 */

import { useMemo } from 'react';
import type { PanelProps } from './types';
import type { GovTimelineEntry, GovDownstream } from './types';
import type { WorldEvent } from '../types';
import { governanceTimeline } from './selectors';
import './inspector-tokens.css';

// The contract's blue governance accent (event-log color-code, §4). Referenced
// as a CSS custom property so it stays in lockstep with the marker legend —
// no hardcoded literal. (Dynamic var() in style is token-guard clean.)
const GOV_ACCENT = 'var(--marker-governance)';

// Human labels for the rule effects the world knows about (open-ended: an
// unknown effect just shows its raw key, never crashes).
const EFFECT_LABEL: Record<string, string> = {
  ban_stealing: 'Ban stealing',
  ubi: 'Universal basic income',
  recharge_subsidy: 'Recharge subsidy',
  work_bonus: 'Honest-work bonus',
};

function effectLabel(effect: string | null): string {
  if (!effect) return 'Ordinance';
  return EFFECT_LABEL[effect] ?? effect.replace(/_/g, ' ');
}

interface Tally {
  forVotes: number;
  against: number;
  cast: number;
  /** Votes needed to pass (simple majority of those cast). */
  threshold: number;
}

/** Vote tally + the implied passing threshold (simple majority of cast). */
function tallyOf(entry: GovTimelineEntry): Tally {
  let forVotes = 0;
  let against = 0;
  for (const v of entry.votes) {
    if (v.choice) forVotes += 1;
    else against += 1;
  }
  const cast = forVotes + against;
  // Simple majority: strictly more than half the votes cast. Mirrors the
  // engine's `yes > cast / 2`. With no votes yet the threshold is 1 (a single
  // aye would carry an otherwise-empty floor).
  const threshold = cast > 0 ? Math.floor(cast / 2) + 1 : 1;
  return { forVotes, against, cast, threshold };
}

/** True when a rule made it onto the books but caused nothing — the clock tower. */
function isClockTower(entry: GovTimelineEntry): boolean {
  return entry.outcome === 'passed' && entry.downstream.length === 0;
}

export default function GovernanceHistory(props: PanelProps) {
  const { events, agents, currentTick } = props;

  // Re-project at the shared scrub tick: only legislate over what had happened
  // by `currentTick` (scrub once, every panel follows — the inspector contract).
  const scoped = useMemo(
    () => events.filter((e) => e.tick <= currentTick),
    [events, currentTick],
  );

  const timeline = useMemo(() => governanceTimeline(scoped), [scoped]);

  // id → display name for proposers / the consequence narration.
  const nameOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of agents) m.set(a.id, a.name);
    return m;
  }, [agents]);

  const stats = useMemo(() => summarize(timeline), [timeline]);

  return (
    <section
      className="lab-panel flex flex-col h-full min-h-[9rem]"
      aria-label="Governance & laws history (EM-057)"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <i
            className="inline-block w-2 h-2 rounded-sm"
            style={{ backgroundColor: GOV_ACCENT }}
            aria-hidden="true"
          />
          Governance · Laws
        </span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          EM-057
        </span>
      </div>

      {/* Assembly summary strip */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 border-b border-lab-border bg-lab-bg shrink-0">
        <Stat label="PROPOSED" value={stats.proposed} />
        <Stat label="ACTIVE" value={stats.active} accent={GOV_ACCENT} />
        <Stat label="REJECTED" value={stats.rejected} />
        <Stat label="OPEN" value={stats.open} />
        {stats.clockTowers > 0 && (
          <span
            className="ml-auto font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-warn text-lab-warn"
            title="Rules that passed but caused nothing in the world"
          >
            {stats.clockTowers} CLOCK-TOWER{stats.clockTowers === 1 ? '' : 'S'}
          </span>
        )}
      </div>

      {/* The legislative timeline */}
      {timeline.length === 0 ? (
        <EmptyState />
      ) : (
        <ol className="flex-1 min-h-0 overflow-y-auto px-3 py-3 flex flex-col gap-3">
          {timeline.map((entry) => (
            <RuleCard
              key={entry.ruleId}
              entry={entry}
              nameOf={nameOf}
              currentTick={currentTick}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

// ── One rule's lifecycle card ────────────────────────────────────────────────

function RuleCard({
  entry,
  nameOf,
  currentTick,
}: {
  entry: GovTimelineEntry;
  nameOf: Map<string, string>;
  currentTick: number;
}) {
  const tally = tallyOf(entry);
  const clockTower = isClockTower(entry);
  const proposer = entry.proposerId
    ? nameOf.get(entry.proposerId) ?? entry.proposerId
    : 'Unknown';

  return (
    <li
      className="relative border-l-2 pl-3 pb-1"
      style={{ borderColor: GOV_ACCENT }}
    >
      {/* Timeline node */}
      <span
        className="absolute -left-[5px] top-1 w-2 h-2 rounded-full ring-2 ring-lab-surface"
        style={{ backgroundColor: GOV_ACCENT }}
        aria-hidden="true"
      />

      <div className="flex flex-col gap-1.5 bg-lab-chrome border border-lab-border rounded-sm p-2.5">
        {/* Title row: effect + status pill */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="font-mono text-xs font-bold text-lab-text truncate">
              {effectLabel(entry.effect)}
            </span>
            {entry.text && (
              <span className="font-mono text-[10px] text-lab-muted leading-snug line-clamp-2">
                “{entry.text}”
              </span>
            )}
          </div>
          <StatusPill status={entry.status} outcome={entry.outcome} />
        </div>

        {/* Provenance: proposer + the rule_id + tick */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[10px] text-lab-dim">
          <span>
            by <span className="text-lab-muted">{proposer}</span>
          </span>
          <span className="tabular-nums">@ tick {entry.createdTick}</span>
          <span className="text-lab-dim/80 truncate">{entry.ruleId}</span>
        </div>

        {/* Status path: proposed → active / rejected */}
        <StatusPath entry={entry} />

        {/* Vote tally vs threshold */}
        <VoteTally tally={tally} />

        {/* Downstream consequences (or the clock-tower flag) */}
        <Downstream
          entry={entry}
          nameOf={nameOf}
          clockTower={clockTower}
          currentTick={currentTick}
        />
      </div>
    </li>
  );
}

// ── Status pill (proposed / active / rejected) ───────────────────────────────

function StatusPill({
  status,
  outcome,
}: {
  status: GovTimelineEntry['status'];
  outcome: GovTimelineEntry['outcome'];
}) {
  if (status === 'active') {
    return (
      <span
        className="shrink-0 font-mono text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-sm"
        style={{ backgroundColor: GOV_ACCENT, color: 'var(--lab-bg)' }}
      >
        ✓ Active
      </span>
    );
  }
  if (status === 'rejected') {
    return (
      <span className="shrink-0 font-mono text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-sm border border-lab-danger text-lab-danger">
        ✕ Rejected
      </span>
    );
  }
  // proposed (still on the floor)
  return (
    <span className="shrink-0 font-mono text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-sm border border-lab-border-bright text-lab-muted animate-pulse">
      ⋯ {outcome ? outcome : 'On floor'}
    </span>
  );
}

// ── Status path: proposed → (votes) → active / rejected ──────────────────────

function StatusPath({ entry }: { entry: GovTimelineEntry }) {
  const resolvedLabel =
    entry.status === 'active'
      ? 'enacted'
      : entry.status === 'rejected'
        ? 'rejected'
        : 'pending';
  const resolvedAccent =
    entry.status === 'active'
      ? GOV_ACCENT
      : entry.status === 'rejected'
        ? 'var(--lab-danger)'
        : 'var(--lab-dim)';

  return (
    <div className="flex items-center gap-1 font-mono text-[9px] uppercase tracking-wide text-lab-dim">
      <PathNode label="proposed" active accent={GOV_ACCENT} tick={entry.createdTick} />
      <PathArrow />
      <PathNode
        label={`${entry.votes.length} vote${entry.votes.length === 1 ? '' : 's'}`}
        active={entry.votes.length > 0}
        accent={GOV_ACCENT}
      />
      <PathArrow />
      <PathNode
        label={resolvedLabel}
        active={entry.status !== 'proposed'}
        accent={resolvedAccent}
        tick={entry.resolvedTick}
      />
    </div>
  );
}

function PathNode({
  label,
  active,
  accent,
  tick,
}: {
  label: string;
  active: boolean;
  accent: string;
  tick?: number | null;
}) {
  return (
    <span
      className={active ? 'text-lab-text' : 'text-lab-dim'}
      style={active ? { color: accent } : undefined}
    >
      {label}
      {tick != null && active ? (
        <span className="text-lab-dim normal-case"> @{tick}</span>
      ) : null}
    </span>
  );
}

function PathArrow() {
  return <span className="text-lab-dim">→</span>;
}

// ── Vote tally vs threshold ──────────────────────────────────────────────────

function VoteTally({ tally }: { tally: Tally }) {
  const { forVotes, against, cast, threshold } = tally;
  const max = Math.max(cast, threshold, 1);
  const forPct = (forVotes / max) * 100;
  const againstPct = (against / max) * 100;
  const thresholdPct = (threshold / max) * 100;
  const carried = forVotes >= threshold && cast > 0;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between font-mono text-[10px] text-lab-muted">
        <span>
          <span style={{ color: GOV_ACCENT }}>{forVotes} for</span>
          <span className="text-lab-dim"> · </span>
          <span className="text-lab-danger">{against} against</span>
        </span>
        <span className="tabular-nums text-lab-dim" title="Votes needed to carry (simple majority of those cast)">
          need {threshold}/{cast || '—'}
        </span>
      </div>
      {/* For / against bar with the threshold marker. */}
      <div className="relative h-1.5 w-full bg-lab-bg rounded-sm overflow-hidden">
        <span
          className="absolute inset-y-0 left-0"
          style={{ width: `${forPct}%`, backgroundColor: GOV_ACCENT }}
          aria-hidden="true"
        />
        <span
          className="absolute inset-y-0"
          style={{ left: `${forPct}%`, width: `${againstPct}%`, backgroundColor: 'var(--lab-danger)' }}
          aria-hidden="true"
        />
        {/* Threshold tick. */}
        {cast > 0 && (
          <span
            className="absolute inset-y-0 w-px"
            style={{ left: `${thresholdPct}%`, backgroundColor: 'var(--lab-text)' }}
            title={`Threshold: ${threshold}`}
            aria-hidden="true"
          />
        )}
      </div>
      <span className="font-mono text-[9px] text-lab-dim">
        {cast === 0
          ? 'awaiting votes'
          : carried
            ? `carried (${forVotes} ≥ ${threshold})`
            : `short of threshold (${forVotes} < ${threshold})`}
      </span>
    </div>
  );
}

// ── Downstream consequences (the clock-tower reveal) ─────────────────────────

function Downstream({
  entry,
  nameOf,
  clockTower,
  currentTick,
}: {
  entry: GovTimelineEntry;
  nameOf: Map<string, string>;
  clockTower: boolean;
  currentTick: number;
}) {
  // The clock-tower case: passed, but nothing followed. Surface it loudly —
  // this is the whole reason the panel exists.
  if (clockTower) {
    return (
      <div className="flex items-start gap-2 border border-lab-warn/60 bg-lab-warn/5 rounded-sm px-2 py-1.5">
        <span className="font-mono text-sm leading-none text-lab-warn" aria-hidden="true">
          ⏛
        </span>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[10px] font-bold uppercase tracking-wide text-lab-warn">
            Clock-tower failure
          </span>
          <span className="font-mono text-[10px] text-lab-muted leading-snug">
            Passed on the books, but no downstream events
            {entry.resolvedTick != null ? ` since tick ${entry.resolvedTick}` : ''}. The
            assembly enacted it — the world never moved.
          </span>
        </div>
      </div>
    );
  }

  if (entry.downstream.length === 0) {
    // A rejected or still-open rule has no consequences yet; say so plainly.
    return (
      <span className="font-mono text-[9px] text-lab-dim">
        {entry.outcome === 'rejected'
          ? 'no consequences (rejected)'
          : 'no downstream effects yet'}
      </span>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[9px] uppercase tracking-wide text-lab-dim">
        Caused {entry.downstream.length} downstream event
        {entry.downstream.length === 1 ? '' : 's'}
      </span>
      <ul className="flex flex-col gap-1">
        {entry.downstream.slice(0, 6).map((d) => (
          <DownstreamLink key={d.seq} down={d} nameOf={nameOf} sinceTick={entry.resolvedTick} />
        ))}
        {entry.downstream.length > 6 && (
          <li className="font-mono text-[9px] text-lab-dim pl-3">
            +{entry.downstream.length - 6} more…
          </li>
        )}
      </ul>
      <span className="sr-only">Projected through tick {currentTick}.</span>
    </div>
  );
}

function DownstreamLink({
  down,
  nameOf,
  sinceTick,
}: {
  down: GovDownstream;
  nameOf: Map<string, string>;
  sinceTick: number | null;
}) {
  const tone = consequenceTone(down.kind);
  const lag = sinceTick != null ? down.tick - sinceTick : null;
  return (
    <li className="flex items-start gap-1.5 font-mono text-[10px] leading-snug">
      {/* The causal connector — a small elbow from the rule to its effect. */}
      <span className="text-lab-dim select-none" aria-hidden="true">
        └─
      </span>
      <span
        className="shrink-0 px-1 py-px rounded-sm text-[9px] uppercase tracking-wide"
        style={{ color: tone, borderColor: tone, borderWidth: '1px', borderStyle: 'solid' }}
      >
        {kindLabel(down.kind)}
      </span>
      <span className="text-lab-muted min-w-0">
        {down.text ? linkifyNames(down.text, nameOf) : kindLabel(down.kind)}
        <span className="text-lab-dim tabular-nums">
          {' '}
          @{down.tick}
          {lag != null && lag > 0 ? ` (+${lag})` : ''}
        </span>
      </span>
    </li>
  );
}

// ── Empty / labeled state ────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2 px-4 py-6 text-center">
      <span
        className="font-mono text-2xl leading-none"
        style={{ color: GOV_ACCENT }}
        aria-hidden="true"
      >
        §
      </span>
      <p className="font-mono text-xs text-lab-muted leading-relaxed max-w-prose">
        No legislation yet. When an agent proposes a rule, its full lifecycle —
        proposal, votes, enactment or rejection, and every downstream
        consequence — will chart here.
      </p>
      <span className="font-mono text-[10px] uppercase tracking-widest text-lab-dim border border-lab-border px-2 py-0.5">
        Assembly idle
      </span>
    </div>
  );
}

// ── Small bits ───────────────────────────────────────────────────────────────

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] text-lab-muted">{label}</span>
      <span
        className="font-mono text-xs font-bold tabular-nums text-lab-text"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </span>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

interface Summary {
  proposed: number;
  active: number;
  rejected: number;
  open: number;
  clockTowers: number;
}

function summarize(timeline: GovTimelineEntry[]): Summary {
  let active = 0;
  let rejected = 0;
  let open = 0;
  let clockTowers = 0;
  for (const e of timeline) {
    if (e.status === 'active') active += 1;
    else if (e.status === 'rejected') rejected += 1;
    else open += 1;
    if (isClockTower(e)) clockTowers += 1;
  }
  return { proposed: timeline.length, active, rejected, open, clockTowers };
}

// Map a downstream event kind to a readable badge label.
function kindLabel(kind: WorldEvent['kind']): string {
  const k = String(kind);
  switch (k) {
    case 'economy':
      return 'economy';
    case 'agent_died':
      return 'death';
    case 'conflict':
      return 'conflict';
    case 'relationship':
      return 'relationship';
    case 'agent_speech':
      return 'speech';
    default:
      return k.replace(/_/g, ' ');
  }
}

// Color the consequence badge by severity: deaths/conflict read as danger,
// economy as the governance accent (it's the rule paying out), the rest dim.
function consequenceTone(kind: WorldEvent['kind']): string {
  const k = String(kind);
  if (k === 'agent_died' || k === 'conflict') return 'var(--lab-danger)';
  if (k === 'economy') return GOV_ACCENT;
  return 'var(--lab-muted)';
}

// Replace bare agent ids in a feed line with their display names, when the
// selector handed us id-shaped text. Cheap, defensive — never throws.
function linkifyNames(text: string, nameOf: Map<string, string>): string {
  if (nameOf.size === 0) return text;
  let out = text;
  for (const [id, name] of nameOf) {
    if (id && id !== name && out.includes(id)) {
      out = out.split(id).join(name);
    }
  }
  return out;
}
