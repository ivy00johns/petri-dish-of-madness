/**
 * CozyWorld — the cozy 3D village view (Stardew x Animal Crossing vibe).
 * Owns the R3F <Canvas>, warm late-afternoon lighting, a pleasant sky + fog,
 * the ground, scenery, buildings, and villagers.
 *
 * W11a camera navigation (EM-095, contract §9): the camera is no longer
 * orbit-locked to town center —
 *   • PAN: right-drag (mouse) / two-finger (touch), ground-plane panning with
 *     sane bounds (the orbit target is clamped over the village).
 *   • ZOOM-TO-PLACE: clicking a building smoothly moves the orbit target to it
 *     and eases to a comfortable viewing distance.
 *   • FOLLOW: selecting an agent/critter (bottom strip, or clicking the
 *     villager itself) makes the target track it until the user drags —
 *     user input ALWAYS breaks programmed motion.
 *   • RESET VIEW: `resetNonce` restores the default framing.
 *
 * Data contract:
 *   world.places[] : { id, name, x, y (0..1000), kind, description }
 *   world.agents[] : { id, name, profile, profile_color, location, energy,
 *                      credits, mood, alive, ... }
 *   events[]       : NEWEST-FIRST, each with monotonic numeric `seq`.
 *                    'agent_speech' carries payload.said + payload.private.
 *                    Many kinds carry payload.routed_via (actual model).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Environment, OrbitControls, Sky, SoftShadows, useGLTF } from '@react-three/drei';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import * as THREE from 'three';
import type { WorldState, WorldEvent, FocusTarget } from '../../types';
import { Ground } from './Ground';
import { Scenery } from './Scenery';
import { Foliage } from './Foliage';
import { TownProps } from './Props';
import { Building } from './Building';
import { Structure } from './Structure';
import { PlacedProps } from './PlacedProps';
import { NoticeBoard, type NoticeBoardPost } from './NoticeBoard';
import { PlazaBanner } from './PlazaBanner';
import { Villager, type AnimPos } from './Villager';
import { Critter, type CritterPos } from './Critter';
import type { BubbleData } from './ChatBubble';
import { placeToWorld, ringOffset, buildingSpot, latestRoutedVia, resolveLivingOwner, WORLD_REACH } from './worldSpace';
import { GOLDEN_HOUR } from './toon';
import { preloadHeroModels } from './assets/Model';
import { allCityModelSpecs } from './assets/cityModels';
import { allPropModelSpecs } from './assets/propModels';
import { CityScape, useCityPlan } from './CityScape';
import { assignBuildingLots, DEFAULT_CITY_SEED } from './cityLayout';
import { Traffic } from './Traffic';
import { StreetLabels } from './StreetLabels';
import { CityNameChip } from './CityNameChip';
import type { AnimalModelId } from '../../lib/animalIdentity';

// Wave C (EM-148/149): warm the GLB cache for the hero set (place anchors,
// buildings, villager, cat/dog) ONCE at module scope — the Suspense
// fallbacks cover the in-flight window.
preloadHeroModels();

/**
 * Wave D1 (EM-154): warm the city-kit GLBs the same way. Both preload lists
 * derive from the live registries (allModelSpecs / allCityModelSpecs), so the
 * Wave D1.5 asset swap — medieval kit deleted, city kits shared between the
 * registries — keeps them correct with no hand-kept url list. Rejections are
 * handled — drei's preload routes failures through suspend-react's internal
 * catch (the error surfaces only at render time, where CityScape's per-piece
 * ModelBoundary skips the piece), and the try/catch guards any synchronous
 * loader-construction throw — so a blocked /models/** never spills unhandled
 * promise noise into the console (rule 10).
 */
function preloadCityModels(): void {
  for (const spec of allCityModelSpecs()) {
    try {
      useGLTF.preload(spec.url);
    } catch {
      // skip — CityScape's ModelBoundary owns the render-time fallback
    }
  }
}
preloadCityModels();

/**
 * Wave K (EM-218): warm the prop GLBs (bench/lamp/tree/fence/bin/hydrant/
 * fountain) the same way. Most share URLs with the city kit (already warmed
 * above) — useGLTF.preload de-dupes by url, so this is cheap belt-and-braces
 * that keeps the prop set correct even if the city registry ever drops one.
 * Rejections are handled exactly like the city preload (PlacedProps'
 * per-prop ModelBoundary owns the render-time procedural fallback).
 */
function preloadPropModels(): void {
  for (const spec of allPropModelSpecs()) {
    try {
      useGLTF.preload(spec.url);
    } catch {
      // skip — PlacedProps' ModelBoundary owns the render-time fallback
    }
  }
}
preloadPropModels();

// How recent an animal's last chaotic event must be (in seq distance from the
// newest event) for the critter to still wear its magenta chaos accent. This
// keeps the accent a transient "they just did something" glow, not permanent.
const CHAOS_RECENCY_SEQ = 80;

interface CozyWorldProps {
  world: WorldState | null;
  events: WorldEvent[];
  /**
   * EM-089: animalId → the model profile the critter consults (derived by the
   * caller from animal llm_call events — world_state animals don't carry it).
   * Optional; absent/empty ⇒ the critter labels omit the model chip.
   */
  animalModels?: Map<string, AnimalModelId>;
  /** EM-095: the entity/place the camera is locked onto (null = free). */
  focus?: FocusTarget | null;
  /** EM-095: bump to restore the default framing ("reset view"). */
  resetNonce?: number;
  /** EM-095/099: a villager/critter/building was clicked in the scene. */
  onPick?: (target: FocusTarget) => void;
  /** EM-095: the user's drag broke a follow — the caller clears its selection. */
  onFocusBreak?: () => void;
}

const BUBBLE_LIFETIME_MS = 5200;
const MAX_BUBBLES_PER_AGENT = 3;
const SPEECH_TRUNCATE = 120;

// ── EM-095 camera constants (Wave D1.5: retuned for ONE compact dense 66u
// city — the default framing shows the whole grid, blocks and landmarks
// legible, matching the EW reference) ──
const DEFAULT_CAMERA = new THREE.Vector3(54, 46, 54);
const DEFAULT_TARGET = new THREE.Vector3(0, 1.5, 0);
/** The orbit target stays within this XZ box (pan bounds: city + apron). */
const PAN_BOUND = WORLD_REACH * 0.9;
/** Comfortable viewing radius zoom-to-place eases toward. */
const FOCUS_DOLLY_DIST = 20;
/** Convergence epsilon for transit/reset motion. */
const ARRIVE_EPS = 0.08;

/** Truncate spoken text for a tidy bubble. */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1).trimEnd() + '…';
}

interface LiveBubble extends BubbleData {
  actorId: string;
  expires: number;
}

/** Resolved world-space point a focus target currently occupies. */
interface FocusPoint {
  x: number;
  y: number;
  z: number;
}

type CamMode = 'free' | 'follow' | 'transit' | 'reset';

/**
 * EM-082 a11y: respect prefers-reduced-motion in the 3D view — the idle
 * auto-rotate drift is a pure nicety and is disabled for motion-sensitive
 * users (programmed follow/zoom still work; they're user-initiated).
 */
function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

/**
 * CameraDirector — owns the OrbitControls and the programmed camera motion
 * (EM-095). It mutates `controls.target` (and translates the camera by the
 * same delta, so the framing is preserved) toward the resolved focus point
 * every frame; drei's own OrbitControls update loop (priority -1) applies the
 * result. Any user interaction fires the controls' 'start' event, which
 * immediately returns the camera to 'free' and notifies the caller — user
 * input always wins. Pan bounds are clamped every frame in every mode.
 */
function CameraDirector({
  focus,
  resetNonce,
  resolveFocus,
  onFocusBreak,
}: {
  focus: FocusTarget | null;
  resetNonce: number;
  resolveFocus: (f: FocusTarget) => FocusPoint | null;
  onFocusBreak?: () => void;
}) {
  const controlsRef = useRef<OrbitControlsImpl>(null);
  const modeRef = useRef<CamMode>('free');
  const focusRef = useRef<FocusTarget | null>(focus);
  // EM-082: the idle auto-rotate is a motion nicety — off under reduced motion.
  const reducedMotionRef = useRef(prefersReducedMotion());

  // Focus changes select the programmed mode.
  useEffect(() => {
    focusRef.current = focus;
    if (!focus) {
      if (modeRef.current === 'follow' || modeRef.current === 'transit') {
        modeRef.current = 'free';
      }
      return;
    }
    modeRef.current = focus.type === 'place' ? 'transit' : 'follow';
  }, [focus]);

  // Reset view (skip the mount-time value).
  const firstResetRef = useRef(true);
  useEffect(() => {
    if (firstResetRef.current) {
      firstResetRef.current = false;
      return;
    }
    modeRef.current = 'reset';
  }, [resetNonce]);

  // User input ('start' fires only for pointer/touch/wheel interaction)
  // breaks any programmed motion.
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const onStart = () => {
      if (modeRef.current !== 'free') {
        modeRef.current = 'free';
        if (focusRef.current) onFocusBreak?.();
      }
    };
    controls.addEventListener('start', onStart);
    return () => controls.removeEventListener('start', onStart);
  }, [onFocusBreak]);

  useFrame((state, delta) => {
    const controls = controlsRef.current;
    if (!controls) return;
    const cam = state.camera;
    const mode = modeRef.current;

    // The idle auto-rotate drift pauses while a programmed motion runs — and
    // stays OFF entirely under prefers-reduced-motion (EM-082).
    controls.autoRotate = mode === 'free' && !reducedMotionRef.current;

    // Frame-rate-aware smoothing factor (≈ settles in well under a second).
    const k = 1 - Math.pow(0.002, delta);

    if (mode === 'follow' || mode === 'transit') {
      const f = focusRef.current;
      const pos = f ? resolveFocus(f) : null;
      if (pos) {
        // Translate target AND camera by the same delta → the user's chosen
        // framing (distance/angle) is preserved while tracking.
        const dx = (pos.x - controls.target.x) * k;
        const dy = (pos.y - controls.target.y) * k;
        const dz = (pos.z - controls.target.z) * k;
        controls.target.x += dx;
        controls.target.y += dy;
        controls.target.z += dz;
        cam.position.x += dx;
        cam.position.y += dy;
        cam.position.z += dz;

        if (mode === 'transit') {
          // Zoom-to-place: also ease the orbit radius to a comfortable
          // viewing distance (clamped by the controls' min/max).
          const offset = cam.position.clone().sub(controls.target);
          const len = offset.length();
          const newLen = len + (FOCUS_DOLLY_DIST - len) * k;
          offset.setLength(Math.max(0.001, newLen));
          cam.position.copy(controls.target).add(offset);

          // Arrived → hand the camera back (focus stays selected so the
          // building's full label remains revealed, EM-102).
          const remaining = Math.hypot(
            pos.x - controls.target.x,
            pos.z - controls.target.z,
          );
          if (remaining < ARRIVE_EPS && Math.abs(len - FOCUS_DOLLY_DIST) < 0.5) {
            modeRef.current = 'free';
          }
        }
      }
    } else if (mode === 'reset') {
      controls.target.lerp(DEFAULT_TARGET, k);
      cam.position.lerp(DEFAULT_CAMERA, k);
      if (
        controls.target.distanceTo(DEFAULT_TARGET) < ARRIVE_EPS &&
        cam.position.distanceTo(DEFAULT_CAMERA) < ARRIVE_EPS * 2
      ) {
        controls.target.copy(DEFAULT_TARGET);
        cam.position.copy(DEFAULT_CAMERA);
        modeRef.current = 'free';
      }
    }

    // Pan bounds — in EVERY mode (manual pans included): the orbit target
    // never leaves the village neighborhood, and never dives underground.
    controls.target.x = THREE.MathUtils.clamp(controls.target.x, -PAN_BOUND, PAN_BOUND);
    controls.target.z = THREE.MathUtils.clamp(controls.target.z, -PAN_BOUND, PAN_BOUND);
    controls.target.y = THREE.MathUtils.clamp(controls.target.y, 0, 12);
  });

  return (
    <OrbitControls
      ref={controlsRef}
      // EM-095(a): pan enabled — right-drag / two-finger, along the ground
      // plane (not screen space), bounded by the per-frame target clamp above.
      enablePan
      screenSpacePanning={false}
      autoRotate={!reducedMotionRef.current}
      autoRotateSpeed={0.4}
      enableDamping
      dampingFactor={0.08}
      minDistance={14}
      maxDistance={130}
      minPolarAngle={0.25}
      maxPolarAngle={Math.PI / 2.3}
      target={[DEFAULT_TARGET.x, DEFAULT_TARGET.y, DEFAULT_TARGET.z]}
    />
  );
}

export function CozyWorld({
  world,
  events,
  animalModels,
  focus = null,
  resetNonce = 0,
  onPick,
  onFocusBreak,
}: CozyWorldProps) {
  // ── Chat bubble lifecycle ──────────────────────────────────────────────
  const lastSeqRef = useRef<number>(-1);
  const [bubbles, setBubbles] = useState<LiveBubble[]>([]);

  // Per-entity animated positions (mutated in useFrame, survive re-renders).
  // Lifted here (was Scene-local) so the CameraDirector can FOLLOW a moving
  // villager/critter by reading the same live coordinates the renderer uses.
  const animMap = useRef<Map<string, AnimPos>>(new Map());
  const critterMap = useRef<Map<string, CritterPos>>(new Map());

  // Spawn bubbles for NEW agent_speech events (events are newest-first).
  useEffect(() => {
    if (events.length === 0) return;
    const maxSeq = events[0].seq;
    if (maxSeq <= lastSeqRef.current) return;

    // First time we see events, just adopt the baseline seq — don't flood the
    // scene with bubbles for the entire historical backlog.
    if (lastSeqRef.current < 0) {
      lastSeqRef.current = maxSeq;
      return;
    }

    const fresh: LiveBubble[] = [];
    const now = Date.now();
    for (const e of events) {
      if (e.seq <= lastSeqRef.current) break; // rest are older
      if (e.kind !== 'agent_speech') continue;
      const said = e.payload?.said;
      const actorId = e.actor_id;
      if (typeof said !== 'string' || !said || !actorId) continue;
      const isPrivate = e.payload?.private === true;
      fresh.push({
        id: e.seq,
        actorId,
        text: truncate(said, SPEECH_TRUNCATE),
        private: isPrivate,
        expires: now + BUBBLE_LIFETIME_MS,
      });
    }
    lastSeqRef.current = maxSeq;

    if (fresh.length > 0) {
      // newest first within this batch reads better when stacked
      setBubbles((prev) => [...prev, ...fresh.reverse()]);
    }
  }, [events]);

  // Expire old bubbles on a light interval.
  useEffect(() => {
    const t = window.setInterval(() => {
      const now = Date.now();
      setBubbles((prev) => {
        const next = prev.filter((b) => b.expires > now);
        return next.length === prev.length ? prev : next;
      });
    }, 500);
    return () => window.clearInterval(t);
  }, []);

  // Map: agentId -> latest routed_via model (scanned once per events change).
  const routedByAgent = useMemo(() => {
    const m = new Map<string, string>();
    if (world) {
      for (const a of world.agents) {
        const via = latestRoutedVia(events, a.id);
        if (via) m.set(a.id, via);
      }
    }
    return m;
  }, [events, world]);

  // W8: which animals are CURRENTLY chaotic — scan the (newest-first) events for
  // a recent animal event flagged is_chaotic, keyed by the animal's actor_id.
  // The critter wears the magenta chaos accent while that event is still recent.
  const chaoticAnimals = useMemo(() => {
    const set = new Set<string>();
    if (events.length === 0) return set;
    const newestSeq = events[0].seq;
    for (const e of events) {
      if (newestSeq - e.seq > CHAOS_RECENCY_SEQ) break; // events are newest-first
      const isAnimal = e.actor_type === 'animal' || e.kind === 'animal_action' || e.kind === 'animal_spawned';
      if (isAnimal && e.is_chaotic && e.actor_id) set.add(e.actor_id);
    }
    return set;
  }, [events]);

  // Group active bubbles by agent (cap per agent).
  const bubblesByAgent = useMemo(() => {
    const m = new Map<string, BubbleData[]>();
    for (const b of bubbles) {
      const list = m.get(b.actorId) ?? [];
      list.push({ id: b.id, text: b.text, private: b.private });
      m.set(b.actorId, list);
    }
    for (const [k, v] of m) {
      if (v.length > MAX_BUBBLES_PER_AGENT) {
        m.set(k, v.slice(v.length - MAX_BUBBLES_PER_AGENT));
      }
    }
    return m;
  }, [bubbles]);

  // ── Geometry shared by the scene AND the camera (EM-095) ────────────────
  const places = world?.places;
  const placeCenters = useMemo(() => {
    const m = new Map<string, { x: number; z: number }>();
    (places ?? []).forEach((p) => m.set(p.id, placeToWorld(p)));
    return m;
  }, [places]);

  // EM-174: real W7 buildings claim REAL lots — street-front lots inside
  // their place's landmark block first (stable id order → lot index), then
  // nearest-block overflow onto the city's platted lots; the EM-131 slot
  // ring only when the whole city is full. The plan itself is a pure
  // function of (places, city_seed); the same content-memoized plan feeds
  // CityScape.
  const buildings = world?.buildings;
  const { plan: cityPlan } = useCityPlan({
    places: places ?? [],
    city_seed: world?.city_seed,
  });
  const buildingSpots = useMemo(() => {
    const list = buildings ?? [];
    const spotById = assignBuildingLots(cityPlan, list, placeCenters);
    return list.map((b) => ({ building: b, ...(spotById.get(b.id) ?? { x: 0, z: 0 }) }));
  }, [buildings, cityPlan, placeCenters]);

  const buildingSpotById = useMemo(
    () => new Map(buildingSpots.map((s) => [s.building.id, s])),
    [buildingSpots],
  );

  // W11b (EM-091a): the notice board sits at a stable satellite spot near the
  // plaza (id 'plaza', falling back to the first social place). No plaza in
  // this world → no board (graceful: procgen towns always have a social hub).
  const noticeSpot = useMemo(() => {
    const plaza =
      (places ?? []).find((p) => p.id === 'plaza') ??
      (places ?? []).find((p) => p.kind === 'social');
    if (!plaza) return null;
    const c = placeToWorld(plaza);
    return { plazaId: plaza.id, ...buildingSpot(c, 'notice-board', 4.2) };
  }, [places]);

  // The newest billboard post for the board's in-canvas label (author resolved
  // from the live roster; god replies flagged so the label takes the god ink).
  const newestPost = useMemo<NoticeBoardPost | null>(() => {
    const posts = world?.billboard ?? [];
    if (posts.length === 0) return null;
    let top = posts[0];
    for (const p of posts) if (p.tick > top.tick) top = p;
    const god = top.actor_type === 'god';
    const author = god
      ? 'the watchers'
      : world?.agents.find((a) => a.id === top.actor_id)?.name ?? top.actor_id;
    return { text: top.text, author, god };
  }, [world]);

  // Wave I (EM-211, I1): the NEWEST gallery image's RELATIVE url for the notice
  // board's front note (textured, else the procedural PAPER fallback). The
  // gallery rides the per-tick world_state snapshot; entries are appended newest-
  // last (mirror the backend cap), so the newest is the tail. null ⇒ no art yet.
  const newestImageUrl = useMemo<string | null>(() => {
    const gallery = world?.gallery ?? [];
    if (gallery.length === 0) return null;
    return gallery[gallery.length - 1].url || null;
  }, [world]);

  // Wave I (EM-213, I4): resolve world.plaza_banner_ref (a gallery image_id) to
  // its RELATIVE url for the PlazaBanner texture. Unset ref OR an id missing
  // from the gallery ⇒ null (PlazaBanner shows its procedural civic fallback).
  const plazaBannerUrl = useMemo<string | null>(() => {
    const ref = world?.plaza_banner_ref;
    if (!ref) return null;
    const img = (world?.gallery ?? []).find((g) => g.image_id === ref);
    return img?.url || null;
  }, [world]);

  // EM-095: where is the focus target RIGHT NOW. Agents/animals read the live
  // animated positions (the same refs the renderer lerps), so a follow tracks
  // the walking villager, not its last place center. 'place' ids may be a
  // Place id or a W7 Building id (FocusTarget contract in types/index.ts).
  const resolveFocus = useCallback(
    (f: FocusTarget): FocusPoint | null => {
      if (f.type === 'agent') {
        const p = animMap.current.get(f.id);
        return p ? { x: p.x, y: 1.4, z: p.z } : null;
      }
      if (f.type === 'animal') {
        const p = critterMap.current.get(f.id);
        return p ? { x: p.x, y: 0.6, z: p.z } : null;
      }
      const c = placeCenters.get(f.id);
      if (c) return { x: c.x, y: 1.2, z: c.z };
      const b = buildingSpotById.get(f.id);
      return b ? { x: b.x, y: 1.2, z: b.z } : null;
    },
    [placeCenters, buildingSpotById],
  );

  if (!world) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-lab-bg">
        <span className="font-mono text-xs text-lab-dim">AWAITING WORLD STATE…</span>
      </div>
    );
  }

  // EM-188: the city's title — absent-safe (town_name is additive backend
  // state; mock mode / old snapshots may lack it, and it is not yet part of
  // the frontend WorldState type, so it is read defensively).
  const townName = (world as { town_name?: unknown }).town_name;

  return (
    <div className="relative h-full w-full">
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}
        camera={{ position: [54, 46, 54], fov: 42, near: 0.1, far: 420 }}
      >
        <color attach="background" args={[GOLDEN_HOUR.background]} />
        {/* EM-111: PCSS soft shadows on the existing shadow map — warm,
            feathered golden-hour shadows instead of hard stencils. */}
        <SoftShadows size={24} samples={10} focus={0.5} />
        <Scene
          world={world}
          bubblesByAgent={bubblesByAgent}
          routedByAgent={routedByAgent}
          chaoticAnimals={chaoticAnimals}
          animalModels={animalModels}
          animMap={animMap}
          critterMap={critterMap}
          placeCenters={placeCenters}
          buildingSpots={buildingSpots}
          noticeSpot={noticeSpot}
          newestPost={newestPost}
          newestImageUrl={newestImageUrl}
          plazaBannerUrl={plazaBannerUrl}
          focus={focus}
          onPick={onPick}
        />
        {/* EM-188: painted street-name labels — proximity-gated (EM-102
            threshold), flat on the roads so they never collide with the
            floating place/structure labels. Lives here (not CityScape):
            useProximity needs the R3F frame loop. */}
        <StreetLabels streets={cityPlan.streets} />
        {/* EM-169: ambient moving traffic on the road grid (deterministic
            fleet, clock-driven sweep, reduced-motion-safe). Sibling of the
            scene so it shares the frame loop + world space; no handlers. */}
        <Traffic seed={world?.city_seed ?? DEFAULT_CITY_SEED} streets={cityPlan.streets} />
        <CameraDirector
          focus={focus}
          resetNonce={resetNonce}
          resolveFocus={resolveFocus}
          onFocusBreak={onFocusBreak}
        />
      </Canvas>
      {/* EM-188: the city's name, once, as a HUD chip (absent-safe). */}
      <CityNameChip name={typeof townName === 'string' ? townName : null} />
    </div>
  );
}

/**
 * Scene — all in-Canvas contents: warm sky/light/fog, ground, scenery,
 * buildings, and villagers. The per-entity animated-position maps live in
 * CozyWorld (shared with the camera director); re-renders from new world
 * state never reset in-flight animations. The routed_via model map is
 * precomputed by CozyWorld (O(agents) per events change) and injected here,
 * keeping that scan out of the per-frame path.
 */
function Scene({
  world,
  bubblesByAgent,
  routedByAgent,
  chaoticAnimals,
  animalModels,
  animMap,
  critterMap,
  placeCenters,
  buildingSpots,
  noticeSpot,
  newestPost,
  newestImageUrl,
  plazaBannerUrl,
  focus,
  onPick,
}: {
  world: WorldState;
  bubblesByAgent: Map<string, BubbleData[]>;
  routedByAgent: Map<string, string>;
  chaoticAnimals: Set<string>;
  animalModels?: Map<string, AnimalModelId>;
  animMap: React.MutableRefObject<Map<string, AnimPos>>;
  critterMap: React.MutableRefObject<Map<string, CritterPos>>;
  placeCenters: Map<string, { x: number; z: number }>;
  buildingSpots: Array<{ building: NonNullable<WorldState['buildings']>[number]; x: number; z: number }>;
  /** W11b (EM-091a): where the notice board stands (null = no plaza). */
  noticeSpot: { plazaId: string; x: number; z: number } | null;
  /** Newest billboard post for the board's label (null = bare board). */
  newestPost: NoticeBoardPost | null;
  /** Wave I (EM-211, I1): newest gallery image url for the board texture (null = none). */
  newestImageUrl: string | null;
  /** Wave I (EM-213, I4): the promoted plaza-banner image url (null = none/unset). */
  plazaBannerUrl: string | null;
  focus: FocusTarget | null;
  onPick?: (target: FocusTarget) => void;
}) {
  const { places, agents } = world;
  const animals = world.animals ?? [];

  const focusedPlaceId = focus?.type === 'place' ? focus.id : null;

  // Wave I (EM-213, I4): the plaza banner's world spot — a stable satellite of
  // the plaza anchor (a DIFFERENT buildingSpot seed than the notice board so the
  // two don't overlap). Derived from the same plaza the notice board resolved
  // (null = no plaza → no banner, exactly like the board).
  const plazaSpot = useMemo(() => {
    if (!noticeSpot) return null;
    const c = placeCenters.get(noticeSpot.plazaId);
    if (!c) return null;
    return buildingSpot(c, 'plaza-banner', 5.2);
  }, [noticeSpot, placeCenters]);

  const targets = useMemo(() => {
    const byPlace = new Map<string, string[]>();
    agents.forEach((a) => {
      const list = byPlace.get(a.location) ?? [];
      list.push(a.id);
      byPlace.set(a.location, list);
    });
    const result = new Map<string, AnimPos>();
    agents.forEach((a) => {
      const center = placeCenters.get(a.location);
      if (!center) {
        result.set(a.id, { x: 0, z: 0 });
        return;
      }
      const colocated = byPlace.get(a.location) ?? [a.id];
      const idx = colocated.indexOf(a.id);
      const pos = ringOffset(center, idx, colocated.length);
      result.set(a.id, { x: pos.x, z: pos.z });
      if (!animMap.current.has(a.id)) {
        animMap.current.set(a.id, { x: pos.x, z: pos.z });
      }
    });
    return result;
  }, [agents, placeCenters, animMap]);

  return (
    <>
      {/* EM-111 golden hour (art Direction 1): the sun sits LOW — the Sky
          shader paints the warm horizon gradient, the vendored sunset HDRI
          (Poly Haven, CC0 — see ASSET_LICENSES.md) supplies soft warm image-
          based lighting for any PBR materials, and a low-angle warm key light
          drives the toon ramp's banding. */}
      <Sky
        distance={450000}
        sunPosition={[10, 2.4, 6]}
        turbidity={7.5}
        rayleigh={2.2}
        mieCoefficient={0.014}
        mieDirectionalG={0.88}
      />
      <Environment files="/hdri/venice_sunset_1k.hdr" />
      <hemisphereLight
        args={[GOLDEN_HOUR.hemiSky, GOLDEN_HOUR.hemiGround, 0.55]}
      />
      {/* Faint warm ambient only — the directional must dominate so the toon
          bands read; it also keeps shadows warm, never black. */}
      <ambientLight intensity={0.15} color={GOLDEN_HOUR.ambient} />
      {/* Wave D1.5: the whole 66u city fits ONE shadow frustum now — ±48
          covers the grid's ~47u half-diagonal (verified against the light
          axis), so every block gets shadows AND the 2048 map gains texel
          density over D1's ±64. Fog (80/215): the far half of the compact
          grid picks up gentle depth haze and the outer terrain ring dissolves
          before it can shimmer at a full zoom-out, while the city itself stays
          crisp inside the 130u zoom range; same low golden-hour sun ANGLE as
          Wave C. shadow-normalBias kills the shadow-acne crawl that made the
          grass look "jittery" at the edge of the view when zoomed out. */}
      <directionalLight
        position={[27, 13.5, 12]}
        intensity={2.2}
        color={GOLDEN_HOUR.sun}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={1}
        shadow-camera-far={150}
        shadow-camera-left={-48}
        shadow-camera-right={48}
        shadow-camera-top={48}
        shadow-camera-bottom={-48}
        shadow-bias={-0.0004}
        shadow-normalBias={0.04}
      />
      <fog attach="fog" args={[GOLDEN_HOUR.fog, 80, 215]} />

      <Ground places={places} />
      <Scenery places={places} />
      {/* EM-118: instanced treeline (LOD) + lived-in town props. */}
      <Foliage places={places} />
      <TownProps places={places} />

      {/* Wave D1.5: THE city — non-interactive instanced set dressing for
          the whole compact grid (roads, zoned blocks, props, parked cars);
          the places' own anchors render via <Building> below. */}
      <CityScape world={world} />

      {/* Wave K (EM-218): agent/god-PLACED props — benches, lamps, trees,
          fences, bins, hydrants, fountains the agents put down. Distinct from
          the deterministic CityScape scatter above: these are first-class
          `Prop` entities the world tracks, positioned at their place center +
          the engine-assigned (dx,dz). Each renders its GLB with a procedural
          fallback (never a hole). */}
      <PlacedProps places={places} props={world.props} />

      {places.map((p) => (
        <Building
          key={p.id}
          place={p}
          focusedId={focusedPlaceId}
          onPick={onPick ? (id) => onPick({ type: 'place', id }) : undefined}
        />
      ))}

      {/* W11b (EM-091a): the village notice board at the plaza — its label
          shows the newest post (proximity-gated like every other label).
          Wave I (EM-211): the newest gallery image textures its front note. */}
      {noticeSpot && (
        <NoticeBoard
          x={noticeSpot.x}
          z={noticeSpot.z}
          newest={newestPost}
          imageUrl={newestImageUrl}
          onPick={onPick ? () => onPick({ type: 'place', id: noticeSpot.plazaId }) : undefined}
        />
      )}

      {/* Wave I (EM-213, I4): the civic banner the town voted over the plaza. It
          stands on its own satellite spot beside the plaza anchor (a distinct
          buildingSpot angle from the notice board) and textures the promoted
          image; a procedural civic canvas stands in until a vote passes. */}
      {plazaSpot && (
        <PlazaBanner x={plazaSpot.x} z={plazaSpot.z} url={plazaBannerUrl} />
      )}

      {/* W7: living structures/projects, rendered by status near their place. */}
      {buildingSpots.map(({ building, x, z }) => (
        <Structure
          key={building.id}
          building={building}
          x={x}
          z={z}
          focusedId={focusedPlaceId}
          onPick={onPick ? (id) => onPick({ type: 'place', id }) : undefined}
        />
      ))}

      {agents.map((a) => {
        const target = targets.get(a.id) ?? { x: 0, z: 0 };
        let anim = animMap.current.get(a.id);
        if (!anim) {
          anim = { x: target.x, z: target.z };
          animMap.current.set(a.id, anim);
        }
        return (
          <Villager
            key={a.id}
            agent={a}
            target={target}
            animRef={anim}
            routedVia={routedByAgent.get(a.id)}
            bubbles={bubblesByAgent.get(a.id) ?? []}
            focused={focus?.type === 'agent' && focus.id === a.id}
            onPick={onPick ? () => onPick({ type: 'agent', id: a.id }) : undefined}
          />
        );
      })}

      {/* W8: the roaming chaos critters (cat + dog), each wandering near its
          place; chaotic ones wear the magenta accent. 3D stays primary. */}
      {/* Wave H4 (EM-209): owned pets follow their owner. We resolve the owner's
          current animated position from animMap (the same mutable ref that
          Villager updates each frame), so the pet trails the owner in real time.
          Falls back to standard wander when owner_id is absent/null or owner
          not found — no crash, no stuck-at-origin. */}
      {animals.map((animal) => {
        const center = placeCenters.get(animal.location) ?? { x: 0, z: 0 };
        let anim = critterMap.current.get(animal.id);
        if (!anim) {
          // Start the critter at its place center so it doesn't fly in from origin.
          anim = { x: center.x, z: center.z };
          critterMap.current.set(animal.id, anim);
        }
        // Resolve the owner's live animated position (undefined = unowned,
        // owner unknown, or owner DEAD — Critter falls back to wander, never
        // crashes). The owner must be alive: to_snapshot() serializes dead
        // agents and the backend never clears owner_id on owner death, so we
        // gate on `a.alive` to mirror the backend's _owner_of() (a dead owner
        // ⇒ pet reverts to wandering) and RosterStrip's bond line. Without
        // this gate all three layers would disagree and the pet would leash
        // to its dead owner's corpse position.
        const ownerAgent = resolveLivingOwner(agents, animal.owner_id);
        const ownerPos = ownerAgent
          ? (animMap.current.get(ownerAgent.id) ?? undefined)
          : undefined;
        return (
          <Critter
            key={animal.id}
            animal={animal}
            center={center}
            animRef={anim}
            chaotic={chaoticAnimals.has(animal.id)}
            model={animalModels?.get(animal.id) ?? null}
            focused={focus?.type === 'animal' && focus.id === animal.id}
            onPick={onPick ? () => onPick({ type: 'animal', id: animal.id }) : undefined}
            ownerPos={ownerPos}
          />
        );
      })}
    </>
  );
}
