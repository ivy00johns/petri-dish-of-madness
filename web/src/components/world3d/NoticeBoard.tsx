/**
 * NoticeBoard (W11b EM-091a) — the physical village billboard: a low-poly
 * plank board on two posts near the plaza, matching the village's procedural
 * Stardew × Animal-Crossing idiom (drei boxes/cylinders, no external assets).
 *
 * Its in-canvas label follows the established proximity-gated idiom
 * (useProximity + Billboard/Text, exactly like Building/Structure): near the
 * camera (or hovered) it shows "NOTICE BOARD" plus a snippet of the NEWEST
 * post with its author — god replies read in the violet god ink; far away it
 * collapses to the MiniMarker so it never buries villager chips.
 *
 * Colors are WebGL material colors (THREE.Color), explicitly OUTSIDE the CSS
 * design-token system — the same GPU-palette convention as Building/Structure/
 * Scenery (the 3D scene owns its warm palette; design-token-guard governs
 * DOM/CSS only).
 */

import { useCallback, useState } from 'react';
import { Billboard, RoundedBox, Text, useCursor } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import { MiniMarker } from './Building';
import { useProximity, PLACE_LABEL_DIST } from './useProximity';
import { toonMaterial } from './toon';

/** The newest post, resolved by the caller (author name + god flag). */
export interface NoticeBoardPost {
  text: string;
  author: string;
  god: boolean;
}

interface NoticeBoardProps {
  /** World position (a satellite spot near the plaza center). */
  x: number;
  z: number;
  /** Newest billboard post, or null when the board is bare. */
  newest: NoticeBoardPost | null;
  /** Clicking the board zooms the camera to it (EM-095 idiom). */
  onPick?: () => void;
}

const SNIPPET_MAX = 64;

// GPU palette (WebGL material colors — outside the CSS token system, the
// established village convention). God ink mirrors the DOM --lab-god register
// by intent so the two surfaces agree.
const WOOD_POST = '#8a6b45';
const WOOD_BOARD = '#a8825a';
const WOOD_ROOF = '#6b4f32';
const PAPER = '#f1e6d4';
const PAPER_GOD = '#cdc4ff';
const LABEL_PLATE = '#3a2f25';
const LABEL_TEXT = '#fff3e0';
const LABEL_GOD = '#a99bff';
const LABEL_MUTED = '#d9c7a0';
const PIN = '#c94f4f';

function snippet(text: string): string {
  if (text.length <= SNIPPET_MAX) return text;
  return text.slice(0, SNIPPET_MAX - 1).trimEnd() + '…';
}

export function NoticeBoard({ x, z, newest, onPick }: NoticeBoardProps) {
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && Boolean(onPick));

  // Label gating: full card near/hovered, MiniMarker far (EM-102 idiom).
  const near = useProximity(useCallback(() => ({ x, z }), [x, z]), PLACE_LABEL_DIST);
  const showFull = near || hovered;

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!onPick) return;
    e.stopPropagation();
    onPick();
  };

  return (
    <group
      position={[x, 0, z]}
      onClick={handleClick}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
      {/* two support posts */}
      {[-0.95, 0.95].map((px) => (
        <mesh key={px} position={[px, 0.95, 0]} castShadow material={toonMaterial(WOOD_POST)}>
          <cylinderGeometry args={[0.08, 0.1, 1.9, 8]} />
        </mesh>
      ))}

      {/* the board itself */}
      <RoundedBox
        args={[2.3, 1.25, 0.12]}
        radius={0.04}
        smoothness={2}
        position={[0, 1.5, 0]}
        castShadow
        material={toonMaterial(WOOD_BOARD)}
      />

      {/* little shingle roof so notes survive the rain */}
      <mesh position={[0, 2.28, 0]} rotation={[0, 0, 0]} castShadow material={toonMaterial(WOOD_ROOF)}>
        <boxGeometry args={[2.6, 0.08, 0.5]} />
      </mesh>

      {/* pinned papers — the newest one tinted god-violet when the watchers
          posted last, so the board itself hints who spoke. (Front-face only is
          fine: the solid board occludes them from behind.) */}
      <mesh
        position={[-0.55, 1.55, 0.075]}
        rotation={[0, 0, 0.06]}
        material={toonMaterial(newest?.god ? PAPER_GOD : PAPER)}
      >
        <planeGeometry args={[0.55, 0.7]} />
      </mesh>
      <mesh position={[0.35, 1.45, 0.075]} rotation={[0, 0, -0.08]} material={toonMaterial(PAPER)}>
        <planeGeometry args={[0.6, 0.5]} />
      </mesh>
      {/* a red pin on the newest note */}
      <mesh position={[-0.55, 1.86, 0.1]} material={toonMaterial(PIN)}>
        <sphereGeometry args={[0.045, 8, 8]} />
      </mesh>

      {/* proximity-gated label: title + newest-post snippet (EM-091a). */}
      {showFull ? (
        <Billboard position={[0, 2.9, 0]}>
          <mesh position={[0, 0, -0.02]}>
            <planeGeometry args={[Math.max(3.2, snippet(newest?.text ?? '').length * 0.16), newest ? 1.35 : 0.95]} />
            <meshBasicMaterial color={LABEL_PLATE} transparent opacity={0.72} />
          </mesh>
          <Text
            position={[0, newest ? 0.42 : 0.12, 0]}
            fontSize={0.4}
            color={LABEL_TEXT}
            anchorX="center"
            anchorY="middle"
            outlineWidth={0.012}
            outlineColor="#241b14"
            maxWidth={10}
          >
            📌 NOTICE BOARD
          </Text>
          {newest ? (
            <>
              <Text
                position={[0, 0.0, 0]}
                fontSize={0.27}
                color={newest.god ? LABEL_GOD : LABEL_TEXT}
                anchorX="center"
                anchorY="middle"
                outlineWidth={0.009}
                outlineColor="#241b14"
                maxWidth={6.4}
              >
                {`“${snippet(newest.text)}”`}
              </Text>
              <Text
                position={[0, -0.45, 0]}
                fontSize={0.24}
                color={newest.god ? LABEL_GOD : LABEL_MUTED}
                anchorX="center"
                anchorY="middle"
                outlineWidth={0.008}
                outlineColor="#241b14"
                maxWidth={6.4}
              >
                {newest.god ? '— ✦ the watchers' : `— ${newest.author}`}
              </Text>
            </>
          ) : (
            <Text
              position={[0, -0.22, 0]}
              fontSize={0.26}
              color={LABEL_MUTED}
              anchorX="center"
              anchorY="middle"
              outlineWidth={0.009}
              outlineColor="#241b14"
              maxWidth={6.4}
            >
              no notices yet
            </Text>
          )}
        </Billboard>
      ) : (
        <MiniMarker y={2.9} color={newest?.god ? LABEL_GOD : PAPER} />
      )}
    </group>
  );
}
