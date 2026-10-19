"""Test logic tổng hợp multi-region: phân biệt sập thật vs lỗi đường mạng."""
from __future__ import annotations

import pytest

from app.checkers.base import CheckOutcome
from app.regions import RegionResult, RegionVerdict, aggregate_regions

UP = lambda ms=100.0: CheckOutcome.up(response_time_ms=ms)  # noqa: E731
DOWN = CheckOutcome.down(error="refused")


def _r(**kw) -> list[RegionResult]:
    return [RegionResult(region=k, outcome=v) for k, v in kw.items()]


def test_all_regions_up():
    agg = aggregate_regions(_r(hanoi=UP(100), sg=UP(200), us=UP(300)))
    assert agg.verdict == RegionVerdict.UP
    assert agg.outcome.is_up
    assert agg.outcome.response_time_ms == 200.0  # trung bình


def test_all_regions_down_is_real_outage():
    agg = aggregate_regions(_r(hanoi=DOWN, sg=DOWN, us=DOWN))
    assert agg.verdict == RegionVerdict.DOWN
    assert not agg.outcome.is_up
    assert set(agg.failed_regions) == {"hanoi", "sg", "us"}


def test_one_region_down_is_degraded_not_outage():
    """Chỉ 1 khu vực lỗi -> nghi lỗi đường mạng, KHÔNG coi là sập."""
    agg = aggregate_regions(_r(hanoi=DOWN, sg=UP(150), us=UP(250)))
    assert agg.verdict == RegionVerdict.DEGRADED
    assert agg.outcome.is_up  # web vẫn tới được -> engine không báo SẬP
    assert agg.failed_regions == ["hanoi"]


def test_threshold_makes_it_sensitive():
    """Hạ ngưỡng xuống 2 -> 2/3 khu vực lỗi là coi sập."""
    agg = aggregate_regions(
        _r(hanoi=DOWN, sg=DOWN, us=UP(250)), min_down_for_outage=2
    )
    assert agg.verdict == RegionVerdict.DOWN
    assert not agg.outcome.is_up


def test_empty_raises():
    with pytest.raises(ValueError):
        aggregate_regions([])
