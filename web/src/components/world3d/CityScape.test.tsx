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
  FREE_PLACEMENT_ENABLED,
  TILE,
  type CityInstance,
  type CityPlan,
  type CityZone,
} from './cityLayout';
import type { CityGraph } from '../../types';
import type { BuildZone, ZoneRule } from './cityFaces';
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
  GRAPH_LOTS_ENABLED,
  GRID_CENTER,
  PEDESTRIAN_ROAD_COLOR,
  ROAD_MESH_ENABLED,
  ZONE_HINT_TINTS,
  ZoneRuleTints,
  chunkCount,
  chunkIndexOf,
  chunkInstances,
  citySignature,
  composeInstanceMatrix,
  extractInstanceParts,
  noopRaycast,
  renderableEntries,
  setupCityMesh,
  zoneRuleTints,
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
      // EM-244 (S3a): pedestrian surface tiles — render-inert for this entry
      // mapping test (rendered by PedestrianRoadPads, never this instancer).
      pedestrianTiles: [],
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

  it('is keyed on (places, city_seed, neighborhoods, city_graph) — buildings/day never churn the memo (EM-174/EM-243)', () => {
    // The EM-155 determinism contract: same places + seed (+ neighborhood tiers,
    // EM-123, + graph node/edge counts, EM-243) ⇒ the same memoized plan, no
    // matter what the rest of the snapshot is doing. The arity guard catches a
    // quietly-added input (EM-243 deliberately added the 4th: city_graph).
    expect(citySignature.length).toBe(4);
    expect(citySignature(TOWN, 1337)).toBe(citySignature(TOWN.map((p) => ({ ...p })), 1337));
  });

  it('EM-243: a grown graph (more edges) churns the memo; an idle poll (same counts) does not', () => {
    const g0 = { nodes: [{}, {}], edges: [{}] };
    const idlePoll = { nodes: [{}, {}], edges: [{}] };       // fresh object, SAME counts
    const grown = { nodes: [{}, {}, {}], edges: [{}, {}] };  // a road was built (+1 node, +1 edge)
    // idle snapshot poll (new object, identical counts) ⇒ stable ⇒ no buffer churn
    expect(citySignature(TOWN, 1337, undefined, idlePoll)).toBe(citySignature(TOWN, 1337, undefined, g0));
    // a built road (counts grow) ⇒ signature changes ⇒ plan re-derives ⇒ road renders live
    expect(citySignature(TOWN, 1337, undefined, grown)).not.toBe(citySignature(TOWN, 1337, undefined, g0));
  });

  it('equal-count graphs with DIFFERENT edges churn the memo (content key, not counts)', () => {
    // demolish+build inside one snapshot poll (or a balanced morph tick): node/edge
    // COUNTS are identical but the edge SET changed — a count-only fold renders the
    // mutation stale on the default (mesh) renderer. The 4th recurrence of the
    // content-key class (EM-243/244/247 + this).
    const before = { nodes: [{}, {}, {}], edges: [{ id: 'e:a->b' }, { id: 'e:b->c' }] };
    const after = { nodes: [{}, {}, {}], edges: [{ id: 'e:a->b' }, { id: 'e:a->c' }] };
    expect(citySignature(TOWN, 1337, undefined, after)).not.toBe(
      citySignature(TOWN, 1337, undefined, before),
    );
    // edge ORDER (poll nondeterminism) never churns the memo — the key is sorted
    const reordered = { nodes: [{}, {}, {}], edges: [{ id: 'e:b->c' }, { id: 'e:a->b' }] };
    expect(citySignature(TOWN, 1337, undefined, reordered)).toBe(
      citySignature(TOWN, 1337, undefined, before),
    );
  });

  it('EM-244: a car_policy flip at CONSTANT counts churns the memo (city + per-edge)', () => {
    // The S3a HIGH: set_car_policy mutates policy WITHOUT changing node/edge counts,
    // so a count-only signature would miss it and the tint/parked-car removal would
    // not render live. citySignature must fold car_policy too.
    const cars = { nodes: [{}, {}], edges: [{ id: 'e1', car_policy: 'inherit' }], car_policy: 'cars' };
    const cityPed = { nodes: [{}, {}], edges: [{ id: 'e1', car_policy: 'inherit' }], car_policy: 'pedestrian' };
    const edgePed = { nodes: [{}, {}], edges: [{ id: 'e1', car_policy: 'pedestrian' }], car_policy: 'cars' };
    // city-scope ban-cars: same counts, different city policy ⇒ signature changes
    expect(citySignature(TOWN, 1337, undefined, cityPed)).not.toBe(citySignature(TOWN, 1337, undefined, cars));
    // street-scope: one edge flips to pedestrian ⇒ signature changes
    expect(citySignature(TOWN, 1337, undefined, edgePed)).not.toBe(citySignature(TOWN, 1337, undefined, cars));
    // an idle re-poll of the SAME policy state is still stable (no churn)
    const carsPoll = { nodes: [{}, {}], edges: [{ id: 'e1', car_policy: 'inherit' }], car_policy: 'cars' };
    expect(citySignature(TOWN, 1337, undefined, carsPoll)).toBe(citySignature(TOWN, 1337, undefined, cars));
  });

  it('EM-123: a district tier change churns the memo; tier-1/absent does not', () => {
    const baseline = [
      { id: 'farm', name: 'Farm', zone_kind: 'farm', tier: 1, progress: 0 },
    ];
    const grown = [
      { id: 'farm', name: 'Farm', zone_kind: 'farm', tier: 3, progress: 0 },
    ];
    // tier-1 (or absent) neighborhoods leave the signature unchanged…
    expect(citySignature(TOWN, 1337, baseline)).toBe(citySignature(TOWN, 1337));
    // …a grown tier changes it (so the plan rebuilds with extra street life).
    expect(citySignature(TOWN, 1337, grown)).not.toBe(citySignature(TOWN, 1337));
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

  it('mounts one instancedMesh per (key × chunk × part) for the non-road pieces + the platted-lot pads (roads render via <RoadMesh>)', () => {
    const { container } = renderCity();
    const meshes = container.querySelectorAll('instancedMesh');
    // EM-247 (PR #65): the procedural mesh is the DEFAULT road renderer, so the
    // road-tile pieces drop out of the instanced-piece path and <RoadMesh> draws
    // the roads instead (empty here — the smoke city carries no graph). Mocked
    // GLBs are single-mesh ⇒ parts = 1, so expected = Σ chunks per NON-ROAD key,
    // plus the Wave D1.6 procedural pad chunks (the young city's empty lots).
    const entries = renderableEntries(PLAN, CITY_MODEL_REGISTRY);
    const drawEntries = entries.filter((e) => !e.key.startsWith('road_'));
    // EM-268 (F1): pads render only on the FIXED-GRID path. Under free placement
    // they are gated off (buildings no longer claim grid lots — the orphaned
    // "yellow tile" fix), so they contribute zero instanced meshes.
    const padChunks = FREE_PLACEMENT_ENABLED ? 0 : chunkInstances(PLAN.emptyLots, CENTER).length;
    const expected =
      drawEntries.reduce((n, e) => n + chunkInstances(e.instances, CENTER).length, 0) + padChunks;
    expect(meshes.length).toBe(expected);
    expect(meshes.length).toBeGreaterThan(0); // non-road pieces mounted too
    // the road tiles no longer render on the default path…
    expect(container.querySelectorAll('[name^="city-road_straight-"]').length).toBe(0);
    // …the procedural mesh group is mounted in their place (empty w/o a graph)
    expect(container.querySelectorAll('[name="roadmesh"]').length).toBe(1);
    // EM-174: the platted city shows its pads on the fixed-grid path; EM-268
    // gates them off under free placement (the plan still carries emptyLots).
    expect(PLAN.emptyLots.length).toBeGreaterThan(0);
    const padMeshes = container.querySelectorAll('[name^="city-pad-"]');
    expect(padMeshes.length).toBe(padChunks);
  });

  // EM-244 (S3a): a pedestrianized city paints its roads with the tint variant.
  const ROAD_IDX = [-13, -8, -3, 2, 7, 12];
  const tc = (i: number) => (i + 0.5) * TILE;
  function pedestrianCityGraph(): CityGraph {
    const nodes = [];
    for (const j of ROAD_IDX) for (const i of ROAD_IDX)
      nodes.push({ id: `n:${i}:${j}`, x: tc(i), z: tc(j), kind: 'junction' as const });
    const edges = [];
    for (const j of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
      const a = `n:${ROAD_IDX[k]}:${j}`, b = `n:${ROAD_IDX[k + 1]}:${j}`;
      edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
    }
    for (const i of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
      const a = `n:${i}:${ROAD_IDX[k]}`, b = `n:${i}:${ROAD_IDX[k + 1]}`;
      edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
    }
    return { version: 1, seed: 1337, car_policy: 'pedestrian', nodes, edges };
  }

  it('EM-244: no pedestrian-tint meshes by default; a pedestrian city paints them', () => {
    expect(PEDESTRIAN_ROAD_COLOR).toMatch(/^#[0-9a-f]{6}$/i); // a real tint, distinct from PAD_COLOR
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      // Default (no graph) ⇒ zero pedestrian-surface meshes (byte-identical city).
      const plain = render(<CityScape world={{ places: TOWN, city_seed: null }} />);
      expect(plain.container.querySelectorAll('[name^="city-pedestrian-"]').length).toBe(0);
      cleanup();
      // City-scope pedestrian ⇒ the tinted surface paints the road tiles.
      const g = pedestrianCityGraph();
      const expectedChunks = chunkInstances(
        computeCityPlan({ places: TOWN, city_seed: null, city_graph: g }).pedestrianTiles,
        CENTER,
      ).length;
      const banned = render(<CityScape world={{ places: TOWN, city_seed: null, city_graph: g }} />);
      const pedMeshes = banned.container.querySelectorAll('[name^="city-pedestrian-"]');
      expect(pedMeshes.length).toBe(expectedChunks);
      expect(pedMeshes.length).toBeGreaterThan(0);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
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

describe('ROAD_MESH_ENABLED flag (EM-247 — procedural mesh is the default; tile path is the fallback)', () => {
  it('defaults to true (EM-247 visual sign-off, PR #65 — the procedural mesh is the default road renderer)', () => {
    expect(ROAD_MESH_ENABLED).toBe(true);
  });

  it('flag on (default) ⇒ <RoadMesh> renders in place of the road tiles; the tile path is retained as the byte-identical fallback', () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const { container } = render(<CityScape world={{ places: TOWN, city_seed: null }} />);
      // the road-tile pieces no longer render on the default path…
      expect(container.querySelectorAll('[name^="city-road_straight-"]').length).toBe(0);
      // …the procedural mesh group is mounted in their place (the EM-247 default)
      expect(container.querySelectorAll('[name="roadmesh"]').length).toBe(1);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
    // The tile path is retained as the fallback + for byte-identical replay of the
    // flag-off configuration: with the flag off, computeCityPlan still emits the
    // road pieces and CityScape draws them through the unchanged CityPiece path.
    // So the fallback's render inputs must stay intact — the road_straight piece
    // is still in the plan with its full instance population, chunked EXACTLY as
    // the tile path draws it (the dominant key still splits into ≥ 2 chunks).
    const entries = renderableEntries(PLAN, CITY_MODEL_REGISTRY);
    const road = entries.find((e) => e.key === 'road_straight');
    expect(road?.instances).toHaveLength(PLAN.pieces.road_straight.length);
    const roadChunks = chunkInstances(PLAN.pieces.road_straight, CENTER);
    expect(roadChunks.length).toBeGreaterThan(1);
    expect(roadChunks.reduce((n, c) => n + c.length, 0)).toBe(PLAN.pieces.road_straight.length);
  });
});

// ── EM-265 (SB) — agent-authored zone rules: wire + render ────────────────────

/** A synthetic BuildZone (a unit-ish block) carrying the given rules — enough
 *  for the tint helper/component, independent of the planar-face algorithm. */
function zoneFixture(id: string, rules: ZoneRule[]): BuildZone {
  return {
    id,
    face: {
      boundary: id.split('|'),
      poly: [
        { x: 0, z: 0 },
        { x: 4, z: 0 },
        { x: 4, z: 4 },
        { x: 0, z: 4 },
      ],
      centroid: { x: 2, z: 2 },
      area: 16,
    },
    suggestedLots: [],
    zoneHint: 'residential' as CityZone,
    rules,
  };
}

describe('citySignature — EM-265 (SB) zone-rule reactivity (content-key, law §0.5)', () => {
  // rules ride ON the 4th param (the CityGraph), so the arity stays 4 — no new
  // argument, the EM-243 arity guard above still reads 4.
  const base = {
    nodes: [{}, {}],
    edges: [{ id: 'e1', car_policy: 'inherit' }],
    car_policy: 'cars',
  };

  it('arity stays 4 (zone_rules ride on the cityGraph param, not a 5th arg)', () => {
    expect(citySignature.length).toBe(4);
  });

  it('a ratified rule changes the signature; an idle poll (same rules) does not', () => {
    const ruled = { ...base, zone_rules: [{ zone_id: 'z1', hint: 'market', density_cap: 2 }] };
    const ruledPoll = { ...base, zone_rules: [{ zone_id: 'z1', hint: 'market', density_cap: 2 }] };
    // a rule appears ⇒ the sig changes ⇒ the tint re-renders LIVE (no reload)
    expect(citySignature(TOWN, 1337, undefined, ruled)).not.toBe(
      citySignature(TOWN, 1337, undefined, base),
    );
    // idle re-poll of the SAME rule state (fresh object) ⇒ stable ⇒ no churn
    expect(citySignature(TOWN, 1337, undefined, ruledPoll)).toBe(
      citySignature(TOWN, 1337, undefined, ruled),
    );
  });

  it('no rules ⇒ stable (absent === empty array), the no-churn baseline (law §0.1)', () => {
    const emptyRules = { ...base, zone_rules: [] };
    expect(citySignature(TOWN, 1337, undefined, emptyRules)).toBe(
      citySignature(TOWN, 1337, undefined, base),
    );
  });

  it('rule ORDER never churns the memo (the hash is sorted)', () => {
    const a = {
      ...base,
      zone_rules: [
        { zone_id: 'a', hint: 'civic', density_cap: 1 },
        { zone_id: 'b', hint: 'open', density_cap: null },
      ],
    };
    const b = {
      ...base,
      zone_rules: [
        { zone_id: 'b', hint: 'open', density_cap: null },
        { zone_id: 'a', hint: 'civic', density_cap: 1 },
      ],
    };
    expect(citySignature(TOWN, 1337, undefined, b)).toBe(citySignature(TOWN, 1337, undefined, a));
  });

  it('hint AND density_cap both participate (a re-zone or a cap change re-renders)', () => {
    const capA = { ...base, zone_rules: [{ zone_id: 'a', hint: 'market', density_cap: 2 }] };
    const capB = { ...base, zone_rules: [{ zone_id: 'a', hint: 'market', density_cap: 5 }] };
    const capNull = { ...base, zone_rules: [{ zone_id: 'a', hint: 'market', density_cap: null }] };
    const hintB = { ...base, zone_rules: [{ zone_id: 'a', hint: 'civic', density_cap: 2 }] };
    expect(citySignature(TOWN, 1337, undefined, capB)).not.toBe(
      citySignature(TOWN, 1337, undefined, capA),
    );
    expect(citySignature(TOWN, 1337, undefined, capNull)).not.toBe(
      citySignature(TOWN, 1337, undefined, capA),
    );
    expect(citySignature(TOWN, 1337, undefined, hintB)).not.toBe(
      citySignature(TOWN, 1337, undefined, capA),
    );
  });
});

describe('zoneRuleTints + ZONE_HINT_TINTS (pure)', () => {
  it('every SB hint maps to a real hex tint', () => {
    for (const h of ['residential', 'market', 'civic', 'open'] as const) {
      expect(ZONE_HINT_TINTS[h]).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it('returns [] for undefined / empty / unruled zones (no-rules ⇒ no tint, law §0.1)', () => {
    expect(zoneRuleTints(undefined)).toEqual([]);
    expect(zoneRuleTints([])).toEqual([]);
    expect(zoneRuleTints([zoneFixture('z', [])])).toEqual([]);
  });

  it('emits one tint per ruled zone, colored by the rule hint, at the face centroid', () => {
    const tints = zoneRuleTints([
      zoneFixture('z1', [{ zone_id: 'z1', hint: 'market', density_cap: 3 }]),
      zoneFixture('z2', []), // unruled ⇒ contributes nothing
      zoneFixture('z3', [{ zone_id: 'z3', hint: 'open', density_cap: null }]),
    ]);
    expect(tints.map((t) => t.id)).toEqual(['z1', 'z3']);
    expect(tints[0].color).toBe(ZONE_HINT_TINTS.market);
    expect(tints[1].color).toBe(ZONE_HINT_TINTS.open);
    expect(tints[0].x).toBe(2);
    expect(tints[0].z).toBe(2);
    expect(tints[0].radius).toBeGreaterThan(0);
  });
});

describe('ZoneRuleTints (render) — a ratified rule paints its block; none ⇒ nothing', () => {
  function renderTints(zones: BuildZone[]) {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      return render(<ZoneRuleTints zones={zones} />);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
  }

  it('a ruled zone renders exactly one zone-tint mesh; an unruled zone renders none', () => {
    const ruled = renderTints([
      zoneFixture('z1', [{ zone_id: 'z1', hint: 'market', density_cap: 3 }]),
    ]);
    expect(ruled.container.querySelectorAll('[name^="city-zone-tint-"]').length).toBe(1);
    cleanup();
    const none = renderTints([zoneFixture('z2', [])]);
    expect(none.container.querySelectorAll('[name^="city-zone-tint-"]').length).toBe(0);
  });
});

describe('CityScape — EM-265 (SB) gate: zone tints only on the graph-lots path', () => {
  const tc = (i: number) => (i + 0.5) * TILE;
  // A minimal real graph (passes hasRealGraph) that ALSO carries a ratified rule.
  function graphWithRules(zone_rules: ZoneRule[]): CityGraph {
    return {
      version: 1,
      seed: 1337,
      car_policy: 'cars',
      nodes: [
        { id: 'a', x: tc(-3), z: tc(-3), kind: 'junction' },
        { id: 'b', x: tc(2), z: tc(-3), kind: 'junction' },
      ],
      edges: [{ id: 'e', a: 'a', b: 'b', road_class: 'street', car_policy: 'inherit' }],
      zone_rules,
    };
  }

  it('GRAPH_LOTS_ENABLED ships ON ⇒ zone tints live on the graph-lots path, but a face-less graph still paints none', () => {
    // Organic-world sign-off (feat/organic-world-regen): the flag now ships ON, so
    // zone tints CAN render. This minimal 2-node / 1-edge graph encloses no planar
    // face ⇒ no derivable zones ⇒ still no tints — a valid on-path edge case (a
    // ratified rule with nowhere to land renders nothing, never a stray tile).
    expect(GRAPH_LOTS_ENABLED).toBe(true);
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const g = graphWithRules([{ zone_id: 'a|b', hint: 'market', density_cap: 2 }]);
      const { container } = render(
        <CityScape world={{ places: TOWN, city_seed: null, city_graph: g }} />,
      );
      expect(container.querySelectorAll('[name^="city-zone-tint-"]').length).toBe(0);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
  });
});
