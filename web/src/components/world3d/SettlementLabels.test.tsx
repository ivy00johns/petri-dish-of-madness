/**
 * SettlementLabels tests (EM-269 F2) — the settlement-marker render law:
 *   • world-frame direct: the marker sits AT the backend-supplied center
 *     (±33 world units) — no logical→world conversion in the frontend
 *   • tolerant: absent/null/empty map renders nothing; a malformed entry
 *     (junk center, empty name) is skipped — never a hole, never a crash
 *   • existing chrome: one floating label per settlement, name text only
 *
 * drei's <Text> is troika (WebGL) and <Billboard> needs the R3F loop — both
 * mocked to plain DOM (the StreetLabels test discipline).
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/react';
import type { MouseEventHandler, PointerEventHandler, ReactNode } from 'react';

vi.mock('@react-three/drei', () => ({
  // EM-121: the labels are clickable — the mock forwards the pointer handlers
  // so the zoom-to-city pick path is testable, and stubs the hover cursor.
  useCursor: () => undefined,
  Billboard: ({
    children,
    position,
    onClick,
    onPointerOver,
    onPointerOut,
  }: {
    children?: ReactNode;
    position?: number[];
    onClick?: MouseEventHandler<HTMLDivElement>;
    onPointerOver?: PointerEventHandler<HTMLDivElement>;
    onPointerOut?: PointerEventHandler<HTMLDivElement>;
  }) => (
    <div
      data-testid="settlement-marker"
      data-position={JSON.stringify(position)}
      onClick={onClick}
      onPointerOver={onPointerOver}
      onPointerOut={onPointerOut}
    >
      {children}
    </div>
  ),
  Text: ({ children }: { children?: ReactNode }) => (
    <span data-testid="settlement-name">{children}</span>
  ),
}));

import {
  SettlementLabels,
  SETTLEMENT_LABEL_Y,
  settlementLabelEntries,
} from './SettlementLabels';
import type { Settlement } from '../../types';

afterEach(cleanup);

const ridge: Settlement = {
  name: 'River Camp',
  center: [26.4, 26.4],
  founded_tick: 3,
  founder_id: 'a',
  members: ['a'],
};

describe('EM-269 — settlement markers render from world-frame centers', () => {
  it('renders one named marker per settlement, at [x, HOVER_Y, z] direct', () => {
    render(
      <SettlementLabels
        settlements={{ stl_1: ridge, stl_2: { name: 'Larkspur', center: [0, -3.5] } }}
      />,
    );
    const names = screen.getAllByTestId('settlement-name').map((n) => n.textContent);
    expect(names.sort()).toEqual(['Larkspur', 'River Camp']);
    const positions = screen
      .getAllByTestId('settlement-marker')
      .map((m) => JSON.parse(m.getAttribute('data-position') ?? '[]'));
    // world-frame DIRECT — the exact backend center, no conversion, hovered
    expect(positions).toContainEqual([26.4, SETTLEMENT_LABEL_Y, 26.4]);
    expect(positions).toContainEqual([0, SETTLEMENT_LABEL_Y, -3.5]);
  });

  it('markers float above the structure/place label band', () => {
    expect(SETTLEMENT_LABEL_Y).toBeGreaterThan(5);
  });
});

describe('EM-269 — fallback discipline (older backends, partial snapshots)', () => {
  it('absent or empty settlements render nothing', () => {
    const { container: c1 } = render(<SettlementLabels />);
    expect(c1.querySelector('[data-testid="settlement-marker"]')).toBeNull();
    const { container: c2 } = render(<SettlementLabels settlements={null} />);
    expect(c2.querySelector('[data-testid="settlement-marker"]')).toBeNull();
    const { container: c3 } = render(<SettlementLabels settlements={{}} />);
    expect(c3.querySelector('[data-testid="settlement-marker"]')).toBeNull();
  });

  it('malformed entries are skipped, valid siblings still render', () => {
    const junk = {
      stl_ok: ridge,
      stl_noname: { name: '', center: [1, 2] },
      stl_nocenter: { name: 'Ghost' },
      stl_badcenter: { name: 'Ghost 2', center: [Number.NaN, 1] },
      stl_shortcenter: { name: 'Ghost 3', center: [1] },
    } as unknown as Record<string, Settlement>;
    expect(settlementLabelEntries(junk).map(([id]) => id)).toEqual(['stl_ok']);
    render(<SettlementLabels settlements={junk} />);
    expect(screen.getAllByTestId('settlement-name')).toHaveLength(1);
    expect(screen.getByTestId('settlement-name').textContent).toBe('River Camp');
  });
});

describe('EM-121 — clicking a settlement marker is zoom-to-city', () => {
  it('clicking a marker picks ITS settlement id', () => {
    const onPick = vi.fn();
    render(
      <SettlementLabels
        settlements={{ stl_1: ridge, stl_2: { name: 'Larkspur', center: [0, -3.5] } }}
        onPick={onPick}
      />,
    );
    const larkspur = screen
      .getAllByTestId('settlement-marker')
      .find((m) => m.textContent === 'Larkspur')!;
    fireEvent.click(larkspur);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith('stl_2');
  });

  it('without onPick the markers stay inert (no handler, no crash)', () => {
    render(<SettlementLabels settlements={{ stl_1: ridge }} />);
    fireEvent.click(screen.getByTestId('settlement-marker')); // must not throw
    expect(screen.getByTestId('settlement-name').textContent).toBe('River Camp');
  });
});
