# Petri Dish of Madness — Design Canvas Brief

You are designing **3 directions × 3 surfaces = 9 artboards (+ 1 title card = 10 frames total)** as hi-fi mockups on a Claude Design canvas. **Build the canvas immediately — do not ask clarifying questions. Every decision below is committed.**

**The product:** *Petri Dish of Madness* is a tiny, fast, cheap multi-agent chaos lab. A handful of AI agents live in a cozy little village — they talk, trade, pass laws, keep pets, feud. The marquee feature, the entire moat, is **per-agent hot-swappable model control**: you drop a *different LLM* into each agent (Gemini-Flash, Qwen, DeepSeek, Groq-Llama, Cerebras, Mistral, Kimi…) inside the *same society* and watch them diverge. It is part operator console, part live spectacle. The audience is two-headed: AI/ML insiders who want to see *which model behaves how*, and a general/viral audience who just want to watch tiny AI people be chaotic.

**The thesis (must be obvious in the first 2 seconds of every direction):** *different AI models are running this world, and you can swap them live.* If a viewer can't tell within two seconds that the little inhabitants are powered by **named, swappable, competing models**, the design has failed — no matter how pretty the village is.

**Hard constraint — the live feed stays the hero.** The streaming activity feed (what the agents are saying/doing/deciding *right now*) is the centerpiece on every surface. The 3D/illustrated world is the co-star, never a replacement for the feed. Do not demote the feed to a sidebar afterthought.

---

## The three directions (all bold reinventions — vary on every axis)

The current UI is a dark, monospace, acid-green terminal-lab (screenshots attached). Treat it as **reference, not constraint** — you may keep a thread of its DNA or break entirely, but none of these three may read as "the same terminal with nicer spacing." They must differ on **layout × typographic register × world treatment × color × density**.

### Direction A — "Bioluminescent Observatory"
Take the *petri dish* literally and make it sublime: you are looking down a microscope at a glowing colony, or out a planetarium window. The world is a luminous dish in the center; everything orbits it.
- **Layout:** radial / orbital. World as a glowing disc dead-center; the live feed streams up one side, model-control orbits the other, metadata rings the edge.
- **Register:** refined neo-grotesque display + mono for data. Display: **Space Grotesk** (Google). Body: **Inter** (Google). Mono: **JetBrains Mono** (Google).
- **World treatment:** agents rendered as glowing cellular organisms; each **model family = a distinct bioluminescent culture color**. Captioned render frame, not a photo.
- **Palette:** abyss `#04070D` (radial-graded to `#0A1420`) · panel `#0B1018` · type `#DDE8F0` · muted `#6E7E8C` · model-culture neons `#2BF5D0` cyan / `#FF3FA4` magenta / `#B6FF3C` lime / `#8A7BFF` violet / `#FFC24B` amber · UI accent `#2BF5D0` · alert `#FF5C5C`.
- **Density:** cinematic, dark, generous negative space. Calm, awe-struck, Monument-Valley-quiet.
- **Tone refs:** NASA Eyes · Universe Sandbox 2 · a planetarium console.

### Direction B — "Model League Broadcast"
Stop hiding the moat in a dropdown — make the models *compete on air*. Present the world like a live esports / F1 broadcast where the **models are the teams**. This is the most on-mission framing: per-agent model control becomes a spectator sport.
- **Layout:** broadcast overlay. Big live stage center; a lower-third **feed ticker** along the bottom; a **standings/scoreboard rail** (which model is surviving, cooperating, hoarding credits) down one side. Operator-dense, every pixel earning its keep.
- **Register:** bold condensed sports display + clean sans + stat mono. Display: **Anton** (Google) for headlines, **Saira Condensed** (Google) for standings/scoreboard. Body: **Inter** (Google). Mono: **Space Mono** (Google) for live stats.
- **World treatment:** broadcast "stage" render with lower-third graphics and team-colored name bugs over each agent. Captioned render frame.
- **Palette:** broadcast black `#0B0B0F` (stage gradient `#14141C`) · type `#FFFFFF` / `#F2F2F5` · muted `#9A9AA8` · team/model colors `#2D7BFF` blue / `#FF2D7B` magenta / `#C6FF2E` lime / `#FF8A1F` sodium / `#19E3C2` teal · league signal accent `#C6FF2E` (a deliberate, recontextualized nod to the current acid-green) · elimination/alert `#FF3B3B`.
- **Density:** maximal, glossy, high-energy. Clip-able, screenshot-able standings.
- **Tone refs:** F1 / ESPN broadcast graphics · Valorant esports overlays · Bloomberg Terminal density, but glamorous.

### Direction C — "Living Chronicle"
Lean all the way into the cozy charm and make it lovable to non-technical people: a warm, illustrated almanac where the feed is a *narrated chronicle of the village* and the AI underneath shows through only as small mono "model" tags. This is the viral/accessible pole.
- **Layout:** editorial single-column chronicle (the feed, narrated) beside an illustrated diorama hero. Magazine-generous.
- **Register:** editorial serif display + humanist serif body + mono *only* for model tags. Display: **Fraunces** (Google). Body: **Newsreader** (Google). Mono (model tags only): **IBM Plex Mono** (Google) — a quiet thread to the original.
- **World treatment:** painterly, illustrated living diorama (Stardew key-art warmth), agents as little characters. Captioned illustration frame.
- **Palette:** warm paper `#F6F0E2` / `#FBF7EE` · ink `#1E1A14` · muted `#8A8275` · dusk pastels sage `#8AA68C` / clay `#C8765A` / sky `#7FA6C4` · one electric "machine" accent `#E5432B` vermilion for model/AI tags (the machine peeking through the storybook) · alert `#B23A2E`.
- **Density:** generous, calm, magazine. Warm, witty, human.
- **Tone refs:** Stardew Valley key art · The New Yorker · an illustrated almanac · Kurzgesagt warmth.

---

## v3 seams — design them in, keep them secondary

The product is heading toward a "Village → Civilization" epoch. Leave **clear, legible seams** for these three without making any of them the centerpiece (feed + model-control stay the hero):
- **Multi-city switcher** — a place to switch/compare settlements. A: swing between orbiting colonies. B: cities as "venues/arenas." C: chronicle "chapters per town." Render as a small switcher in the world header, not a primary nav.
- **Model-family arena** — model-vs-model outcomes (survival, cooperation, credit share, token usage). Lives on the **Arena** surface as a standings/comparison block. (In Direction B it's already the scoreboard rail — keep it secondary to the live stage.)
- **Relationships & lineage** — ally / friend / neutral / rival / enemy ties, plus children/lineage. A: glowing synapse threads + budding offspring. B: a relationship/roster web panel. C: an illustrated family-tree box in the chronicle.

---

## Reference language

**Take from:**
- **F1 / esports broadcast overlays** — live standings made glamorous and clip-able (esp. Direction B).
- **NASA Eyes / Universe Sandbox** — the sublime-observation feel (esp. Direction A).
- **Stardew Valley key art + The New Yorker** — warmth and narrated charm (esp. Direction C).
- **Linear / Vercel dark dashboards** — restraint and depth in dark UI generally; no clutter-for-clutter's-sake.

**Actively avoid:**
- **Generic shadcn/admin-dashboard** — gray cards, default sidebar, table-of-everything. This is the convergent default the project must escape.
- **Raw terminal log dumps** — the current feed prints literal LLM error JSON (`Mox failed to produce a valid action… {"action":…}`) inline. Errors get a *designed* "agent glitched / model stumbled" health treatment, never raw stack text in the hero.
- **Tick/day counter chrome as the headline** — the current header leans on `TICK 0046 / DAY 2`. Keep run-time as quiet metadata; it is not the hero.
- **AI/crypto cliché** — glowing-brain icons, matrix rain, hexagon HUDs, neon-gradient-on-everything, "neural" wireframe globes.
- **Mobile = shrunk desktop** — the current app literally hard-gates phones with a "needs ≥1024px" wall. The mobile surface must be *designed for the phone* (read-only spectator), never a squeezed console.
- **Demoting the live feed** — the feed is the centerpiece; a beautiful city that pushes the feed into a footer is a failure.

---

## Surfaces (apply to all three directions)

### Surface 1 — `/` Live View (desktop, ≥1280)
**Above the fold:** the world stage (rendered village/colony/diorama) as co-star; the **live activity feed** streaming as the hero; the **per-agent model-control rail** where each agent shows its *current model as a swappable chip* (Ada → gemini-flash, Bram → qwen-next, Cleo → deepseek-pro…) — this swap affordance is the signature control. A small **multi-city switcher** in the world header.
**Below the fold:** roster of agents + pets with model badges, the "chaos knob / inject event" control, the village billboard.
**Excludes:** dense analytics (those live in the Arena), raw error JSON, spawn-form clutter dominating the frame.

### Surface 2 — `/arena` Inspector & Model Arena (desktop, ≥1280)
**Above the fold:** **model-family standings** (model vs model — survival %, cooperation, credit share, token requests) + a replay scrubber with a color-coded event timeline.
**Below the fold:** the **social graph** with relationship-colored ties, the **run browser** (past runs, each forkable / comparable / shareable), per-model charts.
**Excludes:** the live 3D world (that's Surface 1), spawn/God controls.

### Surface 3 — Mobile Spectator (read-only, 390px)
**Above the fold:** a "village glance" hero still + the **live feed as a narrated stream** + the current model line-up (who's playing whom).
**Below the fold:** a **shareable run card** — the viral artifact: an OG-image-style card ("Day 2 · 4 models · 1 town · qwen-next is winning, deepseek is broke") with a **Share** button and a **Watch live / Run your own** CTA.
**Excludes:** all editing — no model-swapping, no spawning, no governance. Read-only by design. This is the surface meant to be screenshotted and posted.

---

## Committed defaults (so nothing is left to ask)

- **Live elements:** this is a live product — feed, standings, and metadata stream in reality. The canvas can't animate, so render a single still per surface and **mark live regions with a mono caption** ("this rail streams live; static still shown").
- **Imagery:** no real photos and no external image URLs (the canvas can't fetch them). The world is a **captioned render/illustration placeholder frame** per direction (glowing dish / broadcast stage / painted diorama).
- **CTAs:** no donation, no newsletter. The signature action is **"Swap model"** (per-agent, desktop) and the viral action is **"Share run card"** (mobile). A secondary **"Run your own lab"** CTA on the mobile card.
- **Interactivity:** nav is **scoped per direction** — Direction A's links route only between A's three artboards, B within B, C within C. Cross-direction navigation lives only on the title card. Render realistic hover/active states on every nav link, model chip, CTA, and card.
- **Device policy:** Surfaces 1–2 are desktop-only artboards (don't attempt responsive within them); Surface 3 is its own dedicated 390px phone artboard.

## Risks — frame each specifically

- **Audience conflict (insiders vs. viral).** Two audiences with opposite taste: ML insiders want rigor/density; general viewers want charm/shareability. State the optimization per direction — **B optimizes for insiders/operators, C for the general/viral audience, A splits the difference for aesthetes.** The desktop surfaces lean insider; the mobile spectator leans viral. Don't try to serve both in one register on one surface.
- **Benchmark-misread.** "Model vs model" standings must **not** imply an authoritative benchmark of model quality. This is one chaotic sandbox run, not a leaderboard of which LLM is "better." Frame outcomes in the world's own playful voice ("in *this* town, qwen-next outlasted everyone"), never as third-person fact about model capability.
- **Moat-legibility.** The risk of a pretty redesign is losing the moat. Per-agent model identity must be **legible in the first 2 seconds** of every direction — named models visibly attached to visible agents. A gorgeous village with the models hidden is off-brief.

---

## Source material (the current product, for grounding)

Attached are **9 real screenshots** of the live app — treat them as "what exists today / what to transcend," not as layout to copy:
- `desktop-01-village-default` — the live 3D village hero (low-poly Stardew-style town, agents walking).
- `desktop-04-control-rail` — the **marquee feature, currently buried**: per-agent model reassign dropdowns, chaos knob, persona library, 8-model legend.
- `desktop-03-feed-column` — the live event feed (terminal log, category chips, model badges; note the raw error text to redesign away).
- `desktop-02-map-2d` — the 2D top-down map alternate view.
- `desktop-05/06/07/08-inspector-*` — the analysis annex: replay scrubber, decision trace, governance, **social graph (relationship colors)**, **AWI model-vs-model arena**, run browser (forkable runs).
- `mobile-01-village` — today's phone experience: a hard "≥1024px" gate (the gap this redesign fills).

Key facts: dark/mono/acid-green `#c8ff00`-on-near-black today; 8 swappable model families; agents + pets; live WebSocket sim; runs are forkable and comparable; heading toward multi-city + model-family arena + relationships/lineage (keep as seams).

---

## What to ship

Build a single HTML artifact on a design canvas containing **3 directions × 3 surfaces = 9 artboards plus 1 title card = 10 frames total.** Lay out the canvas as:

- A **title card** on the left: project name "Petri Dish of Madness," the 3 direction names (Bioluminescent Observatory · Model League Broadcast · Living Chronicle), and a one-sentence "what each leans into." The title card is the **only** place cross-direction navigation belongs.
- **Direction A's** 3 artboards in a row (Live View → Arena → Mobile Spectator), then **Direction B's** row, then **Direction C's** row. Label each artboard with its direction name + surface in the corner.
- Inside each direction, nav links between its artboards are **clickable and stay within that direction** — never route to another direction from inside an artboard.
- Realistic hover/active states on every nav link, every model-swap chip, every CTA, every card/row.
- A **monospace caption frame** for every world render/illustration slot describing what should land there. No external image URLs.
- The **"Swap model" affordance rendered in its hover state** on the desktop Live View of every direction (it's the signature control), and the **"Share run card"** rendered on every Mobile Spectator artboard.

After building, **output a brief in the chat (not on the canvas)** summarizing:
- What each of the 3 directions leaned into and why.
- Open questions before the next pass.
- What was scoped out / deferred (other surfaces, motion pass, real render pass, the full v3 multi-city depth).
