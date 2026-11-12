# Chiguru — 3D Agriculture Landing Page

An immersive, scroll-driven 3D landing page for **Chiguru**, an IoT farm assistant that
farmers talk to in their own language. The device understands their questions and answers
in the same language, and farmers see all the information about their own land in the
language they prefer. Built with
**React 19 · Three.js · React Three Fiber · drei · postprocessing · GSAP · Lenis**.

Scrolling walks you *into* the farm: the camera flies in from outside the valley,
passes the farmer, wades into the wheat, follows the pasture fence, glides over the
crop rows, rises above the valley and drifts on toward the mountains and the sun.

## Run it

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # production build in dist/
npm run preview    # serve the production build
```

Quality is chosen automatically from the device (GPU, memory, touch, screen size) and
the render scale adapts at runtime. You can force a tier with `?quality=high|medium|low`.

## What's in the scene

| Element | How it's made |
| --- | --- |
| Farmer (idle, waves on click, head follows the cursor) | Quaternius *Farmer* GLB, skinned + animated |
| Grazing / walking cows | Quaternius *Cow* + *Holstein* GLBs, per-instance skeleton clones |
| Tractor on the farm loop, exhaust smoke + dust | Poly by Google *Tractor* GLB + GPU point sprites |
| Windmill with turning sails | Quaternius *Tower Windmill* GLB, sails re-pivoted at runtime |
| Barn, silo, fences, hay bales | Quaternius GLBs (instanced where repeated) |
| Trees | Quaternius textured tree pack, instanced, wind-swayed leaves |
| Grass, wheat, wildflowers, crop rows | Procedural instanced geometry with wind + pointer-push shaders |
| Terrain, fields, roads, patchwork farms, mountains | One warped grid + a procedural ground shader (Poly Haven soil/grass detail) |
| Sky, clouds, aerial-perspective fog | Custom sky shader; three's fog is replaced with a sky-matched haze |
| Birds, butterflies, pollen | Procedural instanced flocks / sprites |
| Floating glass cards, holographic field scan | drei `Html` + additive shaders, tied to scroll sections |

## Project layout

```
src/
  config/world.ts        layout of the farm + camera shots for every section
  lib/                   noise, terrain height, quality tiers, shared runtime store
  three/                 Canvas, camera rig, sun/shadows, post-processing
  three/world/           every scene element (one file each)
  three/shaders/         shared GLSL + the atmosphere/fog patch
  ui/                    navigation, page sections, scroll + GSAP animations
public/models            optimised GLBs (meshopt + WebP textures)
public/textures          ground detail textures (WebP)
```

### Customising

- **Copy / sections** — `src/ui/Sections.tsx`
- **Camera journey** — `SHOTS_LANDSCAPE` / `SHOTS_PORTRAIT` in `src/config/world.ts`
- **Farm layout** (fields, pasture, roads, trees) — `src/config/world.ts`
- **Sky + haze colours** — `PALETTE` in `src/three/shaders/chunks.ts`
- **Brand colours / type** — CSS variables at the top of `src/index.css`

Profiling helper: `?off=grass,wheat,trees,post,shadows,…` disables subsystems.

## Asset credits & licences

- Farmer, cows, windmill, barn, silo, fence, hay, trees — **Quaternius**, CC0 (via poly.pizza)
- Tractor — **Poly by Google**, CC-BY 3.0 (attribution required — kept in the footer)
- Soil & grass textures — **Poly Haven** (`brown_mud_02`, `grass_ground`), CC0
- Fonts — Fraunces & Manrope (SIL Open Font License), self-hosted via Fontsource

The contact details in the footer (`hello@chiguru.example`, `+91 80 0000 0000`) are
placeholders, and the contact form only shows a confirmation — connect it to your backend.
