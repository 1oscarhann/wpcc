"""Dev helper: render preview scenes into a folder (not part of the build)."""
import sys
from pathlib import Path

from PIL import Image

from artgen import nature, terrain
from artgen.terrain import E, N, NE, NW, S, SE, SW, W, reduce_mask

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def mask(s, x, y):
    m = 0
    for bit, dx, dy in ((N, 0, -1), (NE, 1, -1), (E, 1, 0), (SE, 1, 1), (S, 0, 1), (SW, -1, 1), (W, -1, 0), (NW, -1, -1)):
        if (x + dx, y + dy) in s:
            m |= bit
    return reduce_mask(m)


def scene1():
    t = terrain.generate()
    n = nature.generate()
    w, h = 20, 14
    path, water, cob = set(), set(), set()
    for x in range(3, 15):
        path.add((x, 4)); path.add((x, 9))
    for y in range(4, 10):
        path.add((3, y)); path.add((14, y))
    for x in range(5, 8):
        for y in range(6, 8):
            path.add((x, y))
    for x in range(9, 14):
        for y in range(11, 14):
            water.add((x, y))
    water.add((8, 12))
    for x in range(15, 20):
        for y in range(0, 4):
            cob.add((x, y))
    cob.add((14, 1))
    img = Image.new("RGBA", (w * 16, h * 16))
    for y in range(h):
        for x in range(w):
            if (x, y) in path:
                k = f"tile.path.{mask(path, x, y)}"
            elif (x, y) in water:
                k = f"tile.water.{mask(water, x, y)}"
            elif (x, y) in cob:
                k = f"tile.cobble.{mask(cob, x, y)}"
            else:
                hh = (x * 7 + y * 13) % 11
                k = f"tile.flowers.{hh % 3}" if hh == 0 else f"tile.grass.{hh % 4}"
            img.paste(t[k].img, (x * 16, y * 16))
    objs = {"obj.oak.0": (40, 60), "obj.oak.1": (70, 40), "obj.pine.0": (270, 200), "obj.pine.1": (300, 215),
            "obj.bush.0": (110, 60), "obj.bush.1": (200, 40), "obj.rock.0": (150, 200), "obj.rock_big.1": (60, 215),
            "obj.stump.0": (230, 120), "obj.tall_grass.0": (120, 180), "obj.well.0": (290, 120), "obj.oak.2": (250, 60)}
    for k, (x, y) in objs.items():
        c = n[k]
        img.alpha_composite(c.img, (x - c.w // 2, y - c.h))
    img.resize((img.width * 3, img.height * 3), Image.NEAREST).save(OUT / "scene1.png")


if __name__ == "__main__":
    scene1()


def buildings_sheet():
    from artgen import buildings

    sprites, meta = buildings.generate()
    t = terrain.generate()
    keys = list(buildings.BUILDINGS)
    cell_w, cell_h = 76, 140
    cols = 6
    names = []
    for k in keys:
        names.append([f"building.{k}.a.l{lv}" for lv in range(1, 6)] + ([f"building.{k}.b.l1"] if buildings.BUILDINGS[k].rotatable else [None]))
    img = Image.new("RGBA", (cols * cell_w, len(names) * cell_h))
    for r in range(len(names)):
        for cc in range(cols):
            for yy in range(0, cell_h, 16):
                for xx in range(0, cell_w, 16):
                    img.paste(t[f"tile.grass.{(xx + yy) % 4}"].img, (cc * cell_w + xx, r * cell_h + yy))
    for r, row in enumerate(names):
        for cc, name in enumerate(row):
            if name is None:
                continue
            s = sprites[name]
            img.alpha_composite(s.img, (cc * cell_w + (cell_w - s.w) // 2, r * cell_h + cell_h - s.h - 2))
    img.resize((img.width * 2, img.height * 2), Image.NEAREST).save(OUT / "buildings.png")
    scs = [k for k in sprites if k.startswith("building.scaffold.")]
    sc = Image.new("RGBA", (len(scs) * 76, 110))
    for i, k in enumerate(scs):
        s = sprites[k]
        sc.alpha_composite(s.img, (i * 76 + 2, 110 - s.h))
    sc.resize((sc.width * 3, sc.height * 3), Image.NEAREST).save(OUT / "scaffolds.png")


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[2] == "b":
    buildings_sheet()


def compose(layers, look):
    """Python mirror of the client composer: recolour shade keys, stack, outline."""
    from artgen import characters as ch
    from artgen.palette import EYES, HAIR, INK, OUTFIT, SHADE_KEYS, SKIN, hx

    order = [
        (f"char.body.{look['body']}", SKIN[look["skin"]]),
        (f"char.outfit.{look['outfit']}.{look['body']}", OUTFIT[look["outfit_color"]]),
        (f"char.eyes.{look['eyes']}", EYES[look["eye_color"]]),
        (f"char.hair.{look['hair_style']}", HAIR[look["hair_color"]]),
    ]
    keymap = [k[:3] for k in SHADE_KEYS]
    w, h = layers[order[0][0]].w, layers[order[0][0]].h
    out = Image.new("RGBA", (w, h))
    px = out.load()
    for name, rmp in order:
        src = layers[name].img.load()
        cols = [hx(c) for c in rmp]
        for y in range(h):
            for x in range(w):
                c = src[x, y]
                if c[3] == 0:
                    continue
                if c[:3] in keymap:
                    c = cols[keymap.index(c[:3])]
                px[x, y] = c
    # silhouette outline per frame
    res = out.copy()
    rp = res.load()
    for y in range(h):
        for x in range(w):
            if px[x, y][3]:
                continue
            fx = x % 16
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= ny < h and 0 <= nx < w and (nx // 16 == x // 16) and px[nx, ny][3] == 255:
                    rp[x, y] = INK
                    break
    return res


def chars_sheet():
    import yaml

    from artgen import characters as ch

    creator = yaml.safe_load(open("../../config/avatar.yaml"))["creator"]
    layers = ch.generate(creator)
    looks = [
        dict(body="slim", skin="honey", hair_style="crop", hair_color="chestnut", eyes="round", eye_color="brown", outfit="tunic", outfit_color="leaf"),
        dict(body="sturdy", skin="umber", hair_style="spiky", hair_color="black", eyes="keen", eye_color="amber", outfit="overalls", outfit_color="sky"),
        dict(body="slim", skin="porcelain", hair_style="long", hair_color="ginger", eyes="bright", eye_color="green", outfit="dress", outfit_color="rose"),
        dict(body="slim", skin="tan", hair_style="bun", hair_color="violet", eyes="sleepy", eye_color="blue", outfit="robe", outfit_color="navy"),
        dict(body="sturdy", skin="ebony", hair_style="braids", hair_color="silver", eyes="round", eye_color="hazel", outfit="vest", outfit_color="mustard"),
        dict(body="slim", skin="peach", hair_style="shaved", hair_color="blonde", eyes="keen", eye_color="grey", outfit="cloak", outfit_color="plum"),
    ]
    t = terrain.generate()
    rows = [compose(layers, lk) for lk in looks]
    img = Image.new("RGBA", (rows[0].width, 24 * len(rows) + 8 * len(rows)))
    for yy in range(0, img.height, 16):
        for xx in range(0, img.width, 16):
            img.paste(t["tile.grass.0"].img, (xx, yy))
    for i, r in enumerate(rows):
        img.alpha_composite(r, (0, i * 32 + 4))
    img.resize((img.width * 4, img.height * 4), Image.NEAREST).save(OUT / "chars.png")


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[2] == "c":
    chars_sheet()
