---
title: The 5-minute live demo — 3 agents in the 3D village (FreeLLMAPI)
tags: [the-5-minute-live-demo-3-agents-in-the-3]
paths: [Gemini/Qwen/DeepSeek, config/profiles.yaml, deepseek-ai/deepseek-v4-pro, "**/inspector**"]
updated: 2026-11-10
---

Imported from `docs/GUIDE.md:51` by Andon (import docs/GUIDE.md:51 5279e6fe1db5f693); the original stays there.

The default world is **3 cozy villagers** (Ada, Bram, Cleo) who start together in the
plaza and chat, trade, forage, fund community projects, and pass town-hall rules — while a
cat and dog cause chaos underfoot. Each requests a different model;
all are routed through a local [FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi)
OpenAI-compatible proxy. The center view is a **cozy 3D town** built from real CC0 game art
(Stardew × Animal-Crossing vibe) — animated villagers walk the district streets between real
buildings with floating chat bubbles. A toggle in the panel header switches back to the
legacy 2D map.

> **The fun twist:** FreeLLMAPI is a *best-available router* — it often serves your request
> from a different provider than you asked for. The UI shows the model that **actually
> answered** each turn (the `X-Routed-Via` header), so you ask for Gemini/Qwen/DeepSeek and
> watch Cohere, Cerebras-GLM, gpt-oss-120b, or Gemma show up instead. That divergence is the
> show.

**Step 1 — Run a FreeLLMAPI proxy and enable a provider**

Run the proxy locally (default `http://localhost:3001`) and enable at least one provider on
its dashboard — see the [FreeLLMAPI install guide](https://tashfeenahmed.github.io/freellmapi/).
A zero-key anonymous provider (Pollinations / LLM7 / Kilo) is enough to smoke-test the pipe.

**Step 2 — Configure**

```bash
cp .env.example .env
# Edit .env:
#   FREELLMAPI_BASE_URL=http://localhost:3001/v1
#   FREELLMAPI_KEY=freellmapi-...        # the proxy's unified key (dashboard → Keys)
```

Frontend flags live in the **same `.env`** — Vite reads it via `envDir`, and only
`VITE_*`-prefixed vars ever reach the browser (backend keys stay server-side). For
example, `VITE_COFFEE_BUTTON=false` hides the header's "Buy me a coffee" button.

The default profiles (`config/profiles.yaml`) request three distinct models:

- `gemini-flash` → `gemini-3.5-flash`

- `qwen-next` → `qwen/qwen3-next-80b-a3b-instruct:free`

- `deepseek-pro` → `deepseek-ai/deepseek-v4-pro`

If your proxy exposes different IDs, edit `config/profiles.yaml` — the router will fail over
regardless. Confirm what your proxy serves with `curl -s $FREELLMAPI_BASE_URL/models -H "Authorization: Bearer $FREELLMAPI_KEY"`.

**Step 3 — Run**

```bash
./dev
```

**Step 4 — Watch**

Open **[http://localhost:5173](http://localhost:5173)** and click **Start**. The 3D village comes alive:

- Each villager is tinted by its requested model; the roster strip along the bottom of

the world view carries each one's card — energy, credits, mood, and the **model that
actually answered** its last turn.

- Speech appears as chat bubbles above villagers and streams in the live feed (the

left column — drag its edge wider if the chat is the show for you).

- The camera is yours: **drag** to orbit, **right-drag** to pan, **click a building**

to zoom to it, **click a villager or critter** (in the scene or on the roster strip)
to follow them, and hit **RESET VIEW** to snap back to the default framing.

- Live-reassign any agent's model from its panel — it takes effect on the next turn.

- A cat (**Mochi**) and dog (**Biscuit**) roam and cause chaos — knocking things over,

stealing food — their in-character lines streaming to the Animal Chaos Feed.

- Filter the live feed with the category chips: click a chip to show **only** that

category, click more to stack two or three (e.g. **◉ Chat** + **🐾 Animals**), and
click **✕ clear** to reset.

- Open **/inspector** to replay ticks, read the decision trace behind any action, and

watch the social graph + model dashboards build up.

Runs comfortably past 5 minutes with all 3 alive (they recharge to survive); expect emergent
gossip, alliances, the occasional theft, and passed rules.
