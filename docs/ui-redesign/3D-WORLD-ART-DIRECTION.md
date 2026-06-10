# 3-D World Art Direction — the cozy village

> Look-dev for `web/src/components/world3d/CozyWorld.tsx` (React-Three-Fiber). The goal:
> elevate the current flat low-poly town into a warm, characterful, *shareable* cozy
> world — Stardew Valley × Animal Crossing, but lit and dressed properly.
>
> **Scope note (per `v3-city-depth-before-multi-city`):** this is about making **one**
> town *be more things* — denser, more alive, more place-kinds and props — **not** a
> second settlement. Multi-city is a later seam, not this pass.

Three concept frames live alongside this doc in `3d-concepts/`. Each is a different
**art direction for the same town**, varying on lighting model, material treatment,
camera, and mood — so you can pick a target before any code changes.

---

## Direction 1 — Warm Toon, Golden Hour  ·  `dir1-warm-toon-golden-hour.png`  ★ recommended baseline
The in-world, "you live here" look. Warm low sun, long soft shadows, string lights,
banded toon shading. **This is the lowest-lift, highest-payoff path** — it's essentially
the v3 **EM-108 art-win** (warm HDRI + MeshToonMaterial + AccumulativeShadows) applied to
the geometry you already have.

**R3F recipe:**
- **Lighting:** drei `<Environment>` with a warm dusk HDRI (or `preset="sunset"`); one
  low-angle `directionalLight` as the sun (`color #FFCF99`, intensity ~2.2) + soft sky
  fill (`hemisphereLight`, sky `#FFE9C2` / ground `#3A5A2A`).
- **Shadows:** drei `<AccumulativeShadows>` + `<SoftShadows>` for grounded contact
  shadows; warm shadow tint, not black.
- **Materials:** swap to `MeshToonMaterial` with a 3–4 step `gradientMap` for the banded
  cel look; warm albedo. (Keep `MeshStandardMaterial` only where you want the HDRI's soft GI.)
- **Post (subtle):** `postprocessing` — N8AO ambient occlusion, a *gentle* bloom on the
  string lights/windows, soft vignette, warm color-grade LUT.
- **Palette:** terrain `#8FB85A`→`#6E9A3E`, paths `#C9A36B`, roofs `#B5573C`/`#7C9B6A`,
  walls `#E8D6B0`, sky gradient `#FFD9A0`→`#9EC7E8`, light glow `#FFE08A`.

## Direction 2 — Tilt-Shift Miniature  ·  `dir2-tiltshift-miniature.png`
The town as an adorable tabletop model on a base plate. Reads as a precious little object —
**the best look for share-cards, the mobile spectator hero, and marketing**. Could ship as a
"diorama mode" toggle even if the live world uses Direction 1.

**R3F recipe:**
- **Camera:** near-orthographic 3/4 (`OrthographicCamera` or low-FOV perspective), framed on
  a round/square **ground base tile** with a neutral seamless backdrop.
- **DoF/tilt-shift:** `postprocessing` `DepthOfField` (or a TiltShift pass) — sharp center,
  blurred edges. This single effect *is* the miniature illusion.
- **Lighting:** neutral 3-point studio (cooler than Dir1), crisp soft shadows; little/no HDRI warmth.
- **Materials:** matte "painted-clay" `MeshStandardMaterial` (roughness ~0.8, faint waxiness).
- **Use:** generate the run-card OG image and the mobile glance from this camera.

## Direction 3 — Painterly Storybook  ·  `dir3-painterly-storybook.png`
Gouache/Ghibli pastoral — soft brushwork, watercolor sky, wildflower meadow. The most
*lovable* and least techy. **Higher effort in real-time** — flag as aspirational / a stylized
post-pass, not the first build.

**R3F recipe (harder):**
- Hand-painted albedo/texture maps on buildings + terrain (not flat colors).
- A painterly post shader (Kuwahara/oil-filter) or soft-focus + grain; watercolor skybox.
- Soft-edged **alpha-card foliage** instead of hard low-poly trees; bloom + soft DoF.
- Treat as a "season finale / cinematic" mode rather than the default interactive look.

---

## Mapping to the v3 art roadmap (the EM items this unblocks)
| v3 item | What it is | Direction it serves |
|---|---|---|
| **EM-108** | Warm HDRI + MeshToonMaterial + AccumulativeShadows on existing geometry | **Direction 1, exactly** — start here |
| **EM-115** | Instanced trees/foliage swap @60fps | All — drei `<Instances>`/`<Merged>` for trees, flowers, props |
| **EM-119** | Buildings-per-place-kind swap | Distinct kits: church, town hall, market, dog shelter, farmhouse |
| **EM-121** | 3-D character mesh swap | Rounded chibi villagers + cat/dog; the figures in every frame |
| **EM-124** | Day/night + seasons + particles + sparing bloom/vignette | The post stack above; Dir 1's golden hour is one time-of-day slice |

## "Deepen one city" — what *more things* looks like visually
Make the single town denser and more alive instead of founding a second one:
- **More place-kinds & props:** well, lamp posts, benches, fences, garden plots, market
  goods, notice board, banners, hanging signs, crates, laundry lines.
- **Layered terrain:** gentle elevation, a stream/bridge, a town-edge orchard or field.
- **Life:** chimney smoke, birds, fireflies + lit windows at night, market-day bustle,
  weather (per EM-124).
- **Zones:** a plaza core, a market lane, a residential edge, a civic corner (hall/church) —
  so the one city legibly *has neighborhoods*.

## Assets — license-safe (the v3 license-hygiene rule: CC0 only, never ship ConcernedApe art)
- **Kenney** (CC0): Nature Kit, Survival Kit, City Kit, Castle Kit — buildings, props, trees.
- **Quaternius** (CC0): Cute/Stylized packs, modular nature, characters.
- **Poly Pizza** (CC0/CC-BY): one-off low-poly props.
- Record every source in `CREDITS.md` / `ASSET_LICENSES.md`.

## Recommended path
1. **Ship Direction 1** as the live look = EM-108 (HDRI + toon + soft shadows) on current geometry — biggest visible jump for least work.
2. Add **EM-115** instanced foliage + a first pass of "deepen one city" props.
3. Use **Direction 2 (tilt-shift)** to render the **share-card / mobile** hero — high virality, isolated from the live renderer.
4. Layer **EM-119 → EM-121 → EM-124** (building kits → characters → day-night) over time.
5. Hold **Direction 3 (painterly)** as an aspirational cinematic mode.
