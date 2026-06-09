/**
 * Structure — the W7 Building renderer: the "world feels real as it grows"
 * centerpiece. Renders ONE `world.buildings[]` entry near its place, BY STATUS:
 *
 *   planned            → a surveyor's stake + a roped footprint outline.
 *   under_construction → scaffolding + a structure RISING with progress (a
 *                        clock tower / garden visibly grows from 0→100); a
 *                        floating progress ring tracks `progress`.
 *   operational        → the finished structure, tinted by `kind`, with a
 *                        cheerful bob/sway (clock hand sweep, garden shimmer).
 *   damaged            → scorched, tilted, smoking.
 *   offline            → finished but dimmed/dark (no glow, shutters).
 *   abandoned          → a half-built ruin frozen at its last progress — the
 *                        "clock tower that never got built".
 *   destroyed          → a rubble pile.
 *
 * All geometry is procedural (drei <RoundedBox>, cones, cylinders) — no external
 * assets. Colors are WebGL material colors (THREE.Color), explicitly OUTSIDE the
 * CSS design-token system (same convention as Building/Villager/Scenery — the
 * GPU scene owns its warm palette; design-token-guard governs DOM/CSS only).
 *
 * Charming Stardew × Animal-Crossing register: rounded forms, warm tints, a
 * little life (gentle motion, a glowing window, a fluttering flag).
 */

import { useCallback, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Billboard, RoundedBox, Text, useCursor } from '@react-three/drei';
import * as THREE from 'three';
import type { Building } from '../../types';
import { buildingStyle, type BuildingStyle } from './worldSpace';
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
      <mesh position={[0, 0.02, 0]} receiveShadow>
        <cylinderGeometry args={[2.0, 2.0, 0.04, 20]} />
        <meshStandardMaterial color="#caa873" roughness={1} />
      </mesh>
      {/* corner stakes + a string between them */}
      {corners.map(([cx, cz], i) => (
        <mesh key={i} position={[cx, 0.4, cz]} castShadow>
          <cylinderGeometry args={[0.05, 0.07, 0.8, 6]} />
          <meshStandardMaterial color="#8a6b45" roughness={1} />
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
          <mesh key={`s${i}`} position={[mx, 0.62, mz]} rotation={[0, -rot, 0]}>
            <boxGeometry args={[len, 0.015, 0.015]} />
            <meshStandardMaterial color="#e8d9b0" roughness={1} />
          </mesh>
        );
      })}
      {/* surveyor's marker flag */}
      <group position={[0, 0, 0]}>
        <mesh position={[0, 0.7, 0]} castShadow>
          <cylinderGeometry args={[0.05, 0.05, 1.4, 6]} />
          <meshStandardMaterial color="#6b4f32" roughness={1} />
        </mesh>
        <mesh position={[0.32, 1.2, 0]} castShadow>
          <planeGeometry args={[0.6, 0.36]} />
          <meshStandardMaterial color={accent} roughness={0.7} side={THREE.DoubleSide} />
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
  const op = ghost ? 0.92 : 1;
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
      >
        <meshStandardMaterial color="#b9a07e" roughness={1} transparent={ghost} opacity={op} />
      </RoundedBox>
      {/* rising walls */}
      <RoundedBox
        args={[2.0, h, 2.0]}
        radius={0.12}
        smoothness={3}
        position={[0, 0.3 + h / 2, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial
          color={ghost ? '#a89274' : style.body}
          roughness={0.9}
          transparent={ghost}
          opacity={op}
        />
      </RoundedBox>
      {/* a roof caps it once it's nearly topped out (and not a ghost ruin) */}
      {!ghost && g > 0.85 && (
        <mesh position={[0, 0.3 + h + 0.5, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
          <coneGeometry args={[1.7, 1.0, 4]} />
          <meshStandardMaterial color={style.roof} roughness={0.85} />
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
        <mesh key={i} position={[cx, top / 2, cz]} castShadow>
          <cylinderGeometry args={[0.06, 0.06, top, 6]} />
          <meshStandardMaterial color="#9c7a4d" roughness={1} />
        </mesh>
      ))}
      {/* two horizontal scaffold planks at staggered heights */}
      {[top * 0.45, top * 0.8].map((py, i) => (
        <group key={`p${i}`}>
          <mesh position={[0, py, 1.25]} castShadow>
            <boxGeometry args={[2.7, 0.07, 0.18]} />
            <meshStandardMaterial color="#c79a5b" roughness={1} />
          </mesh>
          <mesh position={[0, py, -1.25]} castShadow>
            <boxGeometry args={[2.7, 0.07, 0.18]} />
            <meshStandardMaterial color="#c79a5b" roughness={1} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// ── operational: finished structure, tinted by kind, with a touch of life ────

function OperationalStructure({
  style,
  kind,
  offline,
}: {
  style: BuildingStyle;
  kind: string;
  offline: boolean;
}) {
  const handRef = useRef<THREE.Group>(null);
  const isTower = kind === 'clocktower' || kind === 'monument';

  useFrame((_, delta) => {
    if (handRef.current) handRef.current.rotation.z -= delta * 0.5;
  });

  const windowGlow = offline ? '#3a3530' : '#ffcf7a';
  const windowEmissive = offline ? 0 : 0.6;

  return (
    <group>
      {/* main body */}
      <RoundedBox
        args={[2.4, isTower ? 3.4 : 2.2, 2.4]}
        radius={0.16}
        smoothness={3}
        position={[0, (isTower ? 3.4 : 2.2) / 2 + 0.1, 0]}
        castShadow
        receiveShadow
      >
        <meshStandardMaterial color={style.body} roughness={0.9} />
      </RoundedBox>

      {/* pitched roof */}
      <mesh
        position={[0, (isTower ? 3.4 : 2.2) + 0.6, 0]}
        rotation={[0, Math.PI / 4, 0]}
        castShadow
      >
        <coneGeometry args={[1.9, 1.2, 4]} />
        <meshStandardMaterial color={style.roof} roughness={0.85} />
      </mesh>

      {/* glowing door-side window (dark when offline) */}
      <mesh position={[0.7, 1.0, 1.22]}>
        <planeGeometry args={[0.5, 0.6]} />
        <meshStandardMaterial
          color={windowGlow}
          emissive={windowGlow}
          emissiveIntensity={windowEmissive}
          roughness={0.5}
        />
      </mesh>
      {/* door */}
      <mesh position={[-0.2, 0.7, 1.22]}>
        <planeGeometry args={[0.6, 1.2]} />
        <meshStandardMaterial color="#7a5a38" roughness={1} />
      </mesh>

      {/* clock tower flourish: a face + sweeping hand */}
      {kind === 'clocktower' && (
        <>
          <mesh position={[0, 2.9, 1.22]}>
            <circleGeometry args={[0.42, 24]} />
            <meshStandardMaterial color="#fff8e7" roughness={0.5} />
          </mesh>
          <group ref={handRef} position={[0, 2.9, 1.24]}>
            <mesh position={[0, 0.16, 0]}>
              <boxGeometry args={[0.04, 0.32, 0.02]} />
              <meshStandardMaterial color="#3a2f25" />
            </mesh>
          </group>
          <mesh position={[0, 4.3, 0]} castShadow>
            <coneGeometry args={[0.5, 0.9, 4]} />
            <meshStandardMaterial color={style.accent} roughness={0.7} />
          </mesh>
        </>
      )}

      {/* garden/farm flourish: little planted rows */}
      {(kind === 'garden' || kind === 'farm') &&
        [-0.7, 0, 0.7].map((gx) => (
          <mesh key={gx} position={[gx, 0.4, 1.5]} castShadow>
            <sphereGeometry args={[0.32, 12, 12]} />
            <meshStandardMaterial color={style.roof} roughness={1} />
          </mesh>
        ))}

      {/* a cheerful pennant on top, fluttering via the operational bob group */}
      <mesh position={[0.9, (isTower ? 3.4 : 2.2) + 0.9, 0]}>
        <planeGeometry args={[0.5, 0.3]} />
        <meshStandardMaterial color={style.accent} roughness={0.7} side={THREE.DoubleSide} />
      </mesh>
    </group>
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
      >
        {/* darkened, sooty body */}
        <meshStandardMaterial color={style.body} roughness={1} emissive="#1a0f08" emissiveIntensity={0.6} />
      </RoundedBox>
      {/* broken roof stub */}
      <mesh position={[0.2, 2.3, 0]} rotation={[0.2, Math.PI / 4, 0.15]} castShadow>
        <coneGeometry args={[1.6, 0.9, 4]} />
        <meshStandardMaterial color="#4a3a2c" roughness={1} />
      </mesh>
      {/* scorch scar */}
      <mesh position={[0, 1.1, 1.22]}>
        <planeGeometry args={[1.4, 1.4]} />
        <meshStandardMaterial color="#241712" roughness={1} transparent opacity={0.7} />
      </mesh>
      {/* drifting smoke puff */}
      <mesh ref={smokeRef} position={[0.4, 2.6, 0.2]}>
        <sphereGeometry args={[0.4, 10, 10]} />
        <meshStandardMaterial color="#3a3a3a" roughness={1} transparent opacity={0.45} />
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
      <mesh position={[0, 0.03, 0]} receiveShadow>
        <cylinderGeometry args={[1.8, 1.8, 0.06, 18]} />
        <meshStandardMaterial color="#7a6a52" roughness={1} />
      </mesh>
      {chunks.map(([cx, cy, cz, s], i) => (
        <mesh
          key={i}
          position={[cx, cy, cz]}
          rotation={[i * 0.7, i * 1.1, i * 0.5]}
          castShadow
          receiveShadow
        >
          <boxGeometry args={[s, s * 0.8, s * 0.9]} />
          <meshStandardMaterial color={i % 2 ? '#9a8a72' : '#83735c'} roughness={1} />
        </mesh>
      ))}
    </group>
  );
}

export function Structure({ building, x, z, focusedId, onPick }: StructureProps) {
  const style = useMemo(() => buildingStyle(building.kind), [building.kind]);
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

  // Label height tuned per status so it clears the (variable) geometry.
  const labelY =
    building.status === 'operational'
      ? building.kind === 'clocktower' || building.kind === 'monument'
        ? 5.4
        : 4.0
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
            kind={building.kind}
            offline={building.status === 'offline'}
          />
        )}

        {building.status === 'damaged' && <DamagedStructure style={style} />}

        {building.status === 'abandoned' && (
          <>
            {/* a half-built ruin frozen at its last progress — desaturated, no
                scaffolding (workers left), overgrown with a weed or two. */}
            <RisingBody grow={Math.max(0.18, grow)} style={style} ghost />
            <mesh position={[1.2, 0.4, 1.0]} castShadow>
              <coneGeometry args={[0.2, 0.7, 5]} />
              <meshStandardMaterial color="#6f8f5a" roughness={1} />
            </mesh>
            <mesh position={[-1.0, 0.35, -1.1]} castShadow>
              <coneGeometry args={[0.18, 0.6, 5]} />
              <meshStandardMaterial color="#7a9a63" roughness={1} />
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
