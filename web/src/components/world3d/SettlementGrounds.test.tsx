/**
 * SettlementGrounds tests (EM-109) — the per-settlement ground footprint:
 *   • settlementGroundEntries yields one footprint per valid settlement, at the
 *     WORLD-frame center, with a deterministic per-city tint — so TWO
 *     settlements render as TWO distinct clusters (distinct centers + tints);
 *   • tolerance mirrors SettlementLabels (junk skipped, empty ⇒ nothing);
 *   • the component renders a <group> per settlement, and NOTHING for a
 *     single-/no-settlement world (no regression).
 *
 * SettlementGrounds uses no hooks, so we call it directly and inspect the
 * returned element tree (no WebGL/DOM needed — the discipline that keeps the
 * 3D component tests headless).
 */

import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import {
  SettlementGrounds,
  settlementGroundEntries,
  settlementTint,
  CORE_CLICK_MAX_DELTA,
} from './SettlementGrounds';
import type { Settlement } from '../../types';

const two: Record<string, Settlement> = {
  genesis: { name: 'Hearthford', center: [0, 0] },
  stl_2: { name: 'Larkspur', center: [24, -12] },
};

describe('settlementGroundEntries (EM-109)', () => {
  it('yields one footprint per settlement, at the world-frame center', () => {
    const e = settlementGroundEntries(two);
    expect(e).toHaveLength(2);
    const byId = Object.fromEntries(e.map((x) => [x.id, x]));
    expect([byId.genesis.x, byId.genesis.z]).toEqual([0, 0]);
    expect([byId.stl_2.x, byId.stl_2.z]).toEqual([24, -12]);
  });

  it('gives two cities DISTINCT accent tints (they read as distinct clusters)', () => {
    const e = settlementGroundEntries(two);
    expect(e[0].tint).not.toBe(e[1].tint);
    // …and each tint is the deterministic per-id color.
    expect(e[0].tint).toBe(settlementTint(e[0].id));
  });

  it('is tolerant: junk entries skipped, empty/absent ⇒ []', () => {
    const junk = {
      ok: two.genesis,
      noname: { name: '', center: [1, 2] },
      nocenter: { name: 'Ghost' },
      badcenter: { name: 'Ghost 2', center: [Number.NaN, 1] },
    } as unknown as Record<string, Settlement>;
    expect(settlementGroundEntries(junk).map((x) => x.id)).toEqual(['ok']);
    expect(settlementGroundEntries({})).toEqual([]);
    expect(settlementGroundEntries(null)).toEqual([]);
    expect(settlementGroundEntries(undefined)).toEqual([]);
  });
});

describe('SettlementGrounds component (EM-109)', () => {
  it('renders one ground group per settlement (2 settlements ⇒ 2 clusters)', () => {
    const el = SettlementGrounds({ settlements: two }) as ReactElement;
    expect(el).not.toBeNull();
    expect((el as { type: unknown }).type).toBe('group');
    const children = (el.props as { children: ReactElement[] }).children;
    expect(children).toHaveLength(2);
    const names = children.map((c) => (c.props as { name: string }).name).sort();
    expect(names).toEqual(['settlement-ground-genesis', 'settlement-ground-stl_2']);
  });

  it('renders NOTHING for an absent/empty settlements map (no regression)', () => {
    expect(SettlementGrounds({ settlements: undefined })).toBeNull();
    expect(SettlementGrounds({ settlements: null })).toBeNull();
    expect(SettlementGrounds({ settlements: {} })).toBeNull();
  });
});

// ── EM-121: the paved core is the zoom-to-city click surface ─────────────────

type ClickEvent = { delta: number; stopPropagation: () => void };

/** The [wash, core, rim] mesh elements of one settlement's ground group. */
function clusterMeshes(
  el: ReactElement,
  name: string,
): Array<{ onClick?: (e: ClickEvent) => void }> {
  const clusters = (el.props as { children: ReactElement[] }).children;
  const cluster = clusters.find((c) => (c.props as { name: string }).name === name)!;
  return ((cluster.props as { children: ReactElement[] }).children).map(
    (m) => m.props as { onClick?: (e: ClickEvent) => void },
  );
}

describe('EM-121 — clicking the paved core is zoom-to-city', () => {
  it('only the CORE carries a handler — the wide wash + rim stay inert', () => {
    const onPick = vi.fn();
    const el = SettlementGrounds({ settlements: two, onPick }) as ReactElement;
    const [wash, core, rim] = clusterMeshes(el, 'settlement-ground-genesis');
    expect(wash.onClick).toBeUndefined();
    expect(typeof core.onClick).toBe('function');
    expect(rim.onClick).toBeUndefined();
  });

  it('a true click picks THAT settlement id (propagation stopped)', () => {
    const onPick = vi.fn();
    const el = SettlementGrounds({ settlements: two, onPick }) as ReactElement;
    const [, core] = clusterMeshes(el, 'settlement-ground-stl_2');
    const stop = vi.fn();
    core.onClick!({ delta: 0, stopPropagation: stop });
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith('stl_2');
    expect(stop).toHaveBeenCalled();
  });

  it('a DRAG that ends on the core is filtered by pointer travel (never zooms)', () => {
    const onPick = vi.fn();
    const el = SettlementGrounds({ settlements: two, onPick }) as ReactElement;
    const [, core] = clusterMeshes(el, 'settlement-ground-genesis');
    core.onClick!({ delta: CORE_CLICK_MAX_DELTA + 1, stopPropagation: () => {} });
    expect(onPick).not.toHaveBeenCalled();
  });

  it('without onPick the core carries no handler (inert set dressing, as before)', () => {
    const el = SettlementGrounds({ settlements: two }) as ReactElement;
    const [, core] = clusterMeshes(el, 'settlement-ground-genesis');
    expect(core.onClick).toBeUndefined();
  });
});
