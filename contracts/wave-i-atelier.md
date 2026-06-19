# Contract — Wave I · The Atelier (EM-210 → EM-213)

**Version 1.0.0** · ledger: `docs/REMAINING-WORK.md` Wave I · branch: `build/wave-i-atelier`

> Agents make ART for their own town: generate images on a FREE model → share them on the
> billboard → VOTE → the winner REPLACES a generic 3-D asset (a plaza banner). Built
> breadth-first (each slice a demo-able PR), **reflex-first** (zero critical-path LLM calls),
> **population-capped**, **replay-safe** (EM-155 byte-identical snapshots).

This contract is the integration layer. Backend and frontend build against it in parallel; the
QE agent gates each slice. File ownership is at the bottom — do not edit a file you do not own.

---

## 0. Cross-cutting invariants (ALL slices)

1. **Reflex-first / north-star.** `create_image` and `post_image` are `tier:"reflex"` tools — the
   prompt/choice rides the agent's existing single turn. ZERO extra `invoke-LLM` calls on the
   critical path. (Image *bytes* come from a free image endpoint off the critical path.)
2. **Replay-safety (EM-155) — the keystone.** Everything that lands in a world snapshot is
   **seeded-deterministic**, never `uuid4`, never wall-clock:
   - `image_id = "img_" + format(_seed_int("image", world.city_seed, place, proposer_id, ordinal) % (16**10), "010x")`
     (mirror `_prop_id`, `engine/world.py:~1276`; collision → bump ordinal, mirror props).
   - `url = "/assets/images/" + image_id + ".png"` — **derived from the id**, so it is known at
     reflex time and is identical across runs/replays.
   - The actual PNG is an **external side-artifact** in `data/assets/images/`. Its bytes NEVER
     re-enter the sim (no agent reads pixels; only the id/url/metadata strings flow). So a missing
     or differing PNG cannot change sim determinism.
3. **Background work emits NOTHING into the sim.** `create_image` records the gallery entry and
   emits the `image_posted` event **synchronously at turn time** (deterministic). The async part is
   *only* a best-effort network-fetch → file-write, drained from a transient outbox by the loop.
   No event is emitted from the async task — so async completion timing is off the replay surface
   (stricter than the narrator/animal pattern, which DOES emit async).
4. **Never stall a tick (skips-don't-queue).** Fetches are bounded by a semaphore
   (`world.params.image_gen.max_concurrent`, default 2). If at cap, **skip** the fetch (the gallery
   entry + event still exist; the PNG is simply absent → frontend fallback). No unbounded queue.
5. **Hermetic tests.** No test may hit the network. `conftest.py` sets `EM_IMAGEGEN_MOCK=1`; the
   provider's mock lane writes a tiny deterministic 1×1 PNG to the derived path (or skips the write
   and the test asserts on the gallery/event, not the file). Mirror the `EM_EMBED_MOCK` pattern
   (EM-222, `backend/tests/conftest.py`).
6. **Additive only.** Every new world-state field is absent-tolerant: pre-Wave-I snapshots restore
   byte-identically (`state.get(key, default)`). No DB schema migration — image metadata rides
   event `payload_json` + the in-memory/snapshot gallery.

---

## 1. Provider seam — `backend/petridish/imagegen/` (NEW module, backend-agent)

A tiny provider abstraction, mirroring `providers/` structure but far simpler.

```
imagegen/
  __init__.py
  provider.py     # ImageProvider protocol + build_provider() factory
```

- **Protocol:** `async def fetch_png(prompt: str) -> bytes | None` — returns PNG bytes or None on
  any failure (never raises into the loop).
- **Default provider = Pollinations** (zero-config, no key): GET
  `https://image.pollinations.ai/prompt/{url-encoded-prompt}?width=512&height=512&nologo=true`,
  follow redirects, 12 s timeout (`httpx.AsyncClient`), return `resp.content` on 200 else None.
- **Env opt-in = Cloudflare Workers AI:** if `CF_ACCOUNT_ID` **and** `CF_API_TOKEN` are set,
  POST to `.../accounts/{id}/ai/run/@cf/black-forest-labs/flux-1-schnell` with
  `Authorization: Bearer {token}`, body `{"prompt": prompt}`; decode the base64 image from the
  JSON response. On any failure, **fall back to Pollinations**.
- **Mock lane:** if `EM_IMAGEGEN_MOCK` is truthy, `fetch_png` returns a fixed minimal valid PNG
  (a hard-coded `bytes` constant) without any network call. `build_provider()` returns the mock
  provider in this case.
- **Selection precedence:** `EM_IMAGEGEN_MOCK` > Cloudflare (if env present) > Pollinations.

The provider does NOT decide paths or ids — the loop hands it a prompt and writes the bytes to the
contract-derived path itself.

---

## 2. World state — `engine/world.py` (backend-agent)

### 2.1 Gallery (the image record store) — I1
- `self.gallery: list[dict] = []` — init beside `self.billboard` (`~world.py:654`).
- Record shape (all JSON-safe, all deterministic at creation):
  ```python
  {"image_id": str, "prompt": str, "proposer_id": str, "created_tick": int,
   "url": str, "promoted": bool}    # promoted defaults False; set True by promote_image (I3/I4)
  ```
- Cap: newest `world.params.image_gen.max_gallery` (default 30), pop-oldest on append (mirror
  `_append_billboard`, `~world.py:2525`).
- Helper `_append_gallery(image_id, prompt, proposer_id, tick, url)` → appends + caps; returns the
  record dict.

### 2.2 Transient fetch outbox — I1 (NOT snapshotted)
- `self.pending_image_fetches: list[dict] = []` — init beside `pending_spawn_events`
  (`~world.py:619`). Each entry `{"image_id", "prompt", "url"}`. Drained by the loop each tick
  (§4). Transient by design (same class as `pending_spawn_events`; not serialized — note EM-190).

### 2.3 `plaza_banner_ref` — I4
- `self.plaza_banner_ref: str = ""` — init beside `town_name` (`~world.py:668`).

### 2.4 Snapshot (replay-safe, additive) — `to_snapshot()` / `from_snapshot()`
- `to_snapshot` (`~world.py:3894`, beside `"billboard"`): conditional, pre-Wave-I byte-identical:
  ```python
  if self.gallery:          snap["gallery"] = [dict(g) for g in self.gallery]
  if self.plaza_banner_ref: snap["plaza_banner_ref"] = self.plaza_banner_ref
  ```
- `from_snapshot` (`~world.py:4126`): 
  ```python
  world.gallery = [dict(g) for g in (state.get("gallery") or []) if isinstance(g, dict) and g.get("image_id")]
  world.plaza_banner_ref = str(state.get("plaza_banner_ref", "") or "")
  ```
- `pending_image_fetches` is **never** serialized (transient outbox).

### 2.5 Reflex world-actions
- **`action_create_image(agent, prompt)` — I1** (ungated; create art anywhere):
  1. `prompt = str(prompt or "").strip()[:240]`; if empty → return a soft no-op error dict
     (`{"kind": "action_failed", ...}`) — never a dead turn, mirror existing reflex failures.
  2. compute `image_id` (§0.2, ordinal = count of gallery entries this tick+place to break ties),
     `url`.
  3. `_append_gallery(...)`; `self.pending_image_fetches.append({"image_id","prompt","url"})`.
  4. return event dict (§5 `image_posted`).
- **`action_post_image(agent, image_id?)` — I2** (`location_gate:"@billboard"`, like
  `post_billboard`): posts an existing gallery image (default: the agent's newest) to the billboard
  so others perceive it — append a billboard entry whose `payload` carries `image_ref=url`
  (mirror `action_post_billboard`, `~world.py:2540`). Returns `billboard_posted` event with
  `payload.image_ref` set. Validates the image exists + belongs-or-is-public.

### 2.6 Governance `promote_image` effect — I3/I4
- Add `"promote_image"` to the valid-effects set in `action_propose_rule` (`~world.py:1672`).
  `payload = {"image_id": <id>}`; reject if the id is not in `gallery`.
- **Relax the one-open-proposal-per-effect guard** (`~world.py:1713`): scope `promote_image`
  per-`image_id` exactly as `demolish` is scoped per-`target` — two different images may have open
  votes simultaneously; the SAME image may not be double-proposed.
- One-shot like `name_town`/`demolish` (no `renewal_of`).
- Threshold: **strict majority** (ordinary-rule path, `_evaluate_rule ~world.py:1934`). No
  supermajority.
- **`_on_rule_activated` branch** (`~world.py:1797`, mirror `name_town`): on pass — set
  `self.plaza_banner_ref = payload["image_id"]`; mark the gallery record `promoted=True`;
  `rule.applied = True`; append an `image_promoted` event (§5) to `pending_spawn_events`.

---

## 3. Agent runtime — `agents/runtime.py` (backend-agent)

- **`_REFLEX_REGISTRY`** (`~runtime.py:276`): add
  `"create_image": {"tier":"reflex","location_gate":None,"agreement_gate":None}` and
  `"post_image": {"tier":"reflex","location_gate":"@billboard","agreement_gate":None}`.
- **ACTION_SCHEMA** (`~runtime.py:90`): add `create_image`, `post_image` to the action enum; add
  `allOf` arg rules — `create_image` requires `prompt` (string, maxLength 240); `post_image` takes
  optional `image_id` (string).
- **`_validate_world`** (`~runtime.py:1305`): `create_image` → require non-empty `prompt` (no
  location gate); `post_image` → require `billboard_here(agent.location)` (mirror `post_billboard`).
- **Dispatch in `_apply_action_inner`** (`~runtime.py:4193`): branches calling
  `self.world.action_create_image(agent, args.get("prompt",""))` and
  `self.world.action_post_image(agent, args.get("image_id"))`, each wrapped by
  `_emit_world_result`.
- **Menu offering** (`~runtime.py:1665`, mirror `post_billboard` gating): offer `create_image`
  always (reflex); offer `post_image` only when `_gate_ok("post_image")` AND the agent has ≥1
  gallery image. Menu text and resolution must agree (EM-108).
- **Prompt-diet aware** (EM-161): the new tools' menu lines are short; no decision-trace bloat.

---

## 4. Loop — `engine/loop.py` (backend-agent)

- Init: a module/loop-level `asyncio.Semaphore(max_concurrent)` for fetches +
  `_image_provider = build_provider()` (lazy).
- **Drain after each turn** (where `drain_spawn_events()` is consumed, `~loop.py` turn tail): pop
  `world.pending_image_fetches`; for each, `_spawn_image_fetch(entry)`:
  ```
  async def _spawn_image_fetch(entry):
      if semaphore.locked()/at-cap: return            # skip-under-load, never queue
      async with semaphore:
          png = await provider.fetch_png(entry["prompt"])
          if png: write png to f'data/assets/images/{entry["image_id"]}.png' (mkdir -p once)
      # emits NOTHING; file is best-effort
  ```
  Use `asyncio.create_task` (fire-and-forget) guarded like `_animal_task`/`_narrator_task`
  (`~loop.py:163`); swallow all exceptions (a failed fetch must never surface or stall).
- Reset/cleanup path: cancel in-flight fetch tasks alongside `_narrator_task` (`~loop.py:300`).
- Config: read `world.params.image_gen.{max_concurrent, max_gallery}` via the loader (§7).

---

## 5. Events — `docs/event-log.md` (backend-agent) + `web/src/types` (frontend-agent)

New `kind`s (open-registry; persisted via `_emit_event` → `save_event`, no schema change):
- **`image_posted`** (I1) — actor = the agent; `payload = {"image_id","prompt","url","place"}`;
  `text` e.g. `🎨 {name} paints "{prompt-excerpt}".`
- **`billboard_posted` with `payload.image_ref`** (I2) — reuse the existing kind; the new optional
  `payload.image_ref = url` is additive.
- **`image_promoted`** (I4) — actor = `"system"`, `actor_type:"system"`;
  `payload = {"image_id","url","proposal_id"}`; `text` e.g.
  `🖼 By vote, {proposer}'s image now hangs over the plaza.`

---

## 6. Frontend (frontend-agent) — `web/src/`

### 6.1 API + static
- `/assets` is served by the backend StaticFiles mount (§ app.py). Frontend uses **relative**
  `url` strings straight from event/gallery payloads (`/assets/images/<id>.png`).

### 6.2 Types — `web/src/types/index.ts`
- `BillboardPost`: add `image_ref?: string | null` (`~:192`).
- `EventKind` union: add `'image_posted' | 'image_promoted'` (`~:249`).
- `WorldState`: add `gallery?: GalleryImage[]` and `plaza_banner_ref?: string`
  (`~:215`); new `GalleryImage = { image_id, prompt, proposer_id, created_tick, url, promoted }`.

### 6.3 NoticeBoard texture — `web/src/components/world3d/NoticeBoard.tsx` + `CozyWorld.tsx` — I1
- Thread the newest gallery image's `url` onto the existing blank paper-plane mesh
  (`NoticeBoard.tsx:~109`) via drei `useTexture` → `meshToonMaterial { map }`. **Suspense + a
  procedural fallback** (the current flat PAPER color) when there is no image or it 404s
  (EM-148 invariant: never a blank/erroring mesh). Derive newest image in `CozyWorld.tsx:~481`.

### 6.4 Banner mesh — `web/src/components/world3d/` (NEW `PlazaBanner.tsx`) + `CozyWorld.tsx` — I4
- A standalone `planeGeometry` + `meshToonMaterial { map: useTexture(bannerUrl) }`, positioned
  over the plaza anchor (reuse `buildingSpot`/`placeToWorld`), reading
  `world.plaza_banner_ref` → resolve to its gallery `url`. Procedural fallback when unset.
  Registered in `CozyWorld` render tree. (Optionally a registry entry in `models.ts` if a frame
  GLB is wanted — texture-only plane is acceptable for v1.)

### 6.5 Ingestion — `web/src/hooks/useSimulation.ts`
- `image_posted` / `image_promoted` flow through the standard event-history path (no special
  case). `gallery` + `plaza_banner_ref` ride the per-tick `world_state` snapshot the WS already
  broadcasts — surface them on the `WorldState` the hook exposes.
- Mock generator (`web/src/mock/generator.ts`): synth a few `image_posted` events + a `gallery`
  with placeholder `url`s so the UI renders without a live backend.

---

## 7. Config — `config/world.yaml` + `config/world.city25.yaml` (backend-agent)
Additive block under `world.params` (both yamls, identical defaults):
```yaml
image_gen:
  max_concurrent: 2     # in-flight PNG fetches; skip-under-load above this
  max_gallery: 30       # newest images retained in world.gallery
```
Loader (`config/loader.py`) parses with the above defaults when absent (pre-Wave-I configs
unchanged in behavior).

---

## 8. API — `backend/petridish/api/app.py` (backend-agent)
- Mount once at startup (after CORS, `~app.py:547`):
  `app.mount("/assets", StaticFiles(directory=<assets_dir>), name="assets")` where `<assets_dir>`
  resolves to `data/assets` (create the dir on boot if missing). Guard for the test client.
- No new POST endpoint required for the agent path (gen is reflex-driven). A god-console
  `create_image` lever is OUT OF SCOPE for Wave I (lives in the existing god tooling later).

---

## 9. Test strategy (qe-agent + each impl agent)
- **Backend (`backend/tests/test_wave_i_*.py`)**, hermetic (`EM_IMAGEGEN_MOCK=1`):
  - reflex registry/schema/gate/dispatch for `create_image`, `post_image`;
  - `action_create_image` records a deterministic gallery entry + `pending_image_fetches` + emits
    `image_posted`; same seed ⇒ identical `image_id`/`url` (replay);
  - snapshot round-trip: gallery + `plaza_banner_ref` survive `to_snapshot`→`from_snapshot`;
    pre-Wave-I snapshot (no keys) restores byte-identically;
  - governance: propose/vote/pass `promote_image` sets `plaza_banner_ref` + `promoted=True` +
    `image_promoted` event; relaxed guard allows two image proposals to be open at once but blocks
    double-proposing one image;
  - provider mock returns bytes; loop drain writes file under cap and skips over cap (no raise).
- **Frontend (`*.test.tsx`)**: NoticeBoard renders a textured plane when a gallery image exists and
  the fallback when not; types compile; banner renders from `plaza_banner_ref`; mock generator
  produces gallery events.
- **QE gate** (`coordination/qa-report.json`) per slice; full `pytest` + `npm test` + `tsc` green.

---

## 10. File ownership (no file edited by two agents in one slice)
- **backend-agent:** `backend/petridish/imagegen/**` (new), `engine/world.py`, `engine/loop.py`,
  `agents/runtime.py`, `api/app.py`, `config/loader.py`, `config/world.yaml`,
  `config/world.city25.yaml`, `docs/event-log.md`, `backend/tests/test_wave_i_*.py`,
  `backend/tests/conftest.py` (add `EM_IMAGEGEN_MOCK`).
- **frontend-agent:** `web/src/types/index.ts`, `web/src/components/world3d/NoticeBoard.tsx`,
  `web/src/components/world3d/CozyWorld.tsx`, `web/src/components/world3d/PlazaBanner.tsx` (new),
  `web/src/components/world3d/assets/models.ts`, `web/src/hooks/useSimulation.ts`,
  `web/src/mock/generator.ts`, and the matching `*.test.tsx` files.
- **qe-agent:** `coordination/qa-report.json` + NEW integration tests
  (`backend/tests/test_wave_i_integration.py`) distinct from impl-agent test files.
- **Shared / lead-only:** `contracts/wave-i-atelier.md`, `docs/REMAINING-WORK.md`.
