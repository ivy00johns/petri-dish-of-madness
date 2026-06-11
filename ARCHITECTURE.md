# Architecture — Execution Layers

> Drop-in section for `ARCHITECTURE.md`. Anchors the vocabulary referenced by the
> multi-city work (**EM-109/110**), the proposed asynchronous **production lane**
> (not yet filed in the ledger), and the parallel-worlds runner (v4). When a new
> capability is proposed, decide its layer here *before* writing code.

## Why this section exists

Three different "two-world" ideas keep getting conflated, and the conflation
produces wrong questions like *"do I need a second router to let a character write
a blog?"* (No.) The fix is to recognize that "two" can mean three unrelated things,
living at three different layers:

- a **second execution lane** (background content vs. the turn heartbeat),
- a **second city** (another settlement inside one world), or
- a **second instance** (a whole separate world, for model-family A/B).

A *router* is a capacity device, not an architectural layer, and it appears in none
of these as a structural element — it just feeds whichever instance with tokens.
Dynamism and event-reactivity come from **what goes in the prompt** (the latest
world state), not from how many routers or lanes exist.

## The hierarchy

```
INSTANCE — one OS process · one World · one event log · one SQLite DB · one key-pool
│
│   ┌──────────────────────────────────────────────────────────────────────┐
│   │  TURN LANE  — one blocking, sequential heartbeat                       │
│   │  exactly one agent acts per tick; the world waits; agents are          │
│   │  grouped/scoped by City. Decisions, consequences, ordering, drama.     │
│   └──────────────────────────────────────────────────────────────────────┘
│   ┌──────────────────────────────────────────────────────────────────────┐
│   │  PRODUCTION LANE  — one non-blocking, async background lane            │
│   │  content (blogs, socials, business ops, media) is COMMISSIONED on a    │
│   │  turn (cheap intent), GENERATED off the heartbeat, and CONSUMED by a   │
│   │  later turn via DIGEST only — never the full text, and only if salient.│
│   └──────────────────────────────────────────────────────────────────────┘
│
└── the two lanes operate over ────────────────────────────────────────────────
        CITY A                CITY B                CITY C
        agents · buildings    agents · buildings    agents · buildings
        per-city context      per-city context      per-city context
        └──── travel · trade · diplomacy move agents/goods BETWEEN cities ────┘
```

A model-family bake-off (all-Gemini world vs. all-Qwen world) is a SECOND INSTANCE:
a separate process, separate DB, isolated key-pool. Sequential by default
(tournament style); concurrent only when there's spare account capacity to feed both.

The two lanes are **instance-level execution mechanisms**; cities are the **spatial
data partition** those lanes operate over. There is one turn lane and one production
lane per instance — "each city has a turn rhythm" is a useful abstraction, but
physically the single sequential heartbeat iterates agents grouped by city (this is
what keeps the free-scale, one-agent-per-tick design intact).

## The layers

### Instance
A single OS process running one `World`: one tick loop, one append-only event log,
one SQLite database, one key/account pool. An instance is the unit of A/B comparison
— you spin up a *second instance*, seeded with a different model family, to compare
whole-society outcomes (survival, governance, crime, culture). Instances do not share
state; they are compared *after the fact* via the run browser + cross-run AWI
dashboard. **Default to running instances sequentially** so they don't multiply
rate-limit pressure across the free-tier pool; run them concurrently only when you
have enough free accounts to feed both without starving either.

### City
A spatial partition *within* one instance's world. Agents are scoped by `city_id`;
context assembly is scoped per city so prompt size stays flat as cities are added;
buildings, places, and local laws/culture belong to a city. Cities share the
instance's tick loop, event log, DB, and key-pool — they are **not** separate
processes. Movement, trade, diplomacy, and migration move agents and goods *between*
cities. Adding a city adds spatial richness and inter-settlement dynamics at
near-zero extra LLM cost (travel/trade resolve as reflex actions).

### Turn lane
The blocking, sequential heartbeat of an instance. One agent acts per tick; the world
advances only when that agent's turn resolves. This lane is where **decisions,
irreversible actions, consequences, enforcement, and ordering** live — anything that
other agents must observe and react to *in sequence, this tick*. It is intentionally
serial and budget-light: it is the single biggest determinant of token spend, so most
of what happens here should resolve as reflex (🟢) where possible, with the LLM (🔵)
reserved for genuine decisions.

### Production lane
A non-blocking, asynchronous background lane that produces *content* without stalling
the heartbeat. An agent **commissions** a work during its turn (a cheap intent →
`work_in_progress` record), the turn immediately moves on, and the full text is
**generated off the heartbeat** (background task, cheap/overflow model) and lands some
ticks later as a finished artifact. Crucially, later turns consume only a one-line
**digest** of that artifact — and only when it's salient to what the character is
doing — never the full text. Institution-scheduled producers (newspaper, radio, a
weekly market report, a talk show) emit on a timed *institution tick*, off-queue.
This lane is what makes rich culture possible at 25 agents on free models: a blog
costs one off-turn generation + one free digest + a handful of salience-gated
reactions, not 24 reading-turns.

## Which layer does my feature belong to?

Walk these in order; stop at the first **yes**.

1. **Does it compare whole worlds seeded differently (e.g., model family A vs. B)?**
   → **Instance.** New process, new DB, isolated key-pool. Compare via run browser / AWI.

2. **Is it about *where* agents or buildings are, or about moving between settlements
   (migration, caravans, treaties, divergent local culture/law)?**
   → **City.** Same instance; partition by `city_id`; resolve travel/trade as reflex.

3. **Is it content an agent *produces or operates* (a blog, a social post, a business
   running in the background, a show, a newspaper) that others consume *later* and
   *only if it's relevant to them*?**
   → **Production lane.** Commission on-turn, generate off-heartbeat, propagate a digest.

4. **Otherwise — does it need to happen in strict order, with immediate consequences
   other agents react to *this tick* (a vote, a trade, an arson, a hire, a death)?**
   → **Turn lane.** Make the tool cheaper/closer than talking about it (see
   phantom-commitment fix, EM-079).

### Examples placed

| Feature                                   | Layer            | Why |
|-------------------------------------------|------------------|-----|
| Agent votes on a law                      | Turn lane        | Ordered, immediate consequence others react to now |
| Agent founds a company                    | Turn lane        | A committed decision with stake/irreversibility |
| Company pays wages each cycle             | Production lane¹ | Background institution tick; no per-entity LLM call |
| Agent writes a blog / posts on socials    | Production lane   | Produced off-turn; consumed later via digest |
| Newspaper prints a weekly edition         | Production lane   | Institution-scheduled producer, off-queue |
| Talk show airs every N ticks              | Production lane   | Timed producer; spectators react via salience gate |
| Agent migrates to another town            | City             | Spatial move between partitions of one world |
| Caravan trades goods between settlements  | City             | Inter-city flow; reflex dispatch/settle |
| All-Gemini vs. all-Qwen society bake-off  | Instance         | Whole-world A/B; separate process + key-pool |

¹ *The decision to set a price or hire is Turn lane; the recurring arithmetic
(wages, insolvency, share value) is the Production/institution tick — 🟢, no LLM.*

## Common confusions (anti-patterns)

- **"Do I need a second router/instance for a blog?"** — No. A blog is **Production
  lane** inside the existing instance. One router already serves it; dynamism comes
  from the prompt context, not the router.
- **"Is a second town a second instance?"** — No. A second town is a **City** in the
  same process, DB, and event log. One brain, several neighborhoods.
- **"More free accounts = a new layer?"** — No. Accounts feed an instance's
  **key-pool** (capacity). Add them when population-wide reflection or scaling past
  ~25 agents pushes you toward a provider's daily cap — not to enable dynamism.
- **"Concurrent A/B worlds for free?"** — Only with spare account capacity. Default to
  **sequential** instances so two worlds don't starve each other's free quota.

## Cross-references

- **EM-109** — multi-city data model; **EM-110** — migration/travel between cities
  (City layer).
- **Asynchronous production lane** (Production lane) — *proposed; not yet filed in the
  ledger.* (`EM-162` is cache-key normalization and is unrelated.)
- **This section** (`ARCHITECTURE.md` § Execution Layers) — the execution-layer model
  and doc anchor. It is documentation, not a tracked work item, so it carries no
  `EM-###`.
- **v4 parallel-worlds runner** — sequential tournament across Instances.
- **Lane/account-pool manager** (proposed) — registers free accounts, maps
  `world/instance → key-pool`, and demotes cadence at 70% of a pool's daily cap.
  Router-agnostic: the pool may be FreeLLMAPI, a second pool (e.g., 9router for its
  per-provider account round-robin), or both stacked. making it closer to EW.
