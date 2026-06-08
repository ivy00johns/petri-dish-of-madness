# PetriDishOfMadness — Future / Out of Scope (frontier)

Explicitly **not** in v1. Kept here so they aren't lost and don't clutter the tactical
ledger. When a scope decision promotes one of these, give it an `EM-###` in
`docs/REMAINING-WORK.md` and remove it here.

Deferred from the design spec (§1 non-goals) and brainstorming:

- **TTS / voice** — agent speech as audio (the original used Google Chirp3-HD).
- **Reactive overhearing chains** — nearby agents auto-reacting to speech (the original's biggest LLM-call multiplier). v1 does one model call per tick.
- **Victory-Arch pitch cycle** — periodic evidence-backed credit-grant competition. v1 economy is work/forage/give/steal only.
- **LLM memory summarization** — compressing old memories via the model (the original's big hidden cost). v1 uses a fixed rolling buffer + beliefs.
- **Agent-authored tools** — agents proposing and adding new tools via governance.
- **Real weather / news integrations** — live external data feeding the world.
- **Image generation** — agents producing images.
- **Head-to-head analytics dashboard** — model-vs-model comparison stats (survival, cooperation, governance dominance). v1 ships the 2D map + live feed; analytics is a strong v2 candidate given the "comparison" angle.
- **Multi-world parallel runs** — the original ran 5 worlds (one per provider) simultaneously. v1 is single-world with mixed models inside it.
- **Replay viewer** — scrub a recorded run from SQLite snapshots. The schema supports it; the UI is deferred.

