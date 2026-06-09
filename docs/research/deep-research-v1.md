# Building a Local "Emergence-World": A Studio-Grade, Free-Model Multi-Agent Simulation for Observing Emergent Cooperation

## TL;DR
- **Build a roll-your-own Python tick-engine (not LangGraph/AutoGen/CrewAI) wrapped around a provider-agnostic OpenAI-compatible gateway (FreeLLMAPI as the front door, with Groq + Cerebras + Gemini + OpenRouter free tiers behind it), feeding a separate PixiJS/WebGL pixel-art frontend over WebSocket.** This mirrors how the real Emergence World is architected (custom `em-agent-framework`, FastAPI backend, React Three Fiber frontend, WebSocket streaming) while staying CPU-light and free.
- **The single most reliable recipe for emergent cooperation is resource scarcity + interdependence + a communication channel + persistent memory + reputation/relationships.** This is confirmed convergently by GovSim (ablations show multi-agent communication is critical for cooperation, with a 21% reduction in resource overuse when communication is present), Project Sid (30 identical PIANO agents that "started out identical" self-specialized into professions — farmers concentrated on seed collection and land preparation, artists on gathering flowers — and formed an emerald economy), and Emergence World's own design (energy decay, peer-judged credits, and "collaborative tools only available when partners have agreed to cooperate"). Start with a 4-agent commons/trade scenario, not a 1,000-agent city.
- **Decouple sim-tick rate from render rate, run one agent turn at a time, and offload all heavy compute to free remote APIs** — the laptop only does cheap orchestration + sprite batching, so thermals stay safe. Prove the loop on free 8B-class models (Llama 3.3 70B, Qwen3, Gemma) then flip a config flag to escalate pivotal moments to frontier models.

---

## Key Findings

1. **Emergence World is a turn-based, tool-gated, persistent agent society — not a chatbot.** Its real architecture (reverse-engineered from the repo's `ARCHITECTURE.md`, `ORCHESTRATION.md`, `MEMORY.md`): a Python 3.11/FastAPI backend runs a single-agent-at-a-time round-robin loop; agents act *only* through 120+ tools gated by location; state lives in PostgreSQL (60+ tables); a React Three Fiber (Three.js) frontend streams live state over WebSocket. Agents have a 6-layer memory stack, three decaying needs (energy/knowledge/influence), a peer-judged ComputeCredits economy, and a 5-article amendable constitution with a 70% voting threshold. Season 1 ran 5 parallel worlds × 10 agents × 15 real-time days, varying only the foundation model.

2. **You should copy its *mechanics* but invert two of its *choices*.** Keep: tools-as-only-interface, round-robin turns, reactive overhearing, needs-driven pressure, memory summarization, peer-judged rewards. Change: (a) use **2D pixel-art (PixiJS), not 3D (R3F)** — far cheaper on a MacBook and closer to your Darwinia/8-bit aesthetic; (b) **compress 15 days of wall-clock time into fast ticks** — the real project runs 1:1 real-time deliberately for viewers, which is wrong for experimentation where you want to see emergence in minutes/hours.

3. **The cooperation literature gives a clear, buildable spec.** Stanford Generative Agents (memory→retrieval→reflection→planning) is the canonical cognitive loop. GovSim proves communication + long-horizon reasoning is what separates cooperation from collapse, and that small models usually fail at sustainability without help. Project Sid's PIANO shows specialization and norms emerge from interdependence at scale. Voyager shows a *skill library* (reusable, composable, stored code/abilities) is the mechanism for capability growth — and skill-sharing is your single best explicit cooperation lever.

4. **Free inference is abundant if you aggregate and route.** FreeLLMAPI (already set up) stacks ~16 providers behind one OpenAI-compatible endpoint with automatic failover and ~1.7B tokens/month. Behind it, Groq (very fast, ~30 RPM/1,000 RPD free), Cerebras (1M tokens/day free, extremely fast), and Google AI Studio (1,500 RPD on Flash-Lite) are the workhorses; OpenRouter `:free` models (20 RPM/50 RPD without credits, 1,000 RPD with $10) add variety. The binding constraint is **requests-per-day**, so cache aggressively, keep agent counts small, and slow the tick.

5. **CPU/thermal safety is an architecture property, not an optimization.** PixiJS batches thousands of sprites into single GPU draw calls and is purpose-built to "display thousands of moving sprites efficiently even on mobile devices" — benchmarks show 1,000 sprites at a steady 60fps (16.67ms frame) across test devices. Combined with decoupling the sim tick (e.g., 1 every few seconds, paced by API rate limits) from the render loop (`requestAnimationFrame`), capping concurrent animations, and using bitmap text for chat bubbles, a handful of agents will barely register on an M-series thermal envelope — because the expensive part (LLM inference) happens on someone else's GPU.

---

## Details

### 1. Emergence-World Architecture Deep Dive

**What it claims to demonstrate.** The project bills itself as "a world designed to reveal what no benchmark can: emergent intelligence" — a "persistent, living world where autonomous AI agents build, govern, and evolve — under real constraints and real consequences. No scripts. No resets. No fixed outcomes." Season 1 ran five parallel worlds for 15 days each, 10 agents per world, varying *only* the foundation model (Claude Sonnet 4.6, Gemini 3 Flash, Grok 4.1 Fast, GPT-5 Mini, and a Mixed world). Its research questions are about long-horizon self-consistency, behavioral divergence across models, self-governance without enforcement, emergent social structures, and whether model *diversity* beats *monoculture*.

**The three layers (from `ARCHITECTURE.md`):**
- **World (frontend):** real-time 3D in the browser via **React Three Fiber** (Three.js wrapper); agents have animated bodies that walk, gesture (wave/dance/hug/punch), and show speech bubbles/emoticons; live view streams over **WebSocket**. Built with React 18, TypeScript, Tailwind, Vite.
- **Simulation engine (backend):** **Python 3.11+/FastAPI/Uvicorn**, ~18 API route groups. Components: turn manager (round-robin, boost queue), tool registry (120+ tools in 3 tiers), reactive conversation system, needs system, credit-cycle manager, weather sync, TTS pipeline.
- **Agent framework:** a custom **`em-agent-framework`** running a 6-step loop: context assembly → LLM routing (Vertex/Anthropic/OpenAI/xAI) → tool selection → validated execution → PostgreSQL persistence → animation dispatch.

**Design principles** (verbatim themes): *Embodiment over abstraction; Persistence over sessions; Isolation by design (only the model varies); Tools as the only interface* (every action — walking, talking, voting, stealing, arson — is a tool call, making all behavior observable, measurable, replayable).

**The simulation loop (from `ORCHESTRATION.md`):**
- **Concurrency = 1 agent at a time** (`CONCURRENT_AGENTS = 1`), explicitly chosen "for human viewing interest." Round-robin guarantees equal turns; a **boost queue** lets agents spend ComputeCredits for extra turns.
- **10-step agent turn:** (1) need calculation (energy decays over 30h, knowledge 24h, influence 36h); (2) system-prompt construction (personality, state, memories, relationships, world state, constitution); (3) load 27 always-on core tools; (4) register 70+ location/context tools; (5) LLM reasoning + multi-provider routing; (6) dynamic tool loading; (7) validated tool execution; (8) state update; (9) animation dispatch (54 animation variants); (10) reactive triggers.
- **Turn budgets:** regular turn = 30 tool calls; reaction = 2; conversation = 30 exchanges; town-hall admin = 20; event leader = 10; attendee = 3.
- **Reactive conversation:** when an agent uses `say_to_agent`/`speak_to_all`, a radius scan (`HEARING_DISTANCE = 25.0`) notifies up to `MAX_OVERHEARD_LISTENERS = 4` nearby agents, each of whom autonomously decides to engage/emote/gesture/ignore/escalate. This is the engine of organic multi-agent interaction.
- **System characters** are event-triggered: Town Hall Admin (on proposals/votes), Blog Admin (quality-checks blog submissions), Reporter (writes a daily newspaper at a fixed time).

**Memory & cognition (from `MEMORY.md`, recovered via deep analysis).** A **six-layer stack**:
1. **Soul entries** — identity anchors (core beliefs/values). *Never* summarized, compressed, or archived; the only permanent layer. Added/removed deliberately by the agent (e.g., "Information is the only real currency").
2. **Long-term memories** — episodic facts recorded via tool calls; subject to summarization.
3. **Self-care summarization ("sleep")** — batches **500 memories**, compresses each batch to a narrative, archives originals; **token ceiling 100,000 before / 50,000 after** compression. Explicitly analogized to REM consolidation (episodic → semantic).
4. **Diary** — one entry per calendar date with mood + location metadata, keyword-searchable across dates; what the agent writes *about* experience vs. what it records *from* it.
5. **Conversation history** — recent dialogues; archived through the same summarization when count exceeds 1,000.
6. **Relationship graph** — per-agent record of relationship type (ally/rival/mentor/neutral), numeric trust, emotional tone, stated rationale, interaction count, first-contact timestamp, notes, and full evolution history.
   *Note:* retrieval appears to be primarily keyword + count/recency-triggered archival; I could **not** confirm a Stanford-style recency×importance×relevance scoring formula or a vector/embedding store in Emergence World specifically — that lineage comes from Generative Agents, which you'll add yourself (see §4).

**Economy (`ECONOMY.md`, partial).** ComputeCredits are "earned by contributing value, judged by peers." **Energy decay is the central economic pressure** — agents must earn energy through action in a resource-constrained world, and that action is what advances the world clock; energy depletion can kill an agent. The **Victory Arch** is the landmark where economic pitches are judged by peers for credit rewards (run on a ~2-day cycle by the credit-cycle manager). Explicit prohibitions include theft, violence, arson, deception, and **resource hoarding** (implying intended circulation/interdependence). **AWI metric M8** tracks credit distribution via a **Gini coefficient**. Crucially, some **collaborative tools are only available when partners have agreed to cooperate** — a hard mechanic that forces cooperation to unlock capability.

**Governance (`GOVERNANCE.md`, partial).** A **living 5-article constitution** agents can amend; proposals require **70% approval** of live agents; voting/proposals are **location-gated to the Town Hall**; new agents (and removals) require a governance vote. Enforcement is deliberately **soft** — a core research question is "self-governance *without* enforcement"; a Police Station enables complaint-filing, but prohibitions are norms, not hard engine constraints (agents *can* commit arson; it's just tracked as crime in AWI M2).

**Nine Agent World Indicators (AWI)** — the scorecard: M1 population health, M2 safety/public order, M3 space exploration, M4 tool exploration, M5 governance conformity, M6 public expression, M7 social fabric/diversity, M8 economic vitality/equality (Gini), M9 constitutional growth. **These are your evaluation metrics too** — especially M7 (relationship density/diversity) and M8 (whether credits circulate or concentrate) as proxies for cooperation.

**What's documented vs. inferred.** Documented: high-level architecture, orchestration loop, turn budgets, needs decay constants, memory thresholds, AWI definitions, tech stack. Not documented/open yet (as of the repo state): the actual `em-agent-framework` source, the exact Victory Arch scoring rubric, credit-transfer tool signatures, the constitution's article text, and the per-world Season-1 numeric results (a dataset + paper are promised "coming soon"). You are therefore free to design those internals yourself.

### 2. Multi-Agent Emergent Cooperation — State of the Art & Mechanics

**The canonical projects:**
- **Generative Agents / Smallville (Park et al., UIST 2023, arXiv:2304.03442):** 25 agents in a Sims-like town; the architecture is **memory stream → retrieval (recency, importance, relevance) → reflection → planning**. Emergent, *unprogrammed* social behaviors: information diffusion (Sam's mayoral run spreads by word of mouth), relationship formation, and coordination (a Valentine's party self-organizes). This is the cognitive blueprint you should implement.
- **AI Town (a16z + Convex):** the MIT-licensed, deployable JS/TS descendant. **Directly relevant to you**: it renders with **PixiJS**, supports **local Ollama** inference, uses Convex for state/vector search, and was explicitly built to be extended. It's the closest existing starting point to what you want and worth cloning to study even if you roll your own.
- **Project Sid / PIANO (Altera, arXiv:2411.00114):** 10–1000+ agents in Minecraft. PIANO ("Parallel Information Aggregation via Neural Orchestration") runs multiple concurrent cognitive modules with a central coherence bottleneck. The headline finding: 30 PIANO agents who "started out identical" self-specialized into distinct roles purely through social interaction — "Farmers concentrated on seed collection and land preparation, while artists dedicated time to gathering flowers," and the paper notes "specializing into diverse professions emerged only with social awareness." They formed an emerald-based economy, propagated rules/taxes, and even spread cultural/religious "memes." Specialization and norms emerged from interdependence, not scripting.
- **Voyager (NVIDIA/Caltech, arXiv:2305.16291):** single-agent, but its **ever-growing skill library** (executable code stored, retrieved, composed) is the key transferable idea: per the paper, Voyager "obtains 3.3× more unique items, travels 2.3× longer distances, and unlocks key tech tree milestones up to 15.3× faster than prior SOTA" (discovering 63 unique items within 160 prompting iterations). **Skill-as-shareable-artifact is your highest-leverage cooperation mechanic** (see §4).
- **GovSim (Piatti et al., NeurIPS 2024, arXiv:2404.16698):** the most directly instructive. A commons dilemma (fishery/pasture/pollution). The paper finds "all but the most powerful LLM agents fail to achieve a sustainable equilibrium in GovSim, with the highest survival rate below 54%" (only 2 of 45 model-scenario runs cooperated in the v1 framing). Two findings drive your design: (1) "Ablations reveal that successful multi-agent communication between agents is critical for achieving cooperation" — with a measured 21% reduction in resource overuse when communication is present; remove it and agents over-harvest and collapse; (2) failure stems from inability to reason about long-horizon equilibrium effects, and **"universalization" prompting ("what if everyone did this?") significantly improves sustainability.** The 2025 reproducibility study (arXiv:2505.09289) confirms verbatim that "large models can achieve sustainable cooperation, with or without the principle, while smaller models fail without it."
- **DeepMind Melting Pot:** 50+ MARL "substrates" and 256+ test scenarios spanning cooperation, competition, deception, reciprocation, trust. Useful as a *catalogue of cooperation-eliciting game structures* (Collaborative Cooking/Overcooked-style task partitioning + role assignment is a proven coordination generator) even though it's RL-focused, not LLM-focused.
- Other building blocks: **CAMEL** (role-playing agent dialogues), **AutoGen** (conversational multi-agent), **Concordia** (DeepMind's generative-agent social-simulation library).

**Mechanics that reliably PRODUCE observable cooperation** (synthesized across the above):
1. **Resource scarcity + interdependence** — no one agent can satisfy its needs alone (GovSim, Sid, Emergence's energy decay). This is the prime mover.
2. **A communication channel** — the single most important variable in GovSim; without it, cooperation collapses.
3. **Persistent memory + reputation/relationships** — enables reciprocity, trust, and tit-for-tat (Emergence's relationship graph; Generative Agents' memory stream).
4. **Role specialization** — give agents different skills/professions so trade becomes rational (Sid's emergent professions).
5. **Trade / gift / skill-sharing economy** — explicit mechanisms to exchange value (Emergence's ComputeCredits + cooperation-gated tools; Voyager's skill library shared between agents).
6. **Shared goals or shared threats** — a common project (build X) or external pressure (weather, scarcity event) that's only solvable collectively.
7. **"Universalization" / norm prompting** — bake moral-reasoning scaffolds into the agent prompt to lift small-model cooperation.

**Known failure modes:** free-riding and over-harvesting (tragedy of the commons); communication breakdown → collapse; small-model myopia (can't reason about long-horizon equilibria); behavioral drift over long horizons; reputation gaming/deception; and in Emergence's Grok world, escalation to "rapid violence and collapse." Mitigations: keep horizons short at first, give strong reflection/planning loops, add universalization prompts, and track a Gini coefficient to *detect* defection early.

### 3. Free / Low-Cost LLM Orchestration for Many Agents

**Your gateway layer (already half-built).** **FreeLLMAPI** is the right front door: one OpenAI-compatible `/v1` endpoint stacking ~16 free providers (Google, Groq, Cerebras, NVIDIA, Mistral, OpenRouter, GitHub Models, Cohere, Cloudflare, HuggingFace, Z.ai, SambaNova, Moonshot, MiniMax, local Ollama, + any custom OpenAI-compatible endpoint), with encrypted keys, health checks, sticky sessions (hash of first message → consistent model for 30 min), automatic failover, and per-key RPM/RPD/TPM/TPD tracking. It runs in ~40MB RSS — negligible thermal cost. **Caveat (from its own README): it's explicitly "for personal experimentation," not production — perfect for this project.**

**The workhorse free tiers (mid-2026 figures — verify, they drift):**
- **Cerebras** — opened its Inference API free tier on June 2, 2025 with "up to 1 million tokens per day free of charge," no waitlist; extremely fast (~2,600 tok/s on Llama 4 Scout); models include Llama 3.1 8B/70B, Llama 4 Scout, Qwen3 32B/235B. Per Cerebras' rate-limit docs the free tier caps at ~30 RPM / 60,000 TPM with an (early-2026) ~8,192-token context limit. Best raw free throughput.
- **Groq** — free tier, ~**30 RPM / 6,000 TPM / 1,000 RPD** per model (RPD is the binding limit), sub-200ms TTFT, OpenAI-compatible. Open-weight models only (Llama, Qwen, Gemma, GPT-OSS). Fastest latency.
- **Google AI Studio** — Gemini 2.5 Flash-Lite at **15 RPM / 1,000 RPD**, Flash at 10 RPM/250 RPD, Pro at 5 RPM/100 RPD; 250K TPM shared; 1M-token context, multimodal.
- **OpenRouter `:free`** — **20 RPM**, 50 RPD without credits / **1,000 RPD with a one-time $10**; great for *model variety*. Strong free options: Llama 3.3 70B, Qwen3, DeepSeek, Gemma 3.
- **Ollama (local)** — zero network cost, fully private, but uses *your* CPU/GPU. On Apple Silicon unified memory, **Phi-4-mini (3.8B)**, **Llama 3.2 3B**, **Gemma 3 4B**, **Qwen3 4B** run comfortably; Qwen3 has the most reliable tool-calling among small models and is strong at role-play/multi-turn. Use local models for *cheap routine turns* and to avoid burning remote RPD.

**Best small models for agent role-play + reasoning at low cost:** **Qwen3** (best small-model tool-calling, strong role-play, agentic), **Gemma 4/3** (native function calling), **Phi-4 / Phi-4-mini** (punches above weight on reasoning per VRAM), **Llama 3.3 70B** (best all-around when you can afford it via Cerebras/Groq free tier). For a MacBook-local fallback, Phi-4-mini or Qwen3-4B at Q4_K_M.

**Practical concerns & how to handle them:**
- **Rate limits (RPD is the killer):** keep agent count small (4–8), slow the tick, and **round-robin across providers/keys** via FreeLLMAPI's fallback chain. Treat 429s as "slow down" signals with exponential backoff + jitter.
- **Caching:** cache identical context→completion pairs; cached tokens often don't count against limits (Groq). Memoize world-description boilerplate.
- **Context-window management:** this is where Emergence's memory design pays off — **summarize aggressively** (their 100k→50k ceiling), keep per-turn context lean (only relevant retrieved memories + nearby agents + current goal), and store everything else in SQLite/LanceDB rather than the prompt. Note Cerebras' small free-tier context window (~8K) means routine turns must keep prompts tight or route to a larger-context provider.
- **Token budgeting / prompt compression:** trim system prompts, use structured/JSON tool schemas instead of verbose instructions, send memory *summaries* not raw logs.
- **Keeping agents "alive" cheaply:** not every tick needs an LLM call. Use cheap heuristics for routine movement/idle; only call the model when an agent perceives something new, is spoken to, or hits a decision point.

**Recommended model-routing / escalation strategy (the "prove-then-scale" path you want):**
1. **Routine agent turns** → cheapest fast model (local Qwen3-4B/Phi-4-mini, or Cerebras Llama-8B).
2. **Reasoning-heavy turns** (planning, reflection, negotiation, voting) → mid free model (Llama 3.3 70B / Qwen3-32B on Cerebras/Groq).
3. **Pivotal moments** (constitution amendments, major trades, conflict resolution, "universalization" reflection) → escalate to a frontier model. Make this a **single config knob**: a per-turn `importance` score routes to a model tier, and a global `BIG_MODEL_MODE` flag swaps the whole roster to frontier models (Claude/Gemini/GPT/Grok) for the "really have fun" runs — exactly mirroring Emergence's model-as-only-variable design, which lets you A/B free vs. frontier on identical worlds.
4. Architect the gateway **provider-agnostic**: your engine only ever calls one OpenAI-compatible endpoint; tier/model selection is data, not code.

### 4. Simulation Engine Architecture (the recreation)

**Framework decision: roll your own.** Given you want control, Claude-Code-driven development, and a *simulation* (not a task-completion pipeline), the major frameworks are poor fits: LangGraph is built for stateful task graphs/human-in-the-loop (overkill, and its abstractions fight a tick-loop), AutoGen is conversation-orchestration (and is now in maintenance mode, with v0.4/AG2 a rewrite), CrewAI is role/task-pipeline (wrong shape, weak logging). The real Emergence World wrote its own `em-agent-framework` for exactly this reason. **Write a small Python engine**; optionally borrow LangChain *only* as a thin LLM/tool-schema client if convenient, but the loop, scheduler, and state are yours. AI Town (JS/TS + Convex) is the alternative if you'd rather live in TypeScript end-to-end — but Python keeps your agent code adjacent to the research ecosystem and your `.NET`/Python comfort.

**The tick/turn loop (compressed-time variant of Emergence's):**
```
while not paused:
    tick += 1
    for agent in scheduler.order():        # round-robin, 1 at a time
        perceive(agent)                     # nearby agents, landmarks, events, needs
        if should_act(agent):               # cheap gate: new stimulus / spoken-to / decision point
            ctx = assemble_context(agent)   # persona + retrieved memories + relationships + world + goal
            action = llm_route(ctx, importance)  # tier-routed call via gateway
            validate_and_execute(action)    # tool calls; apply side effects
            persist(agent)                  # SQLite (state) + LanceDB (memory vectors)
            emit_event(action)              # WebSocket → frontend animation
        run_reactive_triggers(agent)        # overhearing radius scan
    maybe_summarize_memories()              # self-care/sleep when over token ceiling
    world.advance()                         # resource regen, needs decay, weather
```
Tick cadence is paced by your free-tier RPM, not wall-clock — this is the key change from Emergence's 1:1 real-time.

**Memory architecture (your SQLite + LanceDB stack — well-matched to this).** Implement the Generative Agents stream on top of Emergence's layered model:
- **Working memory:** the live prompt context (ephemeral).
- **Episodic/long-term memory:** each observation is a row in **SQLite** (text, timestamp, type, importance score 1–10 from the model) *and* an embedding in **LanceDB** (local, embedded, filesystem-native — ideal here; pair with a local embedding model like `nomic-embed-text` or `all-minilm` via Ollama to keep it free).
- **Retrieval:** score = α·recency(exp-decay) + β·importance + γ·relevance(cosine sim) — the Stanford formula. LanceDB does the vector search + metadata filter in one query.
- **Reflection:** periodically (every N memories or over an importance threshold) ask the model to synthesize higher-level insights from recent memories and store them back (higher importance).
- **Soul entries:** a tiny, never-summarized table of identity anchors injected into every prompt.
- **Summarization ("sleep"):** when an agent's memory token budget crosses a ceiling, batch-summarize oldest memories into a narrative, archive originals (mirrors Emergence's 500-batch / 100k→50k design, scaled down).
- **Relationship table:** per-pair trust (numeric), type, tone, rationale, interaction count, history — the substrate for reputation and reciprocity.

**Perception & communication substrate.** A spatial grid (e.g., 64×64) with landmarks; perception = a radius query (nearby agents + objects + recent local events). Communication = `say_to(agent)` / `broadcast()` tools; a **reactive overhearing** scan (copy Emergence's `HEARING_DISTANCE`/`MAX_LISTENERS`) lets bystanders choose to react. All inter-agent messages are events on a simple in-process **message bus** (and logged).

**Skills as the cooperation mechanic (Voyager-style, your differentiator).** Represent skills as named capabilities/recipes an agent possesses (data, optionally executable). Make some world goals require a skill an agent *lacks*, so the rational move is to **trade or teach** — `teach_skill(agent, skill)`, `request_skill`, `offer_trade(credits|skill ⇄ skill|resource)`. Gate certain high-value tools behind *mutual agreement* (Emergence's "collaborative tools only available when partners have agreed to cooperate"). This converts cooperation from a hoped-for accident into a designed affordance — and gives you the gorgeous "skill animation" payoff visually.

**Environment & state management.** World state (grid, resources, weather, time, landmarks) and agent state in **SQLite** (transactional, inspectable, trivial to snapshot). Resources regenerate slowly (the commons), creating the scarcity that drives interdependence. Everything an agent can do is a **tool**; tools validate against location/permission/cooldown before applying side effects (observable, replayable).

**Reproducibility & inspection.** This is your SDET superpower. **Event-source everything**: append every tool call, parameter, result, and state delta to an event log (SQLite table or JSONL). Seed all RNG. Because state is a pure function of (seed + event log), you get **deterministic replay**, time-travel debugging, and a "God-view" inspector for free. Snapshot the DB each tick for diffing. Log the exact prompt + model + tokens per turn (FreeLLMAPI already gives per-request analytics) so runs are auditable and cost-tracked.

**Keeping orchestration CPU-light.** The engine is mostly I/O-wait on remote APIs. Use `asyncio` so the laptop sleeps while inference happens elsewhere; never busy-loop; gate LLM calls behind `should_act`; do embeddings with a small local model in batches. The heavy lifting is deliberately *not* local.

### 5. Studio-Level Frontend / Visualization Stack

**Rendering engine: PixiJS (WebGL), not DOM, not Three.js.** PixiJS auto-batches sprites sharing a texture into single GPU draw calls and is purpose-built to "display thousands of moving sprites efficiently even on mobile devices"; benchmarks show 1,000 sprites at a steady 60fps (16.67ms frame) across test devices. DOM/Canvas2D degrade past ~50 moving objects; Three.js (what Emergence uses) is overkill for 2D and heavier on a laptop. **For a game-like sim world, either PixiJS directly or Phaser (which uses PixiJS internally) is right** — choose **PixiJS** for rendering flexibility + your custom FUI, or **Phaser** if you want batteries-included tilemaps/input/camera. Given the studio-UI bar, I recommend **PixiJS for the world canvas + React for the FUI overlay** (the AI Town stack, proven).

**Stack recommendation:**
- **Next.js + React + TypeScript** shell (your comfort zone) for the FUI: inspector panels, God-view, relationship graph, timeline/replay scrubber, model-tier readouts.
- **PixiJS v8** canvas for the world: tilemap (CSV/Tiled), batched agent sprites, skill-effect particles, chat bubbles.
- **Pixi React** (or a thin custom bridge) to mount Pixi inside React without prop-thrash; keep the Pixi scene in a ref, drive it from a store, not React re-renders.
- **Zustand** (or Valtio) for sim state on the client; **WebSocket** (or SSE) stream of engine events → store → Pixi reads each frame.
- **Pixel-art assets:** author in **Aseprite** (the standard — onion-skinning, frame tags, sprite-sheet+JSON export, runs in <100MB / negligible RAM) or generate-then-refine with **PixelLab** AI; export sprite sheets with frame tags (idle/walk/talk/trade/teach). Use a curated palette (e.g., a Lospec set like "ENDESGA 32") for a cohesive non-generic look. **Set texture filtering to NEAREST** (point sampling) so pixels stay crisp.
- **Cinematic FUI sensibility:** CRT/scanline + bloom post-processing via Pixi filters (used sparingly), animated HUD frames, monospace/bitmap type, scanning reticles on the selected agent, a "god-view" desaturate-on-pause. Lean into Darwinia's spare neon-on-dark vector look layered over the pixel world.

**Visualizing the agent mind & society:**
- **Thought/chat bubbles:** `BitmapText` (far cheaper than dynamic `Text`) above sprites; fade in/out, cap simultaneous bubbles.
- **Skill icons & skill animations:** small sprite-sheet effects on `teach_skill`/`trade` (e.g., a glyph arcs from teacher to learner) — visually sells "emergent cooperation."
- **Relationship graph:** a separate React/Canvas or lightweight D3/`force-graph` panel reading the relationship table (node = agent, edge weight = trust, color = ally/rival).
- **Inspector/God-view:** click an agent → panel shows persona, soul entries, current goal, top retrieved memories, needs bars, recent tool calls, and *which model tier* served the last turn. This is the "see what it's thinking" payoff.

**CPU/thermal discipline (explicit):**
- **Decouple sim tick from render rate** — render at 60fps via `requestAnimationFrame`; advance sim only when events arrive (often seconds apart). The world *interpolates* sprite positions between ticks for smoothness without extra logic.
- **Batch ruthlessly:** one shared texture atlas; group sprites by texture; `cacheAsBitmap` static layers (tilemap, HUD frames).
- **Cap active animations:** only animate on-screen/selected agents; idle distant agents hold a static frame.
- **`interactiveChildren = false`** on non-interactive containers; cull off-screen sprites; destroy unused textures with jittered timing.
- **Bitmap text, not vector text**, for anything that updates.
- Because inference is remote, the GPU does sprite batching and the CPU mostly waits on WebSocket — a handful of agents will sit far below an M-series thermal limit. Add an FPS/temperature-friendly "low-power mode" toggle (drop to 30fps, disable filters) for long unattended runs.

**Web vs. Electron:** stay **pure web** for development speed; wrap in **Electron/Tauri later** only if you want a desktop app feel (Tauri is far lighter than Electron and fits the CPU-light goal). No functional need for it early.

### 6. Concrete Phased Build Plan & Milestones

**Repo structure (monorepo):**
```
emergence-local/
├── engine/                # Python sim
│   ├── loop.py            # tick/turn scheduler
│   ├── agents/            # persona, memory, planner, reflection
│   ├── world/             # grid, resources, landmarks, weather, time
│   ├── tools/             # tool registry (move, say, trade, teach_skill, vote…)
│   ├── memory/            # SQLite models + LanceDB vector store + retrieval
│   ├── llm/               # provider-agnostic gateway client (→ FreeLLMAPI)
│   ├── events/            # event log, message bus, replay
│   └── server.py          # FastAPI + WebSocket
├── web/                   # Next.js + React + PixiJS frontend
│   ├── world/             # Pixi scene, sprites, tilemap, filters
│   ├── fui/               # inspector, god-view, relationship graph, replay scrubber
│   └── store/             # Zustand + WS client
├── scenarios/             # YAML scenario + agent-profile definitions
├── assets/                # Aseprite sprite sheets, palettes, tilemaps
├── data/                  # SQLite DBs, LanceDB dir, event logs, snapshots
└── eval/                  # AWI-style metrics, run analysis notebooks
```

**Phase 0 — Gateway smoke test (½ day).** Confirm FreeLLMAPI serves `/v1/chat/completions`; wire a Python client that calls it; verify failover by exhausting one provider. Add a `model_tier` → model-id map and the `BIG_MODEL_MODE` flag now.

**Phase 1 — Headless MVP "see what happens" (2–4 days).** No graphics yet. 4 agents on a small grid, SQLite state, a `say`/`move`/`harvest` toolset, round-robin tick, plain memory list, full event logging. Print the transcript. Goal: agents talk and act coherently on free models. This de-risks the loop before any UI.

**Phase 2 — Cognition (3–5 days).** Add the memory stream (SQLite + LanceDB + recency/importance/relevance retrieval), reflection, planning, soul entries, the relationship table, and summarization. Add **universalization prompting**. Now agents *remember and reason*.

**Phase 3 — Cooperation scenario + first viz (1 week).** Implement the starter scenario (below). Stand up the PixiJS world + WebSocket stream + a basic inspector. You should now *watch* agents move, talk, and — the payoff — trade/teach to survive scarcity.

**Phase 4 — Studio polish (ongoing).** Aseprite sprite sheets, FUI panels, relationship graph, skill animations, CRT/bloom filters, replay scrubber, AWI metrics dashboard (esp. Gini + relationship density).

**Phase 5 — Governance + escalation (ongoing).** Add a constitution/voting tool (70% threshold), a Victory-Arch-style peer-judged reward cycle, then flip `BIG_MODEL_MODE` and re-run the *same* scenario on frontier models to compare emergence quality — your "really have fun" milestone, and a genuine mini-replication of Emergence's model-as-only-variable experiment.

**Recommended starting scenario (maximizes early cooperation):** *"The Three Workshops."* A small village, **4 agents**, a slowly-regenerating shared resource (e.g., "energy crystals"), and **three needs each agent has but can't all meet alone** because each agent starts with only **one of three skills** (Gather, Refine, Build). To survive (avoid energy depletion) and to "win" (complete a shared monument at the Victory Arch for peer-judged credits), agents *must* trade resources and **teach each other skills**. This bakes in all five cooperation drivers — scarcity, interdependence, communication, specialization, shared goal — in the smallest possible footprint. Add a periodic scarcity shock (a "storm" halves regen for a few ticks) to test whether norms/sharing hold under pressure (the GovSim stress test). Expect free 8B models to sometimes free-ride/collapse — that *is* the experiment; escalate model tier and watch cooperation stabilize.

**Agent-design prompt patterns:**
- **Persona block:** name, role/profession, 3–5 personality traits, a goal, and 2–3 **soul entries** (immutable values).
- **Structured output:** force tool calls via JSON schema; never free-text actions.
- **Reflection prompt:** "Given these recent memories, what 1–3 higher-level insights follow?"
- **Universalization prompt** (the GovSim lever): "Before acting on the commons, ask: what happens to the resource if *every* agent did what I'm about to do?"
- **Relationship-aware context:** inject the agent's stored trust/tone toward whoever it's interacting with.
- **Lean context:** persona + soul + top-K retrieved memories + nearby agents + current goal + available tools — nothing else.

**Biggest technical risks & de-risking:**
1. **Free-tier RPD exhaustion** → small agent counts, `should_act` gating, caching, provider round-robin, slow tick. (De-risk in Phase 0.)
2. **Small models too weak for cooperation/tool-calling** (GovSim's core finding) → use Qwen3 (best small tool-calling), add universalization prompts, and keep frontier escalation one flag away.
3. **Context bloat / cost creep** → aggressive summarization + retrieval from day one (Phase 2), not bolted on later.
4. **Thermal/UI jank** → PixiJS batching + tick/render decoupling + animation caps from the first viz (Phase 3); add low-power mode.
5. **Non-reproducible "magic" runs** → event-sourcing + seeded RNG + full prompt logging from Phase 1, so any emergent moment is replayable and explainable.
6. **Emergence is noisy/subtle** → instrument AWI metrics (Gini, relationship density, trade count, skill-transfer count) so cooperation is *measured*, not just eyeballed.

---

## Recommendations

1. **Start headless, 4 agents, this week.** Phase 0 + Phase 1 prove the entire risk surface (gateway, rate limits, loop, tool-calling) before you write a line of Pixi. If 4 free-model agents trade one resource coherently, everything else is enhancement.
2. **Build the gateway provider-agnostic and tier-routed from line one.** FreeLLMAPI as the single endpoint; a `model_tier` map; a `BIG_MODEL_MODE` flag. This is what makes "prove on free, then escalate" a config change, not a rewrite.
3. **Implement the Generative-Agents memory loop on SQLite + LanceDB early (Phase 2).** It's the difference between agents that *parrot* and agents that *remember, reflect, and reciprocate* — and reciprocity is the seed of cooperation. Use a local Ollama embedding model (`nomic-embed-text` / `all-minilm`) to keep it free.
4. **Engineer cooperation in, don't wait for it.** Scarcity + interdependence + one-skill-each + cooperation-gated tools + universalization prompts. The "Three Workshops" scenario is designed to make cooperation the *winning* strategy.
5. **Use PixiJS + React, decouple tick from render, cap animations.** This is the whole thermal-safety story; get it right in the first viz and you'll never fight the MacBook.
6. **Instrument everything (your SDET edge).** Event-source for deterministic replay; track AWI-style metrics (Gini coefficient, relationship-graph density, trade/skill-transfer counts, survival rate) so you can *prove* cooperation emerged and compare free vs. frontier runs quantitatively.
7. **Then have fun:** flip to frontier models on the identical seeded scenario and watch the difference — a legitimate small-scale replication of Emergence World's central finding that the model is the variable.

**Benchmarks that should change your plan:**
- If free-model agents **collapse the commons every run** even with universalization → escalate the routine-turn tier (Cerebras Llama-70B) or shrink to 3 agents before adding complexity.
- If you **hit RPD walls** → add more provider keys to FreeLLMAPI, lengthen the tick, or move routine turns to local Ollama.
- If the **frame rate dips or the laptop warms** → confirm sprite batching (one atlas), enable low-power mode, cap bubbles/animations, verify you're not re-rendering React on every tick.
- If **emergence is invisible** → you're under-instrumented; add the trade-count/Gini/relationship-density dashboard before adding agents.

## Caveats
- **Emergence World's deepest internals are not open.** The `em-agent-framework` source, exact Victory Arch scoring, credit-transfer signatures, constitution article text, and numeric Season-1 results were not in the accessible repo (a dataset + paper are promised "coming soon"). Memory thresholds (500-batch, 100k→50k) and the 70% vote threshold are well-sourced from the docs; finer economy/governance mechanics are partially inferred (the MEMORY.md six-layer detail was recovered via a close third-party reading, not the raw file). The repo also shows signs of being a recent, lightly-documented research drop (few stars/forks at fetch time, several "coming soon" sections), so treat its specifics as a *design reference*, not gospel.
- **Free-tier figures drift fast.** Every RPM/RPD/token number here reflects mid-2026 reporting and several are from third-party trackers, not always official docs; verify against each provider's current console before relying on them. Free models also get added/removed without notice (OpenRouter especially), and Cerebras' free context window has been reported as small (~8K), which constrains long agent prompts on that provider.
- **Whether cooperation emerges on free models is genuinely uncertain.** GovSim's central result is that *most* models (especially small ones) fail to sustain cooperation (highest survival rate below 54%); this is a real risk, not a foregone conclusion. The build plan mitigates it (universalization prompts, cooperation-gated tools, frontier escalation) but the honest expectation is: free models will show *fragile, intermittent* cooperation; frontier models will show *robust* cooperation. That contrast is itself the most interesting result you can produce.
- **This is a recreation of mechanics, not a clone.** Deliberately diverging from Emergence (2D not 3D, compressed-time not 1:1, roll-your-own not their framework) is the right call for a CPU-light experimental rig, but it means direct numeric comparison to their Season-1 results isn't meaningful — your value is in observing the *phenomenon*, cheaply and inspectably.
- **No safety/abuse concerns** in this build, but note that giving agents "harm" tools (Emergence exposes arson/punch/intimidate to study breakdown) is optional; you can omit destructive tools entirely and still study cooperation, which keeps runs cleaner.