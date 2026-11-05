"""Phase 10: the world clock (day/night, seasons, weather timeline), weather-aware production, biome bands."""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from hearthforge.config.loader import load_config
from hearthforge.domain import mapgen, worldclock
from hearthforge.domain.resources import ResState, settle, settle_weather
from hearthforge.settings import REPO_ROOT

pytestmark = pytest.mark.nodb
GAME = load_config(REPO_ROOT / "config")
WC = GAME.world_clock
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # a whole number of 24 m days since 1970: dawn starts


def test_day_cycle_phases_follow_the_config() -> None:
    assert worldclock.day_phase(WC, T0).name == "dawn"
    assert worldclock.day_phase(WC, T0 + timedelta(minutes=3)).name == "day"
    assert worldclock.day_phase(WC, T0 + timedelta(minutes=17)).name == "dusk"
    night = worldclock.day_phase(WC, T0 + timedelta(minutes=21))
    assert night.name == "night" and night.progress == pytest.approx(0.5)
    assert worldclock.is_night(WC, T0 + timedelta(minutes=23, seconds=59))
    assert not worldclock.is_night(WC, T0 + timedelta(minutes=24))  # the next dawn


def test_seasons_rotate_weekly() -> None:
    seen = [worldclock.season(WC, T0 + timedelta(days=7 * k)) for k in range(4)]
    assert sorted(seen) == sorted(WC.seasons)
    end = worldclock.season_ends(WC, T0)
    assert worldclock.season(WC, end) != worldclock.season(WC, end - timedelta(seconds=1))


def test_weather_is_a_pure_function_of_seed_and_block() -> None:
    a = [worldclock.weather_for_block(WC, 42, i) for i in range(500)]
    b = [worldclock.weather_for_block(WC, 42, i) for i in range(500)]
    c = [worldclock.weather_for_block(WC, 43, i) for i in range(500)]
    assert a == b and a != c
    assert set(a) <= set(WC.weather.states)


def test_weather_follows_season_weights() -> None:
    """No rain in winter, no snow in summer (weights 0), and clear is the most common overall."""
    per: dict[str, Counter[str]] = {s: Counter() for s in WC.seasons}
    start = worldclock.block_index(WC, T0)
    for i in range(start, start + 4 * 7 * 72):  # four weeks of 20 m blocks
        mid = worldclock.block_start(WC, i) + timedelta(minutes=10)
        per[worldclock.season(WC, mid)][worldclock.weather_for_block(WC, 7, i)] += 1
    assert per["winter"]["rain"] == 0
    assert per["summer"]["snow"] == 0
    total = sum(per.values(), Counter())
    assert total.most_common(1)[0][0] == "clear"


def test_segments_cover_the_range_exactly() -> None:
    t0 = T0 + timedelta(minutes=7)
    t1 = t0 + timedelta(hours=3, minutes=5)
    segs = worldclock.segments(WC, 9, t0, t1)
    assert segs[0][0] == t0 and segs[-1][1] == t1
    for (_, b, _), (a2, _, _) in zip(segs, segs[1:], strict=False):
        assert b == a2
    assert len(worldclock.forecast(WC, 9, t0, 4)) == 4


def test_rain_speeds_up_food_and_settles_like_the_plain_maths() -> None:
    st = ResState(amount=0, rate=60_000, cap=10**9, at=T0)  # 60 food an hour
    hour = T0 + timedelta(hours=1)
    plain = settle(st, hour)
    flat = settle_weather(st, hour, [(T0, hour, 1.0)])
    assert flat.amount == plain.amount
    rainy = settle_weather(
        st, hour, [(T0, T0 + timedelta(minutes=30), 1.0), (T0 + timedelta(minutes=30), hour, 1.2)]
    )
    assert rainy.amount == 30_000 + 36_000
    assert rainy.rate == st.rate  # the base rate is untouched


def test_settle_weather_in_steps_matches_one_go() -> None:
    st = ResState(amount=0, rate=7_777, cap=10**9, at=T0)
    end = T0 + timedelta(hours=5)

    def segs(a: datetime, b: datetime) -> list[tuple[datetime, datetime, float]]:
        return [
            (
                x,
                y,
                1.2 if worldclock.weather_for_block(WC, 3, worldclock.block_index(WC, x)) == "rain" else 1.0,
            )
            for x, y, _ in worldclock.segments(WC, 3, a, b)
        ]

    once = settle_weather(st, end, segs(T0, end))
    cur = st
    t = T0
    while t < end:
        nt = min(end, t + timedelta(minutes=13))
        cur = settle_weather(cur, nt, segs(cur.at, nt))
        t = nt
    assert abs(cur.amount - once.amount) <= 1000 * 16  # < 1 unit per weather boundary


def test_biome_bands_ring_the_map_in_order() -> None:
    gen = mapgen.Generator(GAME, 1234)
    c = GAME.mapgen.map_size // 2
    order = ["meadow", "forest", "stonepeak", "swamp", "frozen", "ashen"]
    found: list[str] = []
    for r in range(60, GAME.mapgen.map_size // 2 - 4, 4):
        votes = Counter(
            gen.biome(int(c + r * math.cos(math.radians(a))), int(c + r * math.sin(math.radians(a))))
            for a in range(0, 360, 10)
        )
        votes.pop("plot", None)  # the village ring sits inside the meadow
        b = votes.most_common(1)[0][0]
        if not found or found[-1] != b:
            found.append(b)
    assert found == order


def test_band_nodes_and_ground_show_up() -> None:
    """Each outer band has its own ground and at least one of its nodes in a slice of the map."""
    gen = mapgen.Generator(GAME, 99)
    c = GAME.mapgen.map_size // 2
    cs = GAME.mapgen.chunk_size
    for band in GAME.mapgen.bands:
        if band.biome == "forest":
            continue
        r = band.radius - 15
        objs: Counter[str] = Counter()
        grounds: Counter[str] = Counter()
        for a in range(0, 360, 30):
            x, y = int(c + r * math.cos(math.radians(a))), int(c + r * math.sin(math.radians(a)))
            ch = gen.chunk(x // cs, y // cs)
            grounds.update(mapgen.TILE_NAMES[t].split(".")[1] for t in ch["ground"])
            objs.update(mapgen.OBJECT_NAMES[o[2]].split(".")[1] for o in ch["objects"])
        assert {"rock", "mud", "snow", "ash"} & set(grounds), band.biome
        assert sum(objs.values()) > 20, band.biome


def test_night_only_flag_is_on_moonpetal_only() -> None:
    assert [k for k, n in GAME.nodes.nodes.items() if n.night_only] == ["moonpetal"]
