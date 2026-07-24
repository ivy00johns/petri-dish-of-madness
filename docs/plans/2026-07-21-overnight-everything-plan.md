# Overnight "Every Angle" Plan — 2026-07-21

**Mission:** unattended overnight run. Root-fix the model-fallback/feed-error pain, refresh
FreeLLMAPI wiring against the live catalog, de-drift docs+skills, and ship a genuinely NEW
emergence capability the user wakes up to. No symptom-hiding, ever.

**Evidence base (produced this session, live-verified):**
- `scratchpad/research/pain-points.md` — 253 transcripts mined; top-10 ranked pains
- `scratchpad/research/fallback-review.md` — routing architecture map + failure taxonomy
- `scratchpad/research/world-inventory.md` — 75-verb capability map + meme-system autopsy
- `scratchpad/research/docs-skills-drift.md` — 23 drift findings (7 H)
- `scratchpad/freellmapi-models.json` (239 models, **92 available**) + `freellmapi-health.json`
  (scratchpad = `/private/tmp/claude-501/-Users-johns-Projects-petri-dish-of-madness/56c491a5-35b5-46b2-bd0f-c32fedd131a9/scratchpad`)

---

## Section 1 — Architecture Reasoning

### 1.1 The error-taxonomy reframe (why router fixes never stuck)
Of ~2,177 recent `parse_failure` events (since 07-14): **~44% are `rejected:True`
action-validation failures** — the model returned valid JSON and the *world* rejected the
action (unknown target/place, wrong location). Only ~30% (truncation + capacity) are lane
problems. Every past "fallback fix" attacked the 30% and left the 44% untouched — hence
"the more I fix routing the worse it feels." **Two independent tracks are required:**
- **Track A (lane-side):** stale/dead pins, silent proxy reroutes onto reasoning
  truncators, no runtime adoption, zero UI visibility.
- **Track B (world-side):** the prompt doesn't enumerate valid targets; no
  validate-and-repair. Caps how good the feed can ever look regardless of routing.

Transparency rule: feed cards get **cause-split labels** (rejected vs truncated vs
exhausted vs repaired) — more information, never less. Repairs are logged as visible
events. This honors fix-don't-hide while killing the undifferentiated "failed to produce
a valid action" wall.

### 1.2 The two mechanical amplifiers behind "fix claimed → pain returns"
1. **Restart-to-adopt:** routing config bakes per-run; a restart can land in a bad
   rate-window and make any fix look failed. Mitigate with runtime-adoptable paths
   (discovery refresh endpoint exists; quota-driven pre-emption) + a **Lane Health panel**
   so the user can *see* lane state instead of inferring it from error cards.
2. **Resume/refresh blind spot:** model chips vanish on resume; flicker/halo bugs recur.
   Filed as ledger items; chips fix attempted this run if S-sized.

Behavioral rule to codify (docs + memory): **diagnose routing from live `/api/health` and
`/api/lanes`, never from error strings.**

### 1.3 The meme verdict (the "figure out the meme thing" answer)
The culture system is **cosmetic to cognition**: `held_memes` never enters the decision
prompt; passive diffusion plants no beliefs; beliefs aren't serialized. Culture is
generated but not *lived* — which is exactly why it reads as spam (high-volume shallow
text with zero behavioral consequence). The fix is the **culture→cognition loop** via the
existing underused `_plant_belief`→prompt seam: near-zero new mechanics, the largest
emergent payoff available. Drift becomes *meaningful* (agents act on distorted beliefs),
so the feed-noise problem is solved at the root rather than by caps alone.

### 1.4 Surprise-feature selection (constraints, not a pre-commitment)
Chosen by an ideation+judge panel during the build, against hard criteria:
live-visible in feed AND 3-D world · rides existing seams (chronicle, drama wire, event
lanes, free art lane, canonized memes) · deterministic/replay-safe (off-surface or
golden-gated) · flag-gated · free lanes only · delights within one wake-up. Seed
shortlist (panel may beat these): **The Petri Gazette** (agent-written in-world newspaper
rendered as a real front page), **Festivals** (meme/faith-born recurring rituals with
nighttime 3-D spectacle), **The Town Archive** (persistent agent-authored texts as
artifacts + cross-run cultural memory), **Origin-Myth cycle** (agents mythologize their
own run history via chronicle). Panel picks 1 flagship + optionally 1 small companion.

### 1.5 Sequencing logic
Fixes before features (a broken feed poisons any demo); observability before discovery
flip (see the lanes before trusting them); docs/ledger after code (record reality);
go-live last with a measured baseline → target: parse-fail rate 12–18% of llm_calls →
**<6%** after W1+W2.

### 1.6 Risks / ambiguities surfaced
- Discovery-ON sweep can pull in reasoning truncators → **must** reasoning-tag/denylist
  (nemotron reasoning variants, r1, gpt-oss-120b) *before* enabling.
- Live flag-flips are historically user-gated. Compromise: everything merges flag-OFF with
  green gates (established W31 pattern); the go-live wave flips ONLY (a) lane/pin config,
  (b) the culture→cognition loop, (c) the surprise flag — each with a 15-min live watch +
  screenshot, and `run.sqlite` backed up (VACUUM INTO) first. Anything misbehaving gets
  flipped back OFF (config revert), not silenced.
- `personas.yaml` suggested_profiles + world.yaml cast pins both need the repin; miss one
  and the "old pins are the top failers" pattern recurs.

---

## Section 2 — Build Plan

**Base:** merge PR #114 (`fix/feed-health`, already the live-running fixes) into `main`
first if gates pass; build in worktree `../petri-dish-build` off `main`. PR #113 handled
in W3. Feature work: one branch per wave, PR opened, merged on green gates (flags OFF).

**Gates (every wave):** `.venv/bin/python -m pytest` (backend ≈2,800) ·
`/usr/local/bin/npx vitest run` (web; move repo-root `node_modules` aside in worktrees —
ELOOP) · `npx tsc -b --force` · determinism goldens where sim-surface is touched · UI
changes require a rendered Playwright screenshot (hard rule).
Commits: conventional format, no session-URL trailer, Co-Authored-By kept; signing off.

### W1 — Lane root fixes (Track A, S-sized, do first)
| # | Item | Files |
|---|------|-------|
| 1 | Fix dead pins: `groq-llama`→live id, `cerebras-glm`→live id, embed model id | `config/profiles.yaml` |
| 2 | Reasoning-tag `gpt-oss-120b` (+ audit tags vs live catalog) so strict-JSON turns skip truncators | `config/lanes.yaml`, `config/profiles.yaml` |
| 3 | De-stale `personas.yaml` suggested_profiles + world.yaml cast onto reachable clean-JSON endpoints | `config/personas.yaml`, `config/world.yaml` |
| 4 | Add rich clean-JSON lanes from live catalog: `glm-5.2`, `qwen3.5-122b`, `deepseek-v4-flash`, `kimi-k2.6`, `minimax-m3` (verify each with a live strict-JSON probe before pinning) | `config/lanes.yaml`, `config/profiles.yaml` |
| 5 | Cause-split feed failure cards: `rejected` / `truncated` / `exhausted` / `timeout` distinct labels + copy | backend event emit + `web` feed card |

### W2 — Action-rejection cut (Track B — the 44%)
1. Compact valid-target enumeration in the decision prompt (places/agents in scope,
   prompt-diet-aware — measure prompt growth, keep within output ceiling per the #77 lesson).
2. Validate-and-repair: nearest-match coercion for near-miss targets, emitted as a visible
   `action_repaired` event (never silent); hard rejects keep the cause-split card.
3. Baseline + after-metric via `run.sqlite` query; report actual % cut in wave results.

### W3 — Observability UI (the user can finally SEE lane health)
1. **Lane Health panel**: consume existing `/api/lanes/registry` + `/api/lanes` health +
   X-Routed-Via reroute map + optional admin-quota enrichment. Lab `lab-*` design tokens,
   screenshot-validated.
2. **Finish PR #113** (Lab Setup panel): style with real `lab-*` tokens (it shipped
   unstyled — known failure), screenshot, update PR, merge on green.

### W4 — Safe discovery-ON + quota pre-emption
1. Catalog-wide reasoning/truncator tag sweep + denylist so the `*` sweep is safe.
2. Enable `adaptive_routing.discovery.enabled` in config (adopts at W7 restart) — dead
   pins then retire themselves; runtime refresh endpoint already exists.
3. Quota-driven pre-emption: demote a lane when admin `/api/health` shows its pool
   exhausted (plumbing exists as enrichment; make it act, transparently logged).

### W5 — Emergence wave (the headline)
1. **Culture→cognition loop** (flag `world.comm.lived_culture`): inject top-K held memes
   into perception; passive diffusion plants decaying beliefs; canonized memes get
   mechanical teeth (e.g. motif-aligned action bonuses); serialize beliefs. Determinism
   golden required. This is the meme-system root fix.
2. **Surprise flagship** via ideation+judge panel (criteria §1.4): 3 independent
   proposals → scored → build winner flag-gated + its feed/3-D surface. Budget the most
   build effort here; it's the wake-up moment.

### W6 — Docs, skills, ledger, memory
1. Apply the 23 drift findings (START-HERE status table, REMAINING-WORK reconcile vs
   merged #107–#112, GUIDE config-knob regen incl. `lanes.yaml`/`adaptive_routing`/comm
   knobs, README counts, FUTURE/ARCHITECTURE multi-city rows).
2. File new EM-325+ ledger entries for: this plan's waves, chips-on-resume, flicker/halo,
   `_parse_comm` wiring rule, rejection-cut follow-ons. Sweep done rows to COMPLETED-WORK.
3. `use-freellmapi` skill roster touch-up (add reka, drop OVH from keyless list).
4. Memory: new files for the not-yet-captured pains + the live-health-first diagnosis
   rule + this run's outcome.

### W7 — Go-live + verification (the wake-up)
1. Backup `data/run.sqlite` (`VACUUM INTO` timestamped copy).
2. Start sim cleanly (no `--reload`), new config adopted (pins, discovery, lived-culture,
   surprise flag). Comm stays ON; multi-city stays OFF (user sign-off pending).
3. Watch ≥20 min: parse-fail rate vs baseline (target <6%), no idle-fallback flood, chat
   legible, surprise visibly firing. Playwright screenshots (feed + 3-D + new panels).
4. Anything misbehaving → flag back OFF + restart + note in report. Never silence.
5. Write **`MORNING-REPORT.md`** at repo root: what shipped, live evidence screenshots,
   error-rate before/after, what to sign off, what was deliberately left OFF.

**Team sizing:** ≤4 parallel agents per wave, waves sequential with QA gates. W1+W2 may
overlap (disjoint files) — orchestrator's call. Contracts for W2 (prompt/perception
shape), W5 (belief/meme injection schema + surprise feature), W3 (lane API consumption).

**Out of scope tonight:** multi-city sign-off, paid lanes, Ollama overflow (EM-167),
throttling of any kind, deleting/rewriting user branches, mass ledger restructuring.
