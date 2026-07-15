import type { FlagsResponse } from '../../types';

interface Props {
  flags: FlagsResponse;
  pending: Record<string, boolean>;
  onToggle: (flag: string) => void;
}

function Group({ title, keys, flags, pending, onToggle }: {
  title: string; keys: string[];
} & Props) {
  return (
    <section className="labsetup-flaggroup">
      <h3>{title}</h3>
      {keys.map((flag) => {
        const baked = !!flags.baked[flag];
        const now = pending[flag] ?? baked;
        const changed = now !== baked;
        return (
          <label key={flag} data-testid={`flag-row-${flag}`} data-changed={changed}
                 className="labsetup-flagrow">
            <input type="checkbox" aria-label={flag} checked={now}
                   onChange={() => onToggle(flag)} />
            <span>{flag}</span>
            {changed && <em className="labsetup-changed"> · needs restart</em>}
          </label>
        );
      })}
    </section>
  );
}

export function FlagBoard({ flags, pending, onToggle }: Props) {
  return (
    <div className="labsetup-flagboard">
      <Group title="Prompt-weight flags (move the estimate)"
             keys={flags.groups.prompt_weight}
             flags={flags} pending={pending} onToggle={onToggle} />
      <Group title="Routing / ops flags (no prompt-size change)"
             keys={flags.groups.routing_ops}
             flags={flags} pending={pending} onToggle={onToggle} />
    </div>
  );
}
