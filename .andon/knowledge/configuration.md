---
title: Configuration
tags: [configuration]
paths: [config/profiles.yaml, config/world.yaml, config/personas.yaml, profile/metric, requests/day, tokens/day, config/lanes.yaml, supersedes/augments, world.yaml, GEMINI/ANTHROPIC/OPENAI/OLLAMA]
updated: 2026-11-10
---

Imported from `docs/GUIDE.md:385` by Andon (import docs/GUIDE.md:385 409a0a38665990eb); the original stays there.

All model routing is driven by `config/profiles.yaml` and `config/world.yaml`; `config/personas.yaml` holds the spawn form's character cards. No code changes are needed to add a model — add a profile entry, assign an agent to it. Same for personas — add a card to the YAML.

The backend reads config from the directory named by `EM_CONFIG_DIR` (default: `./config`).

See `config/profiles.yaml` for the commented Ollama profile example and inline documentation.

**Usage alerts (optional)** — give any profile in `config/profiles.yaml` daily caps and a
one-shot `usage_alert` event fires when it crosses **70%** of a cap (once per
profile/metric per UTC day). Alerts only — calls are never throttled or blocked:

```yaml
profiles:
  - name: groq-llama
    # ...
    rpd: 1000      # requests/day cap
    tpd: 100000    # tokens/day cap (input + output)
```

**Inner life & world physics (W11b)** — all of these live under `world:` in
`config/world.yaml`, and every value below is the engine default if the key is absent:

```yaml
world:
  commitments:
    phantom_after_turns: 12   # talk-only turns before a promise lapses as a 👻 phantom
    max_active: 5             # active commitments per agent (oldest evicted)
  reflection:
    importance_threshold: 10  # witnessed-event importance before a diary entry (✎)
  blackout_ticks: 10          # how long a blackout disables recharge at affected homes
  procgen:                    # procedural towns — DEFAULT OFF (hand-authored town stays)
    enabled: false
    seed: 42
    n_places: 9               # town places incl. the plaza (housing on top), cap 12
    kind_weights:             # weighted picks for the non-guaranteed slots
      work: 2
      social: 2
      governance: 1
      wild: 2
      home: 1
```

Commitments and reflections piggyback on each agent's single turn response — enabling them
costs zero extra LLM calls. Procgen adds a cottage per seed agent plus a communal
Bunkhouse with one bed fewer than there are agents, so bed scarcity exists by design.

**Lane health & resilience (Wave D3)** — keeping a society alive on flaky free tiers. All
live under `world:` in `config/world.yaml`; every value below is the engine default:

```yaml
world:
  turn_llm_budget_seconds: 12   # cancel a turn's LLM call past this wall-clock budget (0 = off);
                                #   the turn then resolves a survival reflex instead of idling
  resume_on_boot: true          # on boot, resume the most recent run from its latest snapshot
                                #   (new run + fork lineage); false = always start fresh
  lane_failover:                # detour calls off sick lanes per-call; assignment never changes
    enabled: true
    sick_threshold: 3           # timed-out turns in the rolling 6-call window that mark a lane sick
    probe_every: 4              # every Nth would-be-detour probes the home lane to auto-recover
  cap_governor:                 # at 70% of a lane's daily cap, demote its agents one cadence tier
    enabled: true               # false ⇒ usage alerts stay alert-only (no demotion)
```

`lane_detour`, `cap_pressure`, and `run_resumed` events narrate all of this in the feed, and
`GET /api/lanes` exposes live per-lane health. Set the `enabled` flags to `false` (or
`turn_llm_budget_seconds: 0`) for byte-identical pre-D3 behavior.

**Adaptive lane routing (`config/lanes.yaml`)** — supersedes/augments Wave D3's per-call
detour above: when a pinned lane fails, an ORDERED, health-aware bounce loop walks a curated
preference list instead of the older single-detour hop. This is a separate file from
`world.yaml` — it is the one place lane *preference* is curated:

```yaml
adaptive_routing:
  enabled: true                # go-live 2026-07-08. false = byte-identical pin→auto backup
  max_attempts: 5               # curated healthy lanes tried + the RESERVED terminal slot
  per_attempt_timeout_s: 12     # per-lane wall-clock cap (no long doomed cascades)
  allow_paid: false             # $0-first: `free: false` lanes stay off unless true
  terminal_fallback: auto       # the GUARANTEED final-attempt lane (any profile may hold it)
  family_pin: false             # EM-341: serve a classified home from its own family only
  discovery:                    # P2 — data-driven lane pool (EM-300)
    enabled: false              # master toggle; false = static registry (this file only)
    every_turns: 40             # counter-based auto-refresh cadence (served turns)
    freellmapi_models: true     # poll /v1/models: retire unavailable, synth new lanes
    direct_keys: true           # detect GEMINI/ANTHROPIC/OPENAI/OLLAMA env keys
    admin_quota: false          # also read admin /api/health quotaStates (needs creds)
  order:                        # priority order, best-headroom-first; `model: "*"` sweeps
    - { source: freellmapi, model: "mistral-large-3-675b", free: true }
    # ... one entry per curated lane; see the file's inline comments for the full list
  exclude:                      # matchers no entry (not even `*`) may place
    - { source: freellmapi, model: "command-a-2" }
```
