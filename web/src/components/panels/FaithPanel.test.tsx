/**
 * Wave O (EM-260–263) — FaithPanel. A religion-free world renders NOTHING (no
 * faiths ⇒ null, so the golden pre-religion UI is unchanged — mirrors WarPanel's
 * peacetime-null test). With faiths it names each faith + its deity, its ✞/☾
 * badge, the aggregate devotion + member count, the ⚔ marker on a hostile faith,
 * a schism/lineage note, and the congregation chips. The pure selectors
 * (faithRows, faithBadge) are pinned directly so the member/devotion/congregation
 * contract can't drift.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FaithPanel, faithRows, faithBadge } from './FaithPanel';
import { world, agent } from '../../test-utils/fixtures';
import type { WorldState } from '../../types';

beforeEach(() => {
  localStorage.clear(); // the panel persists its collapse preference
});

/** A two-faith world: The Ashen Vigil (ada+bram, hostile to the Gilded Dawn) and
 *  the Gilded Dawn (cyn, schismed from the Vigil), plus a congregation. */
function faithfulWorld(): WorldState {
  return world({
    agents: [
      agent({ id: 'ada', faith_id: 'fth_aaa', devotion: 40 }),
      agent({ id: 'bram', faith_id: 'fth_aaa', devotion: 20 }),
      agent({ id: 'cyn', faith_id: 'fth_bbb', devotion: 60 }),
    ],
    faiths: {
      fth_aaa: {
        id: 'fth_aaa',
        name: 'The Ashen Vigil',
        deity: 'Vaal the Ember',
        founder_id: 'ada',
        founded_tick: 3,
        tenets: ['tend the flame'],
        members: ['ada', 'bram'],
        hostile_to: ['fth_bbb'],
      },
      fth_bbb: {
        id: 'fth_bbb',
        name: 'The Gilded Dawn',
        deity: 'Sol Invicta',
        founder_id: 'cyn',
        founded_tick: 9,
        tenets: ['greet the sun'],
        members: ['cyn'],
        parent_id: 'fth_aaa',
      },
    },
    congregations: {
      cng_1: { name: "Ada's Flock", founded_tick: 5, members: ['ada', 'bram'] },
    },
  });
}

describe('FaithPanel — a religion-free world is invisible', () => {
  it('renders nothing when there are no faiths', () => {
    const { container } = render(<FaithPanel world={world()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for an empty faiths map', () => {
    const { container } = render(<FaithPanel world={world({ faiths: {} })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a null world', () => {
    const { container } = render(<FaithPanel world={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('FaithPanel — the faith surface', () => {
  it('names each faith and its deity', () => {
    render(<FaithPanel world={faithfulWorld()} />);
    expect(screen.getByText('The Ashen Vigil')).toBeInTheDocument();
    expect(screen.getByText('The Gilded Dawn')).toBeInTheDocument();
    expect(screen.getByText(/of Vaal the Ember/)).toBeInTheDocument();
  });

  it('marks a faith with declared hostilities with the ⚔ marker', () => {
    render(<FaithPanel world={faithfulWorld()} />);
    const marker = screen.getByTitle('Hostile toward 1 rival faith');
    expect(marker).toHaveTextContent('⚔');
  });

  it('notes a schism lineage (parent_id → the parent faith)', () => {
    render(<FaithPanel world={faithfulWorld()} />);
    expect(screen.getByText(/schism of The Ashen Vigil/)).toBeInTheDocument();
  });

  it('renders the congregation chip in the faith register', () => {
    render(<FaithPanel world={faithfulWorld()} />);
    expect(screen.getByText("Ada's Flock")).toBeInTheDocument();
  });

  it('shows the aggregate devotion (mean over members) and member count', () => {
    render(<FaithPanel world={faithfulWorld()} />);
    // The Ashen Vigil: (40 + 20) / 2 = 30.
    expect(screen.getByText('devotion 30')).toBeInTheDocument();
    expect(screen.getByText('2 members')).toBeInTheDocument();
  });
});

describe('faithRows — the pure selector (contract pins)', () => {
  it('returns [] for a null world and an empty faiths map', () => {
    expect(faithRows(null)).toEqual([]);
    expect(faithRows(world())).toEqual([]);
  });

  it('aggregates members, mean devotion, hostility count, and congregations', () => {
    const rows = faithRows(faithfulWorld());
    // Sorted most-populous first ⇒ the Vigil (2 members) leads.
    expect(rows.map((r) => r.faith.id)).toEqual(['fth_aaa', 'fth_bbb']);
    const vigil = rows[0];
    expect(vigil.members).toBe(2);
    expect(vigil.devotion).toBe(30);
    expect(vigil.hostile).toBe(1);
    expect(vigil.congregations.map((c) => c.name)).toEqual(["Ada's Flock"]);
    // The Dawn has a lone member, no hostility, no congregation.
    expect(rows[1].members).toBe(1);
    expect(rows[1].hostile).toBe(0);
    expect(rows[1].congregations).toEqual([]);
  });

  it('tolerates a faith with no members / no devotion data (devotion 0)', () => {
    const rows = faithRows(
      world({
        faiths: {
          fth_x: {
            id: 'fth_x', name: 'The Hollow', deity: 'None', founder_id: 'ghost',
            founded_tick: 1, tenets: [],
          },
        },
      }),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].members).toBe(0);
    expect(rows[0].devotion).toBe(0);
  });
});

describe('faithBadge — deterministic ✞/☾ pick', () => {
  it('is stable per id and always one of the two glyphs', () => {
    expect(faithBadge('fth_aaa')).toBe(faithBadge('fth_aaa'));
    expect(['✞', '☾']).toContain(faithBadge('fth_aaa'));
    expect(['✞', '☾']).toContain(faithBadge('fth_bbb'));
  });
});
