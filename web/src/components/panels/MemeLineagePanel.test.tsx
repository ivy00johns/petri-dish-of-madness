/**
 * Wave O (EM-251–255) — MemeLineagePanel. A CULTURE-FREE WORLD renders NOTHING
 * (no memes, no camps ⇒ null, so the golden pre-culture UI is unchanged). With
 * culture it builds the meme family tree (roots + drifted descendants in
 * generation order), resolves image-meme thumbnails from the gallery, marks the
 * dominant memes, chips the belief camps, and banners the canonized town motif.
 * The tree builder is pinned directly as a pure function so the parent_id /
 * generation contract can't drift.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemeLineagePanel, dedupeByText, memeLineageRows, sortedCamps } from './MemeLineagePanel';
import { world } from '../../test-utils/fixtures';
import type { Meme, GalleryImage } from '../../types';

beforeEach(() => {
  localStorage.clear(); // the panel persists its collapse preference
  // The panel defaults COLLAPSED via the one-time migration marker; seed a
  // POST-migration user who explicitly expanded so the render tests below
  // reach the lineage rows.
  localStorage.setItem('em.panelDefaults.v2', '1');
  localStorage.setItem('em.culture.collapsed.v2', '0');
});

/** A Meme with contract defaults; override only what a test asserts about. */
function meme(partial: Partial<Meme> & { id: string }): Meme {
  return {
    kind: 'idea',
    text: partial.id,
    origin_agent_id: 'a1',
    origin_tick: 0,
    generation: 0,
    carriers: [],
    last_spread_tick: 0,
    virality: 0,
    ...partial,
  };
}

function galleryImage(partial: Partial<GalleryImage> & { image_id: string }): GalleryImage {
  return {
    prompt: 'a fox',
    proposer_id: 'a1',
    created_tick: 0,
    url: `/assets/images/${partial.image_id}.png`,
    promoted: false,
    ...partial,
  };
}

describe('MemeLineagePanel — culture-free is invisible', () => {
  it('renders nothing when there are no memes and no camps', () => {
    const { container } = render(<MemeLineagePanel world={world()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a null world', () => {
    const { container } = render(<MemeLineagePanel world={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a pre-Wave-O world (every culture key absent)', () => {
    // Pre-culture snapshot: agents/places present, no culture keys at all.
    const { container } = render(
      <MemeLineagePanel world={world({ agents: [], places: [] })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('memeLineageRows — the tree builder (contract pins)', () => {
  it('places a root then its descendants depth-first in generation order', () => {
    const rows = memeLineageRows({
      m0: meme({ id: 'm0', generation: 0 }),
      m1: meme({ id: 'm1', generation: 1, parent_id: 'm0' }),
      m2: meme({ id: 'm2', generation: 2, parent_id: 'm1' }),
    });
    expect(rows.map((r) => [r.meme.id, r.depth])).toEqual([
      ['m0', 0],
      ['m1', 1],
      ['m2', 2],
    ]);
  });

  it('orders sibling children by generation', () => {
    const rows = memeLineageRows({
      root: meme({ id: 'root', generation: 0 }),
      late: meme({ id: 'late', generation: 3, parent_id: 'root' }),
      early: meme({ id: 'early', generation: 1, parent_id: 'root' }),
    });
    expect(rows.map((r) => r.meme.id)).toEqual(['root', 'early', 'late']);
  });

  it('orders roots most-viral first', () => {
    const rows = memeLineageRows({
      quiet: meme({ id: 'quiet', virality: 2 }),
      loud: meme({ id: 'loud', virality: 40 }),
    });
    expect(rows.map((r) => r.meme.id)).toEqual(['loud', 'quiet']);
  });

  it('promotes an orphan (parent id not in the map) to a root rather than dropping it', () => {
    const rows = memeLineageRows({
      orphan: meme({ id: 'orphan', generation: 2, parent_id: 'gone' }),
    });
    expect(rows.map((r) => [r.meme.id, r.depth])).toEqual([['orphan', 0]]);
  });

  it('is empty for an absent / empty meme map', () => {
    expect(memeLineageRows(undefined)).toEqual([]);
    expect(memeLineageRows({})).toEqual([]);
  });

  it('does not loop on a self-referential meme', () => {
    const rows = memeLineageRows({ loop: meme({ id: 'loop', parent_id: 'loop' }) });
    expect(rows.map((r) => r.meme.id)).toEqual(['loop']);
  });
});

describe('sortedCamps — belief circles, most-populous first', () => {
  it('orders camps by member count then founding tick', () => {
    const camps = sortedCamps({
      cmp_a: { name: 'Small', founded_tick: 1, members: ['x'] },
      cmp_b: { name: 'Big', founded_tick: 2, members: ['x', 'y', 'z'] },
    });
    expect(camps.map((c) => c.name)).toEqual(['Big', 'Small']);
  });
});

describe('dedupeByText — the clone-row fold (2026-10-03 live feedback)', () => {
  it('folds identical-text memes onto the first occurrence with a variant count', () => {
    // The live shape: a root, its verbatim clone, and the clone's own clones.
    const rows = memeLineageRows({
      m0: meme({ id: 'm0', text: 'a fox in a crown', generation: 0, virality: 9 }),
      m1: meme({ id: 'm1', text: 'a fox in a crown', generation: 3, parent_id: 'm0' }),
      m2: meme({ id: 'm2', text: 'a fox in a crown', generation: 4, parent_id: 'm1' }),
      m3: meme({ id: 'm3', text: 'a fox in a paper crown', generation: 1, parent_id: 'm0' }),
    });
    const display = dedupeByText(rows);
    // 4 memes ⇒ 2 display rows; the head of the family is the first in tree
    // order (the root), the rest folded into its variant count.
    expect(display.map((d) => d.meme.id)).toEqual(['m0', 'm3']);
    expect(display[0].variants).toBe(3);
    expect(display[1].variants).toBe(1);
  });

  it('keeps distinct texts, empty-text memes (keyed by id), and ordering', () => {
    const rows = memeLineageRows({
      a: meme({ id: 'a', text: 'one idea' }),
      b: meme({ id: 'b', text: '' }),
      c: meme({ id: 'c', text: 'other idea' }),
    });
    const display = dedupeByText(rows);
    expect(display.map((d) => [d.meme.id, d.variants])).toEqual([
      ['a', 1],
      ['b', 1],
      ['c', 1],
    ]);
  });

  it('is empty for an empty row list', () => {
    expect(dedupeByText([])).toEqual([]);
  });
});

describe('MemeLineagePanel — culture renders', () => {
  const cultured = world({
    memes: {
      m0: meme({ id: 'm0', text: 'a fox in a crown', kind: 'image', image_id: 'img_fox', generation: 0, virality: 50, carriers: ['a1', 'a2'] }),
      m1: meme({ id: 'm1', text: 'a fox in a paper crown', kind: 'image', image_id: 'img_paper', generation: 1, parent_id: 'm0', virality: 20, carriers: ['a3'] }),
      m9: meme({ id: 'm9', text: 'bread is sacred', kind: 'idea', generation: 0, virality: 5 }),
    },
    dominant_meme_ids: ['m0'],
    town_motif_ref: 'm0',
    gallery: [
      galleryImage({ image_id: 'img_fox' }),
      galleryImage({ image_id: 'img_paper' }),
    ],
    culture_camps: {
      cmp_foxists: { name: 'The Foxists', founded_tick: 3, members: ['a1', 'a2'] },
    },
  });

  it('renders the root meme and its drifted child (the image family tree)', () => {
    render(<MemeLineagePanel world={cultured} />);
    // The root's text appears in both the motif banner and its lineage row.
    expect(screen.getAllByText(/a fox in a crown/).length).toBeGreaterThan(0);
    expect(screen.getByText(/a fox in a paper crown/)).toBeInTheDocument();
    expect(screen.getByText(/bread is sacred/)).toBeInTheDocument();
  });

  it('resolves image-meme thumbnails from the gallery (image_id → url join)', () => {
    render(<MemeLineagePanel world={cultured} />);
    const imgs = screen.getAllByRole('img') as HTMLImageElement[];
    const srcs = imgs.map((i) => i.getAttribute('src'));
    expect(srcs).toContain('/assets/images/img_fox.png');
    expect(srcs).toContain('/assets/images/img_paper.png');
  });

  it('marks a dominant meme with the ⭐ marker', () => {
    render(<MemeLineagePanel world={cultured} />);
    // m0 is the only dominant meme ⇒ exactly one ⭐ dominance marker.
    expect(screen.getAllByLabelText('dominant')).toHaveLength(1);
  });

  it('chips the belief camps in the culture register', () => {
    render(<MemeLineagePanel world={cultured} />);
    expect(screen.getByText('The Foxists')).toBeInTheDocument();
  });

  it('banners the canonized town motif when town_motif_ref is set', () => {
    render(<MemeLineagePanel world={cultured} />);
    expect(screen.getByText(/dominant motif/)).toBeInTheDocument();
  });

  it('shows NO motif banner when town_motif_ref is null but memes exist', () => {
    const noMotif = world({
      memes: { m9: meme({ id: 'm9', text: 'bread is sacred' }) },
      town_motif_ref: null,
    });
    render(<MemeLineagePanel world={noMotif} />);
    expect(screen.queryByText(/dominant motif/)).not.toBeInTheDocument();
    // …but the panel itself still renders (a meme is present).
    expect(screen.getByText(/bread is sacred/)).toBeInTheDocument();
  });

  it('renders with camps but no memes (camps alone open the panel)', () => {
    const campsOnly = world({
      culture_camps: { cmp_x: { name: 'The Quiet Order', founded_tick: 1, members: ['a1'] } },
    });
    render(<MemeLineagePanel world={campsOnly} />);
    expect(screen.getByText('The Quiet Order')).toBeInTheDocument();
  });

  it('folds verbatim-clone rows into one row with a ×N variant badge', () => {
    // The live-feedback wall: three clones of the same drifted text.
    const cloned = world({
      memes: {
        m0: meme({ id: 'm0', text: 'a fox in a crown', generation: 0, virality: 9 }),
        m1: meme({ id: 'm1', text: 'a fox in a crown', generation: 3, parent_id: 'm0' }),
        m2: meme({ id: 'm2', text: 'a fox in a crown', generation: 4, parent_id: 'm1' }),
      },
    });
    render(<MemeLineagePanel world={cloned} />);
    // One row for the text, the fold counted in a ×3 badge.
    expect(screen.getAllByText(/a fox in a crown/).length).toBe(1);
    expect(screen.getByText('×3')).toBeInTheDocument();
  });

  it('defaults COLLAPSED on a fresh browser and expands on toggle', () => {
    localStorage.clear(); // undo the file-level seed: a fresh browser
    render(<MemeLineagePanel world={cultured} />);
    expect(screen.queryByText(/a fox in a crown/)).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Expand the culture panel' }),
    ).toBeInTheDocument();
  });
});
