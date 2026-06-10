/**
 * Model.tsx — thin React wrappers around the EM-148 GLB asset layer.
 *
 * USAGE PATTERN (load-bearing, Wave C contract rule 7): every <Model> must be
 * mounted inside a <Suspense> whose fallback is the existing procedural mesh,
 * so the scene never shows a hole while a GLB streams (or if it 404s):
 *
 *   <Suspense fallback={<ProceduralHouse ... />}>
 *     <Model spec={MODEL_REGISTRY.house!} tint={style.body} health={b.health}
 *            position={[x, 0, z]} />
 *   </Suspense>
 *
 * What <Model> does:
 *   • drei useGLTF loads + caches the GLB once per url;
 *   • the cached scene is toon-converted ONCE (toonifyScene — materials become
 *     MeshToonMaterial on the shared ramp, maps/colors preserved, shadows on);
 *   • drei <Clone> renders an instance-graph that SHARES those toon materials;
 *   • optional `tint`/`health` clone the materials on THIS instance only and
 *     apply the color override (EM-122 healthTint soot semantics).
 *
 * <InstancedModel> renders many placements of one GLB through drei <Merged>
 * (one InstancedMesh per source mesh — the 60fps rule for repeated models).
 * Instanced placements share materials, so no per-instance tint there.
 *
 * Rigged characters (C5): use the `useToonGLTF` hook directly to get the
 * converted scene + animation clips, then drive drei useAnimations over your
 * own <Clone> ref. Clip names come from spec.clips.
 *
 * preloadHeroModels() warms the useGLTF cache for every non-null registry
 * entry; CozyWorld (wave 2) calls it once at module scope.
 */

import React, { useLayoutEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { Clone, Merged, useGLTF } from '@react-three/drei';
import type { GroupProps } from '@react-three/fiber';
import { healthTint } from '../worldSpace';
import { allModelSpecs, type ModelSpec } from './models';
import { applyTintToScene, toonifyScene } from './toonify';

/**
 * Pure: resolve the effective instance tint from the `tint`/`health` props.
 * Returns null when no override is needed (skip the material-clone pass).
 * `health` darkens toward soot via worldSpace.healthTint, composing with the
 * base tint (white base when only health is given).
 */
export function effectiveTint(
  tint: string | undefined,
  health: number | undefined,
): string | null {
  const base = tint ?? '#ffffff';
  const result =
    health === undefined || health === null ? base : healthTint(base, health);
  return result.toLowerCase() === '#ffffff' ? null : result;
}

/**
 * Load a GLB and toon-convert its cached scene exactly once. Returns the
 * SHARED scene (clone before mutating!) and its animation clips.
 * Suspends while loading — keep a procedural fallback in the Suspense above.
 */
export function useToonGLTF(url: string): {
  scene: THREE.Object3D;
  animations: THREE.AnimationClip[];
} {
  const gltf = useGLTF(url);
  // Convert synchronously during render: cached per scene, so this runs once
  // per GLB per app lifetime no matter how many components consume it.
  toonifyScene(gltf.scene);
  return { scene: gltf.scene, animations: gltf.animations };
}

export interface ModelProps extends GroupProps {
  spec: ModelSpec;
  /** Per-instance color multiplier (identity tints). White = untouched. */
  tint?: string;
  /** 0..100 building health — lerps the tint toward soot (EM-122 semantics). */
  health?: number;
}

/**
 * One toon-converted GLB instance. spec.scale/yOffset/rotation are applied on
 * an inner group, so the outer GroupProps (position etc.) stay in world units.
 */
export function Model({ spec, tint, health, ...groupProps }: ModelProps) {
  const { scene } = useToonGLTF(spec.url);
  const inner = useRef<THREE.Group>(null);
  const wanted = effectiveTint(tint, health);
  useLayoutEffect(() => {
    if (inner.current && wanted) applyTintToScene(inner.current, wanted);
  }, [wanted, scene]);
  return (
    <group {...groupProps}>
      <group
        ref={inner}
        scale={spec.scale}
        position-y={spec.yOffset}
        rotation-y={spec.rotation ?? 0}
      >
        <Clone object={scene} castShadow receiveShadow />
      </group>
    </group>
  );
}

export interface InstancePlacement {
  position: [number, number, number];
  /** Y rotation (radians), composed with spec.rotation. */
  rotationY?: number;
  /** Extra uniform scale multiplier over spec.scale. */
  scale?: number;
}

export interface InstancedModelProps {
  spec: ModelSpec;
  instances: InstancePlacement[];
}

interface MeshPart {
  mesh: THREE.Mesh;
  position: THREE.Vector3;
  quaternion: THREE.Quaternion;
  scale: THREE.Vector3;
}

/** Flatten a (small, static) GLB scene into meshes + root-relative transforms. */
function collectMeshParts(scene: THREE.Object3D): MeshPart[] {
  scene.updateMatrixWorld(true);
  const rootInverse = scene.matrixWorld.clone().invert();
  const parts: MeshPart[] = [];
  scene.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (!mesh.isMesh) return;
    const local = rootInverse.clone().multiply(mesh.matrixWorld);
    const position = new THREE.Vector3();
    const quaternion = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    local.decompose(position, quaternion, scale);
    parts.push({ mesh, position, quaternion, scale });
  });
  return parts;
}

/**
 * Many placements of one GLB, one InstancedMesh per source mesh via drei
 * <Merged> (contract rule 6: instance every repeated model). Each placement
 * is a nested group, so multi-mesh kits keep their internal offsets.
 */
export function InstancedModel({ spec, instances }: InstancedModelProps) {
  const { scene } = useToonGLTF(spec.url);
  const parts = useMemo(() => collectMeshParts(scene), [scene]);
  const meshes = useMemo(() => parts.map((p) => p.mesh), [parts]);
  return (
    // limit doubles ahead of the live count so growing towns don't churn the
    // instance buffers every added building.
    <Merged
      meshes={meshes}
      limit={Math.max(64, instances.length * 2)}
      castShadow
      receiveShadow
    >
      {(...Parts: React.ElementType[]) => (
        <>
          {instances.map((inst, i) => (
            <group
              key={i}
              position={inst.position}
              rotation-y={(spec.rotation ?? 0) + (inst.rotationY ?? 0)}
              scale={spec.scale * (inst.scale ?? 1)}
            >
              <group position-y={spec.yOffset / spec.scale}>
                {Parts.map((Part, j) => (
                  <Part
                    key={j}
                    position={parts[j].position}
                    quaternion={parts[j].quaternion}
                    scale={parts[j].scale}
                  />
                ))}
              </group>
            </group>
          ))}
        </>
      )}
    </Merged>
  );
}

/**
 * Warm the useGLTF cache for every non-null registry entry (place anchors,
 * buildings, villager, cat/dog). Call ONCE at module scope from the scene
 * root (wave 2 wires the call site).
 */
export function preloadHeroModels(): void {
  for (const spec of allModelSpecs()) useGLTF.preload(spec.url);
}
