/**
 * ContactPanel (EM-334) — the First Contact read surface on the Runs tab.
 *
 * Settlement-vs-settlement, fed entirely by GET /api/contact (zero-LLM,
 * read-only): the two towns' cast families + founding ticks + living
 * members, the FIRST CONTACT marker (who crossed, when — EM-334's latch),
 * the EM-333 honesty ledger (cross-border carriage fidelity per family:
 * 1 − mutated/hops), and the recent crossing/travel events.
 *
 * Labeled zero states everywhere: `{enabled: false}` (a world without an
 * armed contact block) renders nothing but its explainer; an unreachable
 * backend renders the standard unreachable line. Off the replay surface.
 *
 * Styling follows the LaneHealthPanel idiom: token-based lab-* classes,
 * mono chips, acid-green accents.
 */

import { useCallback, useEffect, useState } from 'react';
import { inspectorApi, type ContactSummary } from './api';

function Fidelity({ hops, mutated }: { hops: number; mutated: number }) {
  if (hops <= 0) return <span className="opacity-50">—</span>;
  const fidelity = 1 - mutated / hops;
  const pct = Math.round(fidelity * 100);
  return (
    <span className="font-mono text-[10px]" data-testid="contact-fidelity">
      {pct}% <span className="opacity-60">({mutated}/{hops} hops distorted)</span>
    </span>
  );
}

export default function ContactPanel() {
  const [contact, setContact] = useState<ContactSummary | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setContact(await inspectorApi.contact());
    setLoaded(true);
  }, []);

  useEffect(() => {
    void load();
    const iv = setInterval(() => void load(), 5000);
    return () => clearInterval(iv);
  }, [load]);

  if (!loaded) {
    return (
      <section aria-label="First Contact" data-testid="contact-panel" className="min-w-0">
        <h3 className="text-xs font-semibold uppercase tracking-wide mb-1">First Contact</h3>
        <p className="text-[10px] opacity-60">reading…</p>
      </section>
    );
  }
  if (!contact || !contact.enabled) {
    return (
      <section aria-label="First Contact" data-testid="contact-panel" className="min-w-0">
        <h3 className="text-xs font-semibold uppercase tracking-wide mb-1">First Contact</h3>
        <p className="text-[10px] opacity-60" data-testid="contact-disabled">
          contact not armed on this world — start one via POST /api/arena/contact
          (gemini vs llama; the run self-describes)
        </p>
      </section>
    );
  }

  const ledger = contact.ledger;

  return (
    <section aria-label="First Contact" data-testid="contact-panel" className="min-w-0">
      <header className="flex items-baseline justify-between gap-2 mb-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide">First Contact</h3>
        <span className="font-mono text-[10px] opacity-60">tick {contact.tick}</span>
      </header>

      {contact.contact_made ? (
        <p
          className="text-[11px] mb-2 px-1 py-0.5 rounded"
          data-testid="contact-made"
        >
          🌍 first contact at tick {contact.contact_made.tick} —{' '}
          {contact.contact_made.agent_id} left {contact.contact_made.from_settlement} for{' '}
          {contact.contact_made.to_settlement}
        </p>
      ) : (
        <p className="text-[10px] opacity-60 mb-2" data-testid="contact-not-yet">
          no crossing yet — the towns grow in isolation until someone sets out
        </p>
      )}

      <div className="grid grid-cols-2 gap-2 mb-2" data-testid="contact-town-families">
        {contact.settlements.map((s) => (
          <div key={s.id} className="p-1.5 rounded border border-current/10 min-w-0">
            <div className="flex items-baseline justify-between gap-1">
              <span className="text-[11px] font-semibold truncate">{s.name}</span>
              <span className="font-mono text-[10px] opacity-60">t{s.founded_tick}</span>
            </div>
            <div className="font-mono text-[10px] opacity-80">
              {Object.entries(s.families)
                .map(([fam, n]) => `${fam}×${n}`)
                .join(' · ') || '—'}
            </div>
            <div className="font-mono text-[10px] opacity-60">{s.member_count} citizens</div>
          </div>
        ))}
      </div>

      <div className="mb-2" data-testid="contact-ledger">
        <div className="text-[10px] uppercase tracking-wide opacity-70 mb-0.5">
          honesty ledger — carriage fidelity per family
        </div>
        {ledger ? (
          <div className="flex flex-wrap gap-x-3 gap-y-0.5">
            {Object.entries(ledger.by_family).map(([fam, rec]) => (
              <span key={fam} className="text-[10px]">
                <span className="font-mono">{fam}</span>{' '}
                <Fidelity hops={rec.hops} mutated={rec.mutated} />
              </span>
            ))}
            <span className="font-mono text-[10px] opacity-60">
              {ledger.crossings} crossing{ledger.crossings === 1 ? '' : 's'}
            </span>
          </div>
        ) : (
          <span className="text-[10px] opacity-60">no crossings recorded</span>
        )}
      </div>

      {contact.travels.length > 0 && (
        <div className="mb-2" data-testid="contact-travels">
          <div className="text-[10px] uppercase tracking-wide opacity-70 mb-0.5">travel</div>
          <ul className="text-[10px] leading-snug">
            {contact.travels.slice(0, 5).map((t, i) => (
              <li key={`${t.kind}-${t.tick}-${i}`} className="truncate opacity-80">
                <span className="font-mono opacity-60">t{t.tick}</span> {t.text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {contact.crossings.length > 0 && (
        <div data-testid="contact-crossings">
          <div className="text-[10px] uppercase tracking-wide opacity-70 mb-0.5">
            crossed the border
          </div>
          <ul className="text-[10px] leading-snug">
            {contact.crossings.slice(0, 5).map((c, i) => (
              <li key={`${c.kind}-${c.tick}-${i}`} className="truncate opacity-80">
                <span className="font-mono opacity-60">t{c.tick}</span> {c.text}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
