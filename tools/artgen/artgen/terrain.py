"""16×16 terrain tiles: grass, flowers, and 47-blob autotiles for paths, water and cobblestone.

Blob masks use 8 neighbour bits (N=1 NE=2 E=4 SE=8 S=16 SW=32 W=64 NW=128). A corner bit only
counts when both neighbouring cardinals are set, which reduces 256 masks to 47 unique tiles.
The backend's mapgen uses the same `reduce_mask` rule (see backend domain/mapgen.py).
"""

from __future__ import annotations

from artgen.canvas import Canvas, Color, hash2
from artgen.palette import ramp

T = 16
N, NE, E, SE, S, SW, W, NW = 1, 2, 4, 8, 16, 32, 64, 128

GRASS = ramp("grass")
DIRT = ramp("dirt")
SAND = ramp("sand")
STONE = ramp("stone")
WATER = ramp("water")


def reduce_mask(m: int) -> int:
    if not (m & N and m & E):
        m &= ~NE
    if not (m & S and m & E):
        m &= ~SE
    if not (m & S and m & W):
        m &= ~SW
    if not (m & N and m & W):
        m &= ~NW
    return m


BLOB_MASKS = sorted({reduce_mask(m) for m in range(256)})
assert len(BLOB_MASKS) == 47


def grass_color(x: int, y: int, variant: int) -> Color:
    h = hash2(x, y, 11 + variant * 7)
    if h < 0.015:
        return GRASS[1]
    if h > 0.975:
        return GRASS[3]
    return GRASS[2]


def grass_tile(variant: int) -> Canvas:
    """Calm base grass with a few soft blade clusters. Large-scale colour variation is added by the client."""
    c = Canvas(T, T)
    for y in range(T):
        for x in range(T):
            c.put(x, y, grass_color(x, y, variant))
    for i in range(2 + variant % 3):
        tx = int(hash2(i, variant, 5) * 12) + 2
        ty = int(hash2(variant, i, 6) * 11) + 3
        for bx, h in ((0, 2), (2, 3), (4, 2)):
            if tx + bx >= T:
                continue
            for d in range(h):
                c.put(tx + bx - (d == h - 1 and bx == 0), ty - d, GRASS[3] if d == h - 1 else GRASS[1] if d == 0 else GRASS[2])
    return c


def flower_tile(variant: int) -> Canvas:
    c = grass_tile(variant + 10)
    petals = [ramp("flower_pink"), ramp("flower_yellow"), ramp("flower_white"), ramp("flower_purple")]
    spots = [(3, 4), (10, 3), (6, 10), (12, 11), (2, 13)]
    for i, (fx, fy) in enumerate(spots[: 3 + variant % 2]):
        fx += variant % 3 - 1
        p = petals[(i + variant) % len(petals)]
        c.put(fx + 1, fy + 2, GRASS[1])  # little shadow
        c.put(fx, fy + 2, GRASS[1])
        c.put(fx - 1, fy, p[1])
        c.put(fx + 1, fy, p[0])
        c.put(fx, fy - 1, p[2])
        c.put(fx, fy + 1, p[0])
        centre = ramp("flower_yellow")[2] if p is not petals[1] else ramp("flower_red")[1]
        c.put(fx, fy, centre)
    return c


def _in_blob(mask: int, x: int, y: int, inset: int, jitter_salt: int) -> bool:
    lo, hi = inset, T - inset
    jx = 1 if hash2(x, y, jitter_salt) < 0.25 else 0
    jy = 1 if hash2(y, x, jitter_salt + 1) < 0.25 else 0
    in_x = lo + jx <= x < hi - jx
    in_y = lo + jy <= y < hi - jy
    if in_x and in_y:
        # round outer corners of the core where neither neighbouring side continues
        dx0, dx1, dy0, dy1 = x - lo, hi - 1 - x, y - lo, hi - 1 - y
        if dx0 + dy0 < 2 and not (mask & N) and not (mask & W):
            return False
        if dx1 + dy0 < 2 and not (mask & N) and not (mask & E):
            return False
        if dx0 + dy1 < 2 and not (mask & S) and not (mask & W):
            return False
        if dx1 + dy1 < 2 and not (mask & S) and not (mask & E):
            return False
        return True
    top, bottom, left, right = y < lo + jy, y >= hi - jy, x < lo + jx, x >= hi - jx
    if top and in_x:
        return bool(mask & N)
    if bottom and in_x:
        return bool(mask & S)
    if left and in_y:
        return bool(mask & W)
    if right and in_y:
        return bool(mask & E)
    # corners: filled when the diagonal continues; otherwise a softened inner corner
    if top and left:
        return bool(mask & NW) or (bool(mask & N and mask & W) and x == lo - 1 and y == lo - 1)
    if top and right:
        return bool(mask & NE) or (bool(mask & N and mask & E) and x == hi and y == lo - 1)
    if bottom and left:
        return bool(mask & SW) or (bool(mask & S and mask & W) and x == lo - 1 and y == hi)
    if bottom and right:
        return bool(mask & SE) or (bool(mask & S and mask & E) and x == hi and y == hi)
    return False


def _blob_tile(mask: int, inset: int, salt: int, inside, rim_in, rim_out, outside=None) -> Canvas:  # noqa: ANN001
    c = Canvas(T, T)
    inner = [[_in_blob(mask, x, y, inset, salt) for x in range(T)] for y in range(T)]

    def at(x: int, y: int) -> bool:
        if 0 <= x < T and 0 <= y < T:
            return inner[y][x]
        # One pixel outside the tile: decide from the neighbour bits (corner bits imply both cardinals).
        lo, hi = inset, T - inset
        if x < 0 and y < 0:
            return bool(mask & NW)
        if x >= T and y < 0:
            return bool(mask & NE)
        if x < 0 and y >= T:
            return bool(mask & SW)
        if x >= T and y >= T:
            return bool(mask & SE)
        if y < 0:
            return bool(mask & NW) if x < lo else bool(mask & NE) if x >= hi else bool(mask & N)
        if y >= T:
            return bool(mask & SW) if x < lo else bool(mask & SE) if x >= hi else bool(mask & S)
        if x < 0:
            return bool(mask & NW) if y < lo else bool(mask & SW) if y >= hi else bool(mask & W)
        return bool(mask & NE) if y < lo else bool(mask & SE) if y >= hi else bool(mask & E)

    for y in range(T):
        for x in range(T):
            if inner[y][x]:
                edge = not (at(x - 1, y) and at(x + 1, y) and at(x, y - 1) and at(x, y + 1))
                c.put(x, y, rim_in(x, y, at) if edge else inside(x, y))
            else:
                near = at(x - 1, y) or at(x + 1, y) or at(x, y - 1) or at(x, y + 1)
                c.put(x, y, rim_out(x, y, at) if near else (outside or (lambda a, b: grass_color(a, b, 0)))(x, y))
    return c


def path_tile(mask: int) -> Canvas:
    def inside(x: int, y: int) -> Color:
        h = hash2(x, y, 41)
        return DIRT[1] if h < 0.08 else DIRT[3] if h > 0.88 else DIRT[2]

    def rim_in(x: int, y: int, at) -> Color:  # noqa: ANN001
        # sunken path, lit from the top-left: far (bottom/right) inner edges catch light
        if not at(x, y + 1) or not at(x + 1, y):
            return DIRT[3]
        return DIRT[1]

    def rim_out(x: int, y: int, at) -> Color:  # noqa: ANN001
        return GRASS[3] if at(x, y + 1) or at(x + 1, y) else GRASS[1]

    return _blob_tile(mask, 3, 43, inside, rim_in, rim_out)


def water_tile(mask: int) -> Canvas:
    def inside(x: int, y: int) -> Color:
        # short horizontal glints, lit from the top-left
        g = hash2(x // 3, y, 51)
        if g > 0.93 and y % 4 == 1:
            return WATER[4] if x % 3 else WATER[3]
        return WATER[2] if hash2(x // 4, y // 3, 52) < 0.75 else WATER[3]

    def rim_in(x: int, y: int, at) -> Color:  # noqa: ANN001
        if not at(x, y - 1) or not at(x - 1, y):
            return WATER[0]  # shaded bank under the top/left lip
        return WATER[3]

    def rim_out(x: int, y: int, at) -> Color:  # noqa: ANN001
        return SAND[2] if hash2(x, y, 53) < 0.7 else SAND[1]

    return _blob_tile(mask, 2, 57, inside, rim_in, rim_out)


def _cobble_inside(x: int, y: int) -> Color:
    """Seamless Voronoi cobbles: 4×4 cells per tile, points wrap at the tile edge."""
    cell = 4
    best = []
    gx, gy = x // cell, y // cell
    for oy in (-1, 0, 1):
        for ox in (-1, 0, 1):
            cx, cy = gx + ox, gy + oy
            wx, wy = cx % (T // cell), cy % (T // cell)
            px = cx * cell + 0.8 + hash2(wx, wy, 61) * 2.4
            py = cy * cell + 0.8 + hash2(wy, wx, 62) * 2.4
            best.append(((x + 0.5 - px) ** 2 + (y + 0.5 - py) ** 2, px, py, wx, wy))
    best.sort()
    d1, px, py, wx, wy = best[0]
    d2 = best[1][0]
    if d2 ** 0.5 - d1 ** 0.5 < 0.75:
        return STONE[1]
    tone = 2 + (hash2(wx, wy, 63) < 0.45)
    if x + 0.5 < px - 0.6 and y + 0.5 < py - 0.6:
        tone += 1  # lit top-left of each stone
    elif x + 0.5 > px + 0.7 and y + 0.5 > py + 0.4:
        tone -= 1
    return STONE[max(1, min(4, tone))]


def cobble_tile(mask: int) -> Canvas:
    def rim_in(x: int, y: int, at) -> Color:  # noqa: ANN001
        return STONE[1]

    def rim_out(x: int, y: int, at) -> Color:  # noqa: ANN001
        return GRASS[1]

    return _blob_tile(mask, 1, 63, _cobble_inside, rim_in, rim_out)


LEAF = ramp("leaf")
PINE = ramp("pine")
WOOD = ramp("wood")


def forest_tile(variant: int) -> Canvas:
    """Whispering Forest floor: calm, shaded moss with the odd fallen leaf or twig (darker than meadow)."""
    c = Canvas(T, T)
    for y in range(T):
        for x in range(T):
            h = hash2(x, y, 201 + variant * 13)
            col = LEAF[1] if h < 0.82 else PINE[1] if h < 0.97 else LEAF[2]
            c.put(x, y, col)
    for i in range(1 + variant % 2):  # a fallen leaf or two
        lx = int(hash2(i, variant, 202) * 12) + 2
        ly = int(hash2(variant, i, 203) * 12) + 2
        col = (WOOD[2], DIRT[2], WOOD[3])[(i + variant) % 3]
        c.put(lx, ly, col)
        c.put(lx + 1, ly, col)
        c.put(lx + 1, ly + 1, WOOD[1])
    if variant == 2:  # a twig
        tx = int(hash2(variant, 7, 204) * 9) + 2
        ty = int(hash2(7, variant, 205) * 10) + 3
        for d in range(4):
            c.put(tx + d, ty + (d > 1), WOOD[1])
    for i in range(2):  # moss tufts catching the light
        mx = int(hash2(i, variant, 206) * 12) + 2
        my = int(hash2(variant, i, 207) * 12) + 2
        c.put(mx, my, LEAF[2])
        c.put(mx + 1, my - 1, LEAF[3])
        c.put(mx + 2, my, LEAF[2])
    return c


# ── Phase 10: the outer rings ───────────────────────────────────────────────
SNOW = ramp("snow")
ICE = ramp("ice")
ASH = ramp("ash")
LAVA = ramp("lava")
MUD = ramp("mud")
BOG = ramp("bog")


def _speckle_tile(variant: int, salt: int, base: list, speckles: list, rate: float = 0.12) -> Canvas:
    c = Canvas(T, T)
    for y in range(T):
        for x in range(T):
            h = hash2(x, y, salt + variant * 13)
            col = base[0] if h < 0.55 else base[1] if h < 0.9 else base[2]
            if hash2(x // 2, y // 2, salt + 5 + variant) < rate:
                col = speckles[int(hash2(x, y, salt + 9) * len(speckles)) % len(speckles)]
            c.put(x, y, col)
    return c


def rock_tile(variant: int) -> Canvas:
    """Stonepeak: grey gravel with lighter chips and the odd crack."""
    c = _speckle_tile(variant, 401, [STONE[2], STONE[2], STONE[1]], [STONE[3], STONE[4]], 0.09)
    if variant % 2 == 0:
        x0 = int(hash2(variant, 1, 402) * 8) + 3
        for d in range(5):
            c.put(x0 + d, 6 + d // 2 + (d % 2), STONE[0])
    return c


def mud_tile(variant: int) -> Canvas:
    """Murkwater: dark wet mud with mossy patches and puddle glints."""
    c = _speckle_tile(variant, 411, [MUD[1], MUD[2], MUD[1]], [BOG[1], BOG[2]], 0.14)
    gx, gy = int(hash2(variant, 3, 412) * 10) + 3, int(hash2(3, variant, 413) * 10) + 3
    c.hline(gx, gx + 2, gy, ramp("water")[1])
    c.put(gx + 1, gy, ramp("water")[2])
    return c


def snow_tile(variant: int) -> Canvas:
    """Frozen North: soft snow with faint blue shading and sparkles."""
    c = _speckle_tile(variant, 421, [SNOW[3], SNOW[3], SNOW[2]], [SNOW[4], SNOW[2]], 0.06)
    for i in range(2):
        sx, sy = int(hash2(i, variant, 422) * 14) + 1, int(hash2(variant, i, 423) * 14) + 1
        c.put(sx, sy, SNOW[4])
    return c


def ash_tile(variant: int) -> Canvas:
    """Ashen Wastes: grey-black ash with a few glowing embers."""
    c = _speckle_tile(variant, 431, [ASH[2], ASH[1], ASH[2]], [ASH[3], ASH[0]], 0.12)
    if variant % 2:
        ex, ey = int(hash2(variant, 5, 432) * 12) + 2, int(hash2(5, variant, 433) * 12) + 2
        c.put(ex, ey, LAVA[3])
        c.put(ex + 1, ey, LAVA[2])
    return c


def ice_tile(mask: int) -> Canvas:
    def inside(x: int, y: int) -> Color:
        if (x + 2 * y) % 11 == 0 and hash2(x // 3, y, 441) > 0.5:
            return ICE[3]
        return ICE[2] if hash2(x // 4, y // 3, 442) < 0.8 else ICE[1]

    def rim_in(x: int, y: int, at) -> Color:  # noqa: ANN001
        return ICE[0] if not at(x, y - 1) or not at(x - 1, y) else ICE[3]

    def rim_out(x: int, y: int, at) -> Color:  # noqa: ANN001
        return SNOW[2] if hash2(x, y, 443) < 0.7 else SNOW[1]

    def outside(x: int, y: int) -> Color:
        return SNOW[3] if hash2(x, y, 444) < 0.8 else SNOW[2]

    return _blob_tile(mask, 2, 447, inside, rim_in, rim_out, outside)


def lava_tile(mask: int) -> Canvas:
    def inside(x: int, y: int) -> Color:
        g = hash2(x // 3, y // 2, 451)
        return LAVA[3] if g > 0.85 else LAVA[2] if g > 0.35 else LAVA[1]

    def rim_in(x: int, y: int, at) -> Color:  # noqa: ANN001
        return LAVA[0] if not at(x, y - 1) or not at(x - 1, y) else LAVA[4]

    def rim_out(x: int, y: int, at) -> Color:  # noqa: ANN001
        return ASH[0] if hash2(x, y, 453) < 0.6 else ASH[1]

    def outside(x: int, y: int) -> Color:
        return ASH[2] if hash2(x, y, 454) < 0.6 else ASH[1]

    return _blob_tile(mask, 2, 457, inside, rim_in, rim_out, outside)


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for v in range(4):
        out[f"tile.forest.{v}"] = forest_tile(v)
    for v in range(4):
        out[f"tile.grass.{v}"] = grass_tile(v)
    for v in range(3):
        out[f"tile.flowers.{v}"] = flower_tile(v)
    for m in BLOB_MASKS:
        out[f"tile.path.{m}"] = path_tile(m)
        out[f"tile.water.{m}"] = water_tile(m)
        out[f"tile.cobble.{m}"] = cobble_tile(m)
    # Phase 10 rings
    for v in range(4):
        out[f"tile.rock.{v}"] = rock_tile(v)
        out[f"tile.mud.{v}"] = mud_tile(v)
        out[f"tile.snow.{v}"] = snow_tile(v)
        out[f"tile.ash.{v}"] = ash_tile(v)
    for m in sorted({m & (1 | 4 | 16 | 64) for m in range(256)}):  # cardinal-only masks (N, E, S, W)
        out[f"tile.ice.{m}"] = ice_tile(m)
        out[f"tile.lava.{m}"] = lava_tile(m)
    return out
