from __future__ import annotations

import pytest

from hearthforge.config.loader import load_config
from hearthforge.core.profanity import username_problem
from hearthforge.settings import REPO_ROOT

pytestmark = pytest.mark.nodb
CFG = load_config(REPO_ROOT / "config").profanity


def problem(name: str) -> str | None:
    return username_problem(name, CFG, 3, 20)


@pytest.mark.parametrize(
    "name", ["Alex", "sam_the_smith", "Grapefruit99", "Cockatoo_Keeper", "Dickens", "Spicy"]
)
def test_ok_names(name: str) -> None:
    assert problem(name) is None


@pytest.mark.parametrize("name", ["fuck", "FuUuCk_you", "sh1tlord", "b1tch", "a$$hole", "Admin", "x_n4z1_x"])
def test_blocked_names(name: str) -> None:
    assert problem(name) is not None


@pytest.mark.parametrize("name", ["ab", "a" * 21, "has space", "emoji🙂", "_lead", "trail_", "dou__ble"])
def test_shape_rules(name: str) -> None:
    assert problem(name) is not None
