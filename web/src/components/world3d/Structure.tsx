/**
 * Structure — the W7 Building renderer: the "world feels real as it grows"
 * centerpiece. Renders ONE `world.buildings[]` entry near its place, BY STATUS:
 *
 *   planned            → a surveyor's stake + a roped footprint outline.
 *   under_construction → scaffolding + a structure RISING with progress (a
 *                        clock tower / garden visibly grows from 0→100); a
 *                        floating progress ring tracks `progress`.
 *   operational        → a real GLB from the EM-148 registry where one exists
 *                        (EM-150), keyed by `operationalVariant(kind)` and
 *                        mounted in <Suspense> whose fallback is the EM-122
 *                        procedural variant — while the GLB streams (or if the
 *                        registry says null: garden/library), the procedural
 *                        building stands; the scene never shows a hole.
 *                        Either path is tinted by the kind palette, SOOTED
 *                        proportionally to lost health (`healthTint` — passed
 *                        as <Model health>), and bobs/sways cheerfully.
 *   damaged            → scorched, tilted, smoking.
 *   offline            → finished but dimmed/dark (no glow, shutters).
 *   abandoned          → a half-built ruin frozen at its last progress — the
 *                        "clock tower that never got built".
 *   destroyed          → a rubble pile.
 *
 * All geometry is procedural (drei <RoundedBox>, cones, cylinders) — no external
 * assets. Materials come from the shared warm-toon cache (`toonMaterial`,
 * EM-111) so the whole village cel-shades consistently; colors are WebGL
 * material colors (THREE.Color), explicitly OUTSIDE the CSS design-token system
 * (same convention as Building/Villager/Scenery — the GPU scene owns its warm
 * palette; design-token-guard governs DOM/CSS only).
 *
 * Charming Stardew × Animal-Crossing register: rounded forms, warm tints, a
 * little life (gentle motion, a glowing window, a fluttering flag).
 */

import { useCallback, useMemo, useRef, useState, type ComponentType } from 'react';
import { useFrame } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Billboard, RoundedBox, Text, useCursor } from '@react-three/drei';
import * as THREE from 'three';
import type { Building } from '../../types';
import {
  buildingStyle,
  healthTint,
  type BuildingStyle,
  type VariantKey,
} from './worldSpace';
import { toonGradientMap, toonMaterial } from './toon';
import { Model } from './assets/Model';
import { ModelBoundary } from './ModelBoundary';
import type { ModelSpec } from './assets/models';
import {
  modelRotationY,
  resolveStructureModel,
  structureModelTint,
} from './structureModel';
import { MiniMarker } from './Building';
import { useProximity, PLACE_LABEL_DIST } from './useProximity';

interface StructureProps {
  building: Building;
  /** World position (already a satellite spot near the place). */
  x: number;
  z: number;
  /** EM-095/102: the current focus id (a place or building id), or null. */
  focusedId?: string | null;
  /** EM-095: clicked → zoom-to-place (the building's satellite spot). */
  onPick?: (buildingId: string) => void;
}

// ── Shared structural tints (wood/stone/glow — kind palettes come from
//    worldSpace.BUILDING_STYLES; these are the connective tissue) ─────────────

const WOOD = '#8a6b45';
const WOOD_DARK = '#6b4f32';
const PLANK = '#c79a5b';
const SOIL = '#7d5f3e';
const SOIL_DARK = '#6f5436';
const DOOR = '#7a5a38';
const CREAM = '#f0e7d2';
const WINDOW_GLOW = '#ffcf7a';
const WINDOW_OFF = '#3a3530';
const GHOST_OPTS = { transparent: true, opacity: 0.92 } as const;

// ── Floating label: name, kind tag, and a status/progress readout ────────────

const STATUS_TINT: Record<string, string> = {
  planned: '#bcd0ff',
  under_construction: '#ffd27f',
  operational: '#bff58a',
  damaged: '#ff9a6b',
  offline: '#9aa0a6',
  abandoned: '#c7a98a',
  destroyed: '#8a8a8a',
};

function StructureLabel({
  building,
  style,
  y,
}: {
  building: Building;
  style: BuildingStyle;
  y: number;
}) {
  const tint = STATUS_TINT[building.status] ?? '#fff3e0';
  const sub =
    building.status === 'under_construction'
      ? `${style.tag} · ${building.progress}%`
      : building.status === 'planned'
        ? `${style.tag} · planned`
        : building.status === 'abandoned'
          ? `${style.tag} · abandoned`
          : building.status === 'destroyed'
            ? `${style.tag} · destroyed`
            : building.status === 'damaged'
              ? `${style.tag} · damaged`
              : building.status === 'offline'
                ? `${style.tag} · offline`
                : `${style.tag}${building.function ? ` · ${building.function}` : ''}`;

  const w = Math.max(2.6, building.name.length * 0.32);
  return (
    <Billboard position={[0, y, 0]}>
      <mesh position={[0, 0, -0.02]}>
        <planeGeometry args={[w, 1.15]} />
        <meshBasicMaterial color="#3a2f25" transparent opacity={0.72} />
      </mesh>
      <Text
        position={[0, 0.22, 0]}
        fontSize={0.46}
        color="#fff3e0"
        anchorX="center"
        anchorY="middle"
        outlineWidth={0.014}
        outlineColor="#241b14"
        maxWidth={10}
      >
        {building.name}
      </Text>
      <Text
        position={[0, -0.28, 0]}
        fontSize={0.3}
        color={tint}
        anchorX="center"
        anchorY="middle"
        outlineWidth={0.01}
        outlineColor="#241b14"
        maxWidth={10}
      >
        {sub}
      </Text>
    </Billboard>
  );
}

// ── A horizontal progress ring that fills with `progress` (0..100) ───────────
// Built from two ring sectors: a dim full ring + a bright arc covering the
// fraction done. Floats above an under-construction site so the growth reads
// at a glance even before the geometry is tall.

function ProgressRing({ progress, y, color }: { progress: number; y: number; color: string }) {
  const frac = Math.max(0, Math.min(1, progress / 100));
  const arcRef = useRef<THREE.Mesh>(null);

  // Gentle spin so the ring feels alive while building.
  useFrame((_, delta) => {
    if (arcRef.current) arcRef.current.rotation.z -= delta * 0.6;
  });

  return (
    <group position={[0, y, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      {/* track */}
      <mesh>
        <ringGeometry args={[0.62, 0.8, 40]} />
        <meshBasicMaterial color="#5b4a36" transparent opacity={0.55} side={THREE.DoubleSide} />
      </mesh>
      {/* filled arc */}
      {frac > 0 && (
        <mesh ref={arcRef}>
          <ringGeometry args={[0.62, 0.8, 40, 1, 0, frac * Math.PI * 2]} />
          <meshBasicMaterial color={color} side={THREE.DoubleSide} />
        </mesh>
      )}
    </group>
  );
}

// ── planned: a stake + a roped footprint square ──────────────────────────────

function PlannedSite({ accent }: { accent: string }) {
  const corners: Array<[number, number]> = [
    [-1.6, -1.6],
    [1.6, -1.6],
    [1.6, 1.6],
    [-1.6, 1.6],
  ];
  return (
    <group>
      {/* cleared dirt pad */}
      <mesh position={[0, 0.02, 0]} receiveShadow material={toonMaterial('#caa873')}>
        <cylinderGeometry args={[2.0, 2.0, 0.04, 20]} />
      </mesh>
      {/* corner stakes + a string between them */}
      {corners.map(([cx, cz], i) => (
        <mesh key={i} position={[cx, 0.4, cz]} castShadow material={toonMaterial(WOOD)}>
          <cylinderGeometry args={[0.05, 0.07, 0.8, 6]} />
        </mesh>
      ))}
      {/* string lines (thin boxes between corners) */}
      {corners.map((c, i) => {
        const n = corners[(i + 1) % corners.length];
        const mx = (c[0] + n[0]) / 2;
        const mz = (c[1] + n[1]) / 2;
        const len = Math.hypot(n[0] - c[0], n[1] - c[1]);
        const rot = Math.atan2(n[1] - c[1], n[0] - c[0]);
        return (
          <mesh
            key={`s${i}`}
            position={[mx, 0.62, mz]}
            rotation={[0, -rot, 0]}
            material={toonMaterial('#e8d9b0')}
          >
            <boxGeometry args={[len, 0.015, 0.015]} />
          </mesh>
        );
      })}
      {/* surveyor's marker flag */}
      <group position={[0, 0, 0]}>
        <mesh position={[0, 0.7, 0]} castShadow material={toonMaterial(WOOD_DARK)}>
          <cylinderGeometry args={[0.05, 0.05, 1.4, 6]} />
        </mesh>
        <mesh position={[0.32, 1.2, 0]} castShadow>
          <planeGeometry args={[0.6, 0.36]} />
          {/* DoubleSide isn't a toonMaterial() cache option, so this one mesh
              gets its own (still toon-ramped) material instance. */}
          <meshToonMaterial color={accent} gradientMap={toonGradientMap()} side={THREE.DoubleSide} />
        </mesh>
      </group>
    </group>
  );
}

// ── A rising structure body whose height scales with `grow` (0..1) ───────────
// Shared by under_construction (grow = progress) and abandoned (frozen grow).

function RisingBody({
  grow,
  style,
  ghost,
}: {
  grow: number;
  style: BuildingStyle;
  ghost: boolean;
}) {
  const g = Math.max(0.06, Math.min(1, grow));
  const fullH = 3.2;
  const h = fullH * g;
  const opts = ghost ? GHOST_OPTS : {};
  return (
    <group>
      {/* foundation slab (always present once building starts) */}
      <RoundedBox
        args={[2.4, 0.3, 2.4]}
        radius={0.06}
        smoothness={2}
        position={[0, 0.15, 0]}
        castShadow
        receiveShadow
        material={toonMaterial('#b9a07e', opts)}
      />
      {/* rising walls */}
      <RoundedBox
        args={[2.0, h, 2.0]}
        radius={0.12}
        smoothness={3}
        position={[0, 0.3 + h / 2, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(ghost ? '#a89274' : style.body, opts)}
      />
      {/* a roof caps it once it's nearly topped out (and not a ghost ruin) */}
      {!ghost && g > 0.85 && (
        <mesh
          position={[0, 0.3 + h + 0.5, 0]}
          rotation={[0, Math.PI / 4, 0]}
          castShadow
          material={toonMaterial(style.roof)}
        >
          <coneGeometry args={[1.7, 1.0, 4]} />
        </mesh>
      )}
    </group>
  );
}

// ── Scaffolding poles around a construction site ─────────────────────────────

function Scaffolding({ grow }: { grow: number }) {
  const top = 0.3 + Math.max(0.06, Math.min(1, grow)) * 3.2 + 0.5;
  const corners: Array<[number, number]> = [
    [-1.25, -1.25],
    [1.25, -1.25],
    [1.25, 1.25],
    [-1.25, 1.25],
  ];
  return (
    <group>
      {corners.map(([cx, cz], i) => (
        <mesh key={i} position={[cx, top / 2, cz]} castShadow material={toonMaterial('#9c7a4d')}>
          <cylinderGeometry args={[0.06, 0.06, top, 6]} />
        </mesh>
      ))}
      {/* two horizontal scaffold planks at staggered heights */}
      {[top * 0.45, top * 0.8].map((py, i) => (
        <group key={`p${i}`}>
          <mesh position={[0, py, 1.25]} castShadow material={toonMaterial(PLANK)}>
            <boxGeometry args={[2.7, 0.07, 0.18]} />
          </mesh>
          <mesh position={[0, py, -1.25]} castShadow material={toonMaterial(PLANK)}>
            <boxGeometry args={[2.7, 0.07, 0.18]} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// ── operational (EM-122): one DISTINCT procedural mesh per variant ───────────
// All variants stay within a ~3-unit footprint (slot rings are 4.2 apart) and
// share the same props: the kind palette plus health-tinted body/roof hexes
// (a half-burned building reads scorched before it ever flips to `damaged`)
// and the offline flag (which kills every glow).

interface VariantProps {
  style: BuildingStyle;
  /** style.body after healthTint — soots toward charcoal as health drops. */
  body: string;
  /** style.roof after healthTint. */
  roof: string;
  offline: boolean;
}

/** A flush, glowing wall window (dark and unlit when offline). */
function GlowWindow({
  position,
  size = [0.5, 0.6],
  rotation,
  offline,
}: {
  position: [number, number, number];
  size?: [number, number];
  rotation?: [number, number, number];
  offline: boolean;
}) {
  const mat = offline
    ? toonMaterial(WINDOW_OFF)
    : toonMaterial(WINDOW_GLOW, { emissive: WINDOW_GLOW, emissiveIntensity: 0.6 });
  return (
    <mesh position={position} rotation={rotation} material={mat}>
      <planeGeometry args={size} />
    </mesh>
  );
}

// garden: a raised planting bed with leafy rows, glowing blooms, a rose pole.

function GardenStructure({ style, body, roof, offline }: VariantProps) {
  const leaf = toonMaterial(body);
  const leafDark = toonMaterial(roof);
  const bloom = toonMaterial(style.accent, {
    emissive: style.accent,
    emissiveIntensity: offline ? 0 : 0.35,
  });
  const cells: Array<[number, number]> = [];
  for (const rz of [-0.7, 0, 0.7]) for (const rx of [-0.8, 0, 0.8]) cells.push([rx, rz]);
  return (
    <group>
      {/* raised-bed timber frame + soil fill */}
      <RoundedBox
        args={[2.7, 0.3, 2.3]}
        radius={0.06}
        smoothness={2}
        position={[0, 0.15, 0]}
        castShadow
        receiveShadow
        material={toonMaterial('#9c7a4d')}
      />
      <mesh position={[0, 0.32, 0]} receiveShadow material={toonMaterial(SOIL)}>
        <boxGeometry args={[2.45, 0.08, 2.05]} />
      </mesh>
      {/* three planted rows: leafy mounds, alternating with blooms on top */}
      {cells.map(([cx, cz], i) => (
        <group key={i} position={[cx, 0, cz]}>
          <mesh position={[0, 0.52, 0]} castShadow material={i % 2 ? leafDark : leaf}>
            <sphereGeometry args={[0.26, 10, 10]} />
          </mesh>
          {i % 2 === 0 && (
            <mesh position={[0, 0.78, 0]} castShadow material={bloom}>
              <sphereGeometry args={[0.1, 8, 8]} />
            </mesh>
          )}
        </group>
      ))}
      {/* corner rose pole */}
      <group position={[1.15, 0, 1.0]}>
        <mesh position={[0, 0.7, 0]} castShadow material={toonMaterial(WOOD_DARK)}>
          <cylinderGeometry args={[0.04, 0.05, 1.4, 6]} />
        </mesh>
        <mesh position={[0, 1.45, 0]} castShadow material={bloom}>
          <sphereGeometry args={[0.14, 8, 8]} />
        </mesh>
      </group>
    </group>
  );
}

// farm: a fenced, tilled plot with crop rows and a haystack.

function FarmStructure({ body, roof }: VariantProps) {
  const crop = toonMaterial(body);
  const strips = [-0.9, -0.3, 0.3, 0.9];
  return (
    <group>
      {/* tilled plot: base + alternating furrow strips */}
      <mesh position={[0, 0.06, 0]} receiveShadow material={toonMaterial(SOIL_DARK)}>
        <boxGeometry args={[2.8, 0.12, 2.4]} />
      </mesh>
      {strips.map((sz, i) => (
        <mesh
          key={i}
          position={[0, 0.14, sz]}
          receiveShadow
          material={toonMaterial(i % 2 ? SOIL : SOIL_DARK)}
        >
          <boxGeometry args={[2.6, 0.08, 0.34]} />
        </mesh>
      ))}
      {/* crop sprouts on the raised furrows */}
      {strips
        .filter((_, i) => i % 2 === 1)
        .map((sz) =>
          [-0.9, -0.3, 0.3, 0.9].map((sx) => (
            <mesh key={`${sx}:${sz}`} position={[sx, 0.38, sz]} castShadow material={crop}>
              <coneGeometry args={[0.1, 0.4, 6]} />
            </mesh>
          )),
        )}
      {/* low perimeter fence: corner+mid posts and rails */}
      {(
        [
          [-1.4, -1.2], [0, -1.2], [1.4, -1.2],
          [-1.4, 1.2], [0, 1.2], [1.4, 1.2],
          [-1.4, 0], [1.4, 0],
        ] as Array<[number, number]>
      ).map(([px, pz], i) => (
        <mesh key={i} position={[px, 0.3, pz]} castShadow material={toonMaterial(WOOD)}>
          <cylinderGeometry args={[0.05, 0.06, 0.6, 6]} />
        </mesh>
      ))}
      {[-1.2, 1.2].map((rz) => (
        <mesh key={`rx${rz}`} position={[0, 0.46, rz]} castShadow material={toonMaterial(PLANK)}>
          <boxGeometry args={[2.8, 0.05, 0.06]} />
        </mesh>
      ))}
      {[-1.4, 1.4].map((rx) => (
        <mesh key={`rz${rx}`} position={[rx, 0.46, 0]} castShadow material={toonMaterial(PLANK)}>
          <boxGeometry args={[0.06, 0.05, 2.4]} />
        </mesh>
      ))}
      {/* a golden haystack in the corner */}
      <mesh position={[-1.05, 0.38, -0.9]} castShadow material={toonMaterial(roof)}>
        <coneGeometry args={[0.32, 0.55, 7]} />
      </mesh>
    </group>
  );
}

// workshop: a squat shed with a slanted roof, an ember-lit chimney, and a
// workbench with an anvil outside.

function WorkshopStructure({ body, roof, offline }: VariantProps) {
  return (
    <group>
      <RoundedBox
        args={[2.2, 1.7, 2.0]}
        radius={0.14}
        smoothness={3}
        position={[0, 0.95, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      {/* slanted plank roof */}
      <mesh
        position={[0, 1.95, 0]}
        rotation={[0, 0, 0.1]}
        castShadow
        material={toonMaterial(roof)}
      >
        <boxGeometry args={[2.5, 0.16, 2.3]} />
      </mesh>
      {/* brick chimney + ember glow */}
      <mesh position={[-0.75, 2.15, -0.45]} castShadow material={toonMaterial('#8a5a48')}>
        <boxGeometry args={[0.34, 1.1, 0.34]} />
      </mesh>
      <mesh
        position={[-0.75, 2.74, -0.45]}
        material={
          offline
            ? toonMaterial(WINDOW_OFF)
            : toonMaterial('#ff9a5a', { emissive: '#ff7a3a', emissiveIntensity: 0.8 })
        }
      >
        <boxGeometry args={[0.26, 0.1, 0.26]} />
      </mesh>
      {/* wide work door + window */}
      <mesh position={[-0.4, 0.65, 1.02]} material={toonMaterial(DOOR)}>
        <planeGeometry args={[0.65, 1.1]} />
      </mesh>
      <GlowWindow position={[0.55, 1.05, 1.02]} size={[0.45, 0.5]} offline={offline} />
      {/* workbench + anvil at the side */}
      <group position={[1.25, 0, 0.45]}>
        <mesh position={[0, 0.46, 0]} castShadow material={toonMaterial(PLANK)}>
          <boxGeometry args={[0.55, 0.07, 0.42]} />
        </mesh>
        {([-0.2, 0.2] as const).map((lx) => (
          <mesh key={lx} position={[lx, 0.21, 0]} material={toonMaterial(WOOD_DARK)}>
            <boxGeometry args={[0.07, 0.42, 0.36]} />
          </mesh>
        ))}
        <mesh position={[0, 0.59, 0]} castShadow material={toonMaterial('#5a5a60')}>
          <boxGeometry args={[0.24, 0.18, 0.14]} />
        </mesh>
      </group>
    </group>
  );
}

/** Facade book-spine tints (warm library shelf, reused per spine index). */
const SPINE_COLORS = ['#b55b5b', '#5b7ab5', '#6f9a5a', '#c98b3a', '#7b6cf6'];

// library: a wide hall behind a columned portico, with a band of giant book
// spines along the facade.

function LibraryStructure({ body, roof, offline }: VariantProps) {
  return (
    <group>
      {/* portico step */}
      <mesh position={[0, 0.08, 1.15]} receiveShadow material={toonMaterial('#cfc4ad')}>
        <boxGeometry args={[2.4, 0.16, 0.6]} />
      </mesh>
      {/* main hall */}
      <RoundedBox
        args={[2.6, 2.2, 1.9]}
        radius={0.14}
        smoothness={3}
        position={[0, 1.2, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      {/* four columns + lintel */}
      {[-0.95, -0.35, 0.35, 0.95].map((cx) => (
        <mesh key={cx} position={[cx, 0.85, 1.25]} castShadow material={toonMaterial(CREAM)}>
          <cylinderGeometry args={[0.09, 0.11, 1.5, 8]} />
        </mesh>
      ))}
      <mesh position={[0, 1.7, 1.25]} castShadow material={toonMaterial(CREAM)}>
        <boxGeometry args={[2.4, 0.22, 0.4]} />
      </mesh>
      {/* shallow pediment roof */}
      <mesh
        position={[0, 2.75, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
        material={toonMaterial(roof)}
      >
        <coneGeometry args={[2.0, 0.9, 4]} />
      </mesh>
      {/* book-spine band along the facade, behind the columns */}
      {[-0.62, -0.38, -0.14, 0.1, 0.34, 0.58].map((sx, i) => (
        <mesh
          key={i}
          position={[sx, 0.95, 0.97]}
          material={toonMaterial(SPINE_COLORS[i % SPINE_COLORS.length])}
        >
          <boxGeometry args={[0.18, 0.5 + (i % 3) * 0.06, 0.05]} />
        </mesh>
      ))}
      {/* a reading-lamp window on the side wall */}
      <GlowWindow
        position={[1.31, 1.5, 0]}
        rotation={[0, Math.PI / 2, 0]}
        size={[0.5, 0.55]}
        offline={offline}
      />
    </group>
  );
}

// clocktower: the existing tall body, clock face + sweeping hand, spire,
// pennant — preserved from the pre-EM-122 tower flourish.

function ClocktowerStructure({ style, body, roof, offline }: VariantProps) {
  const handRef = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (handRef.current) handRef.current.rotation.z -= delta * 0.5;
  });
  return (
    <group>
      <RoundedBox
        args={[2.4, 3.4, 2.4]}
        radius={0.16}
        smoothness={3}
        position={[0, 1.8, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      <mesh
        position={[0, 4.0, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
        material={toonMaterial(roof)}
      >
        <coneGeometry args={[1.9, 1.2, 4]} />
      </mesh>
      <GlowWindow position={[0.7, 1.0, 1.22]} offline={offline} />
      <mesh position={[-0.2, 0.7, 1.22]} material={toonMaterial(DOOR)}>
        <planeGeometry args={[0.6, 1.2]} />
      </mesh>
      {/* clock face + sweeping hand */}
      <mesh position={[0, 2.9, 1.22]} material={toonMaterial('#fff8e7')}>
        <circleGeometry args={[0.42, 24]} />
      </mesh>
      <group ref={handRef} position={[0, 2.9, 1.24]}>
        <mesh position={[0, 0.16, 0]} material={toonMaterial('#3a2f25')}>
          <boxGeometry args={[0.04, 0.32, 0.02]} />
        </mesh>
      </group>
      <mesh position={[0, 4.3, 0]} castShadow material={toonMaterial(style.accent)}>
        <coneGeometry args={[0.5, 0.9, 4]} />
      </mesh>
      {/* cheerful pennant */}
      <mesh position={[0.9, 4.3, 0]}>
        <planeGeometry args={[0.5, 0.3]} />
        <meshToonMaterial
          color={style.accent}
          gradientMap={toonGradientMap()}
          side={THREE.DoubleSide}
        />
      </mesh>
    </group>
  );
}

// house: a cozy cottage — chimney, flower box under a lit window, front step.

function HouseStructure({ style, body, roof, offline }: VariantProps) {
  const bloom = toonMaterial(style.accent, {
    emissive: style.accent,
    emissiveIntensity: offline ? 0 : 0.3,
  });
  return (
    <group>
      <RoundedBox
        args={[2.2, 1.9, 2.1]}
        radius={0.16}
        smoothness={3}
        position={[0, 1.05, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      <mesh
        position={[0, 2.55, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
        material={toonMaterial(roof)}
      >
        <coneGeometry args={[1.8, 1.1, 4]} />
      </mesh>
      {/* chimney */}
      <mesh position={[0.65, 2.6, -0.35]} castShadow material={toonMaterial('#a8765a')}>
        <boxGeometry args={[0.3, 0.9, 0.3]} />
      </mesh>
      {/* door + step */}
      <mesh position={[-0.35, 0.62, 1.07]} material={toonMaterial(DOOR)}>
        <planeGeometry args={[0.55, 1.05]} />
      </mesh>
      <mesh position={[-0.35, 0.06, 1.25]} receiveShadow material={toonMaterial('#cfc4ad')}>
        <boxGeometry args={[0.7, 0.12, 0.4]} />
      </mesh>
      {/* lit window with a flower box */}
      <GlowWindow position={[0.55, 1.2, 1.07]} size={[0.45, 0.5]} offline={offline} />
      <mesh position={[0.55, 0.88, 1.12]} castShadow material={toonMaterial(WOOD)}>
        <boxGeometry args={[0.55, 0.1, 0.12]} />
      </mesh>
      {[0.42, 0.68].map((fx) => (
        <mesh key={fx} position={[fx, 0.98, 1.12]} material={bloom}>
          <sphereGeometry args={[0.08, 8, 8]} />
        </mesh>
      ))}
    </group>
  );
}

// stall: an open-air market counter under a striped awning, crates beside it.

function StallStructure({ style, body, roof, offline }: VariantProps) {
  const produce = [toonMaterial(roof), toonMaterial(style.accent), toonMaterial('#d96a4a')];
  return (
    <group>
      {/* counter */}
      <RoundedBox
        args={[2.2, 0.85, 1.3]}
        radius={0.1}
        smoothness={2}
        position={[0, 0.52, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      {/* corner posts */}
      {(
        [
          [-1.0, -0.55], [1.0, -0.55], [-1.0, 0.55], [1.0, 0.55],
        ] as Array<[number, number]>
      ).map(([px, pz], i) => (
        <mesh key={i} position={[px, 1.0, pz]} castShadow material={toonMaterial(WOOD_DARK)}>
          <cylinderGeometry args={[0.06, 0.06, 2.0, 6]} />
        </mesh>
      ))}
      {/* striped awning, sloped toward the front */}
      <group position={[0, 2.05, 0.1]} rotation={[0.18, 0, 0]}>
        {[-0.88, -0.44, 0, 0.44, 0.88].map((ax, i) => (
          <mesh
            key={i}
            castShadow
            position={[ax, 0, 0]}
            material={toonMaterial(i % 2 ? '#fff6e3' : style.accent)}
          >
            <boxGeometry args={[0.44, 0.05, 1.7]} />
          </mesh>
        ))}
      </group>
      {/* produce on the counter (a lantern-warm sheen while open) */}
      {[-0.5, 0, 0.5].map((gx, i) => (
        <mesh key={i} position={[gx, 1.05, 0.15]} castShadow material={produce[i]}>
          <sphereGeometry args={[0.14, 10, 10]} />
        </mesh>
      ))}
      {/* a lantern hanging from the awning edge (dark when offline) */}
      <mesh
        position={[0.95, 1.65, 0.85]}
        material={
          offline
            ? toonMaterial(WINDOW_OFF)
            : toonMaterial(WINDOW_GLOW, { emissive: WINDOW_GLOW, emissiveIntensity: 0.7 })
        }
      >
        <sphereGeometry args={[0.1, 8, 8]} />
      </mesh>
      {/* stacked crates */}
      <mesh position={[-1.15, 0.21, 0.9]} castShadow material={toonMaterial(PLANK)}>
        <boxGeometry args={[0.42, 0.42, 0.42]} />
      </mesh>
      <mesh
        position={[-1.15, 0.58, 0.9]}
        rotation={[0, 0.4, 0]}
        castShadow
        material={toonMaterial(WOOD)}
      >
        <boxGeometry args={[0.34, 0.34, 0.34]} />
      </mesh>
    </group>
  );
}

// monument: a stepped plinth + tapered obelisk; commemorative cap & plaque
// keep their warm glow (extinguished when offline).

function MonumentStructure({ style, body, offline }: VariantProps) {
  const glowOpts = offline ? {} : { emissive: '#ffd9a0', emissiveIntensity: 0.7 };
  return (
    <group>
      {/* stepped plinth */}
      <mesh position={[0, 0.14, 0]} castShadow receiveShadow material={toonMaterial(body)}>
        <boxGeometry args={[2.4, 0.28, 2.4]} />
      </mesh>
      <mesh position={[0, 0.42, 0]} castShadow receiveShadow material={toonMaterial(body)}>
        <boxGeometry args={[1.8, 0.28, 1.8]} />
      </mesh>
      {/* tapered four-sided obelisk */}
      <mesh
        position={[0, 1.86, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
        material={toonMaterial(body)}
      >
        <cylinderGeometry args={[0.2, 0.46, 2.6, 4]} />
      </mesh>
      {/* glowing commemorative cap */}
      <mesh
        position={[0, 3.38, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
        material={toonMaterial(style.accent, glowOpts)}
      >
        <coneGeometry args={[0.32, 0.45, 4]} />
      </mesh>
      {/* inscription plaque */}
      <mesh
        position={[0, 0.75, 0.92]}
        material={toonMaterial(
          '#fff3e0',
          offline ? {} : { emissive: '#ffd9a0', emissiveIntensity: 0.35 },
        )}
      >
        <boxGeometry args={[0.5, 0.35, 0.05]} />
      </mesh>
    </group>
  );
}

// well: a stone ring with water, two posts carrying a little pitched roof,
// and a bucket on a rope.

function WellStructure({ body, roof, offline }: VariantProps) {
  return (
    <group>
      {/* cobble apron */}
      <mesh position={[0, 0.04, 0]} receiveShadow material={toonMaterial('#7e766a')}>
        <cylinderGeometry args={[1.15, 1.25, 0.08, 16]} />
      </mesh>
      {/* stone ring + water */}
      <mesh position={[0, 0.34, 0]} castShadow receiveShadow material={toonMaterial(body)}>
        <cylinderGeometry args={[0.75, 0.82, 0.6, 12]} />
      </mesh>
      <mesh
        position={[0, 0.62, 0]}
        material={toonMaterial(
          '#4a7a8c',
          offline ? {} : { emissive: '#2f5a6e', emissiveIntensity: 0.25 },
        )}
      >
        <cylinderGeometry args={[0.58, 0.58, 0.06, 12]} />
      </mesh>
      {/* posts + crossbeam */}
      {[-0.78, 0.78].map((px) => (
        <mesh key={px} position={[px, 0.75, 0]} castShadow material={toonMaterial(WOOD_DARK)}>
          <boxGeometry args={[0.09, 1.5, 0.09]} />
        </mesh>
      ))}
      <mesh position={[0, 1.52, 0]} rotation={[0, 0, Math.PI / 2]} material={toonMaterial(WOOD)}>
        <cylinderGeometry args={[0.045, 0.045, 1.7, 6]} />
      </mesh>
      {/* rope + bucket */}
      <mesh position={[0, 1.31, 0]} material={toonMaterial('#e8d9b0')}>
        <boxGeometry args={[0.025, 0.42, 0.025]} />
      </mesh>
      <mesh position={[0, 1.06, 0]} castShadow material={toonMaterial(WOOD)}>
        <cylinderGeometry args={[0.13, 0.1, 0.2, 8]} />
      </mesh>
      {/* little pitched roof */}
      <mesh
        position={[0, 1.95, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
        material={toonMaterial(roof)}
      >
        <coneGeometry args={[1.05, 0.65, 4]} />
      </mesh>
    </group>
  );
}

// generic: the pre-EM-122 neutral structure, kept as the fallback silhouette.

function GenericStructure({ style, body, roof, offline }: VariantProps) {
  return (
    <group>
      <RoundedBox
        args={[2.4, 2.2, 2.4]}
        radius={0.16}
        smoothness={3}
        position={[0, 1.2, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      <mesh
        position={[0, 2.8, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
        material={toonMaterial(roof)}
      >
        <coneGeometry args={[1.9, 1.2, 4]} />
      </mesh>
      <GlowWindow position={[0.7, 1.0, 1.22]} offline={offline} />
      <mesh position={[-0.2, 0.7, 1.22]} material={toonMaterial(DOOR)}>
        <planeGeometry args={[0.6, 1.2]} />
      </mesh>
      {/* a cheerful pennant on top, fluttering via the operational bob group */}
      <mesh position={[0.9, 3.1, 0]}>
        <planeGeometry args={[0.5, 0.3]} />
        <meshToonMaterial
          color={style.accent}
          gradientMap={toonGradientMap()}
          side={THREE.DoubleSide}
        />
      </mesh>
    </group>
  );
}

const VARIANT_COMPONENTS: Record<VariantKey, ComponentType<VariantProps>> = {
  garden: GardenStructure,
  farm: FarmStructure,
  workshop: WorkshopStructure,
  library: LibraryStructure,
  clocktower: ClocktowerStructure,
  house: HouseStructure,
  stall: StallStructure,
  monument: MonumentStructure,
  well: WellStructure,
  generic: GenericStructure,
};

function OperationalStructure({
  style,
  variant,
  spec,
  offline,
  health,
}: {
  style: BuildingStyle;
  /** EM-122 silhouette — the render when spec is null AND the Suspense fallback. */
  variant: VariantKey;
  /** EM-150: the registry GLB for this variant, or null = stay procedural. */
  spec: ModelSpec | null;
  offline: boolean;
  health: number;
}) {
  const Variant = VARIANT_COMPONENTS[variant];
  const procedural = (
    <Variant
      style={style}
      body={healthTint(style.body, health)}
      roof={healthTint(style.roof, health)}
      offline={offline}
    />
  );
  if (!spec) return procedural;
  return (
    // Fallback invariant (contract rule 7): while the GLB streams — or if it
    // FAILS to load — the EM-122 procedural variant stands in (ModelBoundary
    // is Suspense + an error boundary; a bare Suspense doesn't catch loader
    // rejections and would unmount the canvas).
    <ModelBoundary fallback={procedural}>
      <Model
        spec={spec}
        health={health}
        tint={structureModelTint(offline)}
        rotation-y={modelRotationY(variant)}
      />
    </ModelBoundary>
  );
}

// ── damaged: a scorched, tilted finished structure with smoke ────────────────

function DamagedStructure({ style }: { style: BuildingStyle }) {
  const smokeRef = useRef<THREE.Mesh>(null);
  useFrame((_, delta) => {
    if (smokeRef.current) {
      smokeRef.current.position.y += delta * 0.25;
      if (smokeRef.current.position.y > 4.2) smokeRef.current.position.y = 2.6;
      const s = 0.4 + (smokeRef.current.position.y - 2.6) * 0.2;
      smokeRef.current.scale.setScalar(s);
    }
  });
  return (
    <group rotation={[0.06, 0, -0.05]}>
      <RoundedBox
        args={[2.4, 2.0, 2.4]}
        radius={0.16}
        smoothness={3}
        position={[0, 1.1, 0]}
        castShadow
        receiveShadow
        /* darkened, sooty body */
        material={toonMaterial(style.body, { emissive: '#1a0f08', emissiveIntensity: 0.6 })}
      />
      {/* broken roof stub */}
      <mesh
        position={[0.2, 2.3, 0]}
        rotation={[0.2, Math.PI / 4, 0.15]}
        castShadow
        material={toonMaterial('#4a3a2c')}
      >
        <coneGeometry args={[1.6, 0.9, 4]} />
      </mesh>
      {/* scorch scar */}
      <mesh
        position={[0, 1.1, 1.22]}
        material={toonMaterial('#241712', { transparent: true, opacity: 0.7 })}
      >
        <planeGeometry args={[1.4, 1.4]} />
      </mesh>
      {/* drifting smoke puff */}
      <mesh
        ref={smokeRef}
        position={[0.4, 2.6, 0.2]}
        material={toonMaterial('#3a3a3a', { transparent: true, opacity: 0.45 })}
      >
        <sphereGeometry args={[0.4, 10, 10]} />
      </mesh>
    </group>
  );
}

// ── destroyed: a rubble pile ─────────────────────────────────────────────────

function RubblePile() {
  const chunks: Array<[number, number, number, number]> = [
    [-0.6, 0.25, 0.4, 0.5],
    [0.5, 0.2, -0.3, 0.42],
    [0.1, 0.3, 0.6, 0.55],
    [-0.3, 0.18, -0.6, 0.36],
    [0.7, 0.22, 0.5, 0.4],
    [0, 0.34, 0, 0.6],
  ];
  return (
    <group>
      <mesh position={[0, 0.03, 0]} receiveShadow material={toonMaterial('#7a6a52')}>
        <cylinderGeometry args={[1.8, 1.8, 0.06, 18]} />
      </mesh>
      {chunks.map(([cx, cy, cz, s], i) => (
        <mesh
          key={i}
          position={[cx, cy, cz]}
          rotation={[i * 0.7, i * 1.1, i * 0.5]}
          castShadow
          receiveShadow
          material={toonMaterial(i % 2 ? '#9a8a72' : '#83735c')}
        >
          <boxGeometry args={[s, s * 0.8, s * 0.9]} />
        </mesh>
      ))}
    </group>
  );
}

/** Label clearance per operational variant (matches each silhouette's height). */
const OPERATIONAL_LABEL_Y: Record<VariantKey, number> = {
  clocktower: 5.4,
  monument: 5.0,
  library: 4.2,
  generic: 4.0,
  house: 3.8,
  workshop: 3.6,
  well: 3.4,
  stall: 3.2,
  farm: 2.4,
  garden: 2.6,
};

/**
 * EM-150: label clearance overrides for variants whose GLB stands TALLER than
 * the procedural silhouette (measured scaled AABB heights: windmill 3.35,
 * Kenney stall 2.85 — both poke through their old label heights). Variants
 * absent here keep OPERATIONAL_LABEL_Y, which already clears both meshes.
 */
const GLB_LABEL_Y: Partial<Record<VariantKey, number>> = {
  farm: 4.4,
  stall: 3.9,
};

export function Structure({ building, x, z, focusedId, onPick }: StructureProps) {
  const style = useMemo(() => buildingStyle(building.kind), [building.kind]);
  const { variant, spec } = useMemo(
    () => resolveStructureModel(building.kind),
    [building.kind],
  );
  const bobRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && Boolean(onPick));

  // EM-102: full label only when near / hovered / the camera-focus target
  // (EM-095 zoom-to-place reveals it). Far away → a small status-tinted marker.
  const near = useProximity(useCallback(() => ({ x, z }), [x, z]), PLACE_LABEL_DIST);
  const showFull = near || hovered || focusedId === building.id;

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!onPick) return;
    e.stopPropagation();
    onPick(building.id);
  };

  // Operational structures get a gentle, cheerful sway (Animal-Crossing life).
  const bobPhase = useRef(Math.random() * Math.PI * 2);
  useFrame((_, delta) => {
    const g = bobRef.current;
    if (!g) return;
    if (building.status === 'operational') {
      bobPhase.current += delta * 1.6;
      g.position.y = Math.sin(bobPhase.current) * 0.04;
      g.rotation.z = Math.sin(bobPhase.current * 0.5) * 0.012;
    } else {
      g.position.y = 0;
      g.rotation.z = 0;
    }
  });

  const grow = building.progress / 100;

  // Label height tuned per status (and per variant) so it clears the geometry.
  const labelY =
    building.status === 'operational' || building.status === 'offline'
      ? (spec ? GLB_LABEL_Y[variant] : undefined) ?? OPERATIONAL_LABEL_Y[variant]
      : building.status === 'under_construction'
        ? 0.6 + grow * 3.4 + 1.4
        : building.status === 'destroyed' || building.status === 'planned'
          ? 2.0
          : 3.6;

  return (
    <group
      position={[x, 0, z]}
      onClick={handleClick}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
      <group ref={bobRef}>
        {building.status === 'planned' && <PlannedSite accent={style.accent} />}

        {building.status === 'under_construction' && (
          <>
            <RisingBody grow={grow} style={style} ghost={false} />
            <Scaffolding grow={grow} />
            <ProgressRing
              progress={building.progress}
              y={0.6 + grow * 3.4 + 0.8}
              color={style.accent}
            />
          </>
        )}

        {(building.status === 'operational' || building.status === 'offline') && (
          <OperationalStructure
            style={style}
            variant={variant}
            spec={spec}
            offline={building.status === 'offline'}
            health={building.health}
          />
        )}

        {building.status === 'damaged' && <DamagedStructure style={style} />}

        {building.status === 'abandoned' && (
          <>
            {/* a half-built ruin frozen at its last progress — desaturated, no
                scaffolding (workers left), overgrown with a weed or two. */}
            <RisingBody grow={Math.max(0.18, grow)} style={style} ghost />
            <mesh position={[1.2, 0.4, 1.0]} castShadow material={toonMaterial('#6f8f5a')}>
              <coneGeometry args={[0.2, 0.7, 5]} />
            </mesh>
            <mesh position={[-1.0, 0.35, -1.1]} castShadow material={toonMaterial('#7a9a63')}>
              <coneGeometry args={[0.18, 0.6, 5]} />
            </mesh>
          </>
        )}

        {building.status === 'destroyed' && <RubblePile />}
      </group>

      {showFull ? (
        <StructureLabel building={building} style={style} y={labelY} />
      ) : (
        <MiniMarker y={labelY} color={STATUS_TINT[building.status] ?? style.accent} />
      )}
    </group>
  );
}
