/**
 * Ambiance.tsx — EM-127 (partial): golden-hour dust motes (set dressing).
 *
 * Renders the deterministic mote field from motes.ts as ONE THREE.Points (a
 * single draw call) with a soft warm round sprite, additive blending and low
 * opacity, drifting via a clock-driven useFrame. NON-INTERACTIVE, depthWrite
 * off (never occludes geometry), and reduced-motion-safe (static under
 * prefers-reduced-motion). The sprite texture is generated at runtime (a radial
 * gradient on a canvas) so no asset is vendored.
 *
 * Tuned to complement the existing golden-hour lighting — subtle, warm, sparse.
 * The mood-reshaping EM-127 beats (day/night, Bloom/Vignette, tone-mapping) are
 * deferred for visual sign-off.
 */

import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { AMBIANCE_ENABLED, computeMotes, motePosition } from './motes';

const PREFERS_REDUCED_MOTION =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Soft round warm sprite (radial gradient → transparent), built once. */
function makeSpriteTexture(): THREE.Texture | null {
  if (typeof document === 'undefined') return null;
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,244,214,1)');
  g.addColorStop(0.4, 'rgba(255,226,170,0.5)');
  g.addColorStop(1, 'rgba(255,226,170,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

export function Ambiance({ seed }: { seed: number }) {
  const motes = useMemo(() => computeMotes(seed), [seed]);
  const ref = useRef<THREE.Points>(null);

  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const arr = new Float32Array(motes.length * 3);
    motes.forEach((m, i) => {
      const p = motePosition(m, 0);
      arr[i * 3] = p.x;
      arr[i * 3 + 1] = p.y;
      arr[i * 3 + 2] = p.z;
    });
    g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
    return g;
  }, [motes]);

  const material = useMemo(() => {
    const map = makeSpriteTexture();
    return new THREE.PointsMaterial({
      size: 0.5,
      map: map ?? undefined,
      color: new THREE.Color('#ffe2aa'),
      transparent: true,
      opacity: 0.38,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });
  }, []);

  useFrame((state) => {
    if (!ref.current || PREFERS_REDUCED_MOTION) return;
    const attr = ref.current.geometry.getAttribute('position') as THREE.BufferAttribute;
    const t = state.clock.elapsedTime;
    for (let i = 0; i < motes.length; i++) {
      const p = motePosition(motes[i], t);
      attr.setXYZ(i, p.x, p.y, p.z);
    }
    attr.needsUpdate = true;
  });

  if (!AMBIANCE_ENABLED || motes.length === 0) return null;
  return <points ref={ref} geometry={geometry} material={material} frustumCulled={false} />;
}
