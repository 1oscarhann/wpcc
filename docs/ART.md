# Art, audio and feel: asset choices

> Depends on decision **B1** in PLAN.md. This doc assumes the recommended **top-down 3/4 pixel art**. If you keep isometric, this section gets rewritten before Phase 3.

## 1. Rules

| Rule | Value |
|---|---|
| Perspective | Top-down 3/4 (front-facing buildings, 4-direction characters) |
| Base pixel scale | **16×16 px per tile**. Never mixed. Assets from other packs are only used if they're 16 px-native. |
| Display scale | Integer zoom only at rest: 2× (Build overview), 3× (Avatar default), 4× (close). Non-integer only mid-tween. |
| Filtering | Nearest-neighbour everywhere (`TextureStyle.defaultOptions.scaleMode = 'nearest'`), `roundPixels: true`, atlas padding 2 px with edge extrusion (no bleeding) |
| Lighting | Key light from the **top-left**. Shadows fall bottom-right as a 1-px-offset dark ellipse under every standing sprite. Anything imported must match, or it gets mirrored or edited. |
| Outline | Follow Ninja Adventure's outline treatment. Packs with a different outline weight (e.g. Tiny Creatures' thick outlines) are only used after an outline pass, or not at all. |
| Palette | One master palette derived from Ninja Adventure (`assets-src/palette/master.hex`). Other packs are colour-remapped to it by `tools/pack_atlases.ts`. |
| Rarity colours | grey `#9aa0a6`, green `#4caf50`, blue `#3d8bfd`, purple `#a259ff`, orange `#ff9f1c`. These are UI tokens **and** glow/beam tints, used everywhere. |

## 2. Packs

All packs get unzipped untouched into `assets-src/<pack>/` with their licence file, and are processed into atlases by the tool. **Every** shipped file appears in `CREDITS.md`.

| Pack | Author | Licence | Use | Status |
|---|---|---|---|---|
| **Ninja Adventure Asset Pack** (itch.io, updated Mar 2026) | Pixel-boy & AAA | **CC0** | **Primary.** Terrain tilesets (autotiling), houses and interiors, 50+ animated characters (avatar bases, villagers, NPCs, guide), 30+ animated monsters, 9 animated bosses, 60+ items, 30+ FX, UI elements, 2 fonts, 37 music tracks, 100+ SFX | Confirmed CC0, 16×16, top-down |
| Kenney **Tiny Town** | Kenney | CC0 | Extra village props and building fill-ins (fences, wells, stalls, crops), remapped to the master palette | Confirmed CC0, 16×16 |
| Kenney **Tiny Dungeon** | Kenney | CC0 | Dungeon props, chests, levers, plates (fill-ins) | Confirmed CC0, 16×16 |
| **Tiny Creatures** | Clint Bellanger | CC0 | Extra monsters, animals and pet candidates (180 sprites), only if the outline pass makes them fit | Confirmed CC0, 16×16 (thick outlines, so style risk) |
| Kenney audio packs (UI Audio, RPG Audio, Impact Sounds, Interface Sounds, Music Jingles) | Kenney | CC0 | UI clicks, impacts per weapon type, pickups, level-up stings | Verify per pack in Phase 2/5 |
| Ambient loops (birds, wind, crickets, owls, rain, biome beds) | various | **CC0 only** (OpenGameArt/Freesound filtered to CC0) | Ambience | Picked per file in Phase 10, each file with its URL in CREDITS |
| **Pixelify Sans** | Stefie Justprince | SIL OFL 1.1 | Headings | Self-hosted woff2 subset (no Google CDN at runtime) |
| **Fredoka** | Milena Brandão | SIL OFL 1.1 | Body text | Self-hosted woff2 subset |

OFL isn't CC0, but it explicitly allows embedding in apps. It's listed in CREDITS with the licence text. If Fredoka looks too smooth next to the pixel art in the screenshot checks, the fallback is one of Ninja Adventure's own fonts for small labels.

### Rejected

| Option | Why not |
|---|---|
| Kenney isometric packs | Pre-rendered, not pixel art; no character or monster animation |
| LPC | CC-BY-SA/GPL (attribution plus share-alike), 32 px-native (clashes with 16 px), uneven quality across contributors. Still the fallback if a real layered character creator matters more than CC0 (see B1). |

## 3. Covering the gaps (what the packs don't have)

| Need | Approach |
|---|---|
| **Building level 1–5 art** (P7) | Base sprite per building plus a reusable **level overlay kit**: L2 pennant, L3 stone foundation and window boxes, L4 banners and a roof-trim palette shift, L5 gold trim plus an idle sparkle particle. Composed at runtime from manifest keys `building.<key>.base` + `overlay.level.<n>.<size>`. |
| Building rotation (P6) | Horizontal mirror plus footprint swap; a door marker shows the facing. |
| **Weapon sprite per tier** (P7) | One sprite per weapon type plus a **palette-ramp shader** with 5 ramps (copper, iron, steel, mythril, starforged). Rarity is drawn as an outline glow in its colour. Missing weapon types (harpoon, crystal staff, tome, bomb bag) are hand-edited from pack items in their phase. |
| Weapon animation | Weapons are a **separate sprite** anchored to the avatar's hand, rotated to the aim angle and swung through tweened arcs, with a trail mesh. This works for every weapon without per-weapon body animations, which is how many top-down action games do it. |
| **Character creator** | Ninja Adventure characters are whole sprites, not layered parts. v1: pick a **base body** (4–6 compatible pack characters sharing the same frame layout, verified in Phase 2) and palette-swap **skin** (6 tones), **hair colour** (10), **eye colour** (6), **outfit colour** (12). "Hair style" = 4–6 hand-edited hair overlay frame sets. If the bases don't share a frame layout, the fallback is a "pick a hero + recolour" creator. Either way you get a live animated preview. |
| Bosses | Map the pack's 9 bosses onto our 5 (recolour plus scale), with phase tints. |
| Parchment and wood UI | Built from 9-slice panels (pack UI elements plus hand-made corners), so every panel, button, slot and tooltip shares one kit. |
| Seasons | Palette **LUT per season** applied to terrain and foliage layers only (spring blossom tint, autumn orange, winter snow overlay tiles on top). |
| Day/night | Global `ColorMatrixFilter` tint curve on the world layer plus additive light sprites (windows, lanterns, fires, fireflies) that fade in at dusk. |
| Juice | Squash and stretch via tweens, dust puffs, a hit-flash shader (white silhouette), afterimages (pooled ghost sprites), rarity beams (tinted gradient quads), damage numbers (bitmap font, pooled). |

## 4. Asset manifest

`frontend/src/assets/manifest.json` is the only way code references art or audio. Logical names never change, so swapping art means editing the manifest (or re-running the packer) without touching code.

```json
{
  "version": 1,
  "tileSize": 16,
  "atlases": {
    "world":    "atlases/world.json",
    "chars":    "atlases/chars.json",
    "monsters": "atlases/monsters.json",
    "fx":       "atlases/fx.json",
    "ui":       "atlases/ui.json"
  },
  "sprites": {
    "building.forge.base":        { "atlas": "world", "frame": "forge" },
    "overlay.level.3.2x2":        { "atlas": "world", "frame": "lvl3_2x2" },
    "weapon.spear":               { "atlas": "fx",    "frame": "spear", "anchor": [0.2, 0.5], "paletteRamp": true },
    "ui.panel.parchment":         { "atlas": "ui",    "frame": "panel_parchment", "nineSlice": [6, 6, 6, 6] }
  },
  "animations": {
    "monster.slime.move":   { "atlas": "monsters", "frames": "slime_move_{0..3}", "fps": 8 },
    "char.base_a.walk.down":{ "atlas": "chars",    "frames": "base_a_walk_down_{0..3}", "fps": 8 }
  },
  "palettes": {
    "tier":   { "copper": "pal/tier_copper.png", "iron": "pal/tier_iron.png" },
    "season": { "spring": "pal/lut_spring.png", "winter": "pal/lut_winter.png" }
  },
  "audio": {
    "sfx.hit.sword":   { "src": ["audio/sfx/hit_sword_{1..3}.webm", "audio/sfx/hit_sword_{1..3}.mp3"], "volume": 0.8, "variants": 3 },
    "music.village":   { "src": ["audio/music/village.webm", "audio/music/village.mp3"], "stream": true, "loop": true },
    "amb.day.meadow":  { "src": ["audio/amb/meadow_day.webm", "audio/amb/meadow_day.mp3"], "stream": true, "loop": true }
  },
  "fonts": { "heading": "fonts/PixelifySans.woff2", "body": "fonts/Fredoka.woff2" }
}
```

- `tools/validate_manifest.ts` runs in CI: every key resolves, there are no orphan files, and every file has a CREDITS entry.
- Audio ships as WebM/Opus with an MP3 fallback (Howler picks). Music and ambience are streamed. SFX are short and preloaded per scene.

## 5. Load budget

| Item | Budget |
|---|---|
| Initial JS + CSS + fonts | ≤ 1.2 MB gzipped (React, Pixi v8, GSAP, Howler, app) |
| Loading screen assets | ≤ 300 KB |
| First playable (village atlas + UI atlas + core SFX) | ≤ 1.5 MB |
| **Total before game assets stream** | **< 3 MB** ✔ |
| Biome atlases, music, ambience | Streamed lazily per biome and scene |

## 6. Audio plan

| Layer | Content |
|---|---|
| Music | Calm village theme ↔ combat theme, crossfaded over 1.5 s on combat-lock enter/exit. Plus a per-biome theme (from the pack's 37 tracks). |
| Ambience | Day bed (birds, wind) ↔ night bed (crickets, owls), crossfaded with day phase. Rain/storm overlays. One biome bed per biome. |
| SFX | UI (hover, click, open, close, error), placement, completion, per-weapon-type hits (light, heavy, crit), dodge, pickup chime (pitch rises in quick succession), level-up, legendary-drop sting, combo-discovery sting, wave horn, boss roar. |
| Settings | Master, music and SFX sliders plus mute, saved in `user_settings.audio` (server) and mirrored to `localStorage` for instant load. |

## 7. `/debug` gallery (Phase 2 skeleton, grows every phase)

Hidden route, admin or dev only. It shows:
- every manifest sprite at 1×/2×/3×;
- every animation playing;
- all tiles in a grid with their autotile variants;
- each palette ramp applied to every weapon;
- the level overlays on every building;
- every UI component in every state (hover, press, disabled);
- the rarity colour chips;
- both fonts at every size used;
- day/night and season previews.

The Playwright screenshot runner captures it every phase, which is the "visual consistency at a glance" check.
