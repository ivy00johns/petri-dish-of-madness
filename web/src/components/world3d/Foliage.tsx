/**
 * Foliage — the EM-118 instanced town-edge treeline. ~60 procedural trees in
 * three variants (round oak / tall conifer / dusk blossom), batched PER PART
 * so the whole forest is ~11 draw calls:
 *
 *   NEAR (within TREE_LOD_RADIUS of the village core — full detail):
 *     trunks ×1 · oak canopy+blob ×2 · conifer cone×2 · blossom canopy+puff ×2
 *   FAR (simplified LOD silhouette, no shadow casting):
 *     trunks ×1 · oak ball ×1 · conifer cone ×1 · blossom ball ×1
 *
 * The LOD split is STATIC and deterministic (foliageLayout.splitByLod): the
 * camera orbits the village core, so distance-from-origin is a faithful,
 * zero-per-frame-cost proxy for distance-from-camera.
 *
 * Placement is deterministic (hashUnit) and keeps ≥ TREE_PLACE_CLEAR (10.5)
 * from every place center — outside all building slot rings. Materials all
 * come from the cached warm-toon factory (EM-111).
 */

import { useMemo } from 'react';
import type { Place } from '../../types';
import { toonMaterial } from './toon';
import { layoutTrees, splitByLod, type TreeItem } from './foliageLayout';
import { InstancedScatter } from './InstancedScatter';

// Golden-hour foliage tints (warm greens; blossoms catch the dusk pink).
const TRUNK = '#7a5230';
const OAK_MAIN = '#5fa05f';
const OAK_BLOB = '#6fb56f';
const CONIFER_LOW = '#4e8a52';
const CONIFER_TOP = '#5c9a58';
const BLOSSOM = '#e8a7b8';
const BLOSSOM_PUFF = '#f3c6d0';

function byVariant(trees: TreeItem[], variant: TreeItem['variant']): TreeItem[] {
  return trees.filter((t) => t.variant === variant);
}

export function Foliage({ places }: { places: Place[] }) {
  const trees = useMemo(() => layoutTrees(places), [places]);
  const { near, far } = useMemo(() => splitByLod(trees), [trees]);

  const nearOak = useMemo(() => byVariant(near, 'oak'), [near]);
  const nearConifer = useMemo(() => byVariant(near, 'conifer'), [near]);
  const nearBlossom = useMemo(() => byVariant(near, 'blossom'), [near]);
  const farOak = useMemo(() => byVariant(far, 'oak'), [far]);
  const farConifer = useMemo(() => byVariant(far, 'conifer'), [far]);
  const farBlossom = useMemo(() => byVariant(far, 'blossom'), [far]);

  return (
    <group>
      {/* ── NEAR: full detail ─────────────────────────────────────────── */}
      <InstancedScatter items={near} material={toonMaterial(TRUNK)} offset={[0, 0.7, 0]}>
        <cylinderGeometry args={[0.18, 0.26, 1.4, 7]} />
      </InstancedScatter>

      {/* oak: big round canopy + offset blob for asymmetry */}
      <InstancedScatter items={nearOak} material={toonMaterial(OAK_MAIN)} offset={[0, 2.0, 0]}>
        <sphereGeometry args={[1.0, 12, 10]} />
      </InstancedScatter>
      <InstancedScatter
        items={nearOak}
        material={toonMaterial(OAK_BLOB)}
        offset={[0.42, 2.52, 0.2]}
      >
        <sphereGeometry args={[0.6, 10, 8]} />
      </InstancedScatter>

      {/* conifer: two stacked cones */}
      <InstancedScatter
        items={nearConifer}
        material={toonMaterial(CONIFER_LOW)}
        offset={[0, 1.75, 0]}
      >
        <coneGeometry args={[1.05, 1.7, 9]} />
      </InstancedScatter>
      <InstancedScatter
        items={nearConifer}
        material={toonMaterial(CONIFER_TOP)}
        offset={[0, 2.8, 0]}
      >
        <coneGeometry args={[0.7, 1.3, 9]} />
      </InstancedScatter>

      {/* blossom: dusk-pink canopy with a lighter puff (faint warm glow,
          same emissive convention as the scenery flowers) */}
      <InstancedScatter
        items={nearBlossom}
        material={toonMaterial(BLOSSOM, { emissive: '#ff9fb6', emissiveIntensity: 0.12 })}
        offset={[0, 1.85, 0]}
      >
        <sphereGeometry args={[0.85, 12, 10]} />
      </InstancedScatter>
      <InstancedScatter
        items={nearBlossom}
        material={toonMaterial(BLOSSOM_PUFF, { emissive: '#ff9fb6', emissiveIntensity: 0.12 })}
        offset={[0.3, 2.3, 0.25]}
      >
        <sphereGeometry args={[0.45, 9, 8]} />
      </InstancedScatter>

      {/* ── FAR: simplified silhouettes, no shadow casting ────────────── */}
      <InstancedScatter
        items={far}
        material={toonMaterial(TRUNK)}
        offset={[0, 0.7, 0]}
        castShadow={false}
      >
        <cylinderGeometry args={[0.18, 0.26, 1.4, 5]} />
      </InstancedScatter>
      <InstancedScatter
        items={farOak}
        material={toonMaterial(OAK_MAIN)}
        offset={[0, 2.0, 0]}
        castShadow={false}
      >
        <sphereGeometry args={[1.0, 7, 6]} />
      </InstancedScatter>
      <InstancedScatter
        items={farConifer}
        material={toonMaterial(CONIFER_LOW)}
        offset={[0, 2.2, 0]}
        castShadow={false}
      >
        <coneGeometry args={[1.0, 2.5, 6]} />
      </InstancedScatter>
      <InstancedScatter
        items={farBlossom}
        material={toonMaterial(BLOSSOM)}
        offset={[0, 1.85, 0]}
        castShadow={false}
      >
        <sphereGeometry args={[0.85, 7, 6]} />
      </InstancedScatter>
    </group>
  );
}
