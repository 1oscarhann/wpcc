from __future__ import annotations

import pytest

from hearthforge.config.loader import load_config
from hearthforge.domain.placement import (
    Placed,
    Rect,
    limit_errors,
    placement_errors,
    rotated_footprint,
    touches,
)
from hearthforge.settings import REPO_ROOT

pytestmark = pytest.mark.nodb
CFG = load_config(REPO_ROOT / "config")
POND = CFG.mapgen.plot.pond  # x 10..15, y 33..36 in frame coords; start square is 8..39


def errs(key: str, x: int, y: int, rot: int = 0, existing=(), ignore=None, size=32, debris=()) -> list[str]:  # noqa: ANN001
    return placement_errors(
        CFG, key, x, y, rot, size=size, existing=list(existing), ignore_id=ignore, debris=list(debris)
    )


def test_rotation_swaps_non_square_footprints() -> None:
    assert rotated_footprint((3, 2), 0) == (3, 2)
    assert rotated_footprint((3, 2), 1) == (2, 3)
    assert rotated_footprint((3, 2), 2) == (3, 2)
    assert rotated_footprint((2, 2), 3) == (2, 2)


def test_valid_spot() -> None:
    assert errs("lumber_camp", 27, 12) == []


@pytest.mark.parametrize(("x", "y"), [(7, 20), (38, 20), (20, 7), (20, 38), (0, 0)])
def test_out_of_bounds(x: int, y: int) -> None:
    assert "out_of_bounds" in errs("lumber_camp", x, y)


def test_bigger_plot_allows_more_room() -> None:
    assert "out_of_bounds" in errs("lumber_camp", 6, 20)
    assert errs("lumber_camp", 6, 20, size=36) == []


def test_overlap_and_ignore_self_when_moving() -> None:
    house = Placed("h1", "house", Rect(20, 20, 3, 3))
    assert "overlap" in errs("lumber_camp", 21, 21, existing=[house])
    assert errs("house", 21, 21, existing=[house], ignore="h1") == []


def test_cannot_build_on_pond() -> None:
    assert "on_water" in errs("house", POND.x, POND.y)


def test_dock_needs_water() -> None:
    assert "needs_water" in errs("fishing_dock", 27, 12)
    # 3×4 dock right of the pond, touching its east edge
    assert errs("fishing_dock", POND.x + POND.w, POND.y - 1) == []
    # rotated (4×3) dock directly above the pond
    assert errs("fishing_dock", POND.x, POND.y - 3, rot=1) == []


def test_debris_blocks() -> None:
    assert errs("house", 27, 12, debris=[(28, 13)]) == ["debris"]
    assert errs("house", 27, 12, debris=[(30, 13)]) == []


def test_touches_is_edge_only() -> None:
    a = Rect(0, 0, 2, 2)
    assert touches(Rect(2, 0, 1, 1), a)
    assert not touches(Rect(2, 2, 1, 1), a)  # diagonal only
    assert not touches(Rect(1, 1, 1, 1), a)  # overlapping


def test_limits() -> None:
    assert limit_errors(CFG, "mine", 1, 0) == ["locked"]
    assert limit_errors(CFG, "mine", 2, 0) == []
    assert limit_errors(CFG, "lumber_camp", 1, 1) == ["limit_reached"]
    assert limit_errors(CFG, "lumber_camp", 2, 1) == []
