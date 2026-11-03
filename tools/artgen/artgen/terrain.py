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


def _blob_tile(mask: int, inset: int, salt: int, inside, rim_in, rim_out) -> Canvas:  # noqa: ANN001
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
                c.put(x, y, rim_out(x, y, at) if near else grass_color(x, y, 0))
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


def generate() -> dict[str, Canvas]:
    out: dict[str, Canvas] = {}
    for v in range(4):
        out[f"tile.grass.{v}"] = grass_tile(v)
    for v in range(3):
        out[f"tile.flowers.{v}"] = flower_tile(v)
    for m in BLOB_MASKS:
        out[f"tile.path.{m}"] = path_tile(m)
        out[f"tile.water.{m}"] = water_tile(m)
        out[f"tile.cobble.{m}"] = cobble_tile(m)
    return out
