"""Atlas packing + manifest writing."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from artgen.canvas import Canvas

PAD = 2


def shelf_pack(items: dict[str, Canvas], width: int = 1024) -> tuple[Image.Image, dict[str, tuple[int, int, int, int]]]:
    """Deterministic shelf packer: sort by height then name, 2 px padding with 1 px edge extrusion."""
    order = sorted(items, key=lambda k: (-items[k].h, k))
    x = y = shelf_h = 0
    rects: dict[str, tuple[int, int, int, int]] = {}
    for k in order:
        c = items[k]
        if x + c.w + PAD * 2 > width:
            x = 0
            y += shelf_h
            shelf_h = 0
        rects[k] = (x + PAD, y + PAD, c.w, c.h)
        x += c.w + PAD * 2
        shelf_h = max(shelf_h, c.h + PAD * 2)
    height = y + shelf_h
    h2 = 1
    while h2 < height:
        h2 *= 2
    img = Image.new("RGBA", (width, h2), (0, 0, 0, 0))
    for k, (rx, ry, w, h) in rects.items():
        src = items[k].img
        img.paste(src, (rx, ry))
        if k.startswith("tile."):  # extrude edges so scaled tiles never show seams
            img.paste(src.crop((0, 0, w, 1)), (rx, ry - 1))
            img.paste(src.crop((0, h - 1, w, h)), (rx, ry + h))
            img.paste(src.crop((0, 0, 1, h)), (rx - 1, ry))
            img.paste(src.crop((w - 1, 0, w, h)), (rx + w, ry))
    return img, rects


def pixi_json(image_name: str, img: Image.Image, rects: dict[str, tuple[int, int, int, int]]) -> dict:
    frames = {
        k: {
            "frame": {"x": x, "y": y, "w": w, "h": h},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h},
        }
        for k, (x, y, w, h) in sorted(rects.items())
    }
    return {"frames": frames, "meta": {"image": image_name, "size": {"w": img.width, "h": img.height}, "scale": "1"}}


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)


def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
