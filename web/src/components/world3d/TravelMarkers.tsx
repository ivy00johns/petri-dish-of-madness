/**
 * TravelMarkers (EM-110) — the in-transit agents, rendered ON THE ROUTE between
 * cities instead of inside one. An agent with `in_transit_to != null` is
 * off-board (0 LLM calls, excluded from the villager render in CozyWorld); here
 * it shows as a floating "{name} → {city}" marker gliding along the straight
 * line from its HOME settlement center to its TARGET center, eased by
 * transit_arrival_tick (travel.travelProgress).
 *
 * Render law:
 *   • WORLD-FRAME DIRECT: settlement centers are already ±33 world units — the
 *     marker + route sit at those coords with no logical conversion (anti-EM-243).
 *   • Existing chrome: drei <Billboard> + <Text> label (the SettlementLabels
 *     treatment) + a small marker dot in the agent's profile color; a faint
 *     route line reuses the StorylineTether <line>/<bufferAttribute> pattern.
 *   • v1 label is text ("{name} → {city}"), NOT the 🧳 emoji — the troika SDF
 *     font drei <Text> uses has no emoji glyph; the 2D map + feed carry the 🧳.
 *   • TOLERANT: travelMarkerEntries skips non-travelers + unresolvable targets,
 *     so a no-travel world renders NOTHING (no regression); a missing home
 *     degrades to the destination point (no line) rather than crashing.
 */

import { Billboard, Text } from '@react-three/drei';
import type { Agent, Settlement } from '../../types';
import { travelMarkerEntries } from './travel';
import { toonMaterial, LABEL_INK, LABEL_OUTLINE } from './toon';

/** Height of the floating traveler label (below the settlement name band). */
export const TRAVEL_LABEL_Y = 4.2;
/** Height of the ground marker dot. */
export const TRAVEL_DOT_Y = 0.7;
/** Height the faint route line floats at (just above the grass). */
export const TRAVEL_ROUTE_Y = 0.08;
/** Neutral marker tint when an agent carries no profile color. */
const TRAVEL_FALLBACK_COLOR = '#f6e2b3';

/**
 * All in-transit route markers. Absent settlements / no travelers ⇒ renders
 * nothing. Mounted by CozyWorld's Scene beside <SettlementGrounds>.
 */
export function TravelMarkers({
  agents,
  settlements,
  tick,
}: {
  agents: readonly Agent[];
  settlements?: Record<string, Settlement> | null;
  tick: number;
}) {
  const markers = travelMarkerEntries(agents, settlements, tick);
  if (markers.length === 0) return null;
  return (
    <group name="travel-markers">
      {markers.map((m) => {
        const color = m.color ?? TRAVEL_FALLBACK_COLOR;
        return (
          <group key={m.id} name={`travel-marker-${m.id}`}>
            {/* Faint route line home → target (StorylineTether pattern). Only
                when both endpoints resolved — a home-less traveler shows just
                the destination marker. */}
            {m.hasRoute && (
              <line>
                <bufferGeometry>
                  <bufferAttribute
                    attach="attributes-position"
                    args={[
                      new Float32Array([
                        m.from[0], TRAVEL_ROUTE_Y, m.from[1],
                        m.to[0], TRAVEL_ROUTE_Y, m.to[1],
                      ]),
                      3,
                    ]}
                  />
                </bufferGeometry>
                <lineBasicMaterial color={color} transparent opacity={0.5} />
              </line>
            )}
            {/* Ground marker dot at the eased position. */}
            <mesh position={[m.pos[0], TRAVEL_DOT_Y, m.pos[1]]} material={toonMaterial(color)}>
              <sphereGeometry args={[0.55, 16, 16]} />
            </mesh>
            {/* Floating "{name} → {city}" label. */}
            <Billboard position={[m.pos[0], TRAVEL_LABEL_Y, m.pos[1]]}>
              <Text
                fontSize={0.85}
                color={LABEL_INK}
                anchorX="center"
                anchorY="middle"
                outlineWidth={0.035}
                outlineColor={LABEL_OUTLINE}
                whiteSpace="nowrap"
                letterSpacing={0.06}
                fillOpacity={0.95}
              >
                {`${m.name}  →  ${m.targetName}`}
              </Text>
            </Billboard>
          </group>
        );
      })}
    </group>
  );
}
