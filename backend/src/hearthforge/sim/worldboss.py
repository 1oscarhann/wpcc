"""Phase 17: the world boss in one realm's room. Same brain as a realm boss (attacks, phases, hazards),
but its HP is the shared pool for every realm (D-120): the room tallies its players' damage, and every
flush takes that off the pool in the database and sets the boss's HP to whatever the pool says now.
No HP scaling by fighters (the pool is already sized for the whole world) and no loot on the spot:
rewards are mailed by damage tier when the event ends."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hearthforge.sim.bosses import BossBrain, BossRow

if TYPE_CHECKING:
    from hearthforge.sim.combat import Monster
    from hearthforge.sim.room import Player, RealmRoom

WORLD = 1024  # entity flag: the client draws it bigger and tinted


@dataclass
class WorldEvent:
    id: uuid.UUID
    key: str
    name: str
    hp_max: int
    hp_remaining: int
    status: str
    ends_ms: int


class WorldBrain(BossBrain):
    def __init__(self, ctl: WorldBoss, row: BossRow, cfg: Any) -> None:
        super().__init__(ctl, row, cfg)  # type: ignore[arg-type]
        self.world = ctl

    def flags(self, m: Monster) -> int:
        return super().flags(m) | WORLD

    def scale(self, m: Monster, n: int) -> None:
        self.fighters = max(1, n)  # the pool is shared; nothing to rescale here

    def on_hit(self, p: Player, dmg: float) -> float:
        if self.room.tick_no < self.vuln_until:
            dmg = round(dmg * self.cfg.vulnerable_mult)
        self.world.pending[str(p.user_id)] += int(dmg)
        p.pending.stats["worldboss.damage"] += int(dmg)
        return dmg

    def on_death(self, m: Monster, killer: Player) -> None:
        """This realm landed the last blow (or its last tally emptied the pool): the world wins."""
        self.hazards.clear()
        for mm in list(self.room.combat.monsters.values()):
            if mm.minion_of == m.id:
                self.room.combat._fade(mm)
        self._tell(
            m, ["down", self.row.key, self.world.event.name if self.world.event else "", []], everyone=True
        )
        self.world.m = None
        self.world.fallen = True


class WorldBoss:
    """The world boss as this room sees it."""

    def __init__(self, room: RealmRoom) -> None:
        self.room = room
        self.event: WorldEvent | None = None
        self.m: Monster | None = None
        self.pending: Counter[str] = Counter()  # user id → damage since the last flush
        self.fallen = False
        self.reload = True

    @property
    def cfg(self) -> Any:
        return self.room.cfg.bosses  # BossBrain reads engage, hp_per_fighter… from here

    def set_event(self, ev: WorldEvent | None) -> None:
        combat = self.room.combat
        live = ev is not None and ev.status == "active" and ev.hp_remaining > 0
        if not live:
            if self.m is not None and combat is not None and self.m.id in combat.monsters:
                if ev is not None and ev.status == "defeated" and self.m.brain is not None:
                    self.m.brain._tell(self.m, ["down", ev.key, ev.name, []], everyone=True)
                combat._fade(self.m)
            self.m = None
            self.event = ev
            return
        assert ev is not None
        fresh = self.event is None or self.event.id != ev.id
        self.event = ev
        if fresh:
            self.fallen = False
        if self.m is not None:
            # the pool moved (other realms' damage): take its value, minus what we haven't sent yet
            self.m.hp_max = ev.hp_max
            self.m.hp = max(1.0, float(ev.hp_remaining - sum(self.pending.values())))

    def tick(self, t: int) -> None:
        if self.room.combat is None or self.event is None or self.m is not None or self.fallen:
            return
        if self.event.status != "active" or self.event.hp_remaining <= 0:
            return
        self.m = self._spawn(t)

    def _spawn(self, t: int) -> Monster:
        from hearthforge.domain import mapgen

        room = self.room
        ev = self.event
        assert ev is not None
        cfg = room.cfg.bosses.bosses[ev.key]
        c = mapgen.layout(room.cfg.mapgen).center
        x, y = int(c), int(c) - 10  # just north of the hub's square
        solid = room.grid.solid
        for rad in range(0, 14):
            spot = next(
                (
                    (x + dx, y + dy)
                    for dx in range(-rad, rad + 1)
                    for dy in range(-rad, rad + 1)
                    if not solid(x + dx, y + dy)
                    and not solid(x + dx + 1, y + dy)
                    and not solid(x + dx, y + dy + 1)
                ),
                None,
            )
            if spot is not None:
                x, y = spot
                break
        row = BossRow(id=str(ev.id), key=ev.key, x=x + 0.5, y=y + 0.5, hp_fraction=1.0, expires_ms=ev.ends_ms)
        m = room.combat.spawn_one(cfg.enemy, x + 0.5, y + 0.5, cfg.biome, t, spread=0.0)
        m.hx, m.hy = x + 0.5, y + 0.5
        m.boss = True
        m.brain = WorldBrain(self, row, cfg)
        m.hp_max = ev.hp_max
        m.hp = max(1.0, float(ev.hp_remaining))
        m.state = "idle"
        return m

    def take_pending(self) -> dict[str, int]:
        out = {k: v for k, v in self.pending.items() if v > 0}
        self.pending.clear()
        return out

    def info(self) -> list[Any] | None:
        """For joiners and the map: [name, x, y, hp share, ends_ms]."""
        if self.event is None or self.event.status != "active":
            return None
        x, y = (self.m.hx, self.m.hy) if self.m is not None else (0.0, 0.0)
        share = self.event.hp_remaining / self.event.hp_max if self.event.hp_max else 0.0
        return [self.event.name, x, y, round(share, 4), self.event.ends_ms]
