/**
 * api.ts — the EM-334 First-Contact read client.
 *
 * Pure fetch-stub tests (no backend): parsing of /api/contact (settlement
 * cards, the contact_made latch, the honesty ledger, crossing/travel legs)
 * and the /api/arena `contact_runs` additive section — malformed rows degrade
 * to safe defaults, `enabled !== true` maps to the disabled shape, and
 * network failures resolve to `null`, never a throw.
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

const made = {
  tick: 31,
  agent_id: 'agent-1',
  from_settlement: 'Mossmarket',
  to_settlement: 'Windrow',
};

const fullContact = {
  enabled: true,
  tick: 45,
  settlements: [
    {
      id: 'Mossmarket',
      name: 'Mossmarket',
      founded_tick: 2,
      member_count: 3,
      families: { gemini: 3 },
    },
    {
      id: 'Windrow',
      name: 'Windrow',
      founded_tick: 4,
      member_count: 2,
      families: { llama: 2 },
    },
  ],
  contact_made: made,
  ledger: {
    crossings: 3,
    by_family: { gemini: { hops: 2, mutated: 1 }, llama: { hops: 1, mutated: 0 } },
  },
  crossings: [{ tick: 34, kind: 'travel_crossed', actor_id: 'agent-1', text: 'crossed the ridge' }],
  travels: [{ tick: 31, kind: 'travel_departed', actor_id: 'agent-1', text: 'set out' }],
};

describe('inspectorApi.contact (EM-334) — the enabled payload', () => {
  it('parses settlements, the latch, the ledger, and both event legs', async () => {
    stubFetch({ 'GET /api/contact': { status: 200, body: fullContact } });
    const out = await inspectorApi.contact();
    expect(out).not.toBeNull();
    expect(out!.enabled).toBe(true);
    expect(out!.tick).toBe(45);
    expect(out!.settlements).toEqual([
      {
        id: 'Mossmarket', name: 'Mossmarket', founded_tick: 2,
        member_count: 3, families: { gemini: 3 },
      },
      {
        id: 'Windrow', name: 'Windrow', founded_tick: 4,
        member_count: 2, families: { llama: 2 },
      },
    ]);
    expect(out!.contact_made).toEqual(made);
    expect(out!.ledger).toEqual({
      crossings: 3,
      by_family: { gemini: { hops: 2, mutated: 1 }, llama: { hops: 1, mutated: 0 } },
    });
    expect(out!.crossings).toEqual([
      { tick: 34, kind: 'travel_crossed', actor_id: 'agent-1', text: 'crossed the ridge' },
    ]);
    expect(out!.travels).toEqual([
      { tick: 31, kind: 'travel_departed', actor_id: 'agent-1', text: 'set out' },
    ]);
  });

  it('an unarmed world (`enabled: false`) maps to the labeled disabled shape', async () => {
    stubFetch({ 'GET /api/contact': { status: 200, body: { enabled: false } } });
    expect(await inspectorApi.contact()).toEqual({
      enabled: false,
      tick: 0,
      settlements: [],
      contact_made: null,
      ledger: null,
      crossings: [],
      travels: [],
    });
  });

  it('missing enabled key on an armed-looking payload counts as disabled', async () => {
    stubFetch({
      'GET /api/contact': {
        status: 200,
        body: { settlements: [{ id: 'Mossmarket' }] }, // enabled absent
      },
    });
    const out = await inspectorApi.contact();
    expect(out!.enabled).toBe(false);
    expect(out!.settlements).toEqual([]);
  });
});

describe('inspectorApi.contact (EM-334) — defensive degradation', () => {
  it('degrades malformed settlement/ledger/marker rows to safe defaults', async () => {
    stubFetch({
      'GET /api/contact': {
        status: 200,
        body: {
          enabled: true,
          tick: 'junk',                       // → 0
          settlements: [
            { id: 'Mossmarket', name: 7, founded_tick: 'x', member_count: null,
              families: { gemini: 'three', llama: 2 } }, // strings/nulls → 0/''; fam count coerced
            'junk',                             // dropped
            { nope: true },                     // dropped (no id)
          ],
          contact_made: { tick: 9 },            // partial latch → '' ids
          ledger: { crossings: 2, by_family: { gemini: { hops: 1 }, llama: 'junk' } },
          crossings: ['junk', { tick: 'x', kind: 'travel_crossed', actor_id: 9 }],
          travels: null,                       // → []
        },
      },
    });
    const out = await inspectorApi.contact();
    expect(out!.tick).toBe(0);
    expect(out!.settlements).toHaveLength(1);
    expect(out!.settlements[0]).toEqual({
      id: 'Mossmarket', name: '', founded_tick: 0, member_count: 0,
      families: { gemini: 0, llama: 2 },
    });
    expect(out!.contact_made).toEqual({
      tick: 9, agent_id: '', from_settlement: '', to_settlement: '',
    });
    expect(out!.ledger).toEqual({
      crossings: 2,
      by_family: { gemini: { hops: 1, mutated: 0 } }, // the non-object llama row is skipped
    });
    expect(out!.crossings).toEqual([
      { tick: 0, kind: 'travel_crossed', actor_id: null, text: '' },
    ]);
    expect(out!.travels).toEqual([]);
  });

  it('a non-object body (JSON string) parses to null', async () => {
    stubFetch({ 'GET /api/contact': { status: 200, body: '"hello"' } });
    expect(await inspectorApi.contact()).toBeNull();
  });

  it('a 404 / unreachable backend resolves to null (never a throw)', async () => {
    stubFetch({ 'GET /api/contact': { status: 404, body: { detail: 'nope' } } });
    expect(await inspectorApi.contact()).toBeNull();
    stubFetch({ 'GET /api/contact': 'throw' });
    expect(await inspectorApi.contact()).toBeNull();
  });
});

describe('inspectorApi.arena (EM-334) — the contact_runs section', () => {
  it('parses contact run cards with the pairing, per-town population, and ledger', async () => {
    stubFetch({
      'GET /api/arena': {
        status: 200,
        body: {
          families: [],
          contact_runs: [
            {
              run_id: 7,
              max_tick: 10,
              family_a: 'gemini',
              family_b: 'llama',
              name_b: 'Bram',
              outcomes: { population: 5, laws_passed: 1, buildings: 0, crimes: 0, credits: 9 },
              population_by_town: { Mossmarket: 3, Windrow: 2 },
              contact_made: { tick: 8, agent_id: 'agent-1', from_settlement: 'Mossmarket', to_settlement: 'Windrow' },
              ledger: { crossings: 3, by_family: { gemini: { hops: 2, mutated: 1 } } },
              events: { contact_made: 1, travel_crossed: 3 },
            },
            { run_id: 'junk' },                                   // dropped (no numeric run_id)
            { run_id: 9, outcomes: null, population_by_town: 'x', ledger: null,
              contact_made: null, name_b: 3 },                     // zeroed/normalized
          ],
        },
      },
    });
    const out = await inspectorApi.arena();
    expect(out).not.toBeNull();
    expect(out!.contact_runs).toHaveLength(2);
    const card = out!.contact_runs[0];
    expect(card.run_id).toBe(7);
    expect(card.family_a).toBe('gemini');
    expect(card.family_b).toBe('llama');
    expect(card.name_b).toBe('Bram');
    expect(card.outcomes).toEqual({
      population: 5, laws_passed: 1, buildings: 0, crimes: 0, credits: 9,
    });
    expect(card.population_by_town).toEqual({ Mossmarket: 3, Windrow: 2 });
    expect(card.contact_made).toEqual({
      tick: 8, agent_id: 'agent-1', from_settlement: 'Mossmarket', to_settlement: 'Windrow',
    });
    expect(card.ledger).toEqual({ crossings: 3, by_family: { gemini: { hops: 2, mutated: 1 } } });
    expect(card.events).toEqual({ contact_made: 1, travel_crossed: 3 });
    // The normalized tolerances row (EM-343 — an absent `failures` block
    // coerces to the all-zero taxonomy).
    expect(out!.contact_runs[1]).toEqual({
      run_id: 9,
      max_tick: 0,
      failures: {
        counts: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
        shares: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
        total: 0, turns: 0, failure_rate: 0, legacy_rows_reclassified: 0,
        curve: [], by_agent: {}, by_route: {},
        failures_attributed: 0, attempts_attributed: 0,
      },
      family_a: '',
      family_b: '',
      name_b: '',
      outcomes: { population: 0, laws_passed: 0, buildings: 0, crimes: 0, credits: 0 },
      population_by_town: {},
      contact_made: null,
      ledger: null,
      events: {},
    });
  });

  it('a pre-EM-334 backend (contact_runs key omitted) parses to []', async () => {
    stubFetch({
      'GET /api/arena': {
        status: 200,
        body: { families: [] },
      },
    });
    const out = await inspectorApi.arena();
    expect(out).not.toBeNull();
    expect(out!.contact_runs).toEqual([]);
  });
});