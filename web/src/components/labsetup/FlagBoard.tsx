import type { FlagsResponse } from '../../types';

interface Props {
  flags: FlagsResponse;
  pending: Record<string, boolean>;
  onToggle: (flag: string) => void;
}

function Group({ title, subtitle, keys, flags, pending, onToggle }: {
  title: string; subtitle: string; keys: string[];
} & Props) {
  return (
    <section className="border border-lab-border bg-lab-bg">
      <div className="px-3 py-1.5 border-b border-lab-border bg-lab-surface">
        <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-lab-text">
          {title}
        </span>
        <span className="ml-2 font-mono text-[9px] normal-case tracking-normal text-lab-muted">
          {subtitle}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5 p-2">
        {keys.map((flag) => {
          const baked = !!flags.baked[flag];
          const now = pending[flag] ?? baked;
          const changed = now !== baked;
          return (
            <label
              key={flag}
              data-testid={`flag-row-${flag}`}
              data-changed={changed}
              title={changed ? `changed — was ${baked ? 'on' : 'off'} · needs restart` : (baked ? 'baked on' : 'baked off')}
              className={[
                'flex items-center gap-1.5 px-2 py-1 border cursor-pointer select-none font-mono text-[10px] transition-colors',
                now
                  ? 'text-lab-text border-lab-border-bright bg-lab-chrome'
                  : 'text-lab-muted border-lab-border hover:text-lab-text hover:border-lab-border-bright',
                changed ? 'ring-1 ring-lab-acid border-lab-acid-dim' : '',
              ].join(' ')}
            >
              <input
                type="checkbox"
                aria-label={flag}
                checked={now}
                onChange={() => onToggle(flag)}
                className="accent-lab-acid h-3 w-3"
              />
              <span>{flag}</span>
              {changed && <span className="text-lab-acid" aria-hidden>▲</span>}
            </label>
          );
        })}
      </div>
    </section>
  );
}

export function FlagBoard({ flags, pending, onToggle }: Props) {
  return (
    <div className="labsetup-flagboard flex flex-col gap-3">
      <Group
        title="Prompt-weight flags"
        subtitle="move the estimate"
        keys={flags.groups.prompt_weight}
        flags={flags} pending={pending} onToggle={onToggle}
      />
      <Group
        title="Routing / ops flags"
        subtitle="no prompt-size change"
        keys={flags.groups.routing_ops}
        flags={flags} pending={pending} onToggle={onToggle}
      />
    </div>
  );
}
