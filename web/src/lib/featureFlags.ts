/**
 * featureFlags — build-time, default-OFF gates for viewer/feed chrome, mirroring
 * the CityScape ROAD_MESH_ENABLED / GRAPH_LOTS_ENABLED const-flag pattern but
 * env-overridable like MOCK_MODE (import.meta.env.VITE_MOCK). A flag reads `1`
 * from its VITE_ env var; anything else (incl. absent) is OFF. Flipping one is
 * a rebuild — these gate presentation only, never sim state.
 */

/**
 * EM-312 — the Storylines Rail (`storylines_rail.enabled`). Default ON since
 * the live sign-off (2026-10-03); the rail still renders nothing until a
 * storyline is promoted, so peacetime chrome is unchanged. Set
 * VITE_STORYLINES_RAIL=0 to opt out of the build.
 */
export const STORYLINES_RAIL_ENABLED = import.meta.env.VITE_STORYLINES_RAIL !== '0';
