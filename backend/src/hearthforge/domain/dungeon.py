"""Dungeon layouts (Phase 12): a seeded room graph on a grid of cells, carved into tiles.

Pure and deterministic: the same (seed, cfg) always gives the same layout, so the daily delve is
identical in every realm and the client could rebuild it from the seed. The server still sends the
layout (it's small) so the two never have to share this code.

Rooms sit one per cell of a `cols × rows` grid. A random spanning tree over the cells (plus one extra
loop) connects them with 3-wide corridors through doors. The room furthest from the entrance is the
boss; one on the way is the mini-boss; dead ends become treasure; one or two rooms on the main path
become puzzles that gate the way on.
"""

from __future__ import annotations

import hashlib
import random
from collections import deque
from dataclasses import dataclass, field

VOID, FLOOR, WALL, DOOR = 0, 1, 2, 3


@dataclass
class Room:
    id: int
    kind: str  # entrance | combat | treasure | puzzle | miniboss | boss
    x: int
    y: int
    w: int
    h: int
    cell: tuple[int, int]
    depth: int = 0  # steps from the entrance
    doors: list[int] = field(default_factory=list)  # door ids
    puzzle: str = ""  # plates | levers

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


@dataclass
class Door:
    id: int
    tiles: list[tuple[int, int]]
    rooms: tuple[int, int]  # (room it belongs to, room on the other side)
    gate: bool = False  # leads deeper from a puzzle room: locked until it's solved


@dataclass
class Prop:
    kind: str  # torch | pillar | rubble | bones | plate | lever | lamp | chest | portal | banner | crystal
    x: int
    y: int
    room: int
    data: int = 0  # plate order / lever index / lamp index / variant


@dataclass
class Layout:
    seed: int
    w: int
    h: int
    tiles: bytearray
    rooms: list[Room]
    doors: list[Door]
    props: list[Prop]
    start: tuple[float, float]
    lever_masks: list[int] = field(default_factory=list)  # lever i toggles these lamps (bitmask)
    lamps_start: int = 0  # initial lamp bits; all lit = solved

    def at(self, x: int, y: int) -> int:
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.tiles[y * self.w + x]
        return VOID

    def room_at(self, x: float, y: float) -> Room | None:
        for r in self.rooms:
            if r.contains(x, y):
                return r
        return None

    def to_wire(self) -> dict:
        return {
            "w": self.w,
            "h": self.h,
            "tiles": bytes(self.tiles),
            "rooms": [[r.id, r.kind, r.x, r.y, r.w, r.h, r.depth, r.puzzle] for r in self.rooms],
            "doors": [[d.id, [list(t) for t in d.tiles], list(d.rooms), d.gate] for d in self.doors],
            "props": [[p.kind, p.x, p.y, p.room, p.data] for p in self.props],
            "start": list(self.start),
        }


def seed_for(*parts: object) -> int:
    h = hashlib.blake2b(":".join(str(p) for p in parts).encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") & 0x7FFFFFFFFFFF


def generate(
    seed: int, cols: int = 4, rows: int = 3, cell_w: int = 22, cell_h: int = 18, rooms: int = 9
) -> Layout:
    rng = random.Random(seed)
    w, h = cols * cell_w + 2, rows * cell_h + 2
    tiles = bytearray(w * h)

    # 1. a random spanning tree over `rooms` cells, starting from a cell on the top row
    start_cell = (rng.randrange(cols), 0)
    chosen = [start_cell]
    parent: dict[tuple[int, int], tuple[int, int] | None] = {start_cell: None}
    frontier = [start_cell]
    while len(chosen) < min(rooms, cols * rows) and frontier:
        c = frontier[rng.randrange(len(frontier))]
        nbrs = [
            (c[0] + dx, c[1] + dy)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            if 0 <= c[0] + dx < cols and 0 <= c[1] + dy < rows and (c[0] + dx, c[1] + dy) not in parent
        ]
        if not nbrs:
            frontier.remove(c)
            continue
        n = nbrs[rng.randrange(len(nbrs))]
        parent[n] = c
        chosen.append(n)
        frontier.append(n)
    edges = {tuple(sorted((c, p))) for c, p in parent.items() if p is not None}
    # one extra loop so it isn't strictly a tree (nicer to explore)
    extra = [
        (a, (a[0] + 1, a[1]))
        for a in chosen
        if (a[0] + 1, a[1]) in parent and tuple(sorted((a, (a[0] + 1, a[1])))) not in edges
    ]
    if extra:
        a, b = extra[rng.randrange(len(extra))]
        edges.add(tuple(sorted((a, b))))

    # 2. rooms inside their cells
    room_of: dict[tuple[int, int], Room] = {}
    out_rooms: list[Room] = []
    for i, c in enumerate(chosen):
        rw = rng.randint(cell_w - 10, cell_w - 6)
        rh = rng.randint(cell_h - 9, cell_h - 6)
        rx = 1 + c[0] * cell_w + rng.randint(2, cell_w - rw - 2)
        ry = 1 + c[1] * cell_h + rng.randint(2, cell_h - rh - 2)
        r = Room(i, "combat", rx, ry, rw, rh, c)
        room_of[c] = r
        out_rooms.append(r)
        for yy in range(ry, ry + rh):
            for xx in range(rx, rx + rw):
                tiles[yy * w + xx] = FLOOR

    # 3. depths from the entrance (BFS over the edges)
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {c: [] for c in chosen}
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    depth = {start_cell: 0}
    q = deque([start_cell])
    while q:
        c = q.popleft()
        for n in adj[c]:
            if n not in depth:
                depth[n] = depth[c] + 1
                q.append(n)
    for c, r in room_of.items():
        r.depth = depth[c]

    # 4. corridors + doors: from each room's edge toward the neighbour, 3 wide (an L if they don't line up)
    doors: list[Door] = []

    def carve(x: int, y: int) -> None:
        if 0 < x < w - 1 and 0 < y < h - 1 and tiles[y * w + x] == VOID:
            tiles[y * w + x] = FLOOR

    for a, b in sorted(edges):
        ra, rb = room_of[a], room_of[b]
        horizontal = a[1] == b[1]
        if horizontal:
            left, right = (ra, rb) if ra.x < rb.x else (rb, ra)
            ylo = max(left.y + 1, right.y + 1)
            yhi = min(left.y + left.h - 2, right.y + right.h - 2)
            if ylo <= yhi - 2:
                yy = rng.randint(ylo, yhi - 2)
                y1 = y2 = yy
            else:
                y1 = rng.randint(left.y + 1, left.y + left.h - 4)
                y2 = rng.randint(right.y + 1, right.y + right.h - 4)
            x0, x1 = left.x + left.w, right.x - 1
            mid = (x0 + x1) // 2
            for x in range(x0, mid + 1):
                for k in range(3):
                    carve(x, y1 + k)
            for y in range(min(y1, y2), max(y1, y2) + 3):
                for k in range(3):
                    carve(mid + k - 1, y)
            for x in range(mid, x1 + 1):
                for k in range(3):
                    carve(x, y2 + k)
            da = Door(len(doors), [(x0, y1 + k) for k in range(3)], (left.id, right.id))
            doors.append(da)
            db = Door(len(doors), [(x1, y2 + k) for k in range(3)], (right.id, left.id))
            doors.append(db)
        else:
            top, bot = (ra, rb) if ra.y < rb.y else (rb, ra)
            xlo = max(top.x + 1, bot.x + 1)
            xhi = min(top.x + top.w - 2, bot.x + bot.w - 2)
            if xlo <= xhi - 2:
                xx = rng.randint(xlo, xhi - 2)
                x1 = x2 = xx
            else:
                x1 = rng.randint(top.x + 1, top.x + top.w - 4)
                x2 = rng.randint(bot.x + 1, bot.x + bot.w - 4)
            y0, y1b = top.y + top.h, bot.y - 1
            mid = (y0 + y1b) // 2
            for y in range(y0, mid + 1):
                for k in range(3):
                    carve(x1 + k, y)
            for x in range(min(x1, x2), max(x1, x2) + 3):
                for k in range(3):
                    carve(x, mid + k - 1)
            for y in range(mid, y1b + 1):
                for k in range(3):
                    carve(x2 + k, y)
            da = Door(len(doors), [(x1 + k, y0) for k in range(3)], (top.id, bot.id))
            doors.append(da)
            db = Door(len(doors), [(x2 + k, y1b) for k in range(3)], (bot.id, top.id))
            doors.append(db)
        for d in (da, db):
            out_rooms[d.rooms[0]].doors.append(d.id)
            for x, y in d.tiles:
                tiles[y * w + x] = DOOR

    # 5. walls: void next to floor
    for y in range(h):
        for x in range(w):
            if tiles[y * w + x] != VOID:
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < w and 0 <= yy < h and tiles[yy * w + xx] in (FLOOR, DOOR):
                        tiles[y * w + x] = WALL
                        break
                else:
                    continue
                break

    # 6. roles
    entrance = room_of[start_cell]
    entrance.kind = "entrance"
    far = max(out_rooms, key=lambda r: (r.depth, r.id))
    far.kind = "boss"
    path: list[Room] = []
    cur: tuple[int, int] | None = far.cell
    while cur is not None:  # walk the BFS tree back from the boss
        path.append(room_of[cur])
        prev = [n for n in adj[cur] if depth[n] == depth[cur] - 1]
        cur = prev[0] if prev else None
    path.reverse()  # entrance … boss
    inner = [r for r in path if r.kind == "combat"]
    if inner:
        mb = inner[min(len(inner) - 1, int(len(inner) * 0.6))]
        mb.kind = "miniboss"
    leaves = [r for r in out_rooms if r.kind == "combat" and len(adj[r.cell]) == 1]
    for r in leaves[:2]:
        r.kind = "treasure"
    puzzles = [r for r in path if r.kind == "combat"]
    for i, r in enumerate(puzzles[:2]):
        r.kind = "puzzle"
        r.puzzle = "plates" if (i + rng.randrange(2)) % 2 == 0 else "levers"
    # puzzle rooms gate the doors that lead deeper
    for d in doors:
        here, there = out_rooms[d.rooms[0]], out_rooms[d.rooms[1]]
        if here.kind == "puzzle" and there.depth > here.depth:
            d.gate = True

    # 7. props
    props: list[Prop] = []
    lever_masks: list[int] = []
    lamps_start = 0
    for r in out_rooms:
        # torches along the top wall, every 5 tiles
        for x in range(r.x + 2, r.x + r.w - 1, 5):
            if tiles[(r.y - 1) * w + x] == WALL:
                props.append(Prop("torch", x, r.y - 1, r.id))
        if r.kind in ("combat", "miniboss", "boss") and r.w >= 12 and r.h >= 9:
            for px, py in ((r.x + 3, r.y + 3), (r.x + r.w - 4, r.y + r.h - 4)):
                props.append(Prop("pillar", px, py, r.id))
        for _ in range(rng.randint(1, 3)):
            px = rng.randint(r.x + 1, r.x + r.w - 2)
            py = rng.randint(r.y + 1, r.y + r.h - 2)
            props.append(Prop(rng.choice(["rubble", "bones", "crystal"]), px, py, r.id, rng.randrange(2)))
        if r.kind == "treasure":
            props.append(Prop("chest", int(r.cx), int(r.cy), r.id))
        if r.kind == "boss":
            props.append(Prop("banner", r.x + 2, r.y - 1, r.id))
            props.append(Prop("banner", r.x + r.w - 3, r.y - 1, r.id))
        if r.kind == "puzzle" and r.puzzle == "plates":
            spots = [
                (r.x + 2 + i * ((r.w - 5) // 2), r.y + r.h // 2 + (1 if i % 2 else -1)) for i in range(3)
            ]
            order = [0, 1, 2]
            rng.shuffle(order)
            for k, (px, py) in enumerate(spots):
                props.append(Prop("plate", px, py, r.id, order[k]))  # data = its place in the sequence
        if r.kind == "puzzle" and r.puzzle == "levers":
            for k in range(3):
                props.append(Prop("lever", r.x + 2 + k * 3, r.y + r.h - 2, r.id, k))
                props.append(Prop("lamp", r.x + 2 + k * 3, r.y + 1, r.id, k))
            masks = [0b011, 0b110, 0b101]
            rng.shuffle(masks)
            lever_masks = masks
            presses = [k for k in range(3) if rng.random() < 0.6] or [rng.randrange(3)]
            lamps_start = 0b111
            for k in presses:
                lamps_start ^= masks[k]
            if lamps_start == 0b111:
                lamps_start ^= masks[0]
    # pillars and props never block a door or the room's middle line
    door_tiles = {t for d in doors for t in d.tiles}
    props = [p for p in props if (p.x, p.y) not in door_tiles]
    start = (entrance.cx, entrance.cy + 1)
    return Layout(seed, w, h, tiles, out_rooms, doors, props, start, lever_masks, lamps_start)


def solid_tile(kind: int) -> bool:
    return kind in (VOID, WALL)


def reachable(layout: Layout) -> set[int]:
    """Room ids reachable from the entrance with every door open (a sanity check for tests)."""
    seen: set[tuple[int, int]] = set()
    sx, sy = int(layout.start[0]), int(layout.start[1])
    q = deque([(sx, sy)])
    seen.add((sx, sy))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n not in seen and layout.at(*n) in (FLOOR, DOOR):
                seen.add(n)
                q.append(n)
    return {
        r.id
        for r in layout.rooms
        if any((x, y) in seen for x in range(r.x, r.x + r.w) for y in range(r.y, r.y + r.h))
    }
