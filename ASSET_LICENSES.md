# Asset licenses

Every external (non-procedural) asset shipped with PetriDishOfMadness is
recorded here, per the v3 license-hygiene rule: **CC0 only**, never art ripped
from commercial games.

| Asset | File | Source | Author | License | Used for |
|---|---|---|---|---|---|
| Venice Sunset (HDRI, 1k) | `web/public/hdri/venice_sunset_1k.hdr` (~1.0 MB) | [Poly Haven](https://polyhaven.com/a/venice_sunset) | Greg Zaal | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Warm golden-hour environment lighting for the 3-D village (EM-111, drei `<Environment>`) |
| KayKit Adventurers Character Pack 1.0 — Rogue | `web/public/models/kaykit-adventurers/villager.glb` (~1.8 MB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-Character-Pack-Adventures-1.0) | Kay Lousberg | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Rigged + animated villager (EM-124). Vendored copy strips the weapon prop nodes (Knife, Knife_Offhand, 1H/2H_Crossbow) and keeps 10 of 76 clips: Idle, Walking_A, Running_A, Cheer, Interact, PickUp, Sit_Floor_Down/Idle/StandUp, Death_A |
| Kenney Fantasy Town Kit 2.0 — round fountain | `web/public/models/kenney-fantasy-town/fountain.glb` (~102 KB) | [kenney.nl](https://kenney.nl/assets/fantasy-town-kit) | Kenney ([kenney.nl](https://www.kenney.nl)) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) (per bundled `License.txt`) | `monument`/`well` building variants + `social` place anchor (city plaza fountain, Wave D1.5; colormap texture embedded at vendor time) + Wave K `PROP_MODELS.fountain` (EM-218) |
| Quaternius — animated Cat | `web/public/models/quaternius/cat.glb` (~91 KB) | [Poly Pizza](https://poly.pizza/m/2f54vbV0In) (mirror of the Quaternius pack) | Quaternius ([quaternius.com](https://quaternius.com)) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Critter cat (EM-124). Clips renamed to drop armature prefixes: Idle, Walk, Jump, Dance, Death, Bite_Front, HitRecieve, No, Yes |
| Quaternius — animated Dog | `web/public/models/quaternius/dog.glb` (~270 KB) | [Poly Pizza](https://poly.pizza/m/2kUk0QqpCg) (mirror of the Quaternius pack) | Quaternius | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | Critter dog (EM-124). Clips renamed to drop armature prefixes: Idle, Walk, Run, Idle_Eating, Jump_Start, Jump_Loop, Headbutt, Death |
| Kenney City Kit Roads 2.0 — road straight | `web/public/models/kenney-city/road-straight.glb` (~12 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-roads) | Kenney ([kenney.nl](https://www.kenney.nl)) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) (per bundled `License.txt`) | `road_straight` city piece (EM-152, `CITY_MODEL_REGISTRY`) |
| Kenney City Kit Roads 2.0 — road bend | `web/public/models/kenney-city/road-bend.glb` (~22 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-roads) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `road_corner` city piece |
| Kenney City Kit Roads 2.0 — road intersection (T) | `web/public/models/kenney-city/road-intersection.glb` (~13 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-roads) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `road_tee` city piece |
| Kenney City Kit Roads 2.0 — road crossroad | `web/public/models/kenney-city/road-crossroad.glb` (~15 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-roads) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `road_cross` city piece |
| Kenney City Kit Roads 2.0 — road end (round) | `web/public/models/kenney-city/road-end-round.glb` (~20 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-roads) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `road_end` city piece (caps roads at the grid edge) |
| Kenney City Kit Roads 2.0 — curved streetlight | `web/public/models/kenney-city/lamp-curved.glb` (~15 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-roads) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `lamp` street prop + Wave K `PROP_MODELS.lamp` (EM-218) |
| Kenney City Kit Commercial 2.1 — building A | `web/public/models/kenney-city/commercial-a.glb` (~84 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-commercial) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `com_a` city building + `stall` building variant (EM-148, Wave D1.5) |
| Kenney City Kit Commercial 2.1 — building G | `web/public/models/kenney-city/commercial-g.glb` (~123 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-commercial) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `com_b` city building + `generic` building variant (Wave D1.5) |
| Kenney City Kit Commercial 2.1 — building E | `web/public/models/kenney-city/commercial-e.glb` (~97 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-commercial) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `com_c` city building (wide storefront) + `work` place anchor (Wave D1.5) |
| Kenney City Kit Commercial 2.1 — building N | `web/public/models/kenney-city/civic-n.glb` (~241 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-commercial) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `civic_a` city building (civic landmark) + `governance` place anchor and `clocktower` building variant (Wave D1.5) |
| Kenney City Kit Suburban 2.0 — house type A | `web/public/models/kenney-city/suburban-a.glb` (~78 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-suburban) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `res_a` city building + `house` building variant (Wave D1.5) |
| Kenney City Kit Suburban 2.0 — house type B | `web/public/models/kenney-city/suburban-b.glb` (~110 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-suburban) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `res_b` city building + `home` place anchor (Wave D1.5) |
| Kenney City Kit Suburban 2.0 — house type Q | `web/public/models/kenney-city/suburban-q.glb` (~78 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-suburban) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `res_c` city building |
| Kenney City Kit Suburban 2.0 — picket fence | `web/public/models/kenney-city/fence.glb` (~18 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-suburban) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `fence` street prop + Wave K `PROP_MODELS.fence` (EM-218) |
| Kenney City Kit Suburban 2.0 — tree (large) | `web/public/models/kenney-city/tree-large.glb` (~15 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-suburban) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `tree_city` greenery (parks + residential) + Wave K `PROP_MODELS.tree` (EM-218) |
| Kenney City Kit Industrial 1.0 — building G | `web/public/models/kenney-city/industrial-g.glb` (~82 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-industrial) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `ind_a` city building (factory) + `workshop` building variant (Wave D1.5) |
| Kenney City Kit Industrial 1.0 — building H | `web/public/models/kenney-city/industrial-h.glb` (~53 KB) | [kenney.nl](https://kenney.nl/assets/city-kit-industrial) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `ind_b` city building (warehouse) + `farm` building variant (Wave D1.5) |
| Kenney Car Kit 3.1 — sedan | `web/public/models/kenney-city/car-sedan.glb` (~85 KB) | [kenney.nl](https://kenney.nl/assets/car-kit) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `car_a` parked car |
| Kenney Car Kit 3.1 — SUV | `web/public/models/kenney-city/car-suv.glb` (~102 KB) | [kenney.nl](https://kenney.nl/assets/car-kit) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `car_b` parked car |
| Kenney Car Kit 3.1 — taxi | `web/public/models/kenney-city/car-taxi.glb` (~85 KB) | [kenney.nl](https://kenney.nl/assets/car-kit) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `car_c` parked car |
| Kenney Furniture Kit 2.0 — bench | `web/public/models/kenney-city/bench.glb` (~8 KB) | [kenney.nl](https://kenney.nl/assets/furniture-kit) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `bench` street prop + Wave K `PROP_MODELS.bench` (EM-218) |
| Kenney Furniture Kit 2.0 — trashcan | `web/public/models/kenney-city/trashcan.glb` (~4 KB) | [kenney.nl](https://kenney.nl/assets/furniture-kit) | Kenney | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `bin` street prop + Wave K `PROP_MODELS.bin` (EM-218) |
| KayKit City Builder Bits 1.0 — fire hydrant | `web/public/models/kaykit-city/firehydrant.glb` (~28 KB) | [GitHub](https://github.com/KayKit-Game-Assets/KayKit-City-Builder-Bits-1.0) | Kay Lousberg ([kaylousberg.com](https://www.kaylousberg.com)) | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) (per bundled `LICENSE.txt`) | `hydrant` street prop (gltf+bin+png repacked to GLB with `citybits_texture.png` embedded) + Wave K `PROP_MODELS.hydrant` (EM-218) |

All vendored GLBs were re-packed headlessly with `@gltf-transform` (gltf→glb
embedding, `resample`/`dedup`/`prune`); no art content was authored or altered
beyond the node/clip removals noted above. The W15 city kits (`kenney-city/`,
`kaykit-city/`, EM-152) had their CC0 `License.txt` verified inside each
downloaded archive before vendoring; their per-kit `colormap.png` textures are
embedded at repack time. No DRACO/meshopt compression is used, so no decoder
lives under `web/public/`. Total payload under `web/public/models/`: ~3.7 MB
(~1.5 MB of that is the W15 city set; the Wave D1.5 city move retired the
KayKit Medieval Hexagon kit and the fantasy-town stall — ~1.4 MB deleted).

Everything NOT listed above in the 3-D village (the procedural building
variants and Suspense fallbacks, scenery, foliage) is procedural geometry
generated in code — no external art assets.

**Wave K (EM-216/218) — asset REUSE, no new downloads.** The placeable-prop
system (`web/src/components/world3d/assets/propModels.ts`, `PROP_MODELS`) wires
the new `Prop` entity to the GLBs ALREADY vendored above — bench, lamp/
streetlight, tree, fence, bin/trashcan, hydrant, and the fantasy-town fountain
(shared BY URL; one download, one toonified scene). No Kenney/KayKit kit was
downloaded for this wave. Acquiring a wider Nature/Furniture vocabulary
(statues, planters, rocks, flowers, distinct per-type building GLBs) is the
recorded HITL follow-on (EM-216 closes when those land; the registries here
consume them with zero further wiring).
