/**
 * Scenery — low-poly park grass scattered via instancing (Wave D1.5).
 *
 * The wilderness is dead: the sim lives on the dense city grid, so the old
 * world-wide grass/flower scatter is gone. What remains is a seeded light
 * grass-tuft scatter ONLY inside the park landmark blocks (foliageLayout
 * .layoutParkGrass — pure + deterministic). Park trees render next door in
 * Foliage.tsx from the same layout module.
 *
 * EM-111 (materials only): everything renders with the shared cached
 * warm-toon materials (toon.ts). The instanced batch shares ONE material —
 * passed via the `material` prop so instancing keeps working unchanged.
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import type { Place } from '../../types';
import { layoutParkGrass, type ScatterItem } from './foliageLayout';
import { toonMaterial } from './toon';

interface SceneryProps {
  places: Place[];
}

// EM-118: grass warmed a touch toward the golden-hour terrain greens.
const GRASS_GREEN = '#7bab54';

/** Instanced mesh that places `items` with per-instance transform. The whole
 *  batch shares ONE cached toon material (EM-111) via the `material` prop. */
function Instances({
  items,
  children,
  material,
  yOffset = 0,
}: {
  items: ScatterItem[];
  children: React.ReactNode;
  material: THREE.Material;
  yOffset?: number;
}) {
  const ref = useMemo(() => ({ current: null as THREE.InstancedMesh | null }), []);

  const setRef = (mesh: THREE.InstancedMesh | null) => {
    ref.current = mesh;
    if (!mesh) return;
    const dummy = new THREE.Object3D();
    items.forEach((it, i) => {
      dummy.position.set(it.x, yOffset * it.scale, it.z);
      dummy.rotation.set(0, it.rot, 0);
      dummy.scale.setScalar(it.scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  };

  return (
    <instancedMesh
      ref={setRef}
      args={[undefined, undefined, items.length]}
      material={material}
      castShadow
      receiveShadow
    >
      {children}
    </instancedMesh>
  );
}

export function Scenery({ places }: SceneryProps) {
  const grass = useMemo(() => layoutParkGrass(places), [places]);

  return (
    <group>
      {/* park grass tufts — small green cones, only inside park blocks */}
      <Instances items={grass} yOffset={0.18} material={toonMaterial(GRASS_GREEN)}>
        <coneGeometry args={[0.14, 0.45, 5]} />
      </Instances>
    </group>
  );
}
