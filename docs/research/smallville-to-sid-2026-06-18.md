# Smallville → Project Sid — research + repo-grounded assessment

> **Source of record** for the cognition-architecture research filed 2026-06-18.
> Original research was pasted into a working session (no upstream file); captured
> here so it doesn't rot. Routed into the ledger via `plan-intake` →
> **EM-222 / EM-223 / EM-224** (Wave L · W22 · Cognition).
> **Status:** research map accepted; three gaps filed as spikes; wrong premises rejected (below).

## How to read this

The literature summary (Smallville generative agents + Project Sid / PIANO) is
**accurate and worth keeping**. The doc's *repo plan*, however, was wrong in three
load-bearing ways (it assumed a Phaser/TS stack we don't have, treated already-shipped
systems as future work, and built its spine on cost-minimization — the opposite of our
max-call-rate north star). Stripped of those premises, **exactly three real gaps remain.**
Those three are filed. The rest is preserved for context, not as a plan.

---

## The three filed gaps (→ ledger)

### EM-222 — Relevance-scored long-term memory retrieval *(highest value)*
The one Smallville mechanism we're actually missing. Today memory is a recency **window**
(`_effective_memory_window`, last-N events); there are **no embeddings anywhere**. Smallville
retrieves with recency × importance × **relevance** against an embedded memory stream, so
agents recall *relevant* old events, not merely recent ones. Importance scoring
(`_IMPORTANCE_WEIGHTS`, EM-159) and reflection (EM-080) already ship — this is **purely the
relevance + long-term-store axis**. North-star-aligned: it **adds** calls (embeddings +
richer prompts), it is not a cost-cut.

- **OPEN QUESTION (gating):** does FreeLLMAPI expose an embeddings endpoint? If **yes** →
  embed the memory stream + cosine relevance. If **no** → lexical/BM25 fallback **or** a
  dedicated local Ollama embedding model. This answer decides the whole approach — resolve
  it before scoping the spike.

### EM-223 — Recursive + reactive planning
Agents emit a flat one-line plan (e.g. "D1 plan: water seedlings → buy seeds"). Smallville
decomposes daily → hourly → 5–15-minute actions, with **reactive re-planning** when
perception changes. Deeper plans = more believable routines **and more calls** (north-star
aligned).

- **OPEN QUESTION:** how deep to decompose given our tick cadence, and how re-planning
  interacts with **salience-gated reflex turns (EM-159/EM-160)** — re-planning must **not
  fight the spontaneity floor** (the anti-dead-town guard).

### EM-224 — PIANO coherence for multi-action turns
Adopt PIANO's **bottleneck → single decision → broadcast** trick to keep speech and action
aligned across **multi-action turns (EM-199)** — preventing the "agent says 'sure!' while
doing something else" incoherence.

- **Take ONLY the coherence idea.** Explicitly **reject** PIANO's "parallelize cognition to
  cut latency" motive: we want **more** calls, not fewer-blocking ones, so the concurrency
  rationale is contrary to our north star.
- **OPEN QUESTION:** how to structure the bottleneck inside the existing single-LLM-turn →
  multi-action flow.

---

## Rejected premises (recorded so they don't get re-litigated)

1. **"Phaser 4 + TypeScript services" stack — false.** We have **zero Phaser**. Backend is
   **Python/FastAPI** (`backend/petridish/agents/runtime.py`, `engine/loop.py`); frontend is
   **React + R3F (three.js)** with a 2-D `WorldMap` alt view. The real port target is the
   Python agent runtime + engine; the frontend stays R3F. The doc's "port `persona/` as TS
   onto your Phaser loop" framing aims at a codebase we don't have.
2. **Treats shipped work as future work.** Working analogs of its Stages A–C already exist:
   importance scoring + salience threshold (EM-159), threshold-triggered reflection/diary
   (EM-080), relationship/social state (EM-113: affinity/trust, reflex friend/feud, bonds),
   governance (townhall/propose+vote/admit/rules — EM-200) plus the emergent Chronicle saga
   (EM-201). The doc would have us rebuild these.
3. **Cost thesis is the inverse of our law.** Its spine is *minimize LLM calls*
   (Lifestyle-Policy caching, situation-keyed decision caching, Summarize-and-Forget, "target
   AGA's 31%-of-baseline"). Our north star is the opposite: **max call-rate, decision cache
   OFF, bounce-don't-mute, never do less.** Its caching would gut the premise — and it's
   internally inconsistent (it also says heterogeneous models *create* diversity, while
   action caching replays canned behavior and **kills** it). Take the *architecture*, reject
   the *economics*.

**Strategic verdict:** a great **literature map**, a poor **repo plan**. Its own best
instinct — *depth + a working emergence loop before agent count* — argues **for** our v3
"deepen the first city before a second," and **against** its own 1000-agent PIANO finale
(which cuts against "tiny, cheap, fast chaos lab"). Mine it for **relevance-retrieval +
recursive planning + coherence**; validate that the existing relationship system actually
feeds role/goal selection (the keystone claim); ignore the Phaser framing, the
rebuild-what-you-have stages, and the entire caching/cost program.

---

## Full assessment (verbatim, 2026-06-18)

Grounded against the repo — and that changes the read significantly. Short version: **the
literature is excellent, the repo-grounding is wrong in three load-bearing ways, and its
central cost thesis directly contradicts the north star.**

**What it gets right.** The Smallville and PIANO summaries are accurate and faithful to the
papers (memory stream + recency×importance×relevance retrieval, threshold-triggered
reflection, recursive planning; PIANO's concurrency + bottlenecked Cognitive Controller;
Social-Awareness-as-keystone from the ablation). The cited numbers match the papers, and it's
honest about which need re-verification. Two pieces of *advice* are genuinely good and align
with our direction: "prove emergence before scaling — this gate matters more than agent count"
and "Social Awareness is the keystone." The observation that **our event log already *is* a
nascent memory stream** is apt.

**Where it's wrong about our project** — see "Rejected premises" above (stack premise false;
treats shipped work as future; cost thesis inverted).

**What's worth mining (the real gaps)** — see "The three filed gaps" above: relevance-based
retrieval over a long-term store (EM-222), recursive + reactive planning (EM-223), PIANO's
coherence trick (EM-224).

**Note on PIANO concurrency:** it is sold as a *latency* win (don't let reflection block
reaction). We care less about that — we *want* more calls, not fewer-blocking ones. So take
the **coherence** idea, skip the "parallelize to save time" motive.

---

## Original research (verbatim, as pasted) — "An Architecture & Roadmap from Smallville to Project Sid"

> Preserved for fidelity. Treat the **literature** sections as accurate; treat the **repo
> plan / stages / cost program** as superseded by the assessment above.

### TL;DR
- Port Smallville's three load-bearing cognitive modules first (memory stream + retrieval,
  reflection, recursive planning).
- Then evolve toward Project Sid's PIANO architecture — concurrent modules coordinated by a
  bottlenecked Cognitive Controller, plus a **Social Awareness** module (the ablation's
  keystone for role specialization, governance, culture).
- Bridge is staged, not a rewrite: (A) port Smallville cognition; (B) social/relationship
  systems + rich object-affordance town; (C) survival/economy pressure so roles emerge;
  (D) parallel cognition + governance/culture. Tiered model routing + caching to keep many
  agents affordable.

### Key findings
1. **Smallville (Park et al. 2023, arXiv:2304.03442) = three modules over a memory stream**,
   all necessary: memory stream (every observation as NL records), retrieval
   (recency × importance × relevance), reflection (periodic synthesis of salient memories into
   higher-level insights), recursive planning (daily → hourly → 5–15-min, reactive
   re-planning). Ablation: observation, planning, reflection each contribute critically.
2. **The Valentine's party emergence** is produced by specific modules: dialogue + memory
   drive diffusion; retrieval + reflection let agents remember/act; planning/re-planning makes
   them coordinate timing/location. (Fig 9: 12 agents besides Isabella heard about the party;
   awareness rose 4%→52% over two sim-days; five attended.)
3. **Project Sid (Altera.AL, arXiv:2411.00114) scales to 10–1000+ via PIANO** — ~10 concurrent
   modules (Memory, Action Awareness, Goal Generation, Social Awareness, Talking, Skill
   Execution, …) vs Smallville's single sequential loop; a **Cognitive Controller** reads a
   shared agent state through an information **bottleneck** and broadcasts decisions to keep
   speech/action coherent.
4. **Ablation = what's load-bearing:** 30 identical agents specialized into roles (farmers,
   artists) — but **only with social awareness**; limiting social perception → uniform
   repetitive actions, no roles. Agents followed/amended tax laws via voting; spread
   Pastafarianism via priests. Social perception is the keystone; survival pressure + goal
   generation are the drivers.

### Smallville internals (the port target)
- **Retrieval:** recency (exp decay, factor **0.995**), importance (LLM rates each memory
  1–10 at write time), relevance (cosine sim of query vs memory embedding); weighted sum
  (~equal weights). Practitioner tuning: top-k ~3–5; recency half-lives of tens of sim-hours;
  control importance inflation.
- **Reflection:** when summed importance of recent events crosses a threshold (~150), take
  ~100 most-recent memories, ask LLM for the 3 most salient questions, generate ~5 insights
  with citations back to source memories; reflections are stored and can reflect on
  reflections (trees). This is what separates it from plain RAG.
- **Planning + reacting:** daily plan (5–8 chunks) from identity + prior-day summary →
  recursively decomposed to hourly then 5–15-min; at each step, perceive and decide
  continue-vs-react (regenerate plan from that point). Dialogue conditioned on agents'
  memories of each other.
- **World model:** a tree (world → areas → objects); objects carry state ("stove on/burning");
  each agent keeps a subtree of only what it has seen; action location chosen by flattening the
  tree into NL and prompting recursively; then pathfinding.
- **Repo structure (joonspk-research/generative_agents):** Django `frontend_server` (renders
  Phaser 2D, writes per-step JSON) + portable `reverie/backend_server` (the sim brain). Port
  the **`persona/`** package: `persona.py` (perceive→retrieve→plan→reflect→execute),
  `cognitive_modules/` (perceive/retrieve/plan/reflect/execute/converse), `memory_structures/`
  (associative_memory = the stream of typed event/thought/chat ConceptNodes w/ embeddings +
  poignancy; spatial_memory tree; scratch working state), `prompt_template/`. Port the *logic*;
  replace frontend, `maze.py`, prompt plumbing, file-IPC.

### Project Sid / PIANO (scale-up target)
- **Why Smallville doesn't scale:** single agents loop/hallucinate (poisoning downstream
  state); groups propagate hallucinations + "sure!"-vs-different-action incoherence; no
  civilizational benchmarks; the sequential loop blocks (slow reflection stalls reaction).
- **Two principles:** concurrency (~10 modules over different timescales, so deliberation
  doesn't block reaction) + coherence via a bottlenecked Cognitive Controller (reads shared
  Agent State through a narrow bottleneck, makes one high-level decision, broadcasts it to
  condition talk/motor modules; inspired by Global Workspace Theory).
- **Emergent phenomena + drivers:** role specialization (Social Awareness + Goal Generation;
  disappears under limited social perception); governance (25 agents followed taxation, then
  voted to change the rate — constitutional-style amendment); culture/religion (a single
  500-agent sim; memes produced distinct town identities; Pastafarianism spread from 20
  priests with measurable direct vs indirect converts). Scale limit: >1000-agent runs exceeded
  the Minecraft server's compute.
- **Ablation implication:** Social Awareness is the keystone; Goal Generation + survival
  pressure are the engines. Caveat (Altera's own): agents struggle with spatial
  reasoning/physical coordination and lack intrinsic drives — emergence is real but fragile;
  research results, not a shipped product.

### Bridge (staged) — *superseded for our repo; see Rejected premises*
A→D staging (cognition → social/affordances → survival/economy → PIANO + governance/culture),
tiered model routing (local Ollama for routine ticks/importance/embeddings; mid pooled models
for dialogue/planning; strongest for reflection/governance), and caching (Lifestyle-Policy,
Summarize-and-Forget). **Our note:** stages A–C are largely already shipped; the caching/cost
program contradicts the north star and is rejected.

### Practical engineering notes (mixed value)
- **Tiered model routing** by cognitive cost — *partially aligned* (we already bounce models;
  but we do not throttle/mute to save cost).
- **Cost-reduction lit** (Affordable Generative Agents arXiv:2402.02053 ~31% baseline; Lyfe
  Agents arXiv:2310.02172 10–100×; AI Metropolis arXiv:2411.03519 out-of-order scheduling
  1.3–4.15×) — **rejected** on north-star grounds (cache OFF, never do less).
- **Scheduling:** run cognition off the render loop with staggered heartbeats + async decision
  scheduling (cf. a16z-infra/ai-town batching ticks ~1/sec). *Architecturally fine; our engine
  already decouples tick from render.*
- **Frameworks to learn from:** a16z-infra/ai-town (TS, engine-tick decoupling),
  joonspk-research/generative_agents (cognition reference), AGA/Lyfe (cost patterns — economics
  rejected), ReplicantLife (Ollama many-agent prior art).

### Caveats (from the research)
- Project Sid is a research result, not a recipe (>1000-agent runs hit compute limits; agents
  weak at spatial reasoning, lack intrinsic drives).
- Smallville used GPT-3.5-turbo + equal retrieval weights; our multi-model mix + free-tier rate
  limits will change tuning (re-tune decay half-life, reflection threshold, top-k).
- Emergence is fragile + ablation-sensitive: under-resourcing Social Awareness (e.g. to save
  cost) silently kills emergence — cost-cutting the wrong module yields a pretty but lifeless
  town.
- Free-tier pooling adds failure modes Smallville never faced (rate limits, provider variance,
  latency spikes) — the scheduler must tolerate per-call failover or agents stall.
- A few internal numbers (reflection threshold ~150, per-module Sid counts) come from the
  papers/summaries — verify against the arXiv version of record before implementation.
