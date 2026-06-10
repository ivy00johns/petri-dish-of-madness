# Asset licenses

Every external (non-procedural) asset shipped with PetriDishOfMadness is
recorded here, per the v3 license-hygiene rule: **CC0 only**, never art ripped
from commercial games.

| Asset | File | Source | Author | License | Used for |
|---|---|---|---|---|---|
| Venice Sunset (HDRI, 1k) | `web/public/hdri/venice_sunset_1k.hdr` (~1.0 MB) | [Poly Haven](https://polyhaven.com/a/venice_sunset) | Greg Zaal | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Warm golden-hour environment lighting for the 3-D village (EM-111, drei `<Environment>`) |
| KayKit Medieval Hexagon Pack 1.0 — windmill | `web/public/models/kaykit-medieval-hexagon/building_windmill.glb` (~157 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg ([kaylousberg.com](https://www.kaylousberg.com)) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) (per bundled `LICENSE.txt`) | `farm` building variant (EM-148, `MODEL_REGISTRY`) |
| KayKit Medieval Hexagon Pack 1.0 — blacksmith | `web/public/models/kaykit-medieval-hexagon/building_blacksmith.glb` (~137 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `workshop` building variant |
| KayKit Medieval Hexagon Pack 1.0 — tower A | `web/public/models/kaykit-medieval-hexagon/building_tower.glb` (~128 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `clocktower` building variant |
| KayKit Medieval Hexagon Pack 1.0 — home A | `web/public/models/kaykit-medieval-hexagon/building_home_a.glb` (~71 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `house` building variant |
| KayKit Medieval Hexagon Pack 1.0 — well | `web/public/models/kaykit-medieval-hexagon/building_well.glb` (~58 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `well` building variant |
| KayKit Medieval Hexagon Pack 1.0 — tavern | `web/public/models/kaykit-medieval-hexagon/building_tavern.glb` (~184 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `generic` building variant |
| KayKit Medieval Hexagon Pack 1.0 — castle | `web/public/models/kaykit-medieval-hexagon/building_castle.glb` (~327 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `governance` place anchor (`PLACE_MODELS`) |
| KayKit Medieval Hexagon Pack 1.0 — lumbermill | `web/public/models/kaykit-medieval-hexagon/building_lumbermill.glb` (~181 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `work` place anchor |
| KayKit Medieval Hexagon Pack 1.0 — home B | `web/public/models/kaykit-medieval-hexagon/building_home_b.glb` (~97 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Medieval-Hexagon-Pack-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `home` place anchor |
| KayKit Adventurers Character Pack 1.0 — Rogue | `web/public/models/kaykit-adventurers/villager.glb` (~1.8 MB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Character-Pack-Adventures-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Rigged + animated villager (EM-124). Vendored copy strips the weapon prop nodes (Knife, Knife_Offhand, 1H/2H_Crossbow) and keeps 10 of 76 clips: Idle, Walking_A, Running_A, Cheer, Interact, PickUp, Sit_Floor_Down/Idle/StandUp, Death_A |
| Kenney Fantasy Town Kit 2.0 — market stall (red) | `web/public/models/kenney-fantasy-town/stall.glb` (~27 KB) | [kenney.nl](https://kenney.nl/assets/fantasy-town-kit) | Kenney ([kenney.nl](https://www.kenney.nl)) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) (per bundled `License.txt`) | `stall` building variant (colormap texture embedded at vendor time) |
| Kenney Fantasy Town Kit 2.0 — round fountain | `web/public/models/kenney-fantasy-town/fountain.glb` (~102 KB) | [kenney.nl](https://kenney.nl/assets/fantasy-town-kit) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `monument` building variant |
| Quaternius — animated Cat | `web/public/models/quaternius/cat.glb` (~91 KB) | [Poly Pizza](https://poly.pizza/m/2f54vbV0In) (mirror of the Quaternius pack) | Quaternius ([quaternius.com](https://quaternius.com)) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Critter cat (EM-124). Clips renamed to drop armature prefixes: Idle, Walk, Jump, Dance, Death, Bite_Front, HitRecieve, No, Yes |
| Quaternius — animated Dog | `web/public/models/quaternius/dog.glb` (~270 KB) | [Poly Pizza](https://poly.pizza/m/2kUk0QqpCg) (mirror of the Quaternius pack) | Quaternius | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Critter dog (EM-124). Clips renamed to drop armature prefixes: Idle, Walk, Run, Idle_Eating, Jump_Start, Jump_Loop, Headbutt, Death |

All vendored GLBs were re-packed headlessly with `@gltf-transform` (gltf→glb
embedding, `resample`/`dedup`/`prune`); no art content was authored or altered
beyond the node/clip removals noted above. No DRACO/meshopt compression is
used, so no decoder lives under `web/public/`. Total payload under
`web/public/models/`: ~3.6 MB.

Everything NOT listed above in the 3-D village (the procedural building
variants and Suspense fallbacks, scenery, foliage) is procedural geometry
generated in code — no external art assets.
