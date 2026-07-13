/**
 * EventFeed × Storylines Rail (EM-312) — the thread filter. With a storyline
 * selected the feed shows ONLY events touching its principals (actor OR target),
 * a banner names the thread, and CLEAR calls back. Absent (feature off / nothing
 * selected) the feed is unchanged.
 */
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its category focus
});

const events = [
  ev({ kind: 'agent_speech', tick: 1, actor_id: 'a1', text: 'Ada speaks to the plaza' }),
  ev({ kind: 'conflict', tick: 2, actor_id: 'a1', target_id: 'a2', text: 'Ada shoves Vesper II' }),
  ev({ kind: 'agent_speech', tick: 3, actor_id: 'a3', text: 'Mara minds her own business' }),
  ev({ kind: 'agent_speech', tick: 4, actor_id: 'a2', text: 'Vesper II fumes' }),
];

describe('EventFeed — no thread filter', () => {
  it('shows everything when threadFilter is absent', () => {
    render(<EventFeed events={events} />);
    expect(screen.getByText('Mara minds her own business')).toBeInTheDocument();
    expect(screen.getByText('Ada shoves Vesper II')).toBeInTheDocument();
  });
});

describe('EventFeed — with a storyline selected', () => {
  const filter = { id: 'dyad:a1~a2', title: 'Ada v. Vesper II', principals: ['a1', 'a2'] };

  it('keeps only events touching a principal (actor OR target)', () => {
    render(<EventFeed events={events} threadFilter={filter} onClearThread={() => {}} />);
    // a1 / a2 lines survive…
    expect(screen.getByText('Ada speaks to the plaza')).toBeInTheDocument();
    expect(screen.getByText('Ada shoves Vesper II')).toBeInTheDocument();
    expect(screen.getByText('Vesper II fumes')).toBeInTheDocument();
    // …the uninvolved third party is filtered out.
    expect(screen.queryByText('Mara minds her own business')).not.toBeInTheDocument();
  });

  it('names the thread in a banner and clears on demand', () => {
    const onClear = vi.fn();
    render(<EventFeed events={events} threadFilter={filter} onClearThread={onClear} />);
    expect(screen.getByText('Ada v. Vesper II')).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Clear the storyline filter — show the whole feed'));
    expect(onClear).toHaveBeenCalledTimes(1);
  });
});
