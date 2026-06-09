# PetriDishOfMadness — Future / Out of Scope (frontier)

Explicitly **not** in v1. Kept here so they aren't lost and don't clutter the tactical
ledger. When a scope decision promotes one of these, give it an `EM-###` in
`docs/REMAINING-WORK.md` and remove it here.

Deferred from the design spec (§1 non-goals) and brainstorming:

- **TTS / voice** — agent speech as audio (the original used Google Chirp3-HD).
- **Victory-Arch pitch cycle** — periodic evidence-backed credit-grant competition. v1 economy is work/forage/give/steal only.
- **LLM memory summarization** — compressing old memories via the model (the original's big hidden cost). v1 uses a fixed rolling buffer + beliefs.
- **Agent-authored tools** — agents proposing and adding new tools via governance.
- **Real weather / news integrations** — live external data feeding the world.
- **Image generation** — agents producing images.
- **Multi-world parallel runs** — the original ran 5 worlds (one per provider) simultaneously. v1 is single-world with mixed models inside it.

Promoted to `docs/REMAINING-WORK.md` (and removed above per the convention):
replay viewer → EM-055 (shipped, W6) · head-to-head analytics dashboard → EM-059
(shipped, W6) · reactive overhearing chains → EM-081 (open, W11).

