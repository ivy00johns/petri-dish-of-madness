/**
 * InstancedScatter — one instanced mesh per PROP PART (EM-118). Multi-part
 * props (a tree = trunk + canopy; a lamp = base + post + head) render as a few
 * instanced meshes over the SAME item list, each part carrying its own local
 * offset — so a 60-tree forest costs a handful of draw calls, not 180.
 *
 * The whole batch shares ONE cached toon material (toon.ts) via the `material`
 * prop (the EM-111 pattern — instancing requires a single material). Offsets
 * are applied in the item's LOCAL space (after its yaw), scaled with the item,
 * so rotated props keep their parts attached.
 */

import * as THREE from 'three';
import type { ScatterItem } from './foliageLayout';

export function InstancedScatter({
  items,
  material,
  children,
  offset = [0, 0, 0],
  squash = 1,
  castShadow = true,
}: {
  items: ScatterItem[];
  material: THREE.Material;
  /** The part geometry, e.g. <cylinderGeometry args={...} />. */
  children: React.ReactNode;
  /** Local-space offset of this part from the item origin (scaled per item). */
  offset?: [number, number, number];
  /** Vertical scale multiplier (squashed bushes/rocks). */
  squash?: number;
  castShadow?: boolean;
}) {
  if (items.length === 0) return null;

  const setRef = (mesh: THREE.InstancedMesh | null) => {
    if (!mesh) return;
    const dummy = new THREE.Object3D();
    items.forEach((it, i) => {
      dummy.position.set(it.x, 0, it.z);
      dummy.rotation.set(0, it.rot, 0);
      dummy.scale.set(it.scale, it.scale * squash, it.scale);
      // translate along LOCAL axes so offsets follow the item's yaw
      dummy.translateX(offset[0] * it.scale);
      dummy.translateY(offset[1] * it.scale * squash);
      dummy.translateZ(offset[2] * it.scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  };

  return (
    <instancedMesh
      // re-mount (and re-write matrices) if the layout itself changes
      key={`${items.length}:${items[0].x.toFixed(2)}:${items[0].z.toFixed(2)}`}
      ref={setRef}
      args={[undefined, undefined, items.length]}
      material={material}
      castShadow={castShadow}
      receiveShadow
    >
      {children}
    </instancedMesh>
  );
}
