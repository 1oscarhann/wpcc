"""Tiny pixel canvas with the helpers every drawing module uses.

Everything is deterministic: randomness comes from `Rng(seed)`, never from global state.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable

from PIL import Image

from artgen.palette import INK

Color = tuple[int, int, int, int]
CLEAR: Color = (0, 0, 0, 0)


class Rng:
    """splitmix64 — tiny, fast, identical everywhere."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
        return z ^ (z >> 31)

    def random(self) -> float:
        return (self.next() >> 11) / float(1 << 53)

    def randint(self, a: int, b: int) -> int:
        return a + self.next() % (b - a + 1)

    def chance(self, p: float) -> bool:
        return self.random() < p

    def choice(self, seq):  # noqa: ANN001, ANN201
        return seq[self.next() % len(seq)]


def hash2(x: int, y: int, salt: int = 0) -> float:
    r = Rng((x * 73856093) ^ (y * 19349663) ^ (salt * 83492791))
    r.next()
    return r.random()


class Canvas:
    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w, h), CLEAR)
        self.px = self.img.load()

    # ── primitives ─────────────────────────────────────────────────────────
    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def put(self, x: int, y: int, c: Color | None) -> None:
        if c is not None and self.inside(x, y):
            self.px[x, y] = c

    def get(self, x: int, y: int) -> Color:
        return self.px[x, y] if self.inside(x, y) else CLEAR

    def filled(self, x: int, y: int) -> bool:
        return self.get(x, y)[3] > 0

    def solid(self, x: int, y: int) -> bool:
        return self.get(x, y)[3] == 255

    def rect(self, x: int, y: int, w: int, h: int, c: Color) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, c)

    def hline(self, x0: int, x1: int, y: int, c: Color) -> None:
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.put(x, y, c)

    def vline(self, x: int, y0: int, y1: int, c: Color) -> None:
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.put(x, y, c)

    def line(self, x0: int, y0: int, x1: int, y1: int, c: Color) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.put(x0, y0, c)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, c: Color) -> None:
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1.0:
                    self.put(x, y, c)

    def shape(self, test: Callable[[int, int], bool], color: Callable[[int, int], Color | None]) -> None:
        for y in range(self.h):
            for x in range(self.w):
                if test(x, y):
                    c = color(x, y)
                    if c is not None:
                        self.put(x, y, c)

    def blit(self, other: Canvas, ox: int, oy: int, flip: bool = False) -> None:
        for y in range(other.h):
            for x in range(other.w):
                c = other.px[(other.w - 1 - x) if flip else x, y]
                if c[3] == 255:
                    self.put(ox + x, oy + y, c)
                elif c[3] > 0:
                    d = self.get(ox + x, oy + y)
                    if d[3] == 0:
                        self.put(ox + x, oy + y, c)
                    else:
                        a = c[3] / 255
                        self.put(ox + x, oy + y, tuple(round(c[i] * a + d[i] * (1 - a)) for i in range(3)) + (255,))

    # ── effects ────────────────────────────────────────────────────────────
    def outline(self, c: Color = INK, diagonal: bool = False) -> None:
        """1 px outline around every opaque pixel (outside only)."""
        add = []
        nbrs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        if diagonal:
            nbrs += [(1, 1), (-1, -1), (1, -1), (-1, 1)]
        for y in range(self.h):
            for x in range(self.w):
                if self.solid(x, y):
                    continue
                if any(self.solid(x + dx, y + dy) and self.get(x + dx, y + dy) != c for dx, dy in nbrs):
                    add.append((x, y))
        for x, y in add:
            self.px[x, y] = c

    def shade_by_light(self, mask: Iterable[tuple[int, int]], ramp: list[Color], base: int) -> None:
        """Paint a region with top-left light: edges facing up/left lighter, down/right darker."""
        pts = set(mask)
        for x, y in pts:
            up = (x, y - 1) not in pts
            left = (x - 1, y) not in pts
            down = (x, y + 1) not in pts
            right = (x + 1, y) not in pts
            i = base
            if up or left:
                i += 1
            if down or right:
                i -= 1
            self.put(x, y, ramp[max(0, min(len(ramp) - 1, i))])

    def drop_shadow(self, cx: float, cy: float, rx: float, ry: float, alpha: int = 70) -> None:
        """Soft oval shadow under a standing object (drawn before the object)."""
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                d = ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2
                if d <= 1.0 and not self.filled(x, y):
                    a = alpha if d < 0.55 else alpha * 2 // 3
                    self.put(x, y, (INK[0], INK[1], INK[2], a))

    def flipped(self) -> Canvas:
        out = Canvas(self.w, self.h)
        out.blit(self, 0, 0, flip=True)
        return out

    def copy(self) -> Canvas:
        out = Canvas(self.w, self.h)
        out.img.paste(self.img)
        out.px = out.img.load()
        return out


def dist(x0: float, y0: float, x1: float, y1: float) -> float:
    return math.hypot(x1 - x0, y1 - y0)


def blob(c: Canvas, circles: list[tuple[float, float, float]], ramp: list[Color], seed: int = 0,
         dither: bool = True) -> set[tuple[int, int]]:
    """Union of circles shaded with top-left light: classic tree canopy / bush."""
    pts: set[tuple[int, int]] = set()
    for y in range(c.h):
        for x in range(c.w):
            for cx, cy, r in circles:
                if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r:
                    pts.add((x, y))
                    break
    n = len(ramp)
    for x, y in pts:
        # brightness from the nearest circle's local normal, lit from top-left
        best = None
        for cx, cy, r in circles:
            d2 = (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2
            if d2 <= r * r and (best is None or d2 / (r * r) < best[0]):
                best = (d2 / (r * r), cx, cy, r)
        assert best is not None
        _, cx, cy, r = best
        nx, ny = (x + 0.5 - cx) / r, (y + 0.5 - cy) / r
        light = -(nx * 0.6 + ny * 0.8)  # -1 (away) .. 1 (towards light)
        v = (light + 1) / 2 * (n - 1) + 0.15
        if dither and hash2(x, y, seed) < (v % 1) * 0.6:
            v += 0.5
        i = max(0, min(n - 1, int(v)))
        c.put(x, y, ramp[i])
    return pts
