# PetriDishOfMadness — Design Spec

**Date:** 2026-05-26
**Status:** Approved (design); pending implementation plan
**Reference project:** `/Users/johns/Repos/ai-tools-and-frameworks/Emergence-World` (large, real-time, 10 agents, 120+ tools, 5 parallel worlds — this is the cheap/small reinterpretation)

---

## 1. Concept

A tiny, fast, cheap multi-agent world whose marquee feature is **per-agent model control**. Drop different models — Gemini-Flash, Groq-Llama, Cerebras-Qwen, Mistral, a local Ollama model — into the *same* society and watch them diverge: cooperate, betray, hoard, legislate, die.

- **4–6 agents**, accelerated tick-driven time (not wall-clock).
- A full arc plays out in **30–60 minutes**.
- Runs **free** on FreeLLMAPI's ~1.3B monthly tokens (OpenAI-compatible proxy over ~14 providers), and/or local Ollama, and/or direct Anthropic/Gemini.

The point is **spectacle + comparison**: which model survives, who cooperates, who dominates governance — watched live, color-coded by model.

### Non-goals (v1) — deferred to v2
3D world, TTS/voice, reactive overhearing chains, Victory-Arch pitch cycle, LLM memory summarization, agent-authored tools, real weather/news integrations, image generation, head-to-head analytics dashboard.

---

## 2. Architecture

Five parts:

1. **Sim engine** (Python / asyncio) — the tick loop, world state, needs decay, round-robin scheduler.
2. **Agent runtime** — per turn: assemble context → call the agent's model via the router → parse & validate a JSON action → mutate world → emit event.
3. **Provider router** — one unified `chat(messages, *, max_tokens) -> str` interface over adapters:
   - **OpenAI-compatible** adapter (covers FreeLLMAPI *and* Ollama's OpenAI endpoint, vLLM, Groq, LM Studio, etc.)
   - **Anthropic** adapter
   - **Gemini** adapter

   Per-agent model is just a `(profile, model_id)` pair, **hot-swappable at runtime**.
4. **Persistence** (SQLite) — agents, events, relationships, rules, world snapshots. Enables replay.
5. **API + frontend** — FastAPI (REST control + WebSocket stream) → React + Vite + Tailwind: 2D canvas map, live feed, per-agent panels, control panel.

### Data flow (one tick)
```
tick → scheduler picks agent → assemble prompt (personality + state + nearby + recent events + relationships + active rules)
     → router.chat() → parse JSON action → validate (legal? in range? has resources? cooldown? permitted by rules?)
     → mutate world state + persist to SQLite → broadcast event over WebSocket → frontend renders (map + feed + panels)
```

### Module boundaries
- `engine/` — world model, tick loop, scheduler, needs/economy/governance rules. Pure logic; no I/O beyond the persistence interface. Testable with MockProvider.
- `providers/` — router + adapters. Single `chat()` contract; adapters are interchangeable.
- `agents/` — context assembly, action protocol parsing/validation, agent state.
- `persistence/` — SQLite repository interface (so the engine depends on an interface, not raw SQL).
- `api/` — FastAPI routes (control + config) and the WebSocket broadcaster.
- `web/` — React frontend (map, feed, panels, controls).

---

## 3. Action protocol (key to cross-model robustness)

Agents do **not** rely on native function-calling (too flaky across free/local models). Each turn the model returns strict JSON:

```json
{ "thought": "short reasoning", "action": "<verb>", "args": { ... } }
```

- A validator checks legality: action exists, target in range, has required resources, not on cooldown, permitted by current active rules.
- On parse or validation failure: **one retry** with the specific error fed back into the prompt.
- On second failure: fall back to `idle` (logged as a parse-failure event — useful signal about which models struggle).
- Every event is tagged with the producing **model + profile** → color-coded in the feed and on agent badges.

### Action vocabulary (~14, v1)
| Action | Args | Effect |
|---|---|---|
| `move_to` | `place` | Move toward/into a named place |
| `say` | `text` | Speak to all agents at the same place |
| `whisper` | `target`, `text` | Private message to one nearby agent |
| `work` | — | Earn credits at a work-enabled place |
| `forage` | — | Earn a small amount of credits/food anywhere |
| `recharge` | — | Spend credits to restore energy |
| `give` | `target`, `amount` | Transfer credits to another agent |
| `steal` | `target` | Attempt to take credits (subject to rules) |
| `insult` / `attack` | `target` | Social/physical conflict (trust hit; spectacle) |
| `set_relationship` | `target`, `type` | Declare ally/rival/etc. |
| `remember` | `fact` | Persist a belief to long-term memory |
| `propose_rule` | `effect`, `text` | Propose a typed governance rule |
| `vote` | `rule_id`, `choice` | Vote yes/no on an active proposal |
| `idle` | — | Do nothing this turn |

---

## 4. Mechanics

### Needs + death
- Each agent has **energy** (0–100) that decays a configurable amount per tick.
- `recharge` (costs credits) and `forage`/`work` restore/earn.
- Energy at/below zero for a sustained window (configurable, e.g. N ticks) → **death**: agent removed from world, broadcast as a death event. This is the engine of stakes and emergent strategy.

### Economy
- A scarce `credits` resource. Earned by `work` (more, at work-enabled places) or `forage` (a little, anywhere).
- Spent on `recharge`. Transferable via `give`, takeable via `steal`.
- Creates competition, theft, generosity, inequality.

### Talk + relationships
- `say` reaches agents at the same place; `whisper` targets one nearby agent.
- Relationships are typed (ally / rival / neutral / etc.) with a trust value and interaction history.
- Conflict actions (`insult`/`attack`) damage trust; `give` builds it.

### Lightweight governance
- Any agent can `propose_rule` from a small set of **typed effects**, e.g.:
  - `ban_stealing` → `steal` disabled or penalized.
  - `ubi` → every living agent gets +N credits/tick.
  - `recharge_subsidy` → recharge cost reduced.
  - (Set is small, extensible, and each effect maps to a concrete world-param mutation.)
- Voting: majority of **living** agents within a window → rule **activates and actually mutates world params**.
- This is the richest emergence source — agents change the rules they live under.

---

## 5. Memory (deliberately cheap)

Per agent:
- A **rolling buffer** of the last K observations/events (configurable).
- A short list of `remember`-ed **beliefs**.
- The **relationship map**.

**No LLM summarization calls** (the reference project's big hidden cost). Context per turn stays small:
```
personality + current state/needs + nearby agents & places + recent events (rolling buffer)
+ relationships + active rules + recent local chat
```

---

## 6. Control surface ("flexible model control")

### Config
- `config/profiles.yaml` — model profiles: `name → { adapter, base_url, api_key_env, model_id, max_tokens }`.
- `config/world.yaml` — scale/pacing: agent count, tick interval (real seconds), ticks-per-day, decay rates, scarcity, seed agent personalities + initial model assignment.

### Live controls (UI)
- Start / pause / step one tick.
- Speed slider (tick interval).
- **Reassign any agent's model live** (takes effect next turn).
- Inject a random event.
- Spawn / kill an agent.
- Model legend (color → model).

---

## 7. Cost & determinism

- Small context, no summarization, cheap/free models, configurable `max_tokens`.
- **One model call per tick** (reactions off in v1) keeps cost and pacing predictable.
- **MockProvider** — a scripted-JSON-action provider — makes the entire engine runnable and testable with **zero LLM calls**. Used for:
  - the deterministic test suite (needs decay, action validation, economy transfers, governance voting, death invariants), and
  - offline development of the engine and UI.

---

## 8. Deployment

- `docker-compose up` brings up backend + frontend, with **optional** services: local Ollama and a bundled FreeLLMAPI.
- All model endpoints come from env/config — the **same image** deploys to a cloud host (Railway/Fly/Render) by swapping the FreeLLMAPI URL and keys. Local-first, no lock-in.
- Root `README.md` with one-command setup and a `dev` script for the multi-service workflow.

---

## 9. Tech stack

| Layer | Choice |
|---|---|
| Sim engine / backend | Python 3.11+, asyncio, FastAPI, Uvicorn |
| Persistence | SQLite (via a repository interface) |
| Realtime | WebSocket (state + event stream) |
| Frontend | React 18 + Vite + TypeScript + Tailwind |
| Map | 2D HTML canvas (no Three.js) |
| Models | FreeLLMAPI (OpenAI-compatible), Ollama, Anthropic, Gemini |
| Packaging | Docker + docker-compose |
| Tests | pytest (engine, with MockProvider); frontend smoke tests |

---

## 10. Testing strategy

- **Engine unit tests** (MockProvider, fully deterministic): needs decay → death, action validation + retry + idle fallback, economy transfers (give/steal/work/recharge), governance proposal → vote → rule activation → world-param mutation, relationship/trust updates.
- **Integration test:** run K ticks with MockProvider, assert invariants (credits conserved except by defined sources/sinks, dead agents take no actions, active rules enforced).
- **Provider adapter tests:** contract tests against a stub OpenAI-compatible endpoint; live smoke test optional/gated.
- **Frontend:** render smoke tests + a WebSocket event-stream mock.

---

## 11. Build path

1. This spec → **writing-plans** for a detailed implementation plan.
2. Plan → **orchestrator** executes as a parallel multi-agent build (backend / frontend / infra / QE), contract-first.
3. `/Users/johns/Projects/petri-dish-of-madness` is **not yet a git repo** — `git init` + feature branch at the start of the build.

---

## 12. Definition of Done (v1)

- `docker-compose up` brings up the lab; the 2D map + live feed render and update live.
- A world of 4–6 agents with **mixed models** runs a full arc (births of conflict, alliances, deaths, at least one passed rule) end-to-end.
- Per-agent model is reassignable live from the UI and the change is visibly reflected.
- Engine test suite passes deterministically with MockProvider (zero LLM calls).
- Runs free against FreeLLMAPI and locally against Ollama.
- Root README documents one-command local run and the path to cloud deploy.
