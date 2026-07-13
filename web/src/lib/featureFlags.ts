/**
 * featureFlags — build-time, default-OFF gates for viewer/feed chrome, mirroring
 * the CityScape ROAD_MESH_ENABLED / GRAPH_LOTS_ENABLED const-flag pattern but
 * env-overridable like MOCK_MODE (import.meta.env.VITE_MOCK). A flag reads `1`
 * from its VITE_ env var; anything else (incl. absent) is OFF. Flipping one is
 * a rebuild — these gate presentation only, never sim state.
 */

/**
 * EM-312 — the Storylines Rail (`storylines_rail.enabled`). When OFF (default)
 * the rail is not mounted, no thread filter is offered, and no 3-D tether is
 * drawn, so the live/golden UI is byte-identical to before the feature. Flip
 * with VITE_STORYLINES_RAIL=1 for a demo/live sign-off build.
 */
export const STORYLINES_RAIL_ENABLED = import.meta.env.VITE_STORYLINES_RAIL === '1';
