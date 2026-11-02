"""需量电费场景测试：目标含峰值项后仍需满足全部物理约束。"""

from __future__ import annotations

import pytest

from optimization import InvalidInput, solve_dispatch
from scenario import DT_H, INITIAL_ENERGY_KWH, LOAD_KW, PARAMS, PRICE_PER_KWH
from simulation import simulate


def solve(rate: float = 0.0):
    return solve_dispatch(
        LOAD_KW,
        PRICE_PER_KWH,
        PARAMS,
        INITIAL_ENERGY_KWH,
        DT_H,
        INITIAL_ENERGY_KWH,
        demand_charge_per_kw=rate,
    )


# 1. 成本构成 ----------------------------------------------------------
def test_total_cost_equals_energy_plus_demand():
    rate = 3.0
    result = solve(rate)
    peak = max(result.grid_kw)

    assert result.peak_grid_kw == pytest.approx(peak, abs=1e-9)
    assert result.demand_charge_cost == pytest.approx(rate * peak, abs=1e-6)
    assert result.total_cost == pytest.approx(result.purchase_cost + result.demand_charge_cost, abs=1e-6)


def test_zero_rate_matches_energy_only_objective():
    energy_only = solve(0.0)
    assert energy_only.demand_charge_cost == 0.0
    assert energy_only.total_cost == pytest.approx(energy_only.purchase_cost, abs=1e-9)
    assert energy_only.purchase_cost == pytest.approx(898.943947, abs=1e-4)


# 2. 峰荷被压低 --------------------------------------------------------
def test_demand_charge_lowers_peak():
    energy_only = solve(0.0)
    demand_aware = solve(3.0)

    assert demand_aware.peak_grid_kw < energy_only.peak_grid_kw - 1.0
    assert demand_aware.peak_grid_kw == pytest.approx(max(demand_aware.grid_kw), abs=1e-9)


def test_demand_aware_solution_beats_energy_only_schedule_under_same_rate():
    rate = 3.0
    energy_only = solve(0.0)
    demand_aware = solve(rate)

    energy_only_total = energy_only.purchase_cost + rate * max(energy_only.grid_kw)
    assert demand_aware.total_cost <= energy_only_total + 1e-6


def test_total_cost_grows_with_demand_rate():
    totals = [solve(rate).total_cost for rate in (0.0, 1.0, 3.0, 6.0)]
    assert totals == sorted(totals)


# 3. 物理约束仍然成立 --------------------------------------------------
def test_demand_aware_solution_is_physically_feasible():
    result = solve(6.0)
    replay = simulate(
        PARAMS,
        INITIAL_ENERGY_KWH,
        LOAD_KW,
        result.charge_kw,
        result.discharge_kw,
        DT_H,
    )
    assert replay.final_energy_kwh == pytest.approx(INITIAL_ENERGY_KWH, abs=1e-6)

    for t in range(len(LOAD_KW)):
        c, d = result.charge_kw[t], result.discharge_kw[t]
        assert c <= PARAMS.p_charge_max_kw + 1e-6
        assert d <= PARAMS.p_discharge_max_kw + 1e-6
        assert not (c > 1e-6 and d > 1e-6)
        assert PARAMS.usable_min_kwh - 1e-6 <= result.energy_kwh[t] <= PARAMS.usable_max_kwh + 1e-6
        assert result.grid_kw[t] >= -1e-6


# 4. 非法输入 ----------------------------------------------------------
@pytest.mark.parametrize("rate", [-1.0, float("nan")])
def test_invalid_demand_rate_raises(rate):
    with pytest.raises(InvalidInput):
        solve(rate)
