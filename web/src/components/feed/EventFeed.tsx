/**
 * EventFeed — live terminal-style event log.
 * Newest entries on top. Left-bordered with profile_color.
 * agent_action entries show thought on hover; animal lines read inline.
 *
 * Scroll stability (EM-093, contract §9): while the reader is scrolled away
 * from the live edge the rendered list is a FROZEN SNAPSHOT of what was
 * visible the moment they left the top. Arrivals mutate nothing in the DOM —
 * neither the prepend-at-top shift nor the 200-cap trim-at-bottom clamp can
 * move the viewport, because the row set literally does not change. The
 * "X new" pill counts live arrivals against the snapshot; clicking it (or
 * scrolling back to the top) thaws the list and re-pins to newest. This is a
 * stronger form of scrollTop compensation: the compensation needed is zero.
 *
 * Filtering is inclusive: click a category chip to show ONLY that category,
 * click more to stack two or three, click an active chip to drop it. With none
 * focused, everything shows except the default-muted trace chain. The focus set
 * is persisted to localStorage.
 */

import { useRef, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import type { WorldEvent, EventKind } from '../../types';
import { llmDecidedAnimalTurns, isLlmDecidedAction, animalModelByTurn } from '../../lib/animalIdentity';
import { inspectorApi } from '../../inspector/api';
import type { GodInterveneKind, GodMiracleKind } from '../../inspector/api';
import { useBlindLineup } from '../blind/BlindLineupContext';

interface EventFeedProps {
  events: WorldEvent[];
  /**
   * Wave E (EM-185): the GRANT-a-petition reply channel — wired from
   * useSimulation.postBillboard (the SAME optimistic-free in_reply_to path
   * the god console's VOICE group uses). When absent (e.g. a context without
   * the god channel) the GRANT affordance does not render.
   */
  onGrantReply?: (text: string, inReplyTo?: string) => void;
  /**
   * EM-312 (Storylines Rail): when a storyline is selected, restrict the feed to
   * that thread — events whose actor or target is one of its principals. Absent
   * (feature off / nothing selected) ⇒ the feed is unchanged. The banner offers
   * a one-click clear via `onClearThread`.
   */
  threadFilter?: { id: string; title: string; principals: string[] } | null;
  onClearThread?: () => void;
}

// Icon per event kind. EventKind is permissive (open string union); FeedEntry
// falls back to '·' for kinds not listed here, so this stays a partial map.
// Exported for the Wave-E registry test (every new kind in all three registries).
export const KIND_ICON: Partial<Record<EventKind, string>> = {
  turn_start:       '▷',
  agent_action:     '◆',
  agent_speech:     '◉',
  agent_moved:      '→',
  economy:          '¢',
  conflict:         '✖',
  relationship:     '♡',
  agent_died:       '✦',
  agent_spawned:    '✧',
  // W9 survival/extinction surfacing (EM-070/071): starvation warnings read as
  // alarms, extinction as the run's full stop.
  agent_starving:   '⚠',
  world_extinct:    '☠',
  world_paused:     '⏸',
  rule_proposed:    '⚖',
  rule_vote:        '☑',
  rule_passed:      '★',
  rule_rejected:    '✘',
  memory:           '◈',
  parse_failure:    '⚠',
  model_reassigned: '⇄',
  // EM-315 — the Healing House verdict card (the town votes to remake a mind).
  sentenced_healing: '⚕',
  // Wave D2 (EM-158) — per-agent cadence tier reassignment receipt.
  cadence_tier_changed: '⇄',
  random_event:     '⊕',
  control:          '⏏',
  // Animal chaos layer (W8) — critter glyphs so the cat/dog read at a glance.
  animal_spawned:   '🐾',
  animal_action:    '🐾',
  animal_died:      '🐾',
  // W11b sim texture (event-log.md v1.3.0): the notice board, the diary, and
  // commitments. commitment_lapsed defaults to ⌛ (expired); the FeedEntry
  // overrides it with the 👻 phantom treatment when reason:"phantom".
  billboard_posted:  '📌',
  // EM-145 — god-voice delivery receipts ("✦ Bram hears the whisper" /
  // "📌 Ada reads the god's note"). Uncategorized ON PURPOSE, like
  // whisper_posted: the god's feedback channel is never filterable away.
  god_voice_heard:   '✦',
  reflection:        '✎',
  commitment_made:   '⚑',
  commitment_lapsed: '⌛',
  // Wave L / EM-223 — an agent set/revised its recursive plan (inner-life channel).
  plan_revised:      '🗺',
  usage_alert:       '⚠',
  run_forked:        '⑂',
  // Wave E (contracts/wave-e.md B6) — the social-city kinds. ♥ a typed bond
  // shifting, 👶 a birth, ⚑ the faction lifecycle, 🌧/☀ a miracle cast /
  // passing (the rains arrive, the rains pass).
  relationship_changed: '♥',
  child_spawned:        '👶',
  faction_formed:       '⚑',
  faction_joined:       '⚑',
  faction_left:         '⚑',
  faction_dissolved:    '⚑',
  god_miracle:          '🌧',
  miracle_expired:      '☀',
  // Wave O (EM-256–259) — organized violence reads with the ⚔ crossed-swords
  // prefix the backend already stamps on every war line; peace_signed answers
  // it with the 🕊 dove (the war is over). One lane, the red conflict register.
  war_declared:         '⚔',
  grievance_accrued:    '⚔',
  war_band_joined:      '⚔',
  war_clash:            '⚔',
  war_siege:            '⚔',
  war_exhausted:        '⚔',
  exiled:               '⚔',
  peace_signed:         '🕊',
  // EM-317 — the Prophecy Board: the 🔮 omen crystal on both the posting and
  // the FULFILLED/BROKEN resolution (the backend stamps the verdict in .text).
  prophecy_posted:      '🔮',
  prophecy_resolved:    '🔮',
  // EM-123 — a zoned district matured a tier (megaproject completed).
  district_grew:        '🏙',
  // Decision-trace chain (event-log.md §3) — default-muted via the Trace
  // category so these don't flood the live feed.
  perceived:        '◌',
  memory_retrieved: '◈',
  llm_call:         '⌁',
  reasoning:        '∴',
  action_chosen:    '◇',
  action_resolved:  '◆',
};

// Color tint for event kinds without a profile color.
// Exported for the Wave-E registry test. New (Wave E) entries are CSS token
// var() references (declared in roster-tokens.css / inspector-tokens.css —
// design-token-guard clean); they intentionally skip the hex-only
// alpha-append badge paths below, like --marker-animal does.
export const KIND_FALLBACK_COLOR: Partial<Record<EventKind, string>> = {
  agent_died:       '#ff3333',
  agent_spawned:    '#c8ff00',
  rule_passed:      '#c8ff00',
  rule_rejected:    '#ff3333',
  random_event:     '#ff9900',
  model_reassigned: '#c8ff00',
  parse_failure:    '#ff9900',
  control:          '#5a5a72',
  // Wave E — bonds read in the partner register, births in the family warmth,
  // the faction lifecycle in the shared faction tint, miracles in god-gold.
  relationship_changed: 'var(--rel-partner)',
  child_spawned:        'var(--rel-family)',
  faction_formed:       'var(--faction-tint)',
  faction_joined:       'var(--faction-tint)',
  faction_left:         'var(--faction-tint)',
  faction_dissolved:    'var(--faction-tint)',
  god_miracle:          'var(--marker-miracle)',
  miracle_expired:      'var(--marker-miracle)',
  // Wave O (EM-256–259) — war reads in the crime-red conflict register (the
  // SAME --marker-crime the social graph's rival/enemy edges wear), so the
  // whole war narrative pops red in the feed. peace_signed reads in the
  // faction tint — the war is settled, not another blow. Token var()s only
  // (design-token-guard); a war event carries no model profile_color (it's an
  // actor_type:"system" faction event) so these fallbacks always win.
  war_declared:         'var(--marker-crime)',
  grievance_accrued:    'var(--marker-crime)',
  war_band_joined:      'var(--marker-crime)',
  war_clash:            'var(--marker-crime)',
  war_siege:            'var(--marker-crime)',
  war_exhausted:        'var(--marker-crime)',
  exiled:               'var(--marker-crime)',
  peace_signed:         'var(--faction-tint)',
  // EM-315 — the Healing House sentence reads in the crime-red register: the
  // pitch's "lobotomy-grim" note — the town wielding the model scalpel as
  // punishment. Token var() only (design-token-guard); the system-emitted card
  // carries no profile_color so this fallback always wins.
  sentenced_healing:    'var(--marker-crime)',
  // EM-317 — the Prophecy Board reads in god-gold (the SAME --marker-miracle the
  // god's miracles wear), so an omen and its verdict pop as the god's voice.
  prophecy_posted:      'var(--marker-miracle)',
  prophecy_resolved:    'var(--marker-miracle)',
};

// W8 — the animal chaos magenta, referenced as the shared --marker-animal token
// (declared in inspector-tokens.css; the SAME magenta the chaos panel + replay
// timeline + 3D critter accent use), so an animal event reads as one color
// everywhere. Animal events ALWAYS use this border regardless of any model
// profile_color, so the critters pop out. It's a dynamic var() reference (the
// established ReplayScrubber/GovernanceHistory pattern) → design-token-guard
// clean. Animal events carry profile:null, so this never hits the hex-only
// alpha-append profile-badge path below.
const ANIMAL_MAGENTA = 'var(--marker-animal)';

/**
 * True for a benign action-rejection — an agent tried something the resolver
 * wouldn't allow (e.g. funding a building that rotted to `abandoned`, recalled
 * from memory), which the backend stamps with `payload.rejected`. These are
 * valid-parse, valid-LLM "no, you can't do that" receipts, NOT the
 * truncated-JSON / provider-error failures the ⚠ errors channel exists for, so
 * the live feed drops them as non-actionable clutter. They still persist in
 * history/DB for forensics; genuine parse_failures (no `rejected` flag) keep
 * their place in the errors channel.
 */
function isBenignRejection(e: WorldEvent): boolean {
  return e.kind === 'parse_failure' && e.payload?.rejected === true;
}

/**
 * FEED-SILENCE (EM-318, defaults ON) — a routing-EXHAUSTION idle-fallback: the
 * turn reached NO model (every lane rate-limited/exhausted or the proxy `auto`
 * returned "All models exhausted", or the connection was down), so the backend
 * idled the agent with a `payload.reason` starting `provider_error`. During a
 * free-tier rate window MANY agents idle this way at once and the live feed
 * used to fill with identical "failed to produce a valid action" cards — pure
 * noise: nothing the watcher can act on, and the agent already retries next
 * tick (never muted — the no-throttling law). We SILENCE these from the live
 * feed; the event still persists in history/DB for forensics AND the loop's
 * server-side provider-error streak still auto-pauses the run (this is a
 * viewer-only filter — off the replay surface). CONTENT parse failures
 * (truncated JSON / finish_reason=length / validation) carry a DIFFERENT reason
 * and keep their place in the ⚠ errors channel — only the "no model answered"
 * exhaustion class is silenced.
 */
function isSilencedProviderError(e: WorldEvent): boolean {
  const reason = e.payload?.reason;
  return (
    e.kind === 'parse_failure' &&
    typeof reason === 'string' &&
    reason.startsWith('provider_error')
  );
}

/** True when an event belongs to the animal chaos channel (W8). */
function isAnimalEvent(e: WorldEvent): boolean {
  return (
    e.actor_type === 'animal' ||
    e.kind === 'animal_spawned' ||
    e.kind === 'animal_action' ||
    e.kind === 'animal_died'
  );
}

// ── GRANT-a-petition (Wave E EM-185) ──────────────────────────────────────────
//
// Petition-shaped entries — an AGENT's billboard post or proclamation answer —
// grow a small GRANT affordance. Clicking it expands a compact INLINE picker
// inside the feed entry (not a god-console handoff: the petition is right
// there, the answer should be too; an inline expander also survives the feed's
// overflow scroll without portal/clipping games). Granting fires BOTH halves
// of the ask→answer loop, optimistic-free:
//   (a) POST /api/god/intervene — world kinds carry NO agent_id key (the
//       backend 422s otherwise); targeted kinds aim at the petitioner;
//   (b) the god billboard reply quoting the petition via the existing
//       in_reply_to mechanism (the same postBillboard path VOICE uses).
// No local echo anywhere — the god_miracle / god_intervention and
// billboard_posted (actor_type 'god') WS events are the only confirmation.

/** True for a petition-shaped entry: an agent (never god) asking the watchers. */
export function isPetitionEvent(e: WorldEvent): boolean {
  return (
    (e.kind === 'billboard_posted' || e.kind === 'proclamation_answered') &&
    e.actor_type !== 'god'
  );
}

interface GrantOption {
  kind: GodMiracleKind | GodInterveneKind;
  label: string;
  /** World-scale ⇒ POST without agent_id; targeted ⇒ aimed at the petitioner. */
  world: boolean;
  /** The reply verb quoted back onto the billboard. */
  granted: string;
}

const GRANT_OPTIONS: GrantOption[] = [
  { kind: 'send_rain',         label: '🌧 SEND RAIN',     world: true,  granted: 'rain falls on the gardens' },
  { kind: 'bountiful_harvest', label: '🌾 HARVEST',       world: true,  granted: 'a bountiful harvest eases every belly' },
  { kind: 'calm_spirits',      label: '🕊 CALM SPIRITS',  world: true,  granted: 'calm settles over every spirit' },
  { kind: 'bless_energy',      label: '☀ BLESS +25⚡',    world: false, granted: 'the petitioner is blessed with energy' },
  { kind: 'grant_credits',     label: '✦ GRANT +10₡',    world: false, granted: 'the petitioner is granted credits' },
];

/** The petition's own words (payload.text is the post body; e.text is prose). */
function petitionQuote(e: WorldEvent): string {
  const p = e.payload?.text;
  return (typeof p === 'string' && p.trim() ? p : e.text ?? '').trim();
}

function GrantAffordance({
  event,
  onReply,
}: {
  event: WorldEvent;
  onReply: (text: string, inReplyTo?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [granted, setGranted] = useState<string | null>(null);

  const quote = petitionQuote(event);
  const petitionerId = event.actor_id ?? null;

  const grant = async (opt: GrantOption) => {
    if (busy) return;
    setBusy(opt.kind);
    setError(null);
    const result = opt.world
      ? await inspectorApi.godMiracle(opt.kind as GodMiracleKind)
      : await inspectorApi.godIntervene(opt.kind as GodInterveneKind, petitionerId ?? '');
    setBusy(null);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    // Half (b): the god's billboard answer, quoting the petition. in_reply_to
    // is backend-capped at 120; postBillboard caps the text at 280 itself.
    onReply(
      `✦ Granted — ${opt.granted}. In answer to: “${quote.slice(0, 160)}”`,
      quote.slice(0, 120) || undefined,
    );
    setGranted(opt.label);
    setOpen(false);
  };

  if (granted) {
    return (
      <span
        className="ml-1.5 font-mono text-[9px] px-1 py-px border rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
        style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
        role="status"
        title="Granted — the miracle/intervention and the god's billboard answer arrive via the feed (no local echo)."
      >
        ✦ granted
      </span>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen((o) => !o); setError(null); }}
        aria-expanded={open}
        aria-label="Grant this petition"
        title="Answer this petition as the god — cast a miracle or intervene, and post the reply on the billboard"
        className="ml-1.5 font-mono text-[9px] font-bold px-1 py-px border rounded-sm align-middle
                   whitespace-nowrap uppercase tracking-wider cursor-pointer transition-colors duration-100
                   hover:bg-lab-chrome"
        style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
      >
        ✦ grant{open ? ' ▾' : ''}
      </button>

      {open && (
        <div
          className="mt-1 p-1.5 border border-lab-border rounded-sm bg-lab-chrome/60 space-y-1"
          role="group"
          aria-label="Grant the petition — pick a miracle or intervention"
        >
          {/* EM-191 — the petitioner's own (injection-shaped, React-escaped,
              280-capped) words read as a QUOTED nested block: a left-border
              rule + italic + softer ink quarantines the agent's voice from the
              god's own UI chrome (the "petition" label, the action buttons), so
              the two channels never visually blend. The label below is the
              god's voice naming the channel; the blockquote is the agent's. */}
          <span className="block font-mono text-[8px] text-lab-dim uppercase tracking-wider not-italic">
            petition
          </span>
          <blockquote
            data-testid="grant-petition-quote"
            className="m-0 pl-2 border-l-2 border-lab-border-bright font-mono text-[9px]
                       text-lab-muted italic leading-snug break-words"
          >
            “{quote || '(no petition text)'}”
          </blockquote>
          <div className="flex flex-wrap gap-1">
            {GRANT_OPTIONS.map((opt) => {
              const needsTarget = !opt.world && !petitionerId;
              return (
                <button
                  key={opt.kind}
                  type="button"
                  onClick={() => void grant(opt)}
                  disabled={busy !== null || needsTarget}
                  aria-label={`Grant via ${opt.kind}`}
                  title={
                    needsTarget
                      ? 'No petitioner on this entry — targeted grants need one'
                      : opt.world
                        ? `World-scale miracle: ${opt.granted} (no target)`
                        : `Targeted at the petitioner: ${opt.granted}`
                  }
                  className="font-mono text-[9px] px-1 py-px border border-lab-border rounded-sm cursor-pointer
                             text-lab-muted hover:text-lab-acid hover:border-lab-acid transition-colors duration-100
                             disabled:opacity-40 disabled:cursor-default"
                >
                  {busy === opt.kind ? '…' : opt.label}
                </button>
              );
            })}
          </div>
          {error && (
            <p role="alert" className="m-0 font-mono text-[9px] text-lab-warn leading-snug">
              ⚠ {error}
            </p>
          )}
        </div>
      )}
    </>
  );
}

// ── Filter categories ─────────────────────────────────────────────────────────
// Every EventKind maps to exactly one category so nothing is orphaned.
interface FeedCategory {
  key: string;
  label: string;
  icon: string;
  kinds: EventKind[];
}

export const CATEGORIES: FeedCategory[] = [
  { key: 'chat',    label: 'Chat',    icon: '◉', kinds: ['agent_speech'] },
  { key: 'actions', label: 'Actions', icon: '◆', kinds: ['agent_action', 'agent_moved'] },
  { key: 'economy', label: 'Economy', icon: '¢', kinds: ['economy'] },
  // Wave E: the social fabric grows typed-bond shifts, births, and the
  // faction lifecycle — all social-texture kinds, one chip. Wave O (EM-256–259)
  // folds the war narrative into the SAME lane the crime `conflict` kind lives
  // in — the red conflict register — so filtering Social surfaces the whole
  // grievance → war → peace arc alongside the crime it grows from.
  { key: 'social',  label: 'Social',  icon: '♡', kinds: ['relationship', 'relationship_changed', 'conflict', 'agent_died', 'agent_spawned', 'child_spawned', 'agent_starving', 'world_extinct', 'faction_formed', 'faction_joined', 'faction_left', 'faction_dissolved', 'war_declared', 'grievance_accrued', 'war_band_joined', 'war_clash', 'war_siege', 'peace_signed', 'war_exhausted', 'exiled'] },
  // EM-315 — the Healing House verdict (`sentenced_healing`) lands with the rule
  // outcomes it is decided by; the follow-on transplant rides `model_reassigned`
  // in the System (model-lever) lane.
  { key: 'rules',   label: 'Rules',   icon: '⚖', kinds: ['rule_proposed', 'rule_vote', 'rule_passed', 'rule_rejected', 'sentenced_healing'] },
  // W11b (EM-091): the notice board gets its own chip — also the contract's
  // suggested feed-filter affordance for billboard traffic.
  { key: 'board',   label: 'Board',   icon: '📌', kinds: ['billboard_posted'] },
  // W11b (EM-079/080): the inner-life channel — diary reflections + spoken
  // commitments (made / kept / 👻 phantom-lapsed).
  { key: 'diary',   label: 'Diary',   icon: '✎', kinds: ['reflection', 'commitment_made', 'commitment_lapsed', 'plan_revised'] },
  // Wave E: god miracles live with the other world-scale levers (random_event
  // is the closest sibling — god_intervention itself is uncategorized ON
  // PURPOSE, but miracles are filterable world events, not feedback receipts).
  { key: 'system',  label: 'System',  icon: '⊕', kinds: ['turn_start', 'control', 'model_reassigned', 'cadence_tier_changed', 'random_event', 'god_miracle', 'miracle_expired', 'prophecy_posted', 'prophecy_resolved', 'memory', 'run_forked', 'world_paused', 'district_grew'] },
  // W8 — the cat & dog chaos channel (magenta). Its OWN category, NOT folded
  // into Trace, so the default-muted trace chain never hides the critters.
  { key: 'animals', label: 'Animals', icon: '🐾', kinds: ['animal_spawned', 'animal_action', 'animal_died'] },
  { key: 'errors',  label: 'Errors',  icon: '⚠', kinds: ['parse_failure', 'usage_alert'] },
  // Decision-trace chain (event-log.md §3). DEFAULT-MUTED: these are the
  // inspector's substrate, not live-feed reading material. Dissect them in the
  // /inspector annex; here they're collapsed so the feed isn't flooded.
  { key: 'trace',   label: 'Trace',   icon: '⌁', kinds: ['perceived', 'memory_retrieved', 'llm_call', 'reasoning', 'action_chosen', 'action_resolved'] },
];

// Categories muted on first load (no saved preference). The trace chain is
// noisy and belongs to the inspector, so it starts collapsed in the live feed.
const DEFAULT_MUTED: string[] = ['trace'];

const KIND_TO_CATEGORY: Partial<Record<EventKind, string>> = {};
CATEGORIES.forEach((c) => c.kinds.forEach((k) => { KIND_TO_CATEGORY[k] = c.key; }));

// Inclusion filter: the set of categories to SHOW. Empty = the default view
// (every category except the noisy DEFAULT_MUTED trace chain). Clicking a chip
// adds it here, so "click a filter" shows FOR that category (and you can stack
// two or three) instead of muting it out.
const STORAGE_KEY = 'em.feed.focusCategories';

function loadFocus(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch { /* ignore */ }
  return new Set();
}

function formatTime(ts: string | undefined): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

interface FeedEntryProps {
  event: WorldEvent;
  isNew: boolean;
  /**
   * EM-089: true when this animal_action was an LLM decision (it shares a
   * turn_id with an animal llm_call). Reflex actions — and histories where the
   * llm_call fell out of the window — get no marker (graceful degradation).
   */
  llmDecided?: boolean;
  /**
   * EM-089: the model profile that decided this animal turn (from the sibling
   * llm_call). Present only for LLM-decided animal_action rows — drives the
   * inline model chip so the feed names WHICH model the critter is running.
   */
  animalModel?: string;
  /** Wave E (EM-185): the GRANT reply channel; absent ⇒ no GRANT affordance. */
  onGrantReply?: (text: string, inReplyTo?: string) => void;
}

function FeedEntry({ event, isNew, llmDecided = false, animalModel, onGrantReply }: FeedEntryProps) {
  // EM-309 (Blind Lineup): the feed is the centerpiece, so its inline model
  // chips are the loudest identity tell — mask them behind ??? while a round is
  // live (the profile COLOR / left-border stays as the slot cue).
  const { maskName } = useBlindLineup();
  // W8: animal events ALWAYS take the magenta border + a critter glyph (they have
  // no model profile_color, and we want them to pop out of the human-agent feed).
  const animal = isAnimalEvent(event);
  // W9 (EM-070/071): starvation warnings ALWAYS read in the warn register and
  // extinction in the danger register — even though these events carry a model
  // profile_color, a survival alarm must not blend into the agent's color.
  const starving = event.kind === 'agent_starving';
  const extinct = event.kind === 'world_extinct';
  // W11b (EM-091): a billboard post by the watchers reads in GOD INK — the
  // violet register the god panel already owns — never an agent color.
  // EM-145: delivery receipts (god_voice_heard) share the ink — the whole
  // god↔agent channel reads as one color in the feed.
  const godPost =
    (event.kind === 'billboard_posted' && event.actor_type === 'god') ||
    event.kind === 'god_voice_heard';
  // W11b (EM-080): diary reflections take the muted-italic diary idiom.
  const reflection = event.kind === 'reflection';
  // W11b (EM-079): a phantom-lapsed commitment — claimed in speech, never
  // enacted — gets the 👻 treatment (the headline failure mode).
  const phantom =
    event.kind === 'commitment_lapsed' && event.payload?.reason === 'phantom';
  // W11b (EM-083): usage alerts read in the warn register like other alarms.
  const usageAlert = event.kind === 'usage_alert';
  // Wave D2 (EM-159/166): a background agent's zero-LLM reflex turn — marked
  // subtly so the free-scale machinery is legible without shouting.
  const reflexTurn = event.payload?.reflex === true;
  // W11b (EM-087): a renewal of an already-active law (rule_passed carrying
  // payload.renewed) renders RENEWED, distinct from a fresh PASSED.
  const renewed = event.kind === 'rule_passed' && event.payload?.renewed === true;
  // EM-202 (A/B persona-across-models): an agent_spawned variant carries
  // payload.ab_group (the shared base name) — surface a chip so the variant
  // reads as part of the model-vs-model group, correlated with the model chip.
  const abGroup =
    event.kind === 'agent_spawned' && typeof event.payload?.ab_group === 'string'
      ? (event.payload.ab_group as string)
      : null;
  const color = animal
    ? ANIMAL_MAGENTA
    : godPost
      ? 'var(--lab-god)'
      : starving || usageAlert
        ? 'var(--lab-warn)'
        : extinct
          ? 'var(--lab-danger)'
          : event.profile_color ?? KIND_FALLBACK_COLOR[event.kind] ?? 'var(--marker-trace)';
  // The inline model chip alpha-appends hex digits, so it only renders with a
  // hex source (the agent's data-driven profile color / a kind fallback) — the
  // var()-register warning kinds (starving/extinct/god) never reach it.
  const badgeColor = event.profile_color ?? KIND_FALLBACK_COLOR[event.kind] ?? null;
  const icon = animal
    ? '🐾'
    : phantom
      ? '👻'
      : renewed
        ? '↻'
        : KIND_ICON[event.kind] ?? '·';
  // Chat-first (contract §9 priority clarification): dialogue is the
  // centerpiece — speech rows read slightly larger with inline speaker/model
  // attribution, so the conversation scans without hovering.
  const speech = event.kind === 'agent_speech';
  // EM-201 — a Chronicle chapter is a wall of prose; in the LIVE feed it
  // collapses to a one-line teaser (the full text lives in the Chronicle tab).
  const chapter = event.kind === 'narrator_summary';
  const chapterTeaser = chapter
    ? `📖 New chapter — "${(event.text ?? '').replace(/\s+/g, ' ').trim().slice(0, 64)}…" · read it in the Chronicle`
    : null;
  // Surface the animal's in-character thought (or any agent_action thought) on hover.
  const tip = animal
    ? (typeof event.payload?.animal_thought === 'string' ? event.payload.animal_thought : event.thought)
    : event.kind === 'agent_action'
      ? event.thought
      : undefined;
  const hasTip = Boolean(tip);

  return (
    <div
      className={`group relative flex items-start gap-2 py-1.5 px-2 border-b border-lab-border/40
                  hover:bg-lab-chrome/50 transition-colors duration-100
                  ${isNew ? 'feed-entry-new' : ''}`}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      {/* Icon */}
      <span
        className={`flex-none font-mono text-xs w-4 text-center mt-px shrink-0 ${phantom ? 'phantom-drift' : ''}`}
        style={{ color }}
        aria-hidden="true"
      >
        {icon}
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <span
          className={`font-mono leading-relaxed break-words ${speech ? 'text-[13px]' : 'text-xs'} ${
            starving || usageAlert
              ? 'text-lab-warn font-semibold'
              : extinct
                ? 'text-lab-danger font-bold uppercase tracking-wide'
                : reflection || phantom
                  ? 'text-lab-muted italic'
                  : godPost
                    ? 'font-semibold'
                    : 'text-lab-text'
          }`}
          style={godPost ? { color: 'var(--lab-god-bright)' } : undefined}
        >
          {chapter ? chapterTeaser : (event.text ?? `[${event.kind}]`)}
        </span>

        {/* Inline model attribution on EVERY model-decided line (not just
            speech) so the feed always names the model with no hover. Excluded:
            reflex turns (zero-LLM → the ⟳ chip instead), god posts (their own
            ink), and animals (profile is null by design → the magenta animal
            chip above). Hex-only, alpha-appended border. */}
        {event.profile && badgeColor && badgeColor.startsWith('#') && !godPost && !reflexTurn && (
          <span
            className="ml-1.5 font-mono text-[9px] px-1 py-px border rounded-sm align-middle whitespace-nowrap"
            style={{ color: badgeColor, borderColor: badgeColor + '50' }}
            title={speech ? `spoken by a ${maskName(event.profile)} villager` : `decided by ${maskName(event.profile)}`}
          >
            {maskName(event.profile)}
          </span>
        )}

        {/* EM-202: the A/B group chip — names the shared base persona so a
            spawned variant reads as one of a model-vs-model group (the model
            chip above already names WHICH model this variant runs). */}
        {abGroup && (
          <span
            className="ml-1.5 font-mono text-[9px] font-bold px-1 py-px border rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            style={{ color: 'var(--lab-acid)', borderColor: 'var(--lab-acid)' }}
            title={`A/B group “${abGroup}” — the same persona spawned across models to compare them`}
          >
            ⚗ A/B · {abGroup}
          </span>
        )}

        {/* W11b (EM-091): the watchers' replies carry the GOD ink chip. */}
        {godPost && (
          <span
            className="ml-1.5 font-mono text-[9px] font-bold px-1 py-px border rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
            title="Posted by the watchers (god mode) — agents will see it on the notice board"
          >
            ✦ god
          </span>
        )}

        {/* Wave E (EM-185): GRANT on petition-shaped entries — an AGENT's
            billboard post / proclamation answer, never the god's own ink. */}
        {onGrantReply && isPetitionEvent(event) && (
          <GrantAffordance event={event} onReply={onGrantReply} />
        )}

        {/* W11b (EM-079): the phantom-commitment chip — promised aloud, never
            enacted. A 👻 haunts the line so the failure mode is legible. */}
        {phantom && (
          <span
            className="ml-1.5 font-mono text-[9px] px-1 py-px border border-lab-border-bright text-lab-muted rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            title="Phantom commitment — claimed in speech, but no matching tool call ever happened. All talk."
          >
            👻 phantom
          </span>
        )}

        {/* W11b (EM-087): renewal of an active law ≠ a fresh enactment. */}
        {renewed && (
          <span
            className="ml-1.5 font-mono text-[9px] font-bold px-1 py-px border rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            style={{ color: 'var(--marker-governance)', borderColor: 'var(--marker-governance)' }}
            title="Renewed — re-proposing an identical active law extends it; it never stacks."
          >
            ↻ renewed
          </span>
        )}

        {/* Wave D2 (EM-159/166): zero-LLM background reflex turn — a subtle
            dim chip, the human-agent sibling of the animals' reflex idiom. */}
        {reflexTurn && (
          <span
            className="ml-1.5 font-mono text-[9px] px-1 py-px border border-lab-border text-lab-dim rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            title="Reflex turn — a background-tier agent resolved this deterministically with zero LLM calls"
          >
            ⟳ reflex
          </span>
        )}

        {/* EM-089: LLM-decided animal action (vs a zero-cost reflex). */}
        {llmDecided && (
          <span
            className="ml-1.5 font-mono text-[10px] cursor-default"
            title="LLM decision — the animal's model chose this action (reflex actions carry no marker)"
            aria-label="LLM decision"
          >
            🧠
          </span>
        )}

        {/* EM-089: name WHICH model decided this animal turn — the critter
            counterpart to the human speech chip, in the animal magenta register
            (the animal_action itself carries no profile by design, so the model
            is sourced from the sibling llm_call via animalModelByTurn). */}
        {animalModel && (
          <span
            className="ml-1.5 font-mono text-[9px] px-1 py-px border rounded-sm align-middle whitespace-nowrap"
            style={{ color: ANIMAL_MAGENTA, borderColor: ANIMAL_MAGENTA }}
            title={`decided by ${maskName(animalModel)}`}
          >
            {maskName(animalModel)}
          </span>
        )}

        {/* An animal's in-character line reads INLINE (the chaos dialogue is the
            point) rather than being buried in a hover tooltip. */}
        {animal && hasTip && (
          <span className="block font-mono text-xs text-lab-muted italic leading-relaxed break-words mt-0.5">
            “{tip}”
          </span>
        )}

        {/* Agent reasoning stays on hover so the live feed isn't flooded. */}
        {!animal && hasTip && (
          <div className="lab-tooltip bottom-full left-0 mb-1 w-56">
            <span className="text-lab-muted">thought: </span>
            <span className="text-lab-text">{tip}</span>
          </div>
        )}
      </div>

      {/* Tick + time */}
      <div className="flex-none flex flex-col items-end gap-0.5 shrink-0">
        <span className="font-mono text-[10px] text-lab-muted tabular-nums">T{event.tick}</span>
        {event.ts && (
          <span className="font-mono text-[9px] text-lab-dim">{formatTime(event.ts)}</span>
        )}
      </div>

    </div>
  );
}

// How close to the top counts as "pinned to newest" (px).
const TOP_THRESHOLD = 8;

export function EventFeed({ events, onGrantReply, threadFilter, onClearThread }: EventFeedProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const highlightLenRef = useRef(0);
  const newEventIdsRef = useRef<Set<number>>(new Set());

  // EM-093: the frozen snapshot. null = pinned to newest (live, list follows
  // arrivals); an array = the exact row set rendered while the reader is
  // scrolled away. Arrivals never touch the frozen DOM, so the viewport can't
  // move — not on prepend, and not on the upstream 200-cap trim.
  const [frozen, setFrozen] = useState<WorldEvent[] | null>(null);
  const [focus, setFocus] = useState<Set<string>>(loadFocus);

  // Persist focused categories.
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...focus])); } catch { /* ignore */ }
  }, [focus]);

  // EM-089: turn_ids of animal LLM decisions, scanned over the FULL feed pool
  // (the llm_call rows themselves are trace-category and default-muted, but
  // they still inform the 🧠 marker on the visible animal_action lines).
  const llmAnimalTurns = useMemo(() => llmDecidedAnimalTurns(events), [events]);
  // EM-089: turn_id → model profile for animal LLM decisions, so a visible
  // animal_action line can name WHICH model decided it (the llm_call rows are
  // trace-category/default-muted but still carry the attribution).
  const animalModels = useMemo(() => animalModelByTurn(events), [events]);

  // Inclusion filter: with categories focused, show ONLY those; with none
  // focused, show everything except the default-muted trace chain. Benign
  // action-rejections AND routing-exhaustion idle-fallbacks (EM-318 feed-
  // silence) are dropped first — they're non-actionable clutter, not real
  // errors, so they never appear (even when the errors channel is focused).
  // EM-312: the selected storyline's principals as a fast lookup (null = off).
  const threadPrincipals = useMemo(
    () => (threadFilter ? new Set(threadFilter.principals) : null),
    [threadFilter],
  );

  const visibleEvents = useMemo(
    () => {
      const base = events.filter(
        (e) => !isBenignRejection(e) && !isSilencedProviderError(e));
      const byCategory = focus.size === 0
        ? base.filter((e) => !DEFAULT_MUTED.includes(KIND_TO_CATEGORY[e.kind] ?? ''))
        : base.filter((e) => focus.has(KIND_TO_CATEGORY[e.kind] ?? ''));
      // EM-312: with a storyline selected, keep only events touching one of its
      // principals (actor OR target) — "catch up on this beef". Orthogonal to
      // the category chips; both must pass.
      if (!threadPrincipals) return byCategory;
      return byCategory.filter(
        (e) =>
          (e.actor_id != null && threadPrincipals.has(e.actor_id)) ||
          (e.target_id != null && threadPrincipals.has(e.target_id)),
      );
    },
    [events, focus, threadPrincipals],
  );

  // What actually renders: the live filtered list while pinned, the snapshot
  // while scrolled away.
  const displayEvents = frozen ?? visibleEvents;
  const scrolledAway = frozen !== null;

  // The "X new" pill: live arrivals not present in the snapshot. Deduped by
  // seq (NOT a max-seq comparison — client-synthesized events carry negative
  // seqs, so set membership is the only safe identity).
  const unseen = useMemo(() => {
    if (!frozen) return 0;
    const held = new Set(frozen.map((e) => e.seq));
    let n = 0;
    for (const e of visibleEvents) if (!held.has(e.seq)) n++;
    return n;
  }, [frozen, visibleEvents]);

  // Highlight freshly-arrived entries briefly. Tracked with its own length ref so
  // it stays independent of the freeze bookkeeping.
  useEffect(() => {
    if (visibleEvents.length > highlightLenRef.current) {
      const added = visibleEvents.length - highlightLenRef.current;
      newEventIdsRef.current = new Set(visibleEvents.slice(0, added).map((e) => e.seq));
      highlightLenRef.current = visibleEvents.length;
      const t = setTimeout(() => { newEventIdsRef.current = new Set(); }, 300);
      return () => clearTimeout(t);
    }
    highlightLenRef.current = visibleEvents.length;
  }, [visibleEvents]);

  // While pinned, newest entries prepend at the top — hold the viewport on
  // the live edge (scrollTop 0). While frozen this is a no-op by design.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && frozen === null) el.scrollTop = 0;
  }, [visibleEvents, frozen]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const atTop = el.scrollTop <= TOP_THRESHOLD;
    if (atTop) {
      // Back at the live edge: thaw and re-pin.
      setFrozen((f) => (f === null ? f : null));
    } else {
      // Leaving the live edge: freeze the row set exactly as rendered now.
      setFrozen((f) => f ?? visibleEvents);
    }
  };

  const jumpToNewest = () => {
    const el = listRef.current;
    if (!el) return;
    setFrozen(null);
    el.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // Click a chip to focus that category (show only it). Click more to stack two
  // or three; click an active one to drop it. Empty focus → default view.
  const toggleFocus = (key: string) => {
    setFocus((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
    // A filter change re-pins to newest so the list doesn't jump unpredictably.
    setFrozen(null);
  };

  const clearFocus = () => {
    setFocus(new Set());
    setFrozen(null);
  };

  const hiddenCount = events.length - visibleEvents.length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="lab-header flex items-center justify-between">
        {/* EM-082 a11y: a real heading so the feed lands in the page outline. */}
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">EVENT STREAM</h2>
        <div className="flex items-center gap-2">
          <span className="text-lab-muted text-[10px]">
            {events.length === 0
              ? 'NO EVENTS'
              : hiddenCount > 0
                ? `${visibleEvents.length}/${events.length}`
                : `${events.length} events`}
          </span>
          <span
            className={`font-mono text-[10px] px-1.5 py-0.5 border
                        ${scrolledAway
                          ? 'border-lab-border text-lab-muted'
                          : 'border-lab-acid text-lab-acid'}`}
            title={scrolledAway ? 'Scrolled — newest entries are paused above' : 'Pinned to newest'}
          >
            {scrolledAway ? 'PAUSED' : 'LIVE'}
          </span>
        </div>
      </div>

      {/* EM-312: the active storyline filter — the feed is narrowed to one
          thread's principals. One click clears it. */}
      {threadFilter && (
        <div className="flex items-center gap-2 px-2 py-1 border-b border-lab-acid/40 bg-lab-acid/10">
          <span aria-hidden="true" className="font-mono text-[10px]" style={{ color: 'var(--marker-crime)' }}>✦</span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-lab-muted shrink-0">Storyline</span>
          <span className="font-mono text-[11px] text-lab-text font-semibold truncate min-w-0">{threadFilter.title}</span>
          {onClearThread && (
            <button
              type="button"
              onClick={onClearThread}
              className="ml-auto font-mono text-[10px] px-1.5 py-0.5 border border-lab-acid text-lab-acid
                         rounded-sm hover:bg-lab-acid/15 cursor-pointer transition-colors duration-100 shrink-0"
              title="Clear the storyline filter — show the whole feed"
            >
              CLEAR ✕
            </button>
          )}
        </div>
      )}

      {/* Filter bar — click a chip to show ONLY that category; click more to stack
          two or three; click an active one to drop it. Empty = default view. */}
      <div className="flex flex-wrap items-center gap-1 px-2 py-1 border-b border-lab-border/40 bg-lab-chrome/20">
        {CATEGORIES.map((cat) => {
          // Active = currently shown. With no focus, that's everything except the
          // default-muted trace chain; with a focus set, only the focused chips.
          const isActive = focus.size === 0
            ? !DEFAULT_MUTED.includes(cat.key)
            : focus.has(cat.key);
          return (
            <button
              key={cat.key}
              onClick={() => toggleFocus(cat.key)}
              title={isActive ? `Showing ${cat.label} — click to hide` : `Click to show only ${cat.label}`}
              className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border cursor-pointer transition-colors duration-100
                          ${isActive
                            ? 'border-lab-acid text-lab-acid'
                            : 'border-lab-border/40 text-lab-dim opacity-50 hover:border-lab-acid hover:text-lab-acid hover:opacity-100'}`}
            >
              <span aria-hidden="true">{cat.icon}</span> {cat.label}
            </button>
          );
        })}
        {focus.size > 0 && (
          <button
            onClick={clearFocus}
            title="Clear filters (show all)"
            className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm border border-lab-acid/60
                       text-lab-acid hover:bg-lab-acid/15 cursor-pointer transition-colors duration-100"
          >
            ✕ clear
          </button>
        )}
      </div>

      {/* Feed list */}
      <div className="relative flex-1 min-h-0">
        <div
          ref={listRef}
          onScroll={handleScroll}
          className="absolute inset-0 overflow-y-auto"
        >
          {displayEvents.length === 0 ? (
            <div className="flex items-center justify-center h-16 font-mono text-xs text-lab-dim text-center px-4">
              {events.length === 0
                ? 'WAITING FOR EVENTS…'
                : 'No events in the selected filters yet — click ✕ clear to show all'}
            </div>
          ) : (
            displayEvents.map((event) => (
              <FeedEntry
                key={event.seq}
                event={event}
                isNew={newEventIdsRef.current.has(event.seq)}
                llmDecided={isLlmDecidedAction(event, llmAnimalTurns)}
                animalModel={
                  event.kind === 'animal_action' && event.turn_id
                    ? animalModels.get(event.turn_id)
                    : undefined
                }
                onGrantReply={onGrantReply}
              />
            ))
          )}
        </div>

        {/* Jump-to-newest pill — only while scrolled away from the top */}
        {scrolledAway && (
          <button
            onClick={jumpToNewest}
            title="Jump back to the newest events (re-pins the feed)"
            className="absolute top-2 left-1/2 -translate-x-1/2 z-10 cursor-pointer
                       font-mono text-[10px] px-2 py-1 rounded-full
                       bg-lab-chrome border border-lab-acid text-lab-acid
                       shadow-lg hover:bg-lab-acid/20 transition-colors duration-150"
          >
            ↑ {unseen > 0 ? `${unseen} new` : 'newest'}
          </button>
        )}
      </div>
    </div>
  );
}
