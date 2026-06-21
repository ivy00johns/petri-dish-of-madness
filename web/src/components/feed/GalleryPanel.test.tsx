/**
 * GalleryPanel (Atelier follow-up — Wave I / EM-210) — the artwork viewer.
 *
 * Source of truth is the disk-aware `GET /api/gallery` (only records with a real
 * PNG), so phantom records (a create_image whose best-effort PNG fetch 402'd or
 * was load-skipped) never reach the grid — no 404 spam, no gray tiles. When the
 * endpoint is unavailable the panel degrades to world.gallery / image_posted
 * history with a per-thumb placeholder. The plaza piece wears a ★ PLAZA badge;
 * clicking a thumbnail opens a lightbox with the prompt + attribution.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { GalleryPanel, galleryImages } from './GalleryPanel';
import { agent, ev, resetSeq, world } from '../../test-utils/fixtures';
import type { GalleryImage } from '../../types';

function gimg(partial: Partial<GalleryImage> & { image_id: string }): GalleryImage {
  return {
    prompt: 'a study',
    proposer_id: 'a1',
    created_tick: 0,
    url: `/assets/images/${partial.image_id}.png`,
    promoted: false,
    ...partial,
  };
}

/** Stub `GET /api/gallery` to return the given materialized payload. */
function mockGallery(payload: {
  images: GalleryImage[];
  plaza_banner_ref?: string;
  total?: number;
  materialized?: number;
}) {
  const body = {
    plaza_banner_ref: '',
    total: payload.images.length,
    materialized: payload.images.length,
    ...payload,
  };
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) }));
}

/** Stub the endpoint as unavailable (a backend predating it / offline). */
function mockGalleryDown() {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
}

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the panel persists its collapse preference
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('galleryImages (pure)', () => {
  it('serves world.gallery newest-first by created_tick', () => {
    const w = world({
      gallery: [
        gimg({ image_id: 'old', created_tick: 1 }),
        gimg({ image_id: 'mid', created_tick: 5 }),
        gimg({ image_id: 'new', created_tick: 9 }),
      ],
    });
    expect(galleryImages(w, []).map((g) => g.image_id)).toEqual(['new', 'mid', 'old']);
  });

  it('falls back to deriving from image_posted, marking promoted ids', () => {
    const history = [
      ev({
        kind: 'image_promoted',
        tick: 10,
        actor_type: 'system',
        payload: { image_id: 'img_a', url: '/assets/images/img_a.png', proposal_id: 'p1' },
      }),
      ev({
        kind: 'image_posted',
        tick: 9,
        actor_id: 'a1',
        payload: { image_id: 'img_b', prompt: 'a harbor', url: '/assets/images/img_b.png' },
      }),
      ev({
        kind: 'image_posted',
        tick: 3,
        actor_id: 'a2',
        payload: { image_id: 'img_a', prompt: 'a forest', url: '/assets/images/img_a.png' },
      }),
      // Not atelier traffic — ignored.
      ev({ kind: 'agent_speech', tick: 4, actor_id: 'a1', text: 'hi' }),
      // No image_id — dropped defensively.
      ev({ kind: 'image_posted', tick: 5, payload: { url: '/assets/images/ghost.png' } }),
    ];
    const imgs = galleryImages(null, history);
    expect(imgs.map((g) => g.image_id)).toEqual(['img_b', 'img_a']);
    expect(imgs.find((g) => g.image_id === 'img_a')!.promoted).toBe(true);
    expect(imgs.find((g) => g.image_id === 'img_b')!.promoted).toBe(false);
    expect(imgs.find((g) => g.image_id === 'img_b')!.proposer_id).toBe('a1');
    // An empty world.gallery array also falls back (not just a null world).
    expect(galleryImages(world({ gallery: [] }), history)).toHaveLength(2);
  });

  it('dedupes repeated image_posted ids and drops records without a url', () => {
    const history = [
      ev({ kind: 'image_posted', tick: 9, actor_id: 'a1', payload: { image_id: 'dup', url: '/assets/images/dup.png' } }),
      ev({ kind: 'image_posted', tick: 8, actor_id: 'a1', payload: { image_id: 'dup', url: '/assets/images/dup.png' } }),
      ev({ kind: 'image_posted', tick: 7, actor_id: 'a1', payload: { image_id: 'nourl' } }),
    ];
    const imgs = galleryImages(null, history);
    expect(imgs.map((g) => g.image_id)).toEqual(['dup']);
  });
});

describe('GalleryPanel (disk-aware /api/gallery)', () => {
  it('labels the empty gallery (§7) instead of rendering a blank', async () => {
    mockGallery({ images: [] });
    render(<GalleryPanel world={world()} history={[]} />);
    expect(await screen.findByText(/The gallery is empty/)).toBeInTheDocument();
    expect(screen.getByText(/create_image/)).toBeInTheDocument();
  });

  it('renders the endpoint images newest-first with the piece count', async () => {
    mockGallery({
      images: [
        gimg({ image_id: 'first', prompt: 'a quiet harbor', created_tick: 1, proposer_id: 'a1' }),
        gimg({ image_id: 'second', prompt: 'a loud market', created_tick: 8, proposer_id: 'a1' }),
      ],
    });
    const w = world({
      agents: [agent({ id: 'a1', name: 'Ada', profile: 'model-a', profile_color: '#00ff00' })],
    });
    render(<GalleryPanel world={w} history={[]} />);

    const thumbs = await screen.findAllByRole('listitem');
    expect(thumbs).toHaveLength(2);
    // newest (tick 8) first
    expect(within(thumbs[0]).getByRole('img')).toHaveAttribute('alt', 'a loud market');
    expect(within(thumbs[1]).getByRole('img')).toHaveAttribute('alt', 'a quiet harbor');
    expect(screen.getByText('2 pieces')).toBeInTheDocument();
  });

  it('shows only the endpoint records, never the unmaterialized phantoms', async () => {
    // The sim record (world.gallery) lists a phantom; the endpoint omits it.
    mockGallery({
      images: [gimg({ image_id: 'real', prompt: 'real art', created_tick: 5 })],
      total: 2,
      materialized: 1,
    });
    const w = world({
      gallery: [
        gimg({ image_id: 'real', created_tick: 5 }),
        gimg({ image_id: 'phantom', created_tick: 6 }), // no PNG — must not render
      ],
    });
    render(<GalleryPanel world={w} history={[]} />);

    const thumbs = await screen.findAllByRole('listitem');
    expect(thumbs).toHaveLength(1);
    expect(within(thumbs[0]).getByRole('img')).toHaveAttribute('alt', 'real art');
    // The header notes how many records have no rendered image.
    expect(screen.getByText(/\+1 unrendered/)).toBeInTheDocument();
  });

  it('badges the piece currently on the plaza (plaza_banner_ref)', async () => {
    mockGallery({
      images: [
        gimg({ image_id: 'hung', created_tick: 5, promoted: true }),
        gimg({ image_id: 'other', created_tick: 4 }),
      ],
      plaza_banner_ref: 'hung',
    });
    render(<GalleryPanel world={world()} history={[]} />);
    await screen.findAllByRole('listitem');
    const badges = screen.getAllByText('★ plaza');
    expect(badges).toHaveLength(1);
    const hungThumb = screen.getAllByRole('listitem')[0];
    expect(within(hungThumb).getByText('★ plaza')).toBeInTheDocument();
  });

  it('opens a lightbox with the prompt + painter + model chip on click', async () => {
    mockGallery({ images: [gimg({ image_id: 'art', prompt: 'a study in green', created_tick: 7, proposer_id: 'a1' })] });
    const w = world({
      agents: [agent({ id: 'a1', name: 'Ada', profile: 'model-a', profile_color: '#00ff00' })],
    });
    render(<GalleryPanel world={w} history={[]} />);

    const thumb = await screen.findByRole('listitem');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(thumb);

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('"a study in green"')).toBeInTheDocument();
    expect(within(dialog).getByText('Ada')).toBeInTheDocument();
    expect(within(dialog).getByText('model-a')).toBeInTheDocument();
    expect(within(dialog).getByText('T7')).toBeInTheDocument();

    // Esc closes it.
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('degrades a thumbnail whose PNG fails to load to a labeled placeholder', async () => {
    mockGallery({ images: [gimg({ image_id: 'gone', prompt: 'lost work' })] });
    render(<GalleryPanel world={world()} history={[]} />);
    const img = await screen.findByRole('img');
    fireEvent.error(img);
    expect(screen.getByText('art unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('degrades to world.gallery / history when the endpoint is unavailable', async () => {
    mockGalleryDown();
    const history = [
      ev({
        kind: 'image_posted',
        tick: 2,
        actor_id: 'a1',
        payload: { image_id: 'fromlog', prompt: 'from the event log', url: '/assets/images/fromlog.png' },
      }),
    ];
    render(<GalleryPanel world={world()} history={history} />);
    const img = await screen.findByRole('img');
    expect(img).toHaveAttribute('alt', 'from the event log');
  });
});
