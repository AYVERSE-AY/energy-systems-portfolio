"""电价峰谷差 × 需量电价二维扫描测试。"""

from __future__ import annotations

import pytest

from run_price_demand_grid import RATES, SPREADS, run

@pytest.fixture(scope="module")
def rows():
    return run()


def test_grid_shape_and_status(rows):
    assert len(rows) == len(SPREADS) * len(RATES) == 16
    assert all(row["status"] == "ok" for row in rows)


def test_saving_increases_with_price_spread(rows):
    lookup = {(r["spread"], r["rate"]): r["saving_pct"] for r in rows}
    for rate in RATES:
        series = [lookup[(spread, rate)] for spread in SPREADS]
        assert series == sorted(series)


def test_saving_increases_with_demand_rate(rows):
    lookup = {(r["spread"], r["rate"]): r["saving_pct"] for r in rows}
    for spread in SPREADS:
        series = [lookup[(spread, rate)] for rate in RATES]
        assert series == sorted(series)


def test_demand_charge_lowers_peak_at_every_spread(rows):
    lookup = {(r["spread"], r["rate"]): r["peak_kw"] for r in rows}
    for spread in SPREADS:
        peak_without = lookup[(spread, 0.0)]
        for rate in RATES[1:]:
            assert lookup[(spread, rate)] < peak_without + 1e-6


def test_flat_price_without_demand_is_idle(rows):
    row = next(r for r in rows if r["spread"] == 0.0 and r["rate"] == 0.0)
    # 平坦电价下没有套利空间：峰值等于负荷峰值，节省仅来自避免规则损耗
    assert row["peak_kw"] == pytest.approx(80.0)
    assert row["saving_pct"] < 1.0
