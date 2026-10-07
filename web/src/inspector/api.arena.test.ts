/**
 * api.ts — the EM-112/EM-119 Arena client additions.
 *
 * Pure fetch-stub tests (no backend): parsing/typing of /api/arena,
 * /api/arena/tournament GET (status), POST (start), DELETE (abort) —
 * labeled failures for 400/409/network, never a throw.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { inspectorApi } from './api';

function stubFetch(responses: Record<string, { status: number; body: unknown } | 'throw'>) {
  const impl = (path: string, init?: RequestInit) => {
    const key = `${(init?.method ?? 'GET').toUpperCase()} ${path.split('?')[0]}`;
    const hit = responses[key];
    if (hit === 'throw' || !hit) return Promise.reject(new TypeError('network down'));
    return Promise.resolve(
      new Response(JSON.stringify(hit.body), {
        status: hit.status,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  };
  vi.stubGlobal('fetch', vi.fn(impl));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('inspectorApi.arena (EM-119)', () => {
  it('parses families/runs/sparklines and coerces odd fields to zeros', async () => {
    stubFetch({
      'GET /api/arena': {
        status: 200,
        body: {
          families: [
            {
              family: 'gemini',
              avg_per_run: { population: 3, laws_passed: 1.5 },
              runs: [
                {
                  run_id: 12,
                  max_tick: 40,
                  outcomes: { population: 4, laws_passed: 2, buildings: 1, crimes: 1, credits: 50 },
                  population_sparkline: [{ tick: 0, alive: 1 }, { tick: 40, alive: 4 }],
                  failures: {
                    counts: { action_rejected: 147, provider_error: 30, parse_failure: 145 },
                    shares: { action_rejected: 0.4565, provider_error: 0.0932, parse_failure: 0.4503 },
                    total: 322, turns: 1103, failure_rate: 0.292, legacy_rows_reclassified: 322,
                  },
                },
                { run_id: 'junk' },                       // dropped
                { run_id: 9, outcomes: null, population_sparkline: 'junk' }, // zeroed
              ],
            },
            { family: 42 },                               // dropped
          ],
        },
      },
    });
    const out = await inspectorApi.arena();
    expect(out).not.toBeNull();
    expect(out!.families).toHaveLength(1);
    const fam = out!.families[0];
    expect(fam.family).toBe('gemini');
    expect(fam.avg_per_run).toEqual({
      population: 3, laws_passed: 1.5, buildings: 0, crimes: 0, credits: 0,
    });
    expect(fam.runs).toHaveLength(2);
    expect(fam.runs[1].outcomes).toEqual({
      population: 0, laws_passed: 0, buildings: 0, crimes: 0, credits: 0,
    });
    expect(fam.runs[1].population_sparkline).toEqual([]);
  });

  it('EM-343 — parses the failures taxonomy, absent block ⇒ zeros', async () => {
    stubFetch({
      'GET /api/arena': {
        status: 200,
        body: {
          families: [
            {
              family: 'gemini',
              avg_per_run: {},
              runs: [
                {
                  run_id: 23,
                  max_tick: 1101,
                  outcomes: {},
                  failures: {
                    counts: { action_rejected: 147, provider_error: 30, parse_failure: 145 },
                    shares: { action_rejected: 0.4565, provider_error: 0.0932, parse_failure: 0.4503 },
                    total: 322, turns: 1103, failure_rate: 0.292, legacy_rows_reclassified: 322,
                  },
                },
                { run_id: 9, outcomes: {} }, // pre-EM-343 run: no failures block
              ],
            },
          ],
        },
      },
    });
    const out = await inspectorApi.arena();
    const runs = out!.families[0].runs;
    expect(runs[0].failures.counts).toEqual({
      action_rejected: 147, provider_error: 30, parse_failure: 145,
    });
    expect(runs[0].failures.total).toBe(322);
    expect(runs[0].failures.turns).toBe(1103);
    expect(runs[0].failures.failure_rate).toBeCloseTo(0.292, 3);
    expect(runs[0].failures.legacy_rows_reclassified).toBe(322);
    // Defensive: an absent block coerces to the all-zero taxonomy, never null.
    expect(runs[1].failures).toEqual({
      counts: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
      shares: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
      total: 0, turns: 0, failure_rate: 0, legacy_rows_reclassified: 0,
      curve: [], by_agent: {}, by_route: {},
      failures_attributed: 0, attempts_attributed: 0,
    });
  });

  it('EM-344/345/346/347 — parses the family rollup + the run curve + per-agent cut', async () => {
    stubFetch({
      'GET /api/arena': {
        status: 200,
        body: {
          // EM-351 — the cross-run lane rollup (junk lane id dropped)
          routes: [
            {
              lane: 'google/gemini-3.1-flash-lite',
              failures: 74, attempts: 255, runs: 3, failure_rate: 0.2902,
            },
            { lane: 42 },
          ],
          families: [
            {
              family: 'gemini',
              avg_per_run: {},
              failures: {
                counts: { action_rejected: 147, provider_error: 30, parse_failure: 145 },
                shares: { action_rejected: 0.4565, provider_error: 0.0932, parse_failure: 0.4503 },
                total: 322, turns: 1143, failure_rate: 0.2817, legacy_rows_reclassified: 322,
              },
              runs: [
                {
                  run_id: 23,
                  outcomes: {},
                  failures: {
                    counts: { action_rejected: 147, provider_error: 30, parse_failure: 145 },
                    shares: { action_rejected: 0.4565, provider_error: 0.0932, parse_failure: 0.4503 },
                    total: 322, turns: 1103, failure_rate: 0.292, legacy_rows_reclassified: 322,
                    curve: [
                      { tick: 0, action_rejected: 0, provider_error: 0, parse_failure: 0 },
                      { tick: 1000, action_rejected: 0, provider_error: 30, parse_failure: 0 },
                      'junk',
                    ],
                    by_agent: {
                      agent_ada: {
                        counts: { action_rejected: 57, provider_error: 6, parse_failure: 47 },
                        shares: { action_rejected: 0.5182, provider_error: 0.0545, parse_failure: 0.4273 },
                        total: 110, turns: 367, failure_rate: 0.2997, legacy_rows_reclassified: 110,
                        routes: { 'kilo/inclusionai/ling-3.0-flash-sante:free': 81, junk: 'x' },
                        top_route: 'kilo/inclusionai/ling-3.0-flash-sante:free',
                        routes_attributed: 104,
                      },
                    },
                    by_route: {
                      'kilo/inclusionai/ling-3.0-flash-sante:free': {
                        failures: 218, attempts: 1449, failure_rate: 0.1504,
                        curve: [
                          { tick: 0, failures: 2, attempts: 900 },
                          { tick: 1000, failures: 216, attempts: 549 },
                          'junk', // dropped
                        ],
                      },
                      'not-an-object': 'junk', // coerced to an all-zero stat
                    },
                    failures_attributed: 300,
                    attempts_attributed: 1999,
                  },
                },
                { run_id: 9, outcomes: {} }, // pre-EM-345 run: no curve/by_agent
              ],
            },
          ],
        },
      },
    });
    const out = await inspectorApi.arena();
    // EM-347 — the family rollup parses as a core (zeros when absent)
    expect(out!.families[0].failures.total).toBe(322);
    expect(out!.families[0].failures.shares.provider_error).toBeCloseTo(0.0932, 3);
    // EM-345 — the curve drops the junk row and coerces each kind
    const run = out!.families[0].runs[0];
    expect(run.failures.curve).toHaveLength(2);
    expect(run.failures.curve[1]).toEqual({
      tick: 1000, action_rejected: 0, provider_error: 30, parse_failure: 0,
    });
    // EM-346 — the per-agent cut
    expect(run.failures.by_agent.agent_ada.total).toBe(110);
    expect(run.failures.by_agent.agent_ada.failure_rate).toBeCloseTo(0.2997, 3);
    // EM-348 — the lane attribution (a junk count coerces to 0, not dropped)
    expect(run.failures.by_agent.agent_ada.top_route).toBe(
      'kilo/inclusionai/ling-3.0-flash-sante:free',
    );
    expect(run.failures.by_agent.agent_ada.routes_attributed).toBe(104);
    expect(run.failures.by_agent.agent_ada.routes['kilo/inclusionai/ling-3.0-flash-sante:free']).toBe(81);
    expect(run.failures.by_agent.agent_ada.routes.junk).toBe(0);
    // absent on a pre-EM-345 run ⇒ an empty cut, never null
    expect(out!.families[0].runs[1].failures.curve).toEqual([]);
    expect(out!.families[0].runs[1].failures.by_agent).toEqual({});
    // EM-349 — the per-lane rate (a junk stat coerces to zeros, never dropped)
    expect(run.failures.by_route['kilo/inclusionai/ling-3.0-flash-sante:free']).toEqual({
      failures: 218, attempts: 1449, failure_rate: 0.1504,
      curve: [
        { tick: 0, failures: 2, attempts: 900 },
        { tick: 1000, failures: 216, attempts: 549 },
      ],
    });
    // the junk `not-an-object` stat coerces to an all-zero entry (with a curve)
    expect(run.failures.by_route['not-an-object']).toEqual({
      failures: 0, attempts: 0, failure_rate: 0, curve: [],
    });
    expect(run.failures.failures_attributed).toBe(300);
    expect(run.failures.attempts_attributed).toBe(1999);
    // EM-351 — the cross-run lane rollup parses (junk lane dropped) and
    // EM-352 — a pre-EM-352 payload's missing chronic fields coerce safely
    // (no evidence ⇒ not chronic; the rule falls back to the shipped default)
    expect(out!.routes).toEqual([
      {
        lane: 'google/gemini-3.1-flash-lite', failures: 74, attempts: 255,
        runs: 3, failure_rate: 0.2902,
        worst_rate: 0, runs_high: 0, chronic: false,
      },
    ]);
    expect(out!.chronic_rule).toEqual({ rate_threshold: 0.2, min_runs: 2 });
    // EM-353 — the default read did not carry the per-lane curves
    expect(out!.lane_curves).toBe(false);

    stubFetch({
      'GET /api/arena': {
        status: 200,
        body: {
          families: [],
          routes: [
            {
              lane: 'lane/bad', failures: 74, attempts: 255, runs: 3,
              failure_rate: 0.2902, worst_rate: 0.56, runs_high: 3, chronic: true,
            },
          ],
          chronic_rule: { rate_threshold: 0.25, min_runs: 3 },
          lane_curves: true,
        },
      },
    });
    const asked = await inspectorApi.arena({ laneCurves: true });
    // EM-353 — the opt-in actually rides the request URL
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/arena?lane_curves=1');
    expect(asked!.lane_curves).toBe(true);
    expect(asked!.chronic_rule).toEqual({ rate_threshold: 0.25, min_runs: 3 });
    expect(asked!.routes[0].chronic).toBe(true);
    expect(asked!.routes[0].runs_high).toBe(3);

    stubFetch({
      'GET /api/arena': { status: 200, body: { families: [] } },
    });
    const absent = await inspectorApi.arena();
    expect(absent!.routes).toEqual([]);
    expect(absent!.lane_curves).toBe(false);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/arena');
  });

  it('returns null on network failure and on a non-object body', async () => {
    stubFetch({ 'GET /api/arena': 'throw' });
    expect(await inspectorApi.arena()).toBeNull();
    stubFetch({ 'GET /api/arena': { status: 200, body: [1, 2] } });
    expect(await inspectorApi.arena()).toBeNull();
  });
});

describe('inspectorApi.tournamentStatus (EM-112)', () => {
  it('parses a running status with results', async () => {
    stubFetch({
      'GET /api/arena/tournament': {
        status: 200,
        body: {
          status: 'running', families: ['gemini'], ticks_per_family: 40,
          current_family: 'gemini', current_index: 0, current_run_id: 12,
          ticks_done_in_current: 3, started_at: 't0', finished_at: null,
          error: null,
          results: [
            { family: 'gemini', run_id: 12, ticks_run: 3, status: 'done', note: '' },
            { family: 'x', status: 'bogus' }, // tolerated → status 'done', zeros
          ],
        },
      },
    });
    const s = await inspectorApi.tournamentStatus();
    expect(s.status).toBe('running');
    expect(s.current_family).toBe('gemini');
    expect(s.results).toHaveLength(2);
    expect(s.results[1]).toEqual({ family: 'x', run_id: null, ticks_run: 0, status: 'done', note: '' });
  });

  it('falls back to the idle shape on failure (no throw)', async () => {
    stubFetch({ 'GET /api/arena/tournament': 'throw' });
    const s = await inspectorApi.tournamentStatus();
    expect(s.status).toBe('idle');
    expect(s.results).toEqual([]);
  });
});

describe('inspectorApi.startTournament / abortTournament (EM-112)', () => {
  it('POSTs the selection and reports ok on 202', async () => {
    const fetchSpy = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ status: 'started' }), { status: 202 })));
    vi.stubGlobal('fetch', fetchSpy);
    const out = await inspectorApi.startTournament(['gemini', 'llama'], 25);
    expect(out.ok).toBe(true);
    const [path, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe('/api/arena/tournament');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({
      families: ['gemini', 'llama'],
      ticks_per_family: 25,
    });
  });

  it('surfaces the backend 400 detail verbatim', async () => {
    stubFetch({
      'POST /api/arena/tournament': {
        status: 400,
        body: { detail: "unknown family 'bogus' — no configured lane matches" },
      },
    });
    const out = await inspectorApi.startTournament(['bogus'], 40);
    expect(out.ok).toBe(false);
    expect(out.status).toBe(400);
    expect(out.message).toContain('unknown family');
  });

  it('maps network failure to a labeled message (never throws)', async () => {
    stubFetch({ 'POST /api/arena/tournament': 'throw' });
    const out = await inspectorApi.startTournament(['gemini'], 40);
    expect(out).toEqual({ ok: false, status: null, message: expect.stringContaining('unreachable') });
  });

  it('DELETE 409 renders the labeled no-op message', async () => {
    stubFetch({ 'DELETE /api/arena/tournament': { status: 409, body: { detail: 'no tournament is running' } } });
    const out = await inspectorApi.abortTournament();
    expect(out.ok).toBe(false);
    expect(out.message).toBe('no tournament is running');
  });
});
