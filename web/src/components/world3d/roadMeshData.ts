/**
 * roadMesh.ts — EM-247 (S5a): PURE procedural road geometry from the CityGraph.
 * Each edge → a width-correct ribbon instance oriented at ANY angle; each node →
 * an intersection patch (roundabout/plaza nodes → ring/plaza geometry, ready for
 * S3b). Output is instance transforms per piece bucket (the existing raw-
 * InstancedMesh-per-bucket pattern), so the whole city is a few draw calls.
 *
 * Pure fn of (graph, seed): same graph ⇒ identical arrays (edge/node order). No
 * RNG/clock/mutable state. This is the data layer S5a's <RoadMesh> renders behind
 * the ROAD_MESH_ENABLED flag (default ON since the EM-247 sign-off, PR #65); the
 * tile path remains the flag-off fallback.
 */
import type { CityGraph, CityGraphNode } from '../../types';

export interface RibbonInstance { x: number; z: number; rotY: number; length: number; width: number }
export interface PatchInstance { x: number; z: number; size: number }
export interface RingInstance { x: number; z: number; outerR: number; innerR: number }
export interface RoadMesh {
  ribbons: RibbonInstance[];
  intersections: PatchInstance[];
  roundabouts: RingInstance[];
  plazas: PatchInstance[];
}

// Road widths by class (world units). 'street' is the S1/S2 default; wider classes
// arrive with S3b master plans. TILE = 2.6 (cityLayout), a lane ~ one tile wide.
export const ROAD_WIDTH: Record<string, number> = {
  street: 2.6,
  avenue: 3.9,
  boulevard: 5.2,
};

const JUNCTION_SIZE = 3.0;   // intersection patch (covers ribbon ends at a node)
const PLAZA_SIZE = 6.0;      // plaza node footprint
const ROUNDABOUT_OUTER = 4.0;
const ROUNDABOUT_INNER = 2.0;

function widthFor(roadClass: string | undefined): number {
  return (roadClass && ROAD_WIDTH[roadClass]) || ROAD_WIDTH.street;
}

export function buildRoadMesh(graph: CityGraph | null | undefined, _seed: number): RoadMesh {
  const empty: RoadMesh = { ribbons: [], intersections: [], roundabouts: [], plazas: [] };
  if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) return empty;

  const nodeById = new Map<string, CityGraphNode>(graph.nodes.map((n) => [n.id, n]));

  const ribbons: RibbonInstance[] = [];
  for (const e of graph.edges) {
    const a = nodeById.get(e.a);
    const b = nodeById.get(e.b);
    if (!a || !b) continue;            // dangling edge: skip (never throw)
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const length = Math.hypot(dx, dz);
    if (length === 0) continue;        // degenerate
    ribbons.push({
      x: (a.x + b.x) / 2,
      z: (a.z + b.z) / 2,
      rotY: Math.atan2(dz, dx),        // ANY angle — the S5a point
      length,
      width: widthFor((e as { road_class?: string }).road_class),
    });
  }

  const intersections: PatchInstance[] = [];
  const roundabouts: RingInstance[] = [];
  const plazas: PatchInstance[] = [];
  for (const n of graph.nodes) {
    const kind = (n as { kind?: string }).kind;
    if (kind === 'roundabout') {
      roundabouts.push({ x: n.x, z: n.z, outerR: ROUNDABOUT_OUTER, innerR: ROUNDABOUT_INNER });
    } else if (kind === 'plaza') {
      plazas.push({ x: n.x, z: n.z, size: PLAZA_SIZE });
    } else {
      intersections.push({ x: n.x, z: n.z, size: JUNCTION_SIZE });
    }
  }

  return { ribbons, intersections, roundabouts, plazas };
}
