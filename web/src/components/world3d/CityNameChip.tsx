/**
 * CityNameChip (EM-188) — the city's title, rendered ONCE as a HUD chip
 * overlaid on the 3-D world view (CozyWorld's wrapper, top-left corner —
 * clear of the bottom roster strip and the view-toggle bar above the canvas).
 *
 * Documented design call (contract B7 item 3 offered in-world signage OR a
 * HUD chip): the chip wins because `town_name` is runtime-mutable (agents
 * vote to rename the town, `town_named` event) and a DOM chip re-renders for
 * free, stays legible at every camera distance, and uses the design-token
 * classes — no new hex anywhere (design-token-guard friendly).
 *
 * ABSENT-SAFE: mock mode / older snapshots may lack `town_name` (it is not
 * even part of the frontend WorldState type yet) — empty/missing ⇒ renders
 * nothing.
 */

export function CityNameChip({ name }: { name?: string | null }) {
  const label = (name ?? '').trim();
  if (!label) return null;
  return (
    <div
      data-testid="city-name-chip"
      className="pointer-events-none absolute left-3 top-3 z-10 border border-lab-border bg-lab-surface/80 px-2.5 py-1 font-mono text-[11px] font-semibold uppercase tracking-widest text-lab-text backdrop-blur-sm"
    >
      🏛 {label}
    </div>
  );
}
