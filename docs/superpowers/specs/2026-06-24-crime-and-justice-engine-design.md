# EM-240 — Crime & Justice engine + persona role/disposition schema (design)

> Status: **design — awaiting "go".** No code yet. This is **Spec #1 of 3** in a
> persona-expansion track agreed during brainstorming:
> - **EM-240 (this doc)** — the Crime & Justice *engine* + the persona role/disposition
>   schema it introduces, seeded with a handful of criminals/enforcers to exercise it.
> - **EM-241 (future)** — the broad persona-library *content* expansion (review/improve
>   the existing 10, author many more across categories) — consumes this schema.
> - **EM-242 (future)** — a persona *management UI* (browse/edit/create at runtime) —
>   consumes this schema.
>
> Engine-first is deliberate: the persona schema added here is the shared contract that
> the content pass and the UI both hang on, so it must land first. Source map: the
> existing persona library is 10 read-only character cards in `config/personas.yaml`,
> served verbatim by `GET /api/personas` and used only to prefill the spawn form
> (`web/src/components/controls/PersonaPicker.tsx`). Crime *acts* (`action_steal`,
> `action_arson`) already exist but are not tied to any persona — every agent shares one
> action set. This spec gives personas mechanical weight for the first time.

## Goal

Turn antagonism from a loose set of one-off actions into a **self-balancing crime↔justice
loop**: criminals commit a richer menu of crimes; witnessed crime accrues **notoriety**;
**enforcer** personas investigate, accuse, and either detain on the spot or escalate to a
**town-hall trial**; conviction means jail + restitution. The loop is **emergent, not
scripted** — the LLM decides every crime and every enforcement act in character; the engine
only does deterministic bookkeeping (notoriety, witness trust, status expiry, vote tally).

This serves the lab's north star directly: investigations, accusations, trials, jail-cell
pleading and plotting are all **extra in-character agent turns** — more LLM call-rate, more
chat-feed drama — at **zero extra cost per action** (every crime/justice verb executes
reflex-tier; only the agent's normal decision turn calls a model).

## Design principles (locked in brainstorming)

1. **`disposition` and `role` are orthogonal.** A `criminal` + `enforcer` is a *dirty cop* —
   intended, not a bug. The most interesting arcs live at the corners.
2. **Crime actions are available to everyone**, gated only by active rules (`ban_stealing`,
   `ban_arson`, …) — *not* locked to `disposition`. Disposition biases via the **prompt**, so
   a "lawful" agent *can* snap. Enforcer actions, by contrast, **are** gated to `role: enforcer`.
3. **Only *witnessed* crime builds notoriety.** Get away clean and you're fine. This is what
   makes `investigate` meaningful and gives criminals a reason to strike when alone.
4. **Ride existing seams.** Trials are a new governance rule `effect`, not new voting code.
   Jail is a place + a validation gate. Status expiry rides the existing per-turn tick check.
   New fields are additive/optional so legacy worlds serialize byte-identically.
5. **Jail is not dead air.** A jailed agent loses crime/movement actions but **keeps talk and
   reflect** — the cell produces feed drama (pleading, plotting, repenting), not silence.

---

## Section 1 — Data model (the shared contract)

### Persona-card + `AgentState` fields (copied from card at spawn, editable in spawn form)

| Field | Values | Default | Meaning |
|---|---|---|---|
| `disposition` | `lawful` · `opportunist` · `criminal` | `lawful` | Prompt bias toward illicit opportunity. A dial, not a cage. |
| `role` | `citizen` · `enforcer` | `citizen` | `enforcer` unlocks the justice action set. |

`opportunist` is the middle tier ("petty when convenient"); it gives the prompt a dial rather
than a binary. Both fields live on the persona YAML card **and** on `AgentState`
(`world.py` `AgentState`, ~lines 144–189), copied at spawn like `name`/`personality`/`profile`.
`load_personas()` (`config/loader.py` ~1714) and `_resolve_spawn_fields()` learn the two new
optional keys; both default when absent, so the existing 10 cards parse unchanged.

### New runtime scalars on `AgentState` (additive — serialized only when set)

Follows the established optional-field pattern (`demoted_from` EM-168, `plan` EM-223,
`parents` EM-114): a pre-EM-240 snapshot stays byte-identical because these serialize only
when non-default.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `notoriety` | `int` (0–100) | `0` | Accrues from **witnessed** crime; decays while lying low. |
| `crime_status` | `str \| None` | `None` | `wanted` · `detained` · `jailed` · `exiled`. |
| `crime_status_until_tick` | `int` | `0` | Release tick for `detained`/`jailed`. |
| `rap_sheet` | `list[dict]` (cap ~10) | `[]` | `{tick, crime, victim_id, witnessed}` — fuels trials, the feed, EM-242. |

`exiled` is reserved here for forward-compatibility (a faction-banishment path); EM-240 ships
`wanted`/`detained`/`jailed` and leaves `exiled` unused but valid.

---

## Section 2 — Crime action set + notoriety mechanics

### Six new verbs (all reflex-tier execution; chosen by the agent's normal LLM turn)

Each verb: mutates state → calls `_update_trust(witness, actor, delta)` for every co-located
witness via `agents_at(place)` (the `action_arson` template, `world.py` ~2762) → bumps
`notoriety` **if witnessed** → appends to `rap_sheet` → emits a feed event. Registered in
`TOOL_REGISTRY` (`runtime.py` ~281–342) with `tier: "reflex"` and an `agreement_gate` where a
matching ban rule exists.

| Verb | Behaviour | `agreement_gate` |
|---|---|---|
| `heist` | Big-score theft, `heist_max ≫ steal_max`. Gated on target wealth (or a prior "case" step). Heavy notoriety, wide witness hit. | `ban_stealing` (reused) |
| `extort` | Threaten a co-located agent for credits. Refusal (low payoff) snaps the relationship to `enemy` via the reflex-transition seam. | `ban_extortion` (new) |
| `vandalize` | Damage a building short of arson (short blackout / stat hit). Lighter than `action_arson`. | `ban_vandalism` (new) |
| `bribe` | Pay credits to a co-located `enforcer` to wipe own notoriety / kill a pending accusation. **If witnessed, the enforcer gains notoriety.** | — |
| `launder` | Spend "hot" credits (lose a cut) to reduce notoriety. Available only when `notoriety > 0`. | — |
| `recruit` | **Contract-crime**: post a crime offer to another agent (two-turn handshake, below). | — |

`heist` **reuses the existing `ban_stealing` rule** (it is theft) rather than inventing a new
gate. `ban_extortion` and `ban_vandalism` are **new ban effects** added to `valid_effects`
(`world.py` ~1958) so the town can outlaw those crimes the same way it already bans stealing
and arson — additive, defaulted off.

**Fold-in:** `action_steal` and `action_arson` join the taxonomy — they now *also* bump
`notoriety` and append to `rap_sheet`. Their existing trust deltas and gates are unchanged
(purely additive).

**Scope note (YAGNI):** the earlier `fence`/`smuggle` ideas **collapse into `launder`** — one
"clean your money" verb covers the illicit-economy beat without three near-identical actions.
If a *named-fence* economy is wanted later, it's an EM-241/own-spec follow-on.

### `recruit` — the one two-turn verb

Single-turn execution everywhere else; `recruit` is a handshake so conspiracies read as
negotiations without extra calls:

1. Recruiter's turn: `recruit(target, crime, split)` posts a **pending offer** on the target
   and emits a `recruited` feed event. No crime occurs yet.
2. Target's **next** LLM turn sees the offer in context and may `accept`/decline in character.
3. On accept: the target commits `crime`; payoff splits per `split`; **notoriety spreads to
   both**; a `partner` bond is set both ways (`set_relationship`, `world.py` ~3696) → the pair
   (and their mutual warm edges) **auto-derive into a faction** = a criminal ring
   (`recompute_factions`, ~3973), surfaced to members via the existing `faction_line`.

### Notoriety model (deterministic, per tick)

- **On a witnessed crime:** `notoriety += base(crime) × witness_factor(n_witnesses)`, clamped
  0–100. Unwitnessed → no notoriety gain (the rap-sheet entry records `witnessed: false`).
- **Passive decay:** `notoriety -= notoriety_decay` each tick (floor 0) — lie low to cool off.
  `launder`, `bribe`, and serving a sentence apply an extra one-off reduction.
- **Threshold:** crossing `wanted_threshold` sets `crime_status = "wanted"` (emits `wanted`);
  dropping back below clears it. `wanted` surfaces in the feed and in the agent's own prompt.

---

## Section 3 — The justice loop

### Enforcer action set (gated to `role: enforcer`; reflex-tier execution)

| Verb | Behaviour |
|---|---|
| `investigate` | At a location, convert *unwitnessed* `rap_sheet` entries for a suspect into confirmed notoriety **iff a co-located witness exists**. This is how "getting away with it" unravels. |
| `accuse` | Formally name a suspect → open a **pending case** (feed event). Precondition for a trial. |
| `detain` | Move suspect to **jail**, `crime_status = "detained"` for `detain_sentence` ticks. Allowed only **red-handed** (enforcer co-located when the crime fired) **or** `notoriety ≥ detain_threshold`. The fast lane. |

### Hybrid resolution — two tracks

1. **On-the-spot detain** — petty / caught-red-handed: immediate short jail; modest notoriety
   burn-off on release. No vote.
2. **Trial** — serious / repeat / contested cases escalate to a **town-hall trial that reuses
   the governance machinery**:
   - New rule `effect: "trial"` added to `valid_effects` (`world.py` ~1958), with
     `payload: {defendant_id, charges}`. Reject a duplicate trial for a defendant already on
     trial (mirrors demolish's target-scoping).
   - The town votes via the **unchanged** `action_vote` (~2044). `_evaluate_rule` tallies.
   - On `_on_rule_activated` for `effect == "trial"`:
     - **Convicted** (majority guilty) → `crime_status = "jailed"` for `trial_sentence` ticks +
       a **fine**: confiscate credits, pay **restitution** to listed victims (from `rap_sheet`),
       remainder to the commons. Emit `trial_verdict` (guilty) + `jailed`.
     - **Acquitted** → notoriety partially cleared; the **accuser takes a standing hit** (trust
       penalty from onlookers) so frivolous accusations cost enforcers. Emit `trial_verdict`
       (acquitted).

### Jail

A `jail` place (`PlaceState.kind = "civic"`), added to the hand-authored town config (and a
procgen slot). While `crime_status ∈ {detained, jailed}`, the `_validate_world` gate
(`runtime.py` ~1210) **blocks `move_to` and all crime/most actions**, but **leaves talk and
reflect open** — the cell generates feed drama, not dead air. Release is automatic when
`tick ≥ crime_status_until_tick` (checked at turn start beside the existing status logic);
notoriety is reduced on release. Emit `released`.

### Corruption (emergent, not scripted)

- `bribe` wipes a criminal's notoriety — but a **witness** to the bribe raises the *enforcer's*
  notoriety. Dirty cops get caught the same way criminals do.
- `disposition: criminal` + `role: enforcer` is a corrupt sheriff by construction.
- The acquittal standing-hit means even honest enforcers weigh real risk on every accusation.

---

## Section 4 — Prompt integration, events, config, seeds, testing

### Prompt integration (where disposition becomes behaviour)

In `_assemble_context` (`runtime.py` ~1556–2100), a conditional block mirroring the existing
`faction_line` seam (~2054):

- `opportunist` / `criminal` → a nudge ("you see angles others miss; crime's on the table when
  the payoff's right and nobody's watching") **plus** live status ("You are **WANTED**" /
  "You're in **jail** for N more ticks").
- `enforcer` → a duty line ("you keep the peace — investigate, accuse, detain, escalate to
  trial") **plus** any open cases against suspects in view.
- **Lawful citizens get no crime prompt** — the menu doesn't nudge the whole town into mayhem;
  crime stays in-character. Criminal-ring membership already surfaces via `faction_line`.

### Events & feed

New open-ended `kind`s (the events schema accepts any string; register in `x-known-kinds` in
`contracts/events.schema.json` for docs): `crime_committed`, `crime_witnessed`, `wanted`,
`investigation`, `accusation`, `detained`, `trial_proposed`, `trial_vote`, `trial_verdict`,
`jailed`, `released`, `bribe`, `recruited`. Each carries `actor_id`/`target_id`/`payload` so
the feed reads as a story. Emission rides the existing `_apply_action` wrapper (`runtime.py`
~4095), which stamps actor/profile/tick and chains parked relationship events via `_multi`.

### Config (`crime:` block in `config/world.yaml`; all defaulted → existing worlds unchanged)

Mirrors the `steal_max` / `ban_*` style. **Proposed defaults, to re-tune against a live run:**

| Key | Proposed default | Notes |
|---|---|---|
| `wanted_threshold` | 40 | notoriety → `wanted` |
| `detain_threshold` | 60 | on-the-spot detain without red-handed |
| `notoriety_decay` | 2 / tick | cool-off rate |
| `heist_max` | 30 | vs `steal_max` (8) |
| `extort_max` | 15 | |
| `detain_sentence` | 6 ticks | fast-lane jail |
| `trial_sentence` | 20 ticks | conviction jail |
| `bribe_efficacy` | 0.75 | fraction of notoriety wiped |
| `launder_cut` | 0.3 | fraction of laundered credits lost |
| `trial_quorum` | reuse rule quorum | no new tally code |
| `restitution_split` | victims first, remainder commons | |

### Seed personas (just enough to exercise the engine end-to-end; broad pass = EM-241)

Add to `config/personas.yaml` (new optional `disposition`/`role` keys; existing 10 untouched):

- **3 criminals** — a *Con Artist* (extort/recruit), a *Smuggler* (launder-heavy), a
  *Protection Racketeer* (extort/heist).
- **2 enforcers** — an honest *Sheriff* and a morally-grey *Vigilante*; **promote Brick**
  (existing "Retired Enforcer") to `role: enforcer`.
- **1 opportunist** — a "petty when convenient" type, to show the middle tier.

~6 new cards + 1 promotion — enough to see crimes, witnesses, an investigation, a bribe, a
trial, and a criminal ring form in a single run.

### Testing & backward-compat

- **Golden-snapshot:** a pre-EM-240 world serializes byte-identically (proves additive fields).
- **Per-verb units:** state mutation, witness trust delta, notoriety gain (witnessed vs not),
  rap-sheet append, correct `agreement_gate` blocking.
- **Notoriety:** accumulation, decay floor, `wanted` set/clear at threshold.
- **Justice flow (happy path):** red-handed `detain`; and the full
  `accuse → propose trial → vote → convict → jail → fine/restitution → release` chain.
- **Jail gate:** blocked verbs rejected; talk/reflect still allowed; auto-release at expiry.
- **Corruption:** witnessed `bribe` raises the enforcer's notoriety; acquittal docks the accuser.
- **Conspiracy:** `recruit` two-turn handshake → `partner` bond → criminal-ring faction derives.

---

## Out of scope (this spec)

- Broad persona-library content expansion → **EM-241**.
- Persona management UI (runtime browse/edit/create; persisting edits back to YAML/DB) →
  **EM-242**. Until then personas remain YAML-authored at boot; the new fields are editable per
  spawn via the existing spawn form.
- A named-`fence` illicit economy, bounty/reward boards, gang-vs-gang turf war — possible
  future follow-ons; not needed to prove the loop.

## Dependencies & extension points (from the engine map)

| Concern | Seam | Location |
|---|---|---|
| New actions | `TOOL_REGISTRY` entries (`tier: reflex`, gates) | `runtime.py` ~281–342 |
| Action validation / jail gate | `_validate_world` | `runtime.py` ~1210 |
| Witness consequence | `_update_trust` + `agents_at` | `world.py` ~3503, ~3632 |
| New agent scalars | `AgentState` additive optional fields | `world.py` ~144–189 |
| Trial = governance | `valid_effects` + `_on_rule_activated` + `action_vote` | `world.py` ~1958, ~2044 |
| Jail = place | `PlaceState` (`kind: civic`) | `world.py` ~237 |
| Event emission | `_apply_action` wrapper + `x-known-kinds` | `runtime.py` ~4095; `contracts/events.schema.json` |
| Criminal rings | `recompute_factions` (auto) + `set_relationship` | `world.py` ~3973, ~3696 |
| Persona load / spawn merge | `load_personas` / `_resolve_spawn_fields` | `config/loader.py` ~1714; `app.py` ~851 |
