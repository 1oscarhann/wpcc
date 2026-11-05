"""Phase 7 maths: P1 population-scaled prices, soft caps, rounding, trends, sparklines, merchant rotation."""

from __future__ import annotations

import math
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hearthforge.config.loader import ConfigError, GameConfig, load_config
from hearthforge.domain import market as dom
from hearthforge.settings import REPO_ROOT

pytestmark = pytest.mark.nodb


def test_price_curve_matches_balance_doc(game_config: GameConfig) -> None:
    m = game_config.market
    bl = dom.baseline(m, "wood", 1)
    assert bl == 400 * 20  # below min_population the floor applies (P1)
    mult = [dom.price_mult(u, bl, 0.6, m.defaults.clamp) for u in (0, bl, 2 * bl, 3 * bl)]
    assert [round(x, 2) for x in mult] == [1.82, 1.0, 0.55, 0.4]  # BALANCE §8.1
    assert dom.price_mult(1e12, bl, 0.6, (0.4, 2.5)) == 0.4
    assert dom.price_mult(0, bl, 5.0, (0.4, 2.5)) == 2.5


def test_baseline_scales_with_population(game_config: GameConfig) -> None:
    """The P1 failure: a fixed baseline pins prices to the ceiling for 12 players and the floor for 5,000.
    Scaled, 'everyone sells a normal amount' prices at ×1.0 for any population."""
    m = game_config.market
    for players in (20, 300, 5000):
        normal = m.items["wood"].baseline * players
        p, _ = dom.price(m, "wood", normal, players)
        assert p == pytest.approx(m.items["wood"].base)


def test_payout_soft_cap_and_rounding() -> None:
    p = dom.payout(3.644, 0.02, 50, 0, 2000, 0.5)
    assert p.coins == math.floor(3.644 * 1.02 * 50) and p.over_units == 0
    p = dom.payout(10.0, 0.0, 30, 15, 40, 0.5)  # 25 at full, 5 past the cap at half
    assert (p.full_units, p.over_units, p.coins) == (25, 5, 275)
    p = dom.payout(10.0, 0.0, 10, 50, 40, 0.5)  # already over the cap
    assert (p.full_units, p.coins) == (0, 50)
    # selling one at a time never beats one big sale
    unit, n = 0.8, 25
    singles = sum(dom.payout(unit, 0.0, 1, i, 1000, 0.5).coins for i in range(n))
    assert singles <= dom.payout(unit, 0.0, n, 0, 1000, 0.5).coins


def test_buckets_trend_sparkline() -> None:
    t = datetime(2026, 1, 1, 12, 7, 33, tzinfo=UTC)
    assert dom.bucket_start(t, 600) == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    hist = [(now - timedelta(hours=h), 10.0 - h * 0.1) for h in range(24, 0, -1)]
    direction, change = dom.trend(hist, 10.0, now, 3600, 0.03)
    assert direction == 0 and change == pytest.approx(0.1 / 9.9, rel=1e-3)
    assert dom.trend(hist, 12.0, now, 3600, 0.03)[0] == 1
    assert dom.trend(hist, 8.0, now, 3600, 0.03)[0] == -1
    assert dom.trend([], 8.0, now, 3600, 0.03) == (0, 0.0)
    line = dom.sparkline(hist, 10.0, now, 86400, 24)
    assert len(line) == 24 and line[-1] == 10.0 and line[0] <= line[-2] <= line[-1]
    assert dom.sparkline([], 4.2, now, 86400, 24) == [4.2]


def test_merchant_rotation_is_seeded(game_config: GameConfig) -> None:
    mc = game_config.merchant
    a = dom.rotation(mc, "hub:abc", 1000)
    assert a == dom.rotation(mc, "hub:abc", 1000)  # same input, same cart
    assert len(a.slots) == mc.slots and len({s.stock_key for s in a.slots}) == mc.slots
    assert sum(s.deal for s in a.slots) == 1
    deal = next(s for s in a.slots if s.deal)
    assert deal.price < mc.stock[deal.stock_key].price
    rots = [dom.rotation(mc, "hub:abc", i) for i in range(1000, 1012)]
    assert len({tuple(s.stock_key for s in r.slots) for r in rots}) > 6  # stock actually rotates
    assert all(a.spot != b.spot for a, b in zip(rots, rots[1:], strict=False))  # she wanders
    assert rots[1].starts_at == rots[0].ends_at
    assert rots[0].ends_at - rots[0].starts_at == timedelta(seconds=mc.rotation)
    now = rots[3].starts_at + timedelta(minutes=5)
    assert dom.rotation_index(mc, now) == 1003


def test_loader_rejects_merchant_arbitrage(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", cfg_dir)
    p = cfg_dir / "merchant.yaml"
    p.write_text(p.read_text().replace("qty: 10, price: 680", "qty: 10, price: 300"))
    with pytest.raises(ConfigError, match="no-arbitrage"):
        load_config(cfg_dir)


def test_loader_checks_market_items(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", cfg_dir)
    p = cfg_dir / "market.yaml"
    p.write_text(
        p.read_text().replace("  wood:  ", "  spear:  ", 1).replace("wood:        {", "spear:       {")
    )
    with pytest.raises(ConfigError, match="only stackable goods"):
        load_config(cfg_dir)
