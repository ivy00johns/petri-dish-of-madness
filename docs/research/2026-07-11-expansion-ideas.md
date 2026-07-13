# Expansion Ideas — 3-Lens Ideation Panel Synthesis

**Date:** 2026-07-11
**Lenses:** emergence · spectacle · model-lab (6 raw proposals per lens per round)
**Round 1:** 18 raw → 15 items — T1: 5 · T2: 7 · T3: 3
**Round 2:** 18 raw → 11 new items — T1: 4 · T2: 4 · T3: 3 — plus 7 proposals folded
into Round 1 entries (see the Round 2 fold log; both lenses credited on each fold)
**Combined open items:** 26 — T1: 9 · T2: 11 · T3: 6
**Status:** **PARTIALLY FILED (2026-07-13)** — the 9 Tier-1 candidates below were filed into
the ledger (`docs/REMAINING-WORK.md`) via `plan-intake`, opening **W31**; a live-experience
routing fix (`model:auto` feed-silence) was filed alongside them as EM-318. All T2/T3
candidates and the Round-2 folds remain UNFILED (see "How to file" at the bottom).

> **FILED mapping (2026-07-13) → EM-309..EM-318, all flag-gated default-off:**
> | Doc item | EM-### | Flag |
> |---|---|---|
> | T1 #1 The Blind Lineup | **EM-309** | `blind_lineup.enabled` |
> | T1 #2 Chimera Twins | **EM-310** | `chimera_twins.enabled` |
> | T1 #3 Self-Authored Charters | **EM-311** | `charters.enabled` |
> | T1 #4 Storylines Rail | **EM-312** | `storylines_rail.enabled` |
> | T1 #5 Fingerprint Ticker | **EM-313** | `fingerprint_ticker.enabled` |
> | Round-2 T1 #16 The Babel Matrix | **EM-314** | `babel_matrix.enabled` |
> | Round-2 T1 #17 The Healing House | **EM-315** | `healing_house.enabled` |
> | Round-2 T1 #18 The Drama Wire | **EM-316** | `drama_wire.enabled` |
> | Round-2 T1 #19 The Prophecy Board | **EM-317** | `prophecy_board.enabled` |
> | *(not in this report — live-experience)* `model:auto` feed-silence fix | **EM-318** | *(routing; no flag)* |
>
> Tier-2 (#6–12, #20–23), Tier-3 (#13–15, #24–26), and the Round-2 fold log are **NOT**
> filed — they stay candidates until individually approved through `plan-intake`.

This report dedups, tiers, and constraint-checks the panel's raw proposals against the
standing laws: **$0-first**, **single-city deepening**, **no throttling / MAX
call-rate**, **byte-identical determinism**, **EW-dense art target**. No proposal was
silently dropped; every tension is flagged inline and collected in the constraint
sweep at the end.

## Merges

Three consolidations (overlap, not coincidence):

1. **The Contested Chronicle** (emergence) **+ The Chronicler** (spectacle) →
   **"The Contested Chronicle & the Town Press"** (T2, credit: both lenses). Same
   object from two angles: emergence supplied the contested-history world object
   (biased entries, winner revisions, governance canonization, mural excerpts);
   spectacle supplied the diegetic author (a real Chronicler agent on its own
   swappable lane filing a dawn broadsheet). Merged: the Chronicler *writes* the
   Chronicle; the broadsheet is its render; revisions are its politics.
2. **Sliding Doors** (spectacle) **+ Brain Transplant Theater** (model-lab) →
   **"Split-Screen Theater"** (T2, credit: both lenses). Both are fork-based
   one-perturbation model A/B with lockstep split-screen playback. Merged spec: the
   transplant event + control fork (model-lab) is the experiment; the divergence
   meter, auto-scrub to first peel-apart tick, and society-notices strip (both) are
   the theater. Sequential fork execution, never concurrent.
3. **Moment Cam + Postcards & clips** (both spectacle) → **"Moments & Postcards"**
   (T2). Postcards explicitly ride Moment Cam's shot specs; both reduce to the same
   primitive — a `(run id, tick range, camera spec)` pointer over byte-identical
   replay. One pipeline, two outputs (live moment replays; shareable stills/clips).

**Kept separate but paired** (sequencing wins, not duplicates):

- **Chimera Twins ↔ Split-Screen Theater** — the same marquee question ("same
  persona, different brain") at two price points. Twins is the within-one-city,
  zero-fork slice; Theater is the fork instrument. Ship Twins first (T1); Theater
  inherits its learnings (T2).
- **The Blind Lineup ↔ Fingerprint Ticker** — human guesses vs machine guesses at
  model identity; they share the reveal moment and should share feed chrome, but are
  distinct deliverables (game mode vs deterministic classifier). Both T1.
- **Secrets as Property ↔ The Ash Circle** — both need the scoped-visibility
  primitive (per-agent perception filtering of hidden state). Secrets (T2) proves the
  primitive on single objects; Ash Circle (T3) scales it to group membership and is
  parked behind it.

---

## Tier 1 — Do-next candidates

High spectacle-per-effort, riding shipped systems. Ordered by spectacle-per-effort.

### 1. The Blind Lineup — spectator (and agent) model taste-test *(model-lab)*

- **Pitch:** A session mode that hides every model chip behind "???" and makes
  identity a game: the viewer files guesses, and at reveal the chips flip live with a
  per-model-family accuracy scorecard. Layer two is diegetic: agents accuse a
  neighbor of being "the local model" and put it to the shipped trial machinery —
  Werewolf with model identity as the hidden role. Layer one is zero new sim
  mechanics (feed chrome plus a reveal event) and produces the exact "wait, THAT was
  the 3B local model?" moment that sells per-agent model control in ten seconds.
  Guess data across sessions is a free human-perception dataset: which models are
  actually distinguishable from behavior alone.
- **Spectacle:** Six "???" chips flip one by one to their real model logos while your
  guess card grades itself — and the room's smartest-sounding philosopher turns out
  to be qwen-4B on the laptop.
- **Builds on:** Model chips + X-Routed-Via attribution, trial/governance machinery
  (EM-240, town-hall votes), personas.
- **Effort:** S — the smallest item in the panel.
- **Risks:** Layer two accusation prompts must not leak routing metadata into
  perception; hidden-chip mode must not break the mock-fallback tell (TICK number
  stays visible); reveal state stays off the replay surface.
- **Constraints:** Clean pass. Cheapest possible showcase of the marquee.

### 2. Chimera Twins — one persona, two brains, one town *(model-lab)*

- **Pitch:** Ships the explicitly wanted-but-unbuilt opt-in: a linked pair of agents
  with byte-identical persona, memory seed, and starting state, differing ONLY in
  model, named by the existing dedup convention (Vesper / Vesper II). The feed gains
  a twin lens — the pair's life-paths as a synchronized dual-strand thread (credits,
  relationships, crimes, buildings) — and the system auto-pins a "divergence point"
  card the first time the twins answer the same class of situation differently,
  quoting both. Unlike EM-112 (whole societies per family, sequential tournament
  runs), this is within-ONE-city A/B: same neighbors, same economy, same weather of
  events, so every divergence is attributable to the weights, not the world.
- **Spectacle:** The first divergence-point card: both twins offered the same shady
  trade — Vesper (gemini) took it, Vesper II (llama) reported it to the constable —
  quoted side by side with model chips.
- **Builds on:** Persona system, ad-hoc spawn (v2), unique-name dedup, relationship
  graph, feed centerpiece.
- **Effort:** M
- **Risks:** Twins interacting with each other contaminates the control (honest
  framing: natural experiment, not clean RCT; consider a soft social-distance prior
  in the seed). Doubles call volume per persona — north-star aligned, but pick twins
  deliberately.
- **Constraints:** Clean pass. Explicitly single-city-deepening; more calls, never
  fewer.

### 3. Self-Authored Charters — agents rewrite their own identity *(emergence)*

- **Pitch:** The strongest divergence amplifier available: each agent gets a small,
  structured CHARTER (2–3 ambition slots from a tight enum grammar + one short
  self-narrative line) that the agent itself periodically rewrites in an ordinary
  turn, injected back into every future prompt above the persona. Personas are static
  inputs; this makes identity a compounding OUTPUT: robbed twice → "I will own this
  street" → biased verb choice → new experiences → next rewrite. Ambitions get
  mechanical teeth (progress perception, completion event, prestige on fulfillment),
  so "found a dynasty" or "expose a conspiracy" become self-set quests that organize
  whole arcs. Charter mutations are events; the enum grammar keeps free models
  coherent (EM-297 probe methodology applies verbatim). More rewrites = more LLM
  calls = the north star. And it's the purest form of the marquee question: hand five
  models the same starting charter and watch who they each decide to become.
- **Spectacle:** Inspector charter diff — tick 200: "I keep the peace here" →
  tick 4000: "I will own this street and everyone on it" — beside the exact robbery
  events that drove each rewrite.
- **Builds on:** Personas + reflections + commitments (v2.1 same-call cognition),
  decision traces/inspector, EM-297 schema-probe method, strict-JSON turn plumbing.
- **Effort:** M
- **Risks:** Self-prompt feedback can lock into loops or drift incoherent — hard cap
  charter size, validate against the enum, keep the persona as an immutable floor.
  Weak models may echo the example charter — run the EM-297-style divergence probe
  first (an afternoon). Charters are sim state — never off-replay.
- **Constraints:** Clean pass. Determinism flag handled by design (events + seeded
  injection); golden required.

### 4. Storylines Rail — the feed notices its own drama *(spectacle)*

- **Pitch:** A deterministic drama-scorer runs over relationship edges, crimes,
  trials, thefts, and votes, promoting recurring pairs and factions into named
  persistent threads — RIVALRY, REDEMPTION ARC, POWER GRAB — pinned in a rail beside
  the feed, each with a "story so far" recap assembled verbatim from the event log
  and a live status. Clicking a storyline filters the feed to that thread and draws a
  tether between its principals in the 3-D city. v1 needs zero LLM (pure event-log
  heuristics); an optional free-lane recap writer later adds prose narration — more
  calls, never fewer. This is the retention mechanic the centerpiece feed lacks:
  continuity, so a viewer returning after an hour knows which beef to catch up on.
- **Spectacle:** Mid-scroll, the "Ada v. Vesper II" card flips from TENSION to FEUD as
  a fresh insult lands, and a red tether snaps taut across the plaza.
- **Builds on:** Relationship graph + notoriety/crime engine (EM-240), factions +
  governance texture, overhearing chains, chat-first feed layout.
- **Effort:** M
- **Risks:** Heuristic scoring will misfire (comic false positives fine, spam is not —
  hysteresis and caps); must be built as the generic container that EM-259's war feed
  lane later slots into, not a parallel one-off.
- **Constraints:** Clean pass. $0, read-only, feed-centerpiece aligned.

### 5. Fingerprint Ticker — live behavioral stylometry, no LLM required *(model-lab)*

- **Pitch:** A deterministic per-model behavioral fingerprint from the event log
  alone: verb-mix distribution, build-vs-talk ratio, JSON-compliance and retry rates,
  cooperation/defection tendencies, meme-adoption latency, sentence-length stats.
  Party trick: a pure-math classifier (seeded, replay-safe, zero LLM calls) watches
  an unlabeled agent and publishes a converging live guess in the feed margin —
  "turn 12: 64% qwen… turn 21: 93% qwen." Everything is event-sourced, so it runs
  retroactively over every historical run in the SQLite — day one it ships with
  fingerprints mined from months of existing data. Distinct from EM-119's cross-run
  family charts: within-run, per-agent, behavior→identity INFERENCE. Pairs with The
  Blind Lineup: machine guesses vs your guesses.
- **Spectacle:** An unlabeled agent's confidence bar racing upward turn by turn until
  it locks — "93% cerebras-qwen" — a beat before the chip reveals it was right.
- **Builds on:** Event-sourced run.sqlite + decision traces, X-Routed-Via ground-truth
  labels, inspector/AWI dashboard stack (uPlot), replay determinism.
- **Effort:** M
- **Risks:** Weak free models may genuinely be indistinguishable on cheap features
  (the null result is itself publishable in-feed, but deflates the ticker —
  de-risk by prototyping the classifier offline over historical data before building
  chrome). Feature extraction must be strictly deterministic and versioned or
  retro-scores drift across releases.
- **Constraints:** Clean pass. $0, zero-LLM, retroactive value on existing data.

---

## Tier 2 — Strong but bigger

Real winners that need more effort, a dependency, a probe, or a ratification first.

### 6. Omens & Wonders — physical god verbs *(spectacle)*

- **Pitch:** God's channel today is text; this hands the viewer world-verbs — drop a
  comet over the plaza, raise a black obelisk overnight, turn the river red —
  deterministic phenomena recorded as god events entering every agent's perception as
  an ambiguous omen. The payoff is the marquee in a single shot: N models publicly
  interpreting the same sign, live. Deliberately NOT the FUTURE-banned real
  weather/news integration — authored, in-world, event-log-recorded, replay-safe. It
  pre-seeds the Wave O belief/meme seams (an omen is a natural meme progenitor)
  without depending on any of it, and its register is EW-dense: blood-red rivers and
  obelisks, not harvest festivals.
- **Spectacle:** Viewer clicks COMET; the sky streaks over the town, and within one
  round five model chips stack up in the feed with five incompatible prophecies.
- **Builds on:** God channel + proclamations (Wave A), billboard/god replies,
  perception formatter, EM-298 decal/prop render seam, event-sourced determinism.
- **Effort:** M (mechanics) — the art pass is what pushes it out of T1.
- **Risks / why T2:** Each phenomenon needs a real art pass to land, and the asset
  path must be CC0 vendoring (poly.pizza pipeline) or parametric recipes — paid
  text→3-D is out of scope per the 2026-07-05 decision. Omen descriptions must fit
  the prompt diet; the verb set should provoke rather than command, or it degrades
  into puppeteering that steals the emergence.
- **Constraints:** Determinism flag handled by design (god events, additive
  serialization, goldens). FUTURE-adjacent (real-weather ban) but the in-world
  reframe is compliant — name it at intake.

### 7. Secrets as Property — an information-asymmetry economy with blackmail *(emergence)*

- **Pitch:** Wave O's rumors are memes that spread and mutate; a SECRET is the
  opposite object: scarce, ownable, ground-truthed information (who burned the
  granary, where a cache is buried, a pact's hidden clause) existing only in specific
  agents' contexts. The shipped crime engine already manufactures them — every
  unsolved EM-240 crime mints a secret held by the perpetrator and witnesses — and
  new verbs weaponize them: blackmail (conditional extortion riding EM-237's
  intimidate surface), sell_secret, confide (trust-gated), with shipped overhearing
  chains giving every secret a seeded leak probability. Information becomes currency
  and motive: hush money, witness murder, preemptive confession; betrayal becomes
  mechanically possible instead of narratively hoped-for. Perception scoping is the
  whole trick — the engine already does per-agent context, so "only these three know"
  is a filter, not new infrastructure.
- **Spectacle:** A blackmail note drops into the feed — "I saw you at the granary the
  night it burned. Forty credits by dusk or the town hears." — and the camera holds
  on the victim's next turn: pay, defy, or make the only witness disappear.
- **Builds on:** EM-240 crime/investigation/notoriety, overhearing chains (EM-081),
  deceive + commitments/phantoms (v2.1), EM-237 intimidate, EM-251 letters when
  landed.
- **Effort:** M
- **Risks / why T2:** Partly sequenced behind EM-237/EM-251 landing; weak free models
  may leak secrets instantly through chat (mitigate with explicit "you are the ONLY
  one who knows" framing — and let leaks be findings, not bugs); needs a hard
  ground-truth table so "reveal" events are verifiable in the inspector; must be more
  than an EM-237 verb — the object model is the point. This is also the proving
  ground for the scoped-visibility primitive that unblocks The Ash Circle (T3).
- **Constraints:** Determinism flag — hidden state must stay fully event-sourced;
  visibility is a perception/render filter, never a data fork. Otherwise clean.

### 8. Houses & Inheritance — dynasties, wills, and distorted birthright *(emergence)*

- **Pitch:** Agents already age, starve, and die (W9), and ad-hoc spawn exists — but
  death is a full stop. This adds the heir: a dying agent's estate (credits, owned
  buildings, debts, faith, notoriety fraction) plus a SEEDED-DISTORTED slice of its
  beliefs and grudges transfers to a newly spawned successor who takes the house name
  (the shipped Vesper→Vesper II dedupe convention becomes lineage for free). Grudges
  that outlive their holders are the raw material of multigenerational feuds;
  inherited wealth compounds into landed houses vs drifters — class structure nobody
  scripted. The cheapest way to make a run's LATE game structurally different from
  its early game, and it plugs straight into Wave O: wars inherit casus belli, faiths
  inherit devotion. Single-city, MC-ready via the EM-249 scope seam; every transfer
  is an event, so replay stays byte-identical.
- **Spectacle:** A deathbed will is read aloud in the feed — "To Vesper II: the mill,
  the forty-credit debt to Moss, and never trust House Qwen" — then the family-tree
  panel grows a node and the heir walks out wearing the grudge.
- **Builds on:** Ad-hoc spawn (v2), survival/extinction (W9), personas + naming
  dedupe, notoriety + relationship edges (EM-240), Wave O _distort_text/_plant_belief
  seams (EM-250) as they land.
- **Effort:** M–L (touches many systems; some Wave O seams not yet landed).
- **Risks / why T2:** Population growth needs a soft ecological cap (housing/food
  gates — never call throttling); belief-distortion inheritance must be seeded and
  additive-serialized or it breaks em161 goldens; heir personality can feel like a
  clone if distortion is too timid. Compounds beautifully with Charters (T1) — an
  heir inheriting a charter seed is the dynasty mechanism at full power.
- **Constraints:** No-throttling flag addressed by design (ecological caps only);
  determinism golden non-negotiable.

### 9. Rent, Debt, and Foreclosure — credit instruments that grow a class system *(emergence)*

- **Pitch:** The economy has flows (work/forage/give/steal, Wave M trade and
  contracts) but no OBLIGATIONS THROUGH TIME — and obligations are where institutions
  come from. Three deterministic instruments: rent (owners charge co-located users,
  turning shipped ownership into income and making location contested), loans
  (agent-to-agent principal + seeded default consequences), foreclosure (defaulted
  collateral transfers ownership, the seizure notice literally painted on the
  building via EM-298 decals). Defaults mint grievances feeding the EM-256 war seam;
  usury-cap and debt-jubilee proposals give governance real economic stakes; AWI gets
  the killer cross-model chart — which family becomes the landlord class, and which
  votes the jubilee. No new UI surface for v1: obligations are feed events plus a
  small ledger panel; every instrument is a pair of events.
- **Spectacle:** A foreclosure decal appears on a debtor's house while the landlord
  posts the seizure to the feed; neighbors rally at the door; an emergency usury-cap
  vote spins up — economics becoming politics in one cut.
- **Builds on:** Credits economy + building ownership, Wave M trade/contracts
  (EM-227–232), governance lanes, EM-298 paint_surface decals, EM-256 grievance seam,
  AWI dashboards.
- **Effort:** M
- **Risks / why T2:** Runaway compounding needs seeded caps (bounded interest, debt ≤
  net worth) or one agent owns the town by tick 500 — though a monopolist is arguably
  a finding; rent must never gate agent ACTION (a broke agent still acts, it just
  accrues debt); integer credits only, no float drift. Economy tuning is the real
  cost. Natural companion to Houses & Inheritance (debts transfer at death).
- **Constraints:** No-throttling flag addressed by design; determinism via
  paired-event instruments and integer arithmetic.

### 10. Split-Screen Theater — fork-from-moment model A/B, made watchable *(spectacle + model-lab, merged)*

- **Pitch:** From any feed moment, god forks the run, applies exactly one
  perturbation — most importantly a transplant: hot-swapping one agent's model
  mid-life without telling the other agents — lets the fork run sequentially (never
  concurrent, protecting free tiers), then plays both timelines back in lockstep
  split-screen: two feeds, two cities, one clock. A divergence meter diffs the event
  streams and auto-scrubs to the first tick where the histories peel apart; a third
  strip tracks whether the SOCIETY notices (trust-edge deltas, lines like "Vesper
  seems different lately"). Model-vs-model science on a single life — far cheaper
  than EM-112's tournament and emotionally sharper because it's one character you
  already know. It answers the question no one else can pose: how much of an agent's
  personality is the persona prompt vs the weights?
- **Spectacle:** Two identical towns side by side; at tick 4,812 the left Vesper
  forgives her rival while the right Vesper — now running qwen — presses charges, and
  the twin feeds visibly diverge line by line while her best friend's trust sparkline
  drops in the qwen timeline.
- **Builds on:** Fork/resume (v2.1), per-agent hot-swappable model control, decision
  traces, byte-identical replay + run browser, deep replay viewer, relationship/trust
  graph.
- **Effort:** L
- **Risks / why T2:** The control fork doubles free-tier request volume for the
  observation window while the EM-301 intermittent rate-window churn is the open
  operational lead — bound it (fixed-turn window, free lanes, sequential) and prefer
  landing after the rate picture stabilizes (PR #84 + EM-167). Rendering two replay
  cities at once needs perf care; split-feed chrome in the centerpiece surface must
  earn its layout cost; fork state must carry pending mid-turn commitments cleanly.
  Must stay scoped against EM-112/EM-119: this is the theater, not the tournament.
  Sequence AFTER Chimera Twins (T1), which answers the same question at zero fork
  cost.
- **Constraints:** $0-cash compliant but free-tier-rate hungry — sequential-runs
  discipline is a run-level constraint, not agent muting, and is compliant with
  no-throttling.

### 11. The Contested Chronicle & the Town Press — agent-written history the winners rewrite *(emergence + spectacle, merged)*

- **Pitch:** FUTURE.md deferred "LLM memory summarization" on cost — but the calculus
  inverted (the north star is now MAX call rate on 1.7B free tokens/month), and this
  isn't private-buffer compression anyway: it's a public WORLD OBJECT with a diegetic
  author. A Chronicler — a real agent on its own swappable lane, self-appointed or
  governance-granted — spends ordinary turns writing dated entries about recent
  events from its own beliefs (history biased at the source, gossip-poisoned by
  design), filed each dawn as a broadsheet artifact in the feed: headlines, an
  editorial, a gallery woodcut, corrections when yesterday's rumor proved false. The
  chronicle is served back as perception — society-level long-range memory outliving
  any agent's rolling buffer, any death, any dynasty. The emergence payoff is
  contested truth: rival chronicles disagree, war winners commission revisions (Wave
  O), governance canonizes one account (EM-254 pattern) or votes to burn another, and
  excerpts get painted onto walls via the shipped mural path. Swap the Chronicler's
  model and the town's whole history is retold in a different editorial voice —
  per-agent model control applied to narrative itself. Deterministic by construction:
  entries are events, injection is seeded top-K.
- **Spectacle:** At dawn the feed unrolls a broadsheet — ARSONIST WALKS FREE over a
  woodcut of the smoking bakery — with a byline chip showing exactly which model
  wrote today's version of the truth; the morning after the war ends, old entry vs
  new render side-by-side under a HISTORY REVISED badge while the losers' motion to
  burn the chronicle enters the vote lane.
- **Builds on:** Beliefs + rolling memory, personas + per-agent routing, billboard/god
  channel, EM-298 murals, governance canonize pattern (EM-254), Wave O war outcomes,
  gallery + free Pollinations image lane, fork/replay.
- **Effort:** M–L (phase it: Chronicler + broadsheet first; contested
  revisions/canonization second).
- **Risks / why T2:** Touches a FUTURE.md deferral and the deliberately-held-back
  meta auto-director — the reframes are structurally sound (adds calls, diegetic,
  fallible) but need explicit user ratification at intake, not silent adoption.
  Prompt-diet pressure: inject only seeded top-K excerpts, never the full chronicle.
  Revisionism needs append-only entries with supersedes links or the inspector loses
  ground truth. Must stay clearly distinct from EM-250 memes (entries anchor to real
  event IDs; memes float free). Weak models may file flat copy — itself a divergence
  datapoint, but the layout must survive it.
- **Constraints:** **$0-first flag:** the daily woodcut must pin to free Pollinations
  ONLY — at a per-dawn cadence the paid Gemini image backstop (~$0.039/img) would
  accrue real cost; make the backstop opt-out or hard-capped for this feature.

### 12. Moments & Postcards — a deterministic moments pipeline *(spectacle, merged)*

- **Pitch:** Because the city is a pure function of the event log, a "moment" is just
  `(run id, tick range, camera spec)` — permanent, re-renderable, byte-identical.
  Slice 1 (Moment Cam): a deterministic director layer maps high-drama events (trial
  verdicts, arson, deaths, vote flips) to short scripted camera moves — dolly onto
  the town hall, slow orbit around the burning bakery — and pins a MOMENT card in the
  feed that replays that 10-second window on click. Slice 2 (Postcards & clips): one
  click on any moment mints a shareable artifact — a composed 3-D still or animated
  clip with quote, agent/model chips, tick, and run hash stamped like a postmark —
  generated entirely client-side at $0. The growth loop the lab is missing: every
  dramatic beat becomes a postable artifact that doubles as a verifiable citation
  back into the run — receipt culture only a deterministic sim can offer.
- **Spectacle:** The feed card flips to VERDICT: GUILTY while the camera whips across
  the golden-hour town and settles on the accused outside the town hall; a postcard
  slides out — "'I hereby ban gossip.' — Vesper II (cerebras-qwen), tick 4,812."
- **Builds on:** Event-sourced log + byte-identical replay (EM-055/EM-155), Wave C
  CC0 town + orbit/zoom-to-place camera (EM-095), crime & trial engine (EM-240), feed
  cards + gallery chrome.
- **Effort:** M for slice 1; L total (offscreen/headless R3F render for stills and
  GIFs is the hard 20% — slice 2 v1 can screenshot the live canvas).
- **Risks / why T2:** Shot templates must be hand-tuned to read cinematic rather than
  nauseating; the event-to-shot mapping lives strictly outside sim state; too many
  triggers cheapens it (drama threshold — Storylines Rail's scorer is the natural
  supplier); compositing stays pure-canvas so no paid image lane is ever touched.
- **Constraints:** Clean pass. $0, presentational, off the replay surface; actively
  showcases the EW-dense city.

---

## Tier 3 — Parked, with reasons

Not rejected — parked. Each has a named unblock condition.

### 13. The Ash Circle — covert coalitions and vote conspiracy *(emergence)*

- **Pitch (condensed):** `found_society` creates a group whose ROSTER IS SECRET
  (scoped out of non-member perception), with a shibboleth, a private letter channel,
  and a shared objective: rig a governance vote, corner a resource, install a leader.
  Whipped bloc votes and vote-buying make the 70% governance lanes a battleground;
  EM-240 investigation becomes counterintelligence — enough sightings EXPOSES the
  roster, triggering mass trials and a trust crater. Cashes the per-model divergence
  question: which model families conspire, and which defect?
- **Effort:** L
- **Why parked:** Double dependency plus an unproven primitive. It needs Wave O
  pieces that haven't landed (EM-250 group recompute, EM-251 letters), and its core
  trick — perception-scoped hidden state — should be proven first at object scale by
  Secrets as Property (T2) before being scaled to group membership, private channels,
  and exposure mechanics. Building it first means inventing the primitive and the
  superstructure simultaneously.
- **Unblock:** Wave O EM-250/EM-251 landed + Secrets as Property shipped and its
  scoping model validated in replay/inspector. Then this is a top-tier candidate —
  the exposure spectacle (five voter chips flipping red mid-tally) is among the best
  beats in the panel.
- **Constraints:** Determinism flag stated correctly by the proposal: hidden state
  stays fully event-sourced; secrecy is a render/perception filter, never a data
  fork. Vote-buying credit sink needs tuning. Leaky conspiracies under small models
  are content, not bugs.

### 14. Night Shift Society — local Ollama citizens as the town's metabolism *(model-lab)*

- **Pitch (condensed):** A caste of agents PINNED to local Ollama as first-class
  citizens — slow, tireless, always-on — beside the fast-but-flaky free-cloud
  majority. When an intermittent rate window hits (the EM-301 churn), nothing is
  throttled: cloud agents keep firing and bouncing at max rate, but a "who's actually
  awake" strip shows their replies thinning while local citizens' chatter visibly
  carries the town. Rate-limit storms render as weather the society survives; beyond
  EM-167 (overflow lane as fallback), locals are residents whose different metabolism
  is legible in the social fabric.
- **Effort:** M
- **Why parked:** The routing substrate it stands on is in flux: the W30 adaptive-
  routing branch is unmerged, EM-167 (the Ollama lane itself) is unbuilt, and it
  requires an always-running Ollama host — an infra commitment not yet made. There is
  also an unresolved interaction with the lane_failover soft-pin design: a sick
  local pin soft-pinning to `auto` would silently turn a "local citizen" into a cloud
  agent, breaking the caste's whole diegetic premise — needs a caste-pin exemption or
  in-world handling designed first.
- **Unblock:** W30 merged + EM-167 landed + host decision + the soft-pin/caste
  interaction written down. Then the awake-strip alone (the observability half) is a
  cheap first slice.
- **Constraints:** No-throttling compliant as proposed — the strip reports upstream
  429 reality, it never causes it; locals favoring short verbs is model choice, not
  muting. $0 (local hardware). Single-city.

### 15. Ghost Decisions — per-moment model counterfactuals on replay *(model-lab)*

- **Pitch (condensed):** Counterfactual forking was held to FUTURE as whole-run
  forking — too expensive. The reframe: don't fork runs, annotate MOMENTS. In the
  shipped replay viewer, scrub to any famous decision and ask 2–3 other free models
  the exact recorded prompt; their answers render as translucent ghost cards beside
  the real event — "haiku would have acquitted; qwen would have burned the evidence
  too." A handful of free-lane calls per interrogated moment instead of thousands per
  fork; ghosts are a viewer-layer overlay (EM-298 off-replay seam precedent), so
  byte-identical replay is untouched.
- **Effort:** L
- **Why parked:** A load-bearing prerequisite is unverified: recorded prompts must be
  faithfully reconstructable per decision — the decision-trace completeness audit has
  to pass BEFORE any UI work, or the instrument lies. Ghost answers are
  non-deterministic across viewings unless cached per (run, tick, model) in a sidecar
  (never in run state) — that cache design should be written first. Old runs'
  prompt contexts may exceed small free-model windows (the #77/#80 lesson: big
  max_tokens excludes free models). And it re-enters FUTURE-deferred counterfactual
  territory — the moment-level reframe is sound but needs explicit re-ratification.
- **Unblock:** Trace-reconstructability audit passes + sidecar cache design written +
  ratification at intake. Then it's a uniquely ownable instrument: history's
  what-ifs, priced at pennies of free tier.
- **Constraints:** Determinism compliant by design (viewer overlay, sidecar cache);
  $0 on free lanes.

---

## Constraint check — full sweep

No proposal hard-violates a standing law. Flags, by law:

- **$0-first:** All 15 are $0-cash on free lanes, zero-LLM heuristics, or client-side
  rendering. Two active flags: (1) the Chronicle's daily woodcut must pin to free
  Pollinations only — the paid Gemini image backstop at per-dawn cadence would accrue
  real cost (make it opt-out/capped for this feature); (2) Omens' phenomena art must
  come from CC0 vendoring or parametric recipes — paid text→3-D is out per the
  2026-07-05 decision. Fork-based items (Split-Screen Theater, and Twins to a lesser
  degree) are cash-free but free-tier-RATE hungry — sequenced behind the EM-301 rate
  picture stabilizing.
- **Single-city deepening:** All compliant. Forks are counterfactual timelines of the
  SAME city, not second cities; Chimera Twins and Houses & Inheritance are explicitly
  single-city (Houses is MC-ready via the EM-249 seam but scoped single-city here).
- **No throttling / MAX call-rate:** Nothing mutes an agent. Charters, Twins, the
  Chronicle/Chronicler, and Split-Screen Theater ADD calls (north-star aligned).
  Houses' population cap is ecological (housing/food), never call-gating; rent/debt
  never gates action (debt accrues, the agent still acts); Night Shift's awake-strip
  reports upstream 429 reality rather than causing it; sequential fork discipline is
  a run-level rule, not agent muting.
- **Determinism / byte-identical replay:** Viewer-layer, no goldens needed: Moments &
  Postcards specs, Blind Lineup reveal state, Fingerprint Ticker (deterministic +
  versioned features), Storylines Rail (derived, not stored), Ghost cards (sidecar
  cache). Sim-surface, goldens + additive serialization required: Charters, Secrets
  (ground-truth table; scoping = perception filter, never a data fork), Houses
  (seeded distortion, em161 goldens), Rent/Debt (integer credits, paired events),
  Chronicle (append-only + supersedes links), Omens (god events), the Theater's
  transplant event, Ash Circle (event-sourced hidden state).
- **EW-dense art target:** Omens explicitly targets the register (obelisks,
  blood-red canals — not harvest festivals); foreclosure decals and chronicle murals
  ride EM-298; Moments & Postcards showcase the dense city as footage. Nothing pulls
  toward Stardew-cozy.
- **Prior-decision touches (need explicit ratification at intake, not silent
  adoption):** Contested Chronicle vs the FUTURE.md memory-summarization deferral
  (argued inverted by the max-call-rate north star); the Chronicler vs the held-back
  meta auto-director (diegetic + fallible + adds calls is structurally different —
  but name it); Ghost Decisions vs deferred counterfactual forking (moment-level
  annotate reframe); Omens vs the banned real-world weather/news feed (authored
  in-world reframe).
- **Scope-overlap guards:** Storylines Rail must be the generic container EM-259's
  war lane slots into; Split-Screen Theater stays scoped against EM-112/EM-119
  (single-life theater, not tournament); Fingerprint Ticker is within-run inference,
  distinct from EM-119's cross-run charts; Secrets must ship the object model, not
  just an EM-237 verb.

---

# Round 2 — second panel sitting (same three lenses, 18 new raw proposals)

Round 2 ran with knowledge of Round 1's output; seven of its eighteen proposals are
re-proposals or extensions of Round 1 items and are FOLDED into those entries below
(both rounds' lenses credited — the fold log records exactly what each adds to the
Round 1 spec). The remaining eleven are new and tiered here, numbered 16–26 to keep
IDs unique across the document. Same laws applied: **$0-first**, **single-city
deepening**, **no throttling / MAX call-rate**, **byte-identical determinism**,
**EW-dense art target**. No proposal silently dropped; the Round 2 constraint sweep
is at the end of this part.

## Round 2 fold log — re-proposals absorbed into Round 1 entries

1. **Self-Narrative Ledger** *(emergence, S)* → folds into **#3 Self-Authored
   Charters** (T1). Same compounding self-authored-identity engine. Round 2 adds to
   the spec: a dedicated free-lane revision cadence (explicitly reopening the
   FUTURE.md memory-summarization deferral on the max-call-rate argument Round 1
   already made for the Chronicle — name it once at intake), a biography-DIFF view,
   and a per-model-family narrative-drift metric on the uPlot stack. Hard token cap
   on the injected doc; injection ordering deterministic.
2. **Storyline Engine** *(spectacle, M)* → folds into **#4 Storylines Rail** (T1).
   Round 2 adds: episode threading with tick-gap-elided "binge view" (one click
   collapses the feed to a single feud's events), a betrayal detector over
   commitments/phantoms, retroactive episode guides for every archived run in the run
   browser (pure recompute from the log), a mercy rule for closing dead arcs, and
   EM-151-style virtualization discipline for 40k-event recomputes.
3. **The Leverage Economy** *(emergence, M)* → folds into **#7 Secrets as Property**
   (T2). Round 2 adds: first-class Secret objects with holder lists minted by every
   unwitnessed EM-240 crime, the `expose` verb (publish to feed → notoriety spike +
   trial trigger + trust crater), vote-buying/leverage-broker dynamics around
   town-hall votes, and the marquee divergence question (which models hoard, confide,
   or burn leverage). Confirms Round 1's boundary rule: secrets are WITHHELD, Wave O
   rumors PROPAGATE — keep it crisp or the systems blur.
4. **Bloodlines** *(emergence, L)* → folds into **#8 Houses & Inheritance** (T2).
   Round 2 adds the marquee twist Round 1 lacked: `name_heir` and `raise_child`
   (two-agent co-spawn via the shipped ad-hoc spawn path) where the child inherits
   its MODEL from one parent but a seeded, distorted subset of BOTH parents' beliefs,
   grudges, credits, and house — live nature-vs-nurture, possible only with per-agent
   model control. Also: family-tree panel chip-colored by model (feed-width tension —
   the chat feed stays the centerpiece), and the framing that population growth ADDS
   call-rate. Keeps Round 1's guardrails: ecological caps only (never throttle),
   _seed_int/_distort_text inheritance, em161 goldens.
5. **The First Bank** *(emergence, M)* → folds into **#9 Rent, Debt & Foreclosure**
   (T2) as its phase 2. Round 2 adds: promissory notes with deterministic due-ticks,
   `found_bank` (any agent turns a building into an agent-run deposit institution —
   interest, loans, ledgers), real solvency (the bank pays out only what it holds),
   and the crown-jewel spectacle: a Wave O insolvency rumor triggering a bank run —
   a crowd converging on one building while the live ledger races to zero.
   Deferred obligations ride the serialize-when-non-default pending-queue pattern;
   interest math integer/floor-guarded (Round 1's rule restated).
6. **The Chronicle** *(emergence, M)* → folds into **#11 The Contested Chronicle &
   the Town Press** (T2). Round 2 adds: the chronicler as a contested OFFICE won
   through the shipped governance machinery (one new election lane), a red-diff
   revision view in the inspector ("started by" quietly rewritten to "ended by"), and
   the revision-detection loop — agents cross-checking the Chronicle against their
   own memories and calling a trial of the historian (may need a cheap witness-check
   nudge in perception). Reinforces Round 1's append-only + supersedes-links rule.
7. **Ghost Race** *(spectacle, L)* → folds into **#10 Split-Screen Theater** (T2) as
   its live presentation mode. Round 2's genuinely new insight: when one branch is
   already-recorded history, the ghost side is a ZERO-LLM-call replay — the whole
   spectacle costs exactly ONE live branch, which materially weakens the fork-cost
   objection while keeping Round 1's sequencing discipline. Adds: lockstep dual feed
   with dimmed/paired lines, first-divergence flare + divergence counter,
   align-on-tick (never wall-clock) sync rule, and feed-only-first (single 3-D city
   view with a branch toggle — no split-screen render in v1). Still sequenced behind
   the EM-301 rate picture per Round 1.

**Kept separate but paired** (cross-round, shared primitives — spec once, consume
twice):

- **The Healing House (#17) ↔ Split-Screen Theater (#10)** — one transplant-event
  primitive, two consumers: god-run instrument (Theater) vs in-world institution
  (Healing House). Scope the shared primitive explicitly at intake.
- **The Prophecy Board (#19) ↔ Omens & Wonders (#6)** — both are watcher omens
  entering perception via the god channel. The Board is text + deterministic scoring
  (no art dependency — which is exactly why it reaches T1 where Omens could not);
  Omens is the physical-phenomena art pass. A fulfilled prophecy triggering a
  physical wonder is the natural joint upgrade.
- **The Dream Lane (#22) ↔ The Prophecy Board (#19)** — both plant low-confidence
  omen-beliefs and need the same epistemic tag (agents KNOW it was a dream/omen; the
  drama is choosing to believe anyway). Design the tag once.
- **Babel Matrix (#16) + Epoch Seismograph (#21) + Fingerprint Ticker (#5)** — one
  versioned, deterministic feature-extraction layer over run.sqlite; three
  instruments (individual, dyadic, longitudinal). Build the layer once.
- **The Understudy (#25) ↔ Night Shift Society (#14)** — one always-on-Ollama host
  decision unblocks both; decide it once.
- **The Drama Wire (#18) ↔ Storylines Rail (#4) + Moments & Postcards (#12)** — the
  Wire's salience scorer is the shared drama-threshold supplier Round 1 already said
  the Moments pipeline needed; its postcard-export slice dedups into Moments &
  Postcards rather than shipping twice.

## Round 2 · Tier 1 — Do-next candidates

### 16. The Babel Matrix — dyadic inter-model social physics *(model-lab)*

- **Pitch:** Fingerprint Ticker (#5) profiles individuals; this measures PAIRS — the
  first instrument anywhere for inter-model social chemistry, and only a mixed-model
  society can produce the data. Mine the event-sourced sqlite for every dyadic
  outcome with known models on both ends — trades completed, commitments honored,
  questions actually answered, insults reciprocated, teach requests granted —
  bucketed by (speaker model × listener model) into an N×N heatmap. Zero LLM calls,
  fully retroactive over months of existing runs. The science question is genuinely
  open: are defection rates a property of the agent, or of the RELATIONSHIP between
  two weight-sets? Every cell clicks through to its feed receipts, so a finding is
  never a chart alone — it is quotable, replayable evidence.
- **Spectacle:** The heatmap wipes in beside the feed and one off-diagonal cell burns
  red — promises from gemini-speakers to llama-listeners break 4x more often than any
  other pairing — one click and the feed becomes a scroll of the exact broken-promise
  receipts, chips on both ends.
- **Builds on:** run.sqlite + X-Routed-Via ground truth, Wave M trade/contracts +
  v2.1 commitments/phantoms, relationship graph + EM-240 notoriety, AWI/uPlot stack;
  shares #5's feature layer.
- **Effort:** S — the smallest item in Round 2, ships value day one from historical
  data.
- **Risks:** Thin dyad samples in small casts (cross-run pooling + honest confidence
  shading); persona/faction confound the model signal (persona-controlled slice;
  Chimera Twins (#2) pairs are the clean control); a null result deflates the heatmap
  but is itself a publishable in-feed finding.
- **Constraints:** Clean pass. $0, zero-LLM, retroactive, off the replay surface.
  Declare distinct-from-EM-119 scoping at intake (within-run dyads, not cross-run
  family outcomes).

### 17. The Healing House — hot-swap as a civic institution the society wields *(model-lab)*

- **Pitch:** Hands the scalpel to the town: a trial verdict or 70% vote can sentence
  a citizen to the Healing House — a real building where the agent's model is
  hot-swapped: therapy, punishment, or political neutering, chosen by the society
  itself. Per-agent model control stops being an operator feature and becomes an
  in-world power agents scheme over ("send him to the healers before the vote"), and
  the society then litigates whether the returned citizen "came back different" —
  with the viewer holding ground truth via the chip. No other lab can pose this: the
  swap is real, the reaction is real, and the before/after is one agent's continuous
  life in one city. A swap changes WHICH model answers but never silences anyone —
  call-rate untouched. Unlike the Theater (#10) it needs no fork and no extra live
  branch, so it is not gated on the EM-301 rate picture — which is what puts it in
  T1 where the Theater could not go.
- **Spectacle:** The verdict card flips to SENTENCED: THE HEALING HOUSE; the convict
  walks into the asylum, their model chip visibly morphs mid-walk, and their first
  post-treatment line lands in the feed while the best friend's trust sparkline
  twitches — "you sound... different."
- **Builds on:** Per-agent hot-swappable model control (the marquee), EM-240 trial
  engine + shipped 70% governance lanes, personas, feed model chips, generic building
  pool for the asylum; shares the transplant-event primitive with #10.
- **Effort:** M
- **Risks:** Must never swap toward silence — target lanes stay full-rate free/local
  models (no-throttling law); the sentence effect is a new seam on the replay surface
  (per-turn attribution already exists) — golden required; register discipline:
  lobotomy-grim fits EW-dense, but keep it expensive (a vote lane, not a reflex) so
  it doesn't become the meta-answer to every conflict.
- **Constraints:** No-throttling flag addressed by design; determinism golden
  non-negotiable; scope the shared transplant primitive against #10 at intake.

### 18. The Drama Wire — a deterministic salience index that lets the feed break its own news *(spectacle)*

- **Pitch:** A pure, replay-off-surface scoring function over the typed event stream
  (crime notoriety deltas, trial verdicts, vote flips, deaths, betrayed commitments,
  first-mural-on-a-building) computes a live Drama Index and promotes
  threshold-crossing beats into red BREAKING interstitial cards in the feed —
  headline templated for $0, optional free-LLM punch-up on an off-replay lane.
  Clicking a card flies the 3-D camera to the scene via the shipped zoom-to-place
  controls. This is NOT v5's punted auto-director: it is feed-native, camera-second,
  and the calculus changed — the crime/justice engine and governance machinery now
  emit typed severity events, so salience is a cheap projection that did not exist
  when direction 10 was shelved. Beyond its own cards, the scorer is shared infra:
  Storylines Rail (#4) arc promotion and Moment Cam (#12) shot triggering both
  consume it, and the Cinematographer (#23) uses it for shot selection.
- **Spectacle:** The feed is scrolling normal chatter, the Drama Index sparkline in
  the header starts climbing, then a red card slams in — "VERDICT: Vesper II GUILTY —
  exiled by 71% vote" — and the city camera is already gliding toward the town hall.
- **Builds on:** EventFeed lanes + billboard, EM-240 typed events, governance/trial
  events, chronicle's pure-projection helpers (EM-201), zoom-to-place camera
  (EM-095). Its postcard-export slice dedups into Moments & Postcards (#12) — one
  postcard pipeline, not two.
- **Effort:** M
- **Risks:** Salience weights are taste — needs a tuning pass or it cries wolf;
  interstitials must be rate-capped so they never crowd raw agent chat (feed-wins
  rule cuts both ways); the scorer must stay a derived view with zero sim feedback to
  preserve byte-identity.
- **Constraints:** Clean pass. $0, read-only, feed-centerpiece aligned. Touches the
  shelved auto-director direction — the feed-native reframe is structurally different
  but name it at intake (Round 1 flagged the same for the Chronicler).

### 19. The Prophecy Board — watchers post omens, the sim perceives them, and the feed scores the future *(spectacle)*

- **Pitch:** A new god-channel verb: the watcher posts a prophecy from a constrained
  predicate menu ("X will be convicted within N ticks", "a building will burn in
  district Y", "X and Z will reconcile") — logged as a god event exactly like shipped
  proclamations, so it is ON the replay surface by design, and agents perceive it as
  a one-line omen ("an omen speaks of fire in the market quarter"). Watching becomes
  participatory in the deepest way: your bet is also an intervention, and the show
  becomes whether the society fulfills, defies, or panics about the omen —
  self-fulfilling prophecies are emergent drama you caused. Resolution is a
  deterministic projection over subsequent events (enum predicates only, no fuzzy
  judging); the feed shows the prophecy card with a live tick countdown, then stamps
  PROPHECY FULFILLED / PROPHECY BROKEN. Nothing in the ledger or FUTURE.md touches
  watcher predictions; it rides the proclamation machinery that already proved
  god-input determinism.
- **Spectacle:** The countdown hits 12 ticks remaining just as an agent, spooked by
  the omen, torches the market himself.
- **Builds on:** God channel (proclamations + god replies + miracle API), event-log
  determinism, billboard/feed card chrome, commitments machinery for the countdown
  pattern. Pairs with Omens & Wonders (#6) — shared god-omen perception line — and
  with the Dream Lane (#22) — shared epistemic omen tag.
- **Effort:** M
- **Risks:** Perception injection hard-capped at one omen line (prompt diet);
  free-text predicates would wreck deterministic scoring — the enum menu is
  load-bearing; rate-limit prophecies per run so watchers can't steer every run the
  same way.
- **Constraints:** Clean pass. Determinism handled by design (god events on-surface,
  enum-scored resolution off-surface). No art dependency — which is why it reaches T1
  while #6 sits in T2.

## Round 2 · Tier 2 — Strong but bigger

### 20. The Petri Protocols — classic behavioral experiments staged live in the town, scored per model *(model-lab)*

- **Pitch:** Makes "the model laboratory" literal: a library of deterministic,
  god-triggered in-world scenarios reproducing canonical behavioral-econ experiments
  with real citizens as subjects — Asch conformity (planted neighbors assert
  something plainly false), the ultimatum game (a credit split with real economy
  stakes), delayed gratification (credits now vs commitment-tracked more later),
  bystander effect (a staged crime with N witnesses). Each protocol is a seeded event
  template riding the god channel; the subject's turn is an ordinary full-rate LLM
  call inside the live society, so results carry ecological validity no chat-window
  benchmark has — and every result files a FINDINGS card with running per-model
  scoreboards: conformity-by-model, fairness-by-model, patience-by-model,
  accumulating into the lab's own published dataset. Confederates are paid in-world
  (god commissions them via the existing channel), keeping the staging diegetic.
- **Spectacle:** An Asch trial runs live: five planted neighbors insist the granary
  is empty when the whole feed can see it is not; the subject's turn card holds for a
  beat... then "the granary is full, and you all know it" — stamped DEFIED — as the
  conformity-by-model bar chart ticks in the margin.
- **Builds on:** God channel + proclamations (Wave A), credits economy + Wave M
  contracts, v2.1 commitments, event-sourced determinism + inspector, feed cards;
  EM-297's probe methodology (tight schemas, hard validation) applies verbatim.
- **Effort:** M
- **Risks / why T2:** Confederate staging must stay diegetic (the bribe itself is an
  event) or it contaminates authenticity — this is the puppeteering line and it needs
  explicit design + ratification; n-per-cell is small, so scoreboards need cross-run
  accumulation before claims; protocol prompts must fit the prompt diet; drama-budget
  cap so protocols stay occasional events, not a firehose cheapening the feed.
- **Constraints:** Determinism by design (seeded templates, on-surface events). $0.
  The confederate/puppeteering boundary must be named at intake.

### 21. The Epoch Seismograph — detecting the day a provider silently swapped the weights *(model-lab)*

- **Pitch:** Free providers silently update, quantize, and re-serve their models —
  and PDoM is accidentally the perfect detector: months of event-sourced,
  X-Routed-Via-labeled behavior from the same lanes under near-stationary prompts. A
  deterministic longitudinal analyzer tracks per-lane behavioral features (verb-mix,
  sentence-length stats, JSON-retry and refusal rates, build-vs-talk ratio) across
  calendar time and flags step-changes as EPOCHS — "the day gemini changed" — stamped
  onto the run-browser timeline and into any run that straddles one. Model-vs-model
  science on the TIME axis, uniquely ownable — and operationally load-bearing, since
  an undetected upstream swap silently invalidates every cross-run comparison
  (EM-112/119 tournaments, the Babel Matrix (#16), any fingerprint (#5)). Zero LLM
  calls, fully retroactive, off the replay surface.
- **Spectacle:** The lane-history timeline snaps a visible step on June 14 —
  verb-mix, sentence length, and retry rate all jump the same day — and the run
  browser stamps EPOCH: GEMINI CHANGED across every run that straddles it, with a
  before/after quote pair from the same agent.
- **Builds on:** Months of labeled history in run.sqlite, X-Routed-Via, run browser +
  inspector + uPlot, adaptive-routing registry (lane identity); shares the versioned
  feature-extraction layer with #16 and #5.
- **Effort:** M
- **Risks / why T2:** Detects THAT behavior changed, not why — serving-param changes
  and our own prompt-template releases both masquerade as weight swaps, so features
  must be conditioned on prompt-template version and release tags; step-detection
  thresholds need tuning against known upstream changelogs; sparse lanes may never
  accumulate enough signal. Moderate spectacle-per-effort keeps it out of T1, but as
  guardian of every other instrument's validity it should land soon after the shared
  feature layer exists.
- **Constraints:** Clean pass. $0, zero-LLM, retroactive, off-surface.

### 22. The Dream Lane — oneiric cognition that turns idle capacity into prophecy *(emergence)*

- **Pitch:** When an agent's turn cadence has slack, spend it: a cheap free-lane
  dream call remixes that agent's own memories into a short surreal narrative, which
  plants a seeded low-confidence belief trace and can be shared next morning as a
  dream-telling. Dreams are divergence fuel for the individual mind (each agent's
  dreams are functions of ITS memories, so no two dream alike) and raw material for
  Wave O: a shared dream becomes a rumor-meme, a recurring one becomes prophecy
  feeding religion's founding and schisms. The purest expression of the never-throttle
  law — idle capacity converts directly into more LLM calls and more emergence — and
  the feed gets a whole new register of content at zero marginal cost.
- **Spectacle:** An agent posts a dream that the temple burns; three ticks later a
  congregation panics and someone actually torches it — and the replay trace lets you
  scrub the exact causal chain from dream to arson.
- **Builds on:** Memory buffer + reflections, feed lanes, adaptive lane routing +
  free-tier lanes, EM-155 replay law; amplified by Wave O seams (EM-250 memes,
  EM-261/262 religion) as they land.
- **Effort:** M
- **Risks / why T2:** Full payoff is gated on Wave O pieces that are filed but not
  landed (dream → meme → prophecy → schism); a phase-1 slice (dream call + seeded
  belief + dream-telling) rides shipped substrate and could pull forward. Needs the
  shared epistemic tag (with #19) so dream-beliefs don't silently pollute factual
  beliefs — agents should KNOW it was a dream; the drama is choosing to believe it
  anyway. **Determinism flag:** dream scheduling must key on deterministic tick
  slack, never wall-clock idle time.
- **Constraints:** No-throttling exemplar (adds calls). Determinism flag above is the
  one hard design requirement; outputs land on the recorded trace.

### 23. Replay Cinematographer — auto-cut highlight reels and skyline hyperlapses from the deterministic log *(spectacle)*

- **Pitch:** Byte-identical replay means any window can be re-rendered with a camera
  that KNOWS the future — a Cinematographer pass picks the top-N salient windows
  (from the Drama Wire scorer, #18), replays each in the 3-D town with pre-planned
  dolly/track/crane moves (it knows exactly where the arsonist will walk), overlays
  feed captions, and captures shareable webm/GIF client-side via MediaRecorder at $0.
  Second output mode on the same substrate: the growth hyperlapse — render the city
  every K ticks and play 6 hours of civilization in 60 seconds, buildings accreting
  via F1 cluster placement, murals appearing, roads snaking out; when EM-299 recipes
  land this becomes the per-model skyline-signature reel for free. Replay THEATER,
  not a live auto-camera: offline, repeatable, exportable — the piece of v5's
  direction 10 that determinism makes uniquely ours.
- **Spectacle:** A 60-second golden-hour hyperlapse from empty ground to dense town —
  the single most shareable artifact this project can produce, and it is pure
  determinism payoff.
- **Builds on:** Byte-identical replay (EM-155) + scrubber/selectors, Wave C CC0 town
  + animated villagers, F1 free placement (EM-268), facades/murals (EM-298), #18 for
  shot selection. Scope as slice 3 of the Moments & Postcards pipeline (#12) — same
  `(run id, tick range, camera spec)` primitive, one pipeline.
- **Effort:** L overall — but the **hyperlapse slice alone is near-T1** (easy, always
  looks good) and should ship first.
- **Risks / why T2:** Auto-cinematography quality is genuinely hard — a bad robot
  camera reads worse than none, so hyperlapse before auto-cut drama shots;
  MediaRecorder codec/perf variance across browsers; rendering replay windows at
  speed needs frame-pacing care in R3F.
- **Constraints:** Clean pass. $0, client-side, off the replay surface; actively
  showcases the EW-dense city (the hyperlapse IS the art target as footage).

## Round 2 · Tier 3 — Parked, with reasons

### 24. Irony Cam — shadow one agent; the feed splits into what's true vs what they believe *(spectacle)*

- **Pitch (condensed):** Pick an agent: a shoulder-height follow cam locks on while
  the feed switches to their subjective channel — beliefs, overheard fragments,
  phantom commitments — rendered as a split lane against ground truth with
  divergences highlighted. Every deception becomes a horror-movie "don't open that
  door" moment: top lane "Kade stole the bread", bottom lane "Mira believes: VESPER
  stole the bread", follow cam on Mira walking toward Vesper's house.
- **Effort:** M
- **Why parked:** Before Wave O rumor volume rises, belief ≈ truth most of the time
  and the split lane is boring — the proposal itself says sequence after EM-251/252
  (rumor distortion), which have not landed. Secondary frictions: the follow cam
  needs villager pathing polish at close range (assets tuned for district scale), and
  the split-lane UI competes for feed width on the chat-first centerpiece layout.
- **Unblock:** EM-251/252 landed + a layout treatment that doesn't tax the feed. Then
  it is the cheapest suspense mechanism in television, pointed at the sim.
- **Constraints:** Determinism clean (render/perception overlay, no sim state).
  Feed-centerpiece tension is the design constraint to solve.

### 25. The Understudy — a local shadow brain for every cloud agent, and the divergence corpus it mints *(model-lab)*

- **Pitch (condensed):** Local Ollama becomes every cloud agent's UNDERSTUDY — a
  per-agent shadow computing what IT would have done, so when a 429 window hits
  mid-turn the understudy's already-warm answer plays instantly and the feed never
  thins. Converts the EM-301 churn from the lab's chief operational wound into its
  best feature demo ("cloud dark 90s — zero turns lost"), at $0, with call volume UP.
  The byproduct is the prize: every dual-computed turn is a paired (cloud, local)
  sample under identical context — a continuously growing same-prompt divergence
  corpus no offline benchmark can fake.
- **Effort:** L
- **Why parked:** Requires an always-on Ollama host — an infra commitment not yet
  made (the same blocker that parked Night Shift Society, #14 — decide the host
  question ONCE for both); the relation to EM-167's overflow lane must be declared at
  intake (standby-with-corpus reframes it as a feature, not a fallback); the
  played-answer/event boundary must be airtight or shadows leak into sim state; the
  interaction with soft-pin failover needs design (understudy fires only on terminal
  bounce failure, never competes with the bounce loop); shadow context must be
  clamped deliberately (the #77/#80 lesson — big contexts exclude small models).
- **Unblock:** Host decision + EM-167 scoping + played-answer boundary and soft-pin
  interaction written down. Then this is the single best answer to the open EM-301
  operational lead.
- **Constraints:** $0-cash but a standing infra commitment (flagged, same as #14).
  No-throttling positive (adds unmetered local calls). Determinism: sidecar-only
  shadows; only the played answer becomes a sim event.

### 26. The Quarters — spatializing the skyline signature: model neighborhoods with a visible seam *(model-lab)*

- **Pitch (condensed):** EM-297 returned GO — gemini builds monumental marble domes,
  gpt-oss builds frugal timber sheds — and EM-299 will put those signatures in one
  city, where free placement will interleave them into statistical mush. The Quarters
  is the experimental-design layer that makes divergence legible to a CAMERA: a
  casting mode seeds each model family's agents in loose spatial clusters (F1
  cluster-accretion already anchors builds near the builder), so per-model
  architecture condenses into adjacent, walkable neighborhoods with a real visible
  seam. Agents stay completely free to move, trade, and build anywhere — BOUNDARY
  DRIFT is the metric: who colonizes whose quarter, which styles hybridize at the
  seam, whether zone-rule politics erupt along it.
- **Effort:** M
- **Why parked:** Hard-gated on EM-299 shipping (and the EM-297 qwen/llama top-up
  probe before its visual sign-off) — the dependency is a whole unbuilt system, not a
  sequencing preference. Guardrail is existential: casting-time initial placement
  ONLY, zero runtime steering, or the emergence claim dies. Boundary-drift metric
  needs a definition robust to organic sprawl (and the EM-303 world-extent clamp when
  it lands); with only 2 lanes proven divergent, degrade gracefully to a 2-quarter
  town.
- **Unblock:** EM-299 landed + probe top-up passed. Then this is the EW-dense art
  target rendered as science — the golden-hour pan across the marble/timber seam is
  the project's poster shot.
- **Constraints:** Single-city by construction (neighborhoods, not cities). EW-dense
  aligned par excellence. Puppeteering line must be named at intake.

## Round 2 constraint check — full sweep

No Round 2 proposal hard-violates a standing law. Flags, by law:

- **$0-first:** All 11 new items are $0-cash (zero-LLM projections, free-lane calls,
  client-side rendering, local models). One standing flag: the Understudy (#25)
  requires an always-on Ollama host — cash-$0 but a real infra commitment, shared
  with Night Shift (#14). Drama Wire's optional headline punch-up stays on free
  lanes; the Cinematographer's export is pure MediaRecorder.
- **Single-city deepening:** All compliant. The Quarters is explicitly neighborhoods
  within ONE city; the Bloodlines fold grows population in-city; the Ghost Race fold
  is a counterfactual timeline of the same city, not a second city.
- **No throttling / MAX call-rate:** Nothing mutes an agent. The Dream Lane is the
  purest expression of the law (idle slack → more calls); the Understudy ADDS
  unmetered local calls; the Bloodlines fold frames births as call-rate growth; the
  Healing House carries the hard guardrail — swap targets are always full-rate
  free/local lanes, NEVER a silent or muted lane.
- **Determinism / byte-identical replay:** Off-surface by design (no goldens): Babel
  Matrix, Drama Wire, Epoch Seismograph, Cinematographer, Irony Cam (perception/render
  overlay), Understudy shadows (sidecar; only the played answer is an event — the
  boundary is the named risk). On-surface (goldens + additive serialization
  required): Prophecy Board (god events; enum predicates load-bearing for
  deterministic scoring), Healing House (sentence-effect seam), Dream Lane (seeded
  triggers keyed to deterministic tick slack, NEVER wall-clock — the one hard flag in
  Round 2), Petri Protocols (seeded templates; the confederate bribe is itself an
  event), and every fold inherits its Round 1 entry's determinism requirements.
- **EW-dense art target:** The Quarters is the art target rendered as geography; the
  Healing House's grim register fits EW-dense (keep it expensive, not reflexive); the
  hyperlapse showcases the dense city as footage. Nothing pulls toward Stardew-cozy.
- **Prior-decision touches (need explicit ratification at intake, not silent
  adoption):** Drama Wire + Cinematographer vs the shelved auto-director direction
  (feed-native / offline-theater reframes); the Self-Narrative fold vs the FUTURE.md
  memory-summarization deferral (same max-call-rate inversion Round 1 argued for the
  Chronicle — ratify once, cite twice); the Ghost Race fold vs deferred
  counterfactual forking (zero-call-ghost reframe); Petri Protocols' confederate
  staging and the Quarters' casting-time seeding both sit on the puppeteering line —
  name the boundary in each intake entry; the Understudy's relation to EM-167 must be
  declared.
- **Scope-overlap guards:** Babel Matrix distinct from EM-119 (within-run dyads);
  Seismograph + Babel + Fingerprint share ONE versioned feature layer; Drama Wire is
  the single salience scorer consumed by Storylines Rail, Moment Cam, and the
  Cinematographer; Healing House and Split-Screen Theater share one transplant
  primitive (institution vs instrument); Prophecy Board and Omens & Wonders share the
  god-omen perception line; postcard export ships once, in Moments & Postcards.

## How to file

Nothing in this report is tracked work. Entries enter the ledger
(`docs/REMAINING-WORK.md` and friends) **only** via the fail-closed `plan-intake`
skill, with explicit user approval per entry. To act on this report, run
`plan-intake` against it and approve/reject proposals individually; do not hand-copy
items into the ledger or BUILD-PLAN.md.
