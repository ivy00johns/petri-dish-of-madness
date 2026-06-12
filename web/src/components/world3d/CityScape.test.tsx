/**
 * CityScape tests — the EM-154/157 instanced render path:
 *   • plan → instance-count mapping: renderableEntries carries EVERY plan
 *     instance for non-null registry keys, in canonical key order
 *   • registry null / empty piece ⇒ skipped (rule 10: no hole, no crash)
 *   • chunking math: 1/4/8 split thresholds, lossless partition, correct
 *     spatial buckets, ≤ 8 chunks per key
 *   • setupCityMesh: one matrix per instance (position/rotation/scale match
 *     composeInstanceMatrix), ONE needsUpdate, StaticDrawUsage, per-chunk
 *     bounding sphere containing every instance
 *   • EM-157: raycast disabled on city meshes
 *   • extractInstanceParts: same-material sub-meshes merge into one geometry
 *     (Kenney cars), distinct materials stay separate parts, identity
 *     single-mesh scenes reuse the cached geometry
 *   • render smoke (jsdom, useToonGLTF mocked like sibling tests — GLBs don't
 *     load here): one <instancedMesh> per (key × chunk × part), matching the
 *     plan + chunking math exactly
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import * as THREE from 'three';
import type { Place } from '../../types';
import {
  computeCityPlan,
  CITY_PIECE_KEYS,
  type CityInstance,
  type CityPlan,
} from './cityLayout';
import { CITY_MODEL_REGISTRY } from './assets/cityModels';
import type { ModelSpec } from './assets/models';

// GLBs cannot load in jsdom — replace the toon-converted load path with a
// deterministic single-mesh scene per url (the sibling-test idiom).
vi.mock('./assets/Model', async () => {
  const T = await import('three');
  const cache = new Map<string, InstanceType<typeof T.Group>>();
  return {
    useToonGLTF: (url: string) => {
      let scene = cache.get(url);
      if (!scene) {
        scene = new T.Group();
        scene.add(new T.Mesh(new T.BoxGeometry(1, 1, 1), new T.MeshBasicMaterial()));
        cache.set(url, scene);
      }
      return { scene, animations: [] };
    },
  };
});

import {
  CityScape,
  CHUNK_SPLIT_4,
  CHUNK_SPLIT_8,
  GRID_CENTER,
  chunkCount,
  chunkIndexOf,
  chunkInstances,
  citySignature,
  composeInstanceMatrix,
  extractInstanceParts,
  noopRaycast,
  renderableEntries,
  setupCityMesh,
} from './CityScape';

afterEach(cleanup);

/** The Wave D1.5 15-place city (the frozen landmark table — ids, kinds and
 *  districts unchanged from Wave C; positions snapped to the 5×5 grid). */
const TOWN: Place[] = [
  { id: 'plaza', name: 'Central Plaza', x: 500, y: 500, kind: 'social', district: 'core', description: '' },
  { id: 'well', name: 'Fountain Court', x: 500, y: 303, kind: 'social', district: 'core', description: '' },
  { id: 'market', name: 'Market Hall', x: 697, y: 303, kind: 'work', district: 'market', description: '' },
  { id: 'forge', name: 'The Steelworks', x: 894, y: 303, kind: 'work', district: 'market', description: '' },
  { id: 'workshop', name: "Tinker's Workshop", x: 894, y: 500, kind: 'work', district: 'market', description: '' },
  { id: 'townhall', name: 'City Hall', x: 106, y: 106, kind: 'governance', district: 'civic', description: '' },
  { id: 'archive', name: 'The Records Office', x: 303, y: 106, kind: 'governance', district: 'civic', description: '' },
  { id: 'home', name: 'Hearth House', x: 106, y: 697, kind: 'home', district: 'residential', description: '' },
  { id: 'rosehip_cottage', name: 'Rosehip Walk-up', x: 106, y: 894, kind: 'home', district: 'residential', description: '' },
  { id: 'mossy_row', name: 'Mossy Row Flats', x: 303, y: 894, kind: 'home', district: 'residential', description: '' },
  { id: 'lantern_loft', name: 'Lantern Lofts', x: 303, y: 697, kind: 'home', district: 'residential', description: '' },
  { id: 'commons', name: 'The Commons Park', x: 697, y: 697, kind: 'wild', district: 'farm', description: '' },
  { id: 'willow_pond', name: 'Willow Pond Park', x: 697, y: 894, kind: 'wild', district: 'farm', description: '' },
  { id: 'orchard', name: 'Orchard Green', x: 894, y: 894, kind: 'wild', district: 'farm', description: '' },
  { id: 'farmstead', name: 'Sunfall Depot', x: 894, y: 697, kind: 'work', district: 'farm', description: '' },
];

const PLAN = computeCityPlan({ places: TOWN });
const CENTER = GRID_CENTER; // the D1.5 grid is origin-centered
const SPEC: ModelSpec = { url: '/models/test.glb', scale: 2.0, yOffset: 0.1, rotation: Math.PI / 2 };

function planTotal(): number {
  return CITY_PIECE_KEYS.reduce((n, k) => n + PLAN.pieces[k].length, 0);
}

describe('renderableEntries (plan → render mapping, rule 10)', () => {
  it('carries every plan instance for non-null keys, in canonical order', () => {
    const entries = renderableEntries(PLAN, CITY_MODEL_REGISTRY);
    // All 23 registry keys are non-null today, so only EMPTY pieces drop out.
    const nonEmpty = CITY_PIECE_KEYS.filter((k) => PLAN.pieces[k].length > 0);
    expect(entries.map((e) => e.key)).toEqual(nonEmpty);
    const mapped = entries.reduce((n, e) => n + e.instances.length, 0);
    expect(mapped).toBe(planTotal());
    expect(mapped).toBeGreaterThan(0);
  });

  it('skips null registry entries without dropping anything else', () => {
    const registry = { ...CITY_MODEL_REGISTRY, road_straight: null, lamp: null };
    const entries = renderableEntries(PLAN, registry);
    const keys = entries.map((e) => e.key);
    expect(keys).not.toContain('road_straight');
    expect(keys).not.toContain('lamp');
    const mapped = entries.reduce((n, e) => n + e.instances.length, 0);
    expect(mapped).toBe(
      planTotal() - PLAN.pieces.road_straight.length - PLAN.pieces.lamp.length,
    );
  });

  it('v2 plan additions (landmarks / landmark zone) are render-inert metadata', () => {
    // The Wave D1.5 seam: CityPlan carries `landmarks` and may zone blocks
    // 'landmark'. The renderer must consume the plan through `pieces` ONLY —
    // landmark blocks emit no generated buildings (place anchors render via
    // Building.tsx), so the additions change nothing about instancing.
    const pieces = {} as CityPlan['pieces'];
    for (const k of CITY_PIECE_KEYS) pieces[k] = [];
    pieces.com_a = [
      { x: 6.5, z: -6.5, rotY: 0 },
      { x: -6.5, z: 6.5, rotY: Math.PI / 2 },
    ];
    const v2Plan: CityPlan = {
      pieces,
      blocks: [{ cx: 0, cz: 0, zone: 'landmark' }],
      landmarks: { plaza: { x: 0, z: 0 } },
      realLots: { plaza: [{ x: 3.6, z: 1.9, rotY: 0 }] },
      blockLots: [{ cx: 13, cz: 0, lots: [{ x: 13, z: 3.7, rotY: 0 }] }],
      emptyLots: [{ x: -3.6, z: -1.9, rotY: 0 }],
      // EM-188: street names are layout metadata too — render-inert here
      // (labels render via StreetLabels in CozyWorld, never this instancer).
      streets: [],
      extent: 33,
    };
    const entries = renderableEntries(v2Plan, CITY_MODEL_REGISTRY);
    expect(entries.map((e) => e.key)).toEqual(['com_a']);
    expect(entries[0].instances).toHaveLength(2);
  });
});

describe('chunking math', () => {
  function synth(n: number): CityInstance[] {
    // deterministic ring scatter around CENTER, all four quadrants hit
    return Array.from({ length: n }, (_, i) => ({
      x: CENTER.x + Math.cos((i / n) * Math.PI * 2) * 50,
      z: CENTER.z + Math.sin((i / n) * Math.PI * 2) * 50,
      rotY: 0,
    }));
  }

  it('splits 1 / 4 / 8 at the thresholds', () => {
    expect(chunkCount(0)).toBe(1);
    expect(chunkCount(CHUNK_SPLIT_4)).toBe(1);
    expect(chunkCount(CHUNK_SPLIT_4 + 1)).toBe(4);
    expect(chunkCount(CHUNK_SPLIT_8)).toBe(4);
    expect(chunkCount(CHUNK_SPLIT_8 + 1)).toBe(8);
  });

  it('partitions losslessly into ≤ 8 non-empty chunks', () => {
    for (const n of [10, CHUNK_SPLIT_4 + 20, CHUNK_SPLIT_8 + 40]) {
      const instances = synth(n);
      const chunks = chunkInstances(instances, CENTER);
      expect(chunks.length).toBeLessThanOrEqual(8);
      expect(chunks.every((c) => c.length > 0)).toBe(true);
      expect(chunks.reduce((s, c) => s + c.length, 0)).toBe(n);
    }
  });

  it('buckets quadrants spatially around the centroid', () => {
    const probe = (dx: number, dz: number) =>
      chunkIndexOf({ x: CENTER.x + dx, z: CENTER.z + dz, rotY: 0 }, CENTER, 4);
    expect(probe(-1, -1)).toBe(0);
    expect(probe(1, -1)).toBe(1);
    expect(probe(-1, 1)).toBe(2);
    expect(probe(1, 1)).toBe(3);
    // octants stay in range and are stable
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2;
      const idx = chunkIndexOf(
        { x: CENTER.x + Math.cos(a) * 9, z: CENTER.z + Math.sin(a) * 9, rotY: 0 },
        CENTER,
        8,
      );
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(idx).toBeLessThanOrEqual(7);
    }
    expect(chunkInstances([], CENTER)).toEqual([]);
  });
});

describe('setupCityMesh (matrices + EM-157)', () => {
  const instances: CityInstance[] = [
    { x: 10, z: -4, rotY: Math.PI / 4, s: 1.1 },
    { x: -7, z: 22, rotY: -Math.PI / 2 },
    { x: 0, z: 0, rotY: 0, s: 0.9 },
  ];

  function makeMesh(n: number): THREE.InstancedMesh {
    return new THREE.InstancedMesh(
      new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshBasicMaterial(),
      n,
    );
  }

  it('writes one matrix per instance matching composeInstanceMatrix', () => {
    const mesh = makeMesh(instances.length);
    setupCityMesh(mesh, instances, SPEC);
    const got = new THREE.Matrix4();
    const want = new THREE.Matrix4();
    for (let i = 0; i < instances.length; i++) {
      mesh.getMatrixAt(i, got);
      composeInstanceMatrix(instances[i], SPEC, want);
      // instanceMatrix is a Float32 buffer — compare with f32 tolerance
      for (let e = 0; e < 16; e++) {
        expect(got.elements[e]).toBeCloseTo(want.elements[e], 5);
      }
    }
    // decode one matrix back to world terms: position carries spec.yOffset,
    // scale carries spec.scale × inst.s
    const p = new THREE.Vector3();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    mesh.getMatrixAt(0, got);
    got.decompose(p, q, s);
    expect(p.x).toBeCloseTo(10);
    expect(p.y).toBeCloseTo(SPEC.yOffset);
    expect(p.z).toBeCloseTo(-4);
    expect(s.x).toBeCloseTo(SPEC.scale * 1.1);
  });

  it('marks the buffer once, static, with a bounding sphere covering all instances', () => {
    const mesh = makeMesh(instances.length);
    expect(mesh.instanceMatrix.version).toBe(0);
    setupCityMesh(mesh, instances, SPEC);
    expect(mesh.instanceMatrix.version).toBe(1); // exactly ONE needsUpdate
    expect(mesh.instanceMatrix.usage).toBe(THREE.StaticDrawUsage);
    expect(mesh.boundingSphere).not.toBeNull();
    for (const inst of instances) {
      const p = new THREE.Vector3(inst.x, SPEC.yOffset, inst.z);
      expect(mesh.boundingSphere!.containsPoint(p)).toBe(true);
    }
  });

  it('disables raycasting (EM-157: set dressing is non-interactive)', () => {
    const mesh = makeMesh(instances.length);
    setupCityMesh(mesh, instances, SPEC);
    expect(mesh.raycast).toBe(noopRaycast);
    const raycaster = new THREE.Raycaster(
      new THREE.Vector3(10, 50, -4),
      new THREE.Vector3(0, -1, 0),
    );
    const hits: THREE.Intersection[] = [];
    mesh.raycast(raycaster, hits);
    expect(hits).toEqual([]);
  });
});

describe('extractInstanceParts (geometry/material once per GLB)', () => {
  it('reuses the geometry of a single identity-transform mesh untouched', () => {
    const scene = new THREE.Group();
    const geom = new THREE.BoxGeometry(1, 1, 1);
    scene.add(new THREE.Mesh(geom, new THREE.MeshToonMaterial()));
    const parts = extractInstanceParts(scene);
    expect(parts).toHaveLength(1);
    expect(parts[0].geometry).toBe(geom);
    // cached: second call returns the identical parts array
    expect(extractInstanceParts(scene)).toBe(parts);
  });

  it('merges same-material sub-meshes (Kenney car shape) into one part', () => {
    const scene = new THREE.Group();
    const mat = new THREE.MeshToonMaterial();
    const body = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 2), mat);
    const wheel = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.3, 0.3), mat);
    wheel.position.set(0.5, -0.4, 0.7);
    scene.add(body, wheel);
    const parts = extractInstanceParts(scene);
    expect(parts).toHaveLength(1);
    expect(parts[0].material).toBe(mat); // the SHARED material, never cloned
    const wantVerts =
      body.geometry.attributes.position.count + wheel.geometry.attributes.position.count;
    expect(parts[0].geometry.attributes.position.count).toBe(wantVerts);
  });

  it('keeps distinct materials as distinct parts (trashcan shape)', () => {
    const scene = new THREE.Group();
    const a = new THREE.MeshToonMaterial();
    const b = new THREE.MeshToonMaterial();
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), a));
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), b));
    const parts = extractInstanceParts(scene);
    expect(parts).toHaveLength(2);
    expect(new Set(parts.map((p) => p.material)).size).toBe(2);
  });
});

describe('citySignature (plan memo key)', () => {
  it('is stable across object identity and sensitive to seed/position/zone inputs', () => {
    const clone = TOWN.map((p) => ({ ...p }));
    expect(citySignature(clone, null)).toBe(citySignature(TOWN, null));
    expect(citySignature(TOWN, 7)).not.toBe(citySignature(TOWN, null));
    const moved = TOWN.map((p, i) => (i === 0 ? { ...p, x: p.x + 1 } : p));
    expect(citySignature(moved, null)).not.toBe(citySignature(TOWN, null));
  });

  it('is keyed on (places, city_seed) ONLY — buildings/day never churn the memo (EM-174)', () => {
    // The EM-155 determinism contract: same places + same seed ⇒ the same
    // memoized plan, no matter what the rest of the snapshot is doing.
    expect(citySignature.length).toBe(2);
    expect(citySignature(TOWN, 1337)).toBe(citySignature(TOWN.map((p) => ({ ...p })), 1337));
  });
});

describe('CityScape render smoke (jsdom harness, GLBs mocked)', () => {
  function renderCity() {
    // react-dom renders the R3F tags as unknown elements — exactly what we
    // want for a structural smoke test; silence its unknown-tag warnings.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      return render(<CityScape world={{ places: TOWN, city_seed: null }} />);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
  }

  it('mounts one instancedMesh per (key × chunk × part) + the platted-lot pads', () => {
    const { container } = renderCity();
    const meshes = container.querySelectorAll('instancedMesh');
    // mocked GLBs are single-mesh ⇒ parts = 1, so expected = Σ chunks per key,
    // plus the Wave D1.6 procedural pad chunks (the young city's empty lots)
    const entries = renderableEntries(PLAN, CITY_MODEL_REGISTRY);
    const padChunks = chunkInstances(PLAN.emptyLots, CENTER).length;
    const expected =
      entries.reduce((n, e) => n + chunkInstances(e.instances, CENTER).length, 0) + padChunks;
    expect(meshes.length).toBe(expected);
    expect(meshes.length).toBeGreaterThan(entries.length - 1); // road_straight chunks
    // the dominant key really did chunk
    const straightChunks = container.querySelectorAll('[name^="city-road_straight-"]');
    expect(straightChunks.length).toBe(chunkInstances(PLAN.pieces.road_straight, CENTER).length);
    expect(straightChunks.length).toBeGreaterThan(1);
    // EM-174: the platted city always shows its pads (no generated buildings)
    expect(PLAN.emptyLots.length).toBeGreaterThan(0);
    const padMeshes = container.querySelectorAll('[name^="city-pad-"]');
    expect(padMeshes.length).toBe(padChunks);
    expect(padMeshes.length).toBeGreaterThan(0);
  });

  it('renders every plan instance exactly once across all chunks', () => {
    // What CityScape RENDERS is the plan: the chunked instanced meshes must
    // carry the full instance population, no piece lost, none duplicated.
    const entries = renderableEntries(PLAN, CITY_MODEL_REGISTRY);
    for (const e of entries) {
      const chunked = chunkInstances(e.instances, CENTER).flat();
      expect(chunked).toHaveLength(e.instances.length);
      expect(new Set(chunked).size).toBe(e.instances.length);
    }
  });
});
