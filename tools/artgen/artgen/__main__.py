"""Build every generated asset: `uv run --project tools/artgen python -m artgen` (from tools/artgen)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from PIL import Image

from artgen import buildings, characters, icons, nature, terrain, ui
from artgen.pack import pixi_json, save_json, save_png, shelf_pack
from artgen.palette import EYES, HAIR, OUTFIT, SHADE_KEYS, SKIN
from artgen.terrain import BLOB_MASKS

ROOT = Path(__file__).resolve().parents[3]
PUBLIC = ROOT / "frontend" / "public" / "assets" / "gen"
SRC = ROOT / "frontend" / "src" / "assets"


def hexs(rgba: tuple[int, int, int, int]) -> str:
    return "#%02x%02x%02x" % rgba[:3]


def main() -> None:
    avatar = yaml.safe_load((ROOT / "config" / "avatar.yaml").read_text())
    creator = avatar["creator"]
    for table, key in ((SKIN, "skin_tones"), (HAIR, "hair_colors"), (EYES, "eye_colors"), (OUTFIT, "outfit_colors")):
        missing = [k for k in creator[key] if k not in table]
        if missing:
            sys.exit(f"artgen: avatar.yaml {key} has no colour ramp for {missing}")

    world = {}
    world.update(terrain.generate())
    world.update(nature.generate())
    world.update(nature.generate_extra())
    bsprites, bmeta = buildings.generate()
    world.update(bsprites)
    world.update(ui.fx())
    world_img, world_rects = shelf_pack(world)
    save_png(world_img, PUBLIC / "world.png")
    save_json(pixi_json("world.png", world_img, world_rects), PUBLIC / "world.json")

    # characters: one 18-frame strip per layer option, stacked vertically
    layers = characters.generate(creator)
    names = sorted(layers)
    strip_w = characters.FW * len(characters.FRAMES)
    chars_img = Image.new("RGBA", (strip_w, characters.FH * len(names)))
    for i, n in enumerate(names):
        chars_img.paste(layers[n].img, (0, i * characters.FH))
    save_png(chars_img, PUBLIC / "chars.png")

    # icons: 16×16 grid, 16 per row
    ic = icons.generate()
    icon_names = sorted(ic)
    cols = 16
    icons_img = Image.new("RGBA", (16 * cols, 16 * ((len(icon_names) + cols - 1) // cols)))
    for i, n in enumerate(icon_names):
        icons_img.paste(ic[n].img, ((i % cols) * 16, (i // cols) * 16))
    save_png(icons_img, PUBLIC / "icons.png")

    # UI textures (individual files for CSS border-image)
    ui_tex = ui.generate()
    ui_paths = {}
    for n, c in sorted(ui_tex.items()):
        fname = n.removeprefix("ui.") + ".png"
        save_png(c.img, PUBLIC / "ui" / fname)
        ui_paths[n] = f"/assets/gen/ui/{fname}"
    save_png(ui.title_scene(world).img, PUBLIC / "title.png")

    manifest = {
        "version": 1,
        "tileSize": 16,
        "atlases": {"world": "/assets/gen/world.json"},
        "sprites": {n: {"atlas": "world", **bmeta.get(n, {})} for n in sorted(world)},
        "blobMasks": BLOB_MASKS,
        "chars": {
            "image": "/assets/gen/chars.png",
            "frame": [characters.FW, characters.FH],
            "frames": [f"{d}.{a}.{i}" for d, a, i in characters.FRAMES],
            "layers": {n: i for i, n in enumerate(names)},
            "shadeKeys": [hexs(k) for k in SHADE_KEYS],
        },
        "recolor": {
            "skin": SKIN,
            "hair": HAIR,
            "eyes": EYES,
            "outfit": OUTFIT,
        },
        "icons": {"image": "/assets/gen/icons.png", "size": 16, "cols": cols,
                  "names": {n.removeprefix("icon."): i for i, n in enumerate(icon_names)}},
        "ui": ui_paths,
        "title": "/assets/gen/title.png",
        "fonts": {"heading": "Pixelify Sans", "body": "Fredoka"},
    }
    save_json(manifest, SRC / "manifest.json")
    print(f"artgen: {len(world)} world sprites, {len(names)} character layers, {len(icon_names)} icons, "
          f"{len(ui_tex)} ui textures → {PUBLIC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
