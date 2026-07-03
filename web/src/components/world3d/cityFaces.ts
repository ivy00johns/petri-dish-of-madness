/**
 * cityFaces — EM-264 (SA): the planar-face keystone of the building-layout
 * initiative. Trace the bounded planar faces (city blocks) of the authoritative
 * road graph, then turn each into a buildable zone with seeded lot pads.
 *
 * The law (contracts/em264-build-contract.md §0):
 *   • DETERMINISTIC (EM-155). Pure function of (graph, seed). No Math.random,
 *     no clock, no unsorted Map/Set iteration leaking into output. Node/edge
 *     INPUT ORDER must not affect output — we sort nodes/edges by id, sort each
 *     vertex's incident half-edges by angle, and walk faces from a globally
 *     sorted half-edge order, so the same cycle always starts at the same
 *     (lexicographically smallest) half-edge ⇒ byte-identical boundaries.
 *   • NEVER THROWS, NEVER SILENTLY DROPS A REGION (pillar 2). A corrupt / stub /
 *     disconnected / degenerate graph returns loose data or []. We mirror
 *     roadTileSetFrom's ModelBoundary guard: not a graph, or nodes/edges aren't
 *     arrays, or no edges ⇒ []. A discarded ENCLOSED face is the FORBIDDEN
 *     failure — we drop ONLY the unbounded outer face(s), identified by winding
 *     (signed area ≤ 0), so every region that encloses area survives, even on a
 *     disconnected graph (each component's outer ring is dropped independently).
 *   • NO SPECIAL-CASING THE CORE (pillar 4). The pentagon inner face is just
 *     another positive-area face — no core branch anywhere.
 *
 * Algorithm — half-edge / next-edge-by-angle (standard planar subdivision):
 *   Each undirected edge {a,b} becomes two directed half-edges a→b and b→a. At
 *   each vertex the outgoing half-edges are sorted by angle (CCW). The next
 *   half-edge around a face, arriving at v via u→v, is the MOST-CLOCKWISE turn
 *   at v: the outgoing edge immediately clockwise of the reverse edge v→u (the
 *   previous entry in v's CCW-sorted list). `next` is a permutation of the
 *   half-edges, so the half-edges partition into disjoint face cycles. Bounded
 *   faces come out counter-clockwise (signed area > 0); each connected
 *   component's unbounded outer face comes out clockwise (signed area ≤ 0) and
 *   is dropped.
 *
 *   The next-by-angle walk ASSUMES a clean planar embedding: no two outgoing
 *   half-edges at a vertex may share an angle. EM-245 morph/merge artifacts
 *   violate that (coincident nodes; a node sitting ON another edge — e.g. the
 *   radial master plan's center→outer spoke passing through the inner-ring
 *   node). An angular tie tangles a bounded face into the outer face and the
 *   region is silently dropped — the FORBIDDEN failure. So planarFaces operates
 *   on a SANITIZED working copy: (1) merge coincident nodes, (2) split edges at
 *   any interior collinear node, (3) tie-break residual equal angles by
 *   distance, and (4) backstop — if an exact-direction tie still survives, bail
 *   the WHOLE graph to [] (caller falls back to the grid). A clean whole-graph
 *   [] is sanctioned; a silent PARTIAL drop is not. The sanitization touches
 *   ONLY this trace — road rendering reads the raw graph and is unaffected.
 *
 * Circular-import discipline (contract §1): cityLayout imports cityFaces, so
 * cityFaces MUST NOT runtime-import cityLayout. CityInstance / CityZone come in
 * as `import type` only, and the zone-hint derivation is an INJECTED callback
 * (computeCityPlan owns places + zoneForPlace). hashUnit is imported from
 * worldSpace (no cycle); CityGraph is a type-only import from ../../types.
 */

import type { CityGraph, ZoneRule } from '../../types';
import type { CityInstance, CityZone } from './cityLayout';
import { hashUnit } from './worldSpace';

// EM-265 (SB): the SA forward stub (`{zoneId, hint: CityZone, densityCap}`) is
// retired for the wire shape `ZoneRule` (snake_case: `{zone_id, hint, density_cap}`,
// matching the backend JSON byte-for-byte — types/index.ts). SA never populated
// `rules` (every BuildZone.rules was []), so there is no data migration; SB just
// fills the same hook from `CityGraph.zone_rules` keyed by zone id.
export type { ZoneRule };

export interface CityFace {
  /** Boundary node ids in walk order (loose; may be slightly degenerate). */
  boundary: string[];
  /** Polygon vertices in world space, same order as `boundary`. */
  poly: { x: number; z: number }[];
  centroid: { x: number; z: number };
  /** Signed area (CCW positive). The unbounded outer face is dropped PER-CYCLE
   *  by winding SIGN (positive signed area kept), NOT by "largest |area|" — a
   *  max-|area| drop would wrongly keep a spurious outer ring of any smaller
   *  disconnected component. */
  area: number;
}

export interface BuildZone {
  /** Stable id: sorted boundary node ids joined (rotation/direction-independent). */
  id: string;
  face: CityFace;
  /** Suggested lot pads — a hint, NOT an assignment (overflow/gaps allowed). */
  suggestedLots: CityInstance[];
  /** Derived default zone (from the injected callback at the centroid). */
  zoneHint: CityZone;
  /** SB hook — always [] in SA. */
  rules: ZoneRule[];
}

// ── tunables ──────────────────────────────────────────────────────────────────

/** Lot-pad grid pitch (world units) — kin to cityLayout.TILE (2.6) but kept
 *  local so cityFaces never runtime-imports cityLayout (circular hazard). */
const LOT_PITCH = 2.6;
/** A pad must sit at least this far inside the face boundary (loose clip). */
const LOT_INSET = 1.0;
/** Position jitter applied to each seeded pad, world units (peak-to-peak). */
const LOT_JITTER = 0.4;
/** Hard cap on pads per face (a huge face never explodes the plan). */
const MAX_LOTS_PER_FACE = 256;
/** Below this |area| a polygon centroid degenerates; fall back to vertex mean. */
const AREA_EPS = 1e-12;

/** Coincident-node merge quantum (world units). Two nodes round to the same
 *  integer lattice cell ⇒ treated as one. Far below the exact-coincidence cliff:
 *  a 0.001 nudge lands in a different cell and stays distinct. */
const MERGE_QUANT = 1e-6;
/** A node within this perpendicular distance of an edge (and strictly between
 *  its endpoints) is treated as lying ON it ⇒ the edge is split there. */
const ON_SEG_EPS = 1e-6;
/** Exclude the endpoints themselves from the point-on-segment test. */
const ON_SEG_T_EPS = 1e-9;
/** Two outgoing half-edges whose normalized cross is below this (and dot > 0)
 *  point in the SAME direction — an unresolved angular tie ⇒ whole-graph []. */
const DIR_TIE_EPS = 1e-9;

// ── internal half-edge types ──────────────────────────────────────────────────

interface FNode {
  id: string;
  x: number;
  z: number;
}

interface HalfEdge {
  from: string;
  to: string;
  dx: number;
  dz: number;
  len: number;
  angle: number;
}

/** Directed half-edge key. JSON-encoded so it is PURE TEXT (no control byte that
 *  would make this source a binary blob) and collision-proof for ANY node-id
 *  charset — `["from","to"]` uniquely identifies a directed half-edge. */
const heKey = (from: string, to: string): string => JSON.stringify([from, to]);

/** Insert an undirected edge into `m`, canonically keyed, first-wins (dedupes
 *  exact-duplicate edges and the duplicates that node-merge / edge-split create).
 *  Self-loops are dropped (they enclose nothing). */
function addUndirected(
  m: Map<string, { a: string; b: string }>,
  a: string,
  b: string,
): void {
  if (a === b) return;
  const key = a < b ? heKey(a, b) : heKey(b, a);
  if (!m.has(key)) m.set(key, { a, b });
}

function isValidNode(n: unknown): n is { id: string; x: number; z: number } {
  if (!n || typeof n !== 'object') return false;
  const r = n as Record<string, unknown>;
  return (
    typeof r.id === 'string' &&
    typeof r.x === 'number' &&
    Number.isFinite(r.x) &&
    typeof r.z === 'number' &&
    Number.isFinite(r.z)
  );
}

// ── geometry ──────────────────────────────────────────────────────────────────

function signedArea(poly: { x: number; z: number }[]): number {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i];
    const q = poly[(i + 1) % poly.length];
    a += p.x * q.z - q.x * p.z;
  }
  return a / 2;
}

function polygonCentroid(
  poly: { x: number; z: number }[],
  area: number,
): { x: number; z: number } {
  if (poly.length === 0) return { x: 0, z: 0 };
  if (poly.length < 3 || Math.abs(area) < AREA_EPS) {
    // Degenerate (sliver / collinear): area-weighted centroid is unstable, so
    // fall back to the vertex mean — still inside the loose polygon's hull.
    let sx = 0;
    let sz = 0;
    for (const p of poly) {
      sx += p.x;
      sz += p.z;
    }
    return { x: sx / poly.length, z: sz / poly.length };
  }
  let cx = 0;
  let cz = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i];
    const q = poly[(i + 1) % poly.length];
    const cross = p.x * q.z - q.x * p.z;
    cx += (p.x + q.x) * cross;
    cz += (p.z + q.z) * cross;
  }
  const f = 1 / (6 * area);
  return { x: cx * f, z: cz * f };
}

function pointInPolygon(
  x: number,
  z: number,
  poly: { x: number; z: number }[],
): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x;
    const zi = poly[i].z;
    const xj = poly[j].x;
    const zj = poly[j].z;
    const hit =
      zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi;
    if (hit) inside = !inside;
  }
  return inside;
}

function distToSegment(
  px: number,
  pz: number,
  ax: number,
  az: number,
  bx: number,
  bz: number,
): number {
  const dx = bx - ax;
  const dz = bz - az;
  const len2 = dx * dx + dz * dz;
  let t = len2 > 0 ? ((px - ax) * dx + (pz - az) * dz) / len2 : 0;
  if (t < 0) t = 0;
  else if (t > 1) t = 1;
  return Math.hypot(px - (ax + t * dx), pz - (az + t * dz));
}

function distToPolygonEdges(
  x: number,
  z: number,
  poly: { x: number; z: number }[],
): number {
  let m = Infinity;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const d = distToSegment(x, z, poly[j].x, poly[j].z, poly[i].x, poly[i].z);
    if (d < m) m = d;
  }
  return m;
}

/** If point p lies strictly between segment endpoints a→b and within ON_SEG_EPS
 *  of the line, return its parameter t∈(0,1); else null. Used to planarize
 *  collinear overlaps by splitting the edge at p. */
function pointOnSegment(
  px: number,
  pz: number,
  ax: number,
  az: number,
  bx: number,
  bz: number,
): number | null {
  const dx = bx - ax;
  const dz = bz - az;
  const len2 = dx * dx + dz * dz;
  if (len2 === 0) return null; // degenerate segment encloses nothing to split
  const t = ((px - ax) * dx + (pz - az) * dz) / len2;
  if (t <= ON_SEG_T_EPS || t >= 1 - ON_SEG_T_EPS) return null; // endpoint/outside
  const d = Math.hypot(px - (ax + t * dx), pz - (az + t * dz));
  return d <= ON_SEG_EPS ? t : null;
}

/** Two outgoing half-edges point in the same direction (an unresolved angular
 *  tie) when their normalized cross ≈ 0 AND they face the same way (dot > 0).
 *  Vector-based, so it catches the ±π wrap an angle compare would miss. */
function sameDirection(p: HalfEdge, q: HalfEdge): boolean {
  if (p.len === 0 || q.len === 0) return false;
  const cross = (p.dx * q.dz - p.dz * q.dx) / (p.len * q.len);
  const dot = p.dx * q.dx + p.dz * q.dz;
  return Math.abs(cross) < DIR_TIE_EPS && dot > 0;
}

/** 2× the signed area of triangle (a,b,c): >0 CCW, <0 CW, 0 collinear. */
function orient(
  ax: number,
  az: number,
  bx: number,
  bz: number,
  cx: number,
  cz: number,
): number {
  return (bx - ax) * (cz - az) - (bz - az) * (cx - ax);
}

/** True iff open segments a1→a2 and b1→b2 cross at a single point interior to
 *  BOTH (a proper transversal crossing). A shared endpoint or a collinear
 *  overlap is NOT a proper crossing (those are handled by node-merge / edge-
 *  split): the strict opposite-orientation test is false whenever ANY of the
 *  four orientations is zero. Symmetric ⇒ input-order independent. */
function segmentsProperlyCross(
  a1: FNode,
  a2: FNode,
  b1: FNode,
  b2: FNode,
): boolean {
  const d1 = orient(b1.x, b1.z, b2.x, b2.z, a1.x, a1.z);
  const d2 = orient(b1.x, b1.z, b2.x, b2.z, a2.x, a2.z);
  const d3 = orient(a1.x, a1.z, a2.x, a2.z, b1.x, b1.z);
  const d4 = orient(a1.x, a1.z, a2.x, a2.z, b2.x, b2.z);
  return (
    ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) &&
    ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))
  );
}

// ── planarFaces ───────────────────────────────────────────────────────────────

/** Trace the bounded planar faces (city blocks) of the road graph.
 *  Pure + deterministic (sort nodes/edges by id first). Defensive: stubs,
 *  disconnected components, and degenerate faces are tolerated; coincident nodes
 *  and collinear edge overlaps are sanitized first so an angular tie never
 *  silently drops a region; a graph with no real nodes/edges returns []. NEVER
 *  throws; NEVER drops an enclosed region (worst case: clean whole-graph []). */
export function planarFaces(graph: CityGraph | null | undefined): CityFace[] {
  // ModelBoundary guard — mirror roadTileSetFrom EXACTLY: not a graph, or
  // nodes/edges aren't arrays, or there are no edges ⇒ no faces. Never throw
  // (computeCityPlan runs upstream of the per-piece <ModelBoundary>, so a throw
  // here would crash the whole 3D world instead of degrading gracefully).
  if (
    !graph ||
    !Array.isArray(graph.nodes) ||
    !Array.isArray(graph.edges) ||
    !graph.edges.length
  ) {
    return [];
  }

  // Sort nodes by id ⇒ input order never matters.
  const sortedNodes = [...graph.nodes]
    .filter(isValidNode)
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  if (sortedNodes.length === 0) return [];

  // ── Sanitize step 1: MERGE coincident nodes ────────────────────────────────
  // EM-264 SA defect fix: EM-245 morph/merge artifacts can leave two node ids at
  // the SAME coordinate. A coincident vertex gives the walk two outgoing half-
  // edges at an IDENTICAL angle, tangling the bounded face into the outer face so
  // its enclosed region is silently dropped. Group nodes onto a fine integer
  // lattice (quantum far below the exact-coincidence cliff, so a 0.001 nudge
  // stays distinct) and collapse each cell to one canonical id (lex-smallest, for
  // determinism). first-wins on duplicate ids, too.
  const canonOf = new Map<string, string>(); // origId → canonical id
  const canonNodes = new Map<string, FNode>(); // canonical id → node
  const cellToCanon = new Map<string, string>(); // quant cell → canonical id
  for (const n of sortedNodes) {
    if (canonOf.has(n.id)) continue; // duplicate id: first (lex-smallest) wins
    const cell = `${Math.round(n.x / MERGE_QUANT)}|${Math.round(n.z / MERGE_QUANT)}`;
    const existing = cellToCanon.get(cell);
    if (existing !== undefined) {
      canonOf.set(n.id, existing); // coincident with an earlier node → merge
    } else {
      cellToCanon.set(cell, n.id);
      canonOf.set(n.id, n.id);
      canonNodes.set(n.id, { id: n.id, x: n.x, z: n.z });
    }
  }
  if (canonNodes.size === 0) return [];

  // Sort edges by id (then endpoints) for deterministic dedupe, then rewrite
  // endpoints to canonical ids and drop self-loops + dangling endpoints + exact
  // duplicates (which also covers the duplicates the node-merge introduces).
  const sortedEdges = [...graph.edges]
    .filter((e): e is NonNullable<typeof e> => !!e)
    .sort((a, b) => {
      const ak = typeof a.id === 'string' ? a.id : heKey(String(a.a), String(a.b));
      const bk = typeof b.id === 'string' ? b.id : heKey(String(b.a), String(b.b));
      return ak < bk ? -1 : ak > bk ? 1 : 0;
    });
  const undirected = new Map<string, { a: string; b: string }>();
  for (const e of sortedEdges) {
    if (typeof e.a !== 'string' || typeof e.b !== 'string') continue;
    const a = canonOf.get(e.a);
    const b = canonOf.get(e.b);
    if (a === undefined || b === undefined) continue; // dangling endpoint
    addUndirected(undirected, a, b); // a===b (self-loop / merged) dropped inside
  }
  if (undirected.size === 0) return [];

  // ── Sanitize step 2: SPLIT collinear overlaps ──────────────────────────────
  // EM-264 SA defect fix: when a node lies ON another edge (e.g. the radial
  // master plan's center→outer spoke passes straight through the inner-ring node),
  // the long edge overlaps the short edge to that intermediate node — two outgoing
  // half-edges at the SAME angle ⇒ angular tie ⇒ silent drop. Split the long edge
  // at every interior node, so center→outer becomes center→inner + inner→outer:
  // the overlapping collinear spoke (and its tie) vanishes and the region
  // decomposes into real sectors. We split ONLY at EXISTING nodes (no new
  // vertices) and every interior node of a sub-edge is also an interior node of
  // the original edge, so one pass per original edge suffices and it terminates.
  const canonList = [...canonNodes.values()].sort((p, q) =>
    p.id < q.id ? -1 : p.id > q.id ? 1 : 0,
  );
  const planarEdges = new Map<string, { a: string; b: string }>();
  const edgeKeys = [...undirected.keys()].sort();
  for (const k of edgeKeys) {
    const { a, b } = undirected.get(k)!;
    const na = canonNodes.get(a)!;
    const nb = canonNodes.get(b)!;
    const interior: { id: string; t: number }[] = [];
    for (const c of canonList) {
      if (c.id === a || c.id === b) continue;
      const t = pointOnSegment(c.x, c.z, na.x, na.z, nb.x, nb.z);
      if (t !== null) interior.push({ id: c.id, t });
    }
    if (interior.length === 0) {
      addUndirected(planarEdges, a, b);
      continue;
    }
    interior.sort((p, q) => p.t - q.t || (p.id < q.id ? -1 : p.id > q.id ? 1 : 0));
    let prev = a;
    for (const it of interior) {
      addUndirected(planarEdges, prev, it.id);
      prev = it.id;
    }
    addUndirected(planarEdges, prev, b);
  }
  if (planarEdges.size === 0) return [];

  // ── Sanitize step 2.5 (EM-283): DETECT segment×segment crossings ────────────
  // Steps 1–2 planarize coincident nodes + node-on-edge overlaps, but a morph
  // that ADDS the new topology before REMOVING the old (guaranteed mid-morph,
  // adds-before-removes) leaves two edges crossing at a NON-node point. The
  // next-by-angle walk assumes a clean planar embedding, so a transversal
  // crossing tangles a bounded face into the outer face — silently DROPPING an
  // enclosed block, or emitting a self-intersecting face whose lots sit on a
  // road (the FORBIDDEN failure). We split ONLY at existing nodes (never invent a
  // vertex), so a crossing can't be planarized here; instead DETECT any proper
  // crossing and bail the WHOLE graph to [] — the caller falls back to the grid
  // plat (EM-282). A sanctioned whole-graph [] is fine; a silent partial drop /
  // lots-on-roads is not. O(E²) over the small road-edge set; the predicate is
  // symmetric ⇒ input-order independent.
  const crossEdges = [...planarEdges.values()].map(({ a, b }) => ({
    a: canonNodes.get(a)!,
    b: canonNodes.get(b)!,
  }));
  for (let i = 0; i < crossEdges.length; i++) {
    for (let j = i + 1; j < crossEdges.length; j++) {
      if (
        segmentsProperlyCross(
          crossEdges[i].a,
          crossEdges[i].b,
          crossEdges[j].a,
          crossEdges[j].b,
        )
      ) {
        return [];
      }
    }
  }

  // Build directed half-edges + per-vertex outgoing lists.
  const outgoing = new Map<string, HalfEdge[]>();
  const addHalfEdge = (from: string, to: string): void => {
    const fn = canonNodes.get(from)!;
    const tn = canonNodes.get(to)!;
    const dx = tn.x - fn.x;
    const dz = tn.z - fn.z;
    const he: HalfEdge = {
      from,
      to,
      dx,
      dz,
      len: Math.hypot(dx, dz),
      angle: Math.atan2(dz, dx),
    };
    const list = outgoing.get(from);
    if (list) list.push(he);
    else outgoing.set(from, [he]);
  };
  for (const { a, b } of planarEdges.values()) {
    addHalfEdge(a, b);
    addHalfEdge(b, a);
  }

  // Sort each vertex's outgoing half-edges CCW by angle. Residual safety
  // (sanitize step 3): tie-break EQUAL angles by distance (nearer endpoint
  // first), then dest id, so any leftover exact tie still hugs the nearer
  // geometry. Record each half-edge's index for the prev-lookup.
  const idxInList = new Map<string, number>();
  for (const [, list] of outgoing) {
    list.sort(
      (p, q) =>
        p.angle - q.angle ||
        p.len - q.len ||
        (p.to < q.to ? -1 : p.to > q.to ? 1 : 0),
    );
    for (let i = 0; i < list.length; i++) {
      idxInList.set(heKey(list[i].from, list[i].to), i);
      // Backstop (sanitize step 4, pillar 2): if two outgoing half-edges STILL
      // point in the exact same direction after merge + split, the next-by-angle
      // walk cannot order them and would silently drop a region. Bail the WHOLE
      // graph to [] (caller falls back to the grid). A clean whole-graph [] is
      // sanctioned; a silent PARTIAL drop is not.
      if (list.length > 1 && sameDirection(list[i], list[(i + 1) % list.length])) {
        return [];
      }
    }
  }

  // next(u→v): at v, the most-clockwise turn = the entry immediately CW of the
  // reverse edge v→u (the PREVIOUS entry in v's CCW-sorted outgoing list).
  const nextOf = (he: HalfEdge): HalfEdge | null => {
    const list = outgoing.get(he.to);
    if (!list || list.length === 0) return null;
    const ti = idxInList.get(heKey(he.to, he.from));
    if (ti === undefined) return null;
    const ni = (ti - 1 + list.length) % list.length;
    return list[ni];
  };

  // Deterministic walk order: all half-edges sorted by key. Each face cycle is
  // therefore started from its globally-smallest half-edge, so the boundary
  // sequence is identical regardless of input order.
  const allHalfEdges: HalfEdge[] = [];
  for (const [, list] of outgoing) for (const he of list) allHalfEdges.push(he);
  allHalfEdges.sort((p, q) => {
    const pk = heKey(p.from, p.to);
    const qk = heKey(q.from, q.to);
    return pk < qk ? -1 : pk > qk ? 1 : 0;
  });

  const visited = new Set<string>();
  const faces: CityFace[] = [];
  const maxSteps = allHalfEdges.length + 1; // paranoia bound — next is a permutation

  for (const start of allHalfEdges) {
    if (visited.has(heKey(start.from, start.to))) continue;
    const boundary: string[] = [];
    const poly: { x: number; z: number }[] = [];
    let cur: HalfEdge | null = start;
    let steps = 0;
    while (cur) {
      const ck = heKey(cur.from, cur.to);
      if (visited.has(ck)) break; // closed the cycle (back at start)
      visited.add(ck);
      boundary.push(cur.from);
      const fn = canonNodes.get(cur.from)!;
      poly.push({ x: fn.x, z: fn.z });
      cur = nextOf(cur);
      if (++steps > maxSteps) break; // never spin (defensive; shouldn't trigger)
    }
    if (poly.length < 3) continue; // a degenerate out-and-back encloses nothing
    const area = signedArea(poly);
    // Keep ONLY positive-area (CCW) bounded faces. Outer faces of every
    // connected component come out CW (area ≤ 0) and are dropped — this is the
    // sign/winding test, not a "largest |area|" test, so disconnected graphs
    // drop each component's outer ring without ever discarding a real region.
    if (area > 0) {
      faces.push({ boundary, poly, centroid: polygonCentroid(poly, area), area });
    }
  }
  return faces;
}

// ── buildZonesFromFaces ───────────────────────────────────────────────────────

function lotHash(
  seed: number,
  faceId: string,
  gi: number,
  gj: number,
  purpose: string,
): number {
  // Mirror cityLayout's h(seed, purpose, gx, gz) seeded-hash idiom (EM-155).
  return hashUnit(`faces:${seed}:${gi}:${gj}:${faceId}:${purpose}`);
}

/** Seeded grid of lot pads inset inside a face, clipped loosely to its
 *  interior. Deterministic in (face, seed); empty is a valid result (gaps and
 *  overflow are allowed — assignBuildingLots tolerates uneven/fewer lots). */
function suggestLots(face: CityFace, seed: number, faceId: string): CityInstance[] {
  const poly = face.poly;
  if (!Array.isArray(poly) || poly.length < 3) return [];

  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const p of poly) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.z < minZ) minZ = p.z;
    if (p.z > maxZ) maxZ = p.z;
  }
  if (!Number.isFinite(minX) || !Number.isFinite(maxZ)) return [];

  const lots: CityInstance[] = [];
  // Grid lines anchored to the absolute world grid (stable across snapshots).
  const gi0 = Math.ceil(minX / LOT_PITCH);
  const gi1 = Math.floor(maxX / LOT_PITCH);
  const gj0 = Math.ceil(minZ / LOT_PITCH);
  const gj1 = Math.floor(maxZ / LOT_PITCH);
  const cx = face.centroid.x;
  const cz = face.centroid.z;

  for (let gj = gj0; gj <= gj1 && lots.length < MAX_LOTS_PER_FACE; gj++) {
    for (let gi = gi0; gi <= gi1 && lots.length < MAX_LOTS_PER_FACE; gi++) {
      const x = gi * LOT_PITCH + (lotHash(seed, faceId, gi, gj, 'jx') - 0.5) * LOT_JITTER;
      const z = gj * LOT_PITCH + (lotHash(seed, faceId, gi, gj, 'jz') - 0.5) * LOT_JITTER;
      if (!pointInPolygon(x, z, poly)) continue;
      if (distToPolygonEdges(x, z, poly) < LOT_INSET) continue;
      lots.push({ x, z, rotY: Math.atan2(cx - x, cz - z) }); // face the interior
    }
  }
  return lots;
}

/** Turn faces into buildable zones. `zoneForCentroid` is injected by the caller
 *  (computeCityPlan owns places + zoneForPlace) to avoid a cityLayout import
 *  cycle. suggestedLots are seeded via hashUnit (the EM-155 idiom), inset from
 *  the face boundary, clipped loosely to the interior.
 *
 *  EM-265 (SB): `zoneRules` (the graph's `zone_rules`, default []) are attached
 *  to each zone by id — `rule.zone_id === zone.id`. The cross-language zone id
 *  formula is IDENTICAL both sides (law §0.2), so a backend-ratified rule's
 *  `zone_id` lands on exactly the matching rendered block. Absent/empty ⇒ every
 *  `rules: []` (byte-identical to SA — the no-rules path, law §0.1). */
export function buildZonesFromFaces(
  faces: CityFace[],
  seed: number,
  zoneForCentroid: (x: number, z: number) => CityZone,
  zoneRules: ZoneRule[] = [],
): BuildZone[] {
  if (!Array.isArray(faces)) return [];
  const rules = Array.isArray(zoneRules) ? zoneRules : [];
  const out: BuildZone[] = [];
  for (const face of faces) {
    if (!face || !Array.isArray(face.boundary) || !Array.isArray(face.poly)) {
      continue; // never throw on a malformed face — just skip it
    }
    // Stable id: sorted boundary node ids joined ⇒ rotation/direction-independent.
    const id = [...face.boundary].sort().join('|');
    const zoneHint = zoneForCentroid(face.centroid.x, face.centroid.z);
    out.push({
      id,
      face,
      suggestedLots: suggestLots(face, seed, id),
      zoneHint,
      // EM-265 (SB): rules for THIS zone (matched by id). No rules ⇒ [] ⇒
      // byte-identical to SA. One rule per zone (backend last-ratified-wins).
      rules: rules.filter((r) => r.zone_id === id),
    });
  }
  return out;
}
