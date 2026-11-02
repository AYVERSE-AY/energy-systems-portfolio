"""敏感性分析测试：每个场景必须经求解器求解并通过物理模型复核。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bess_model import BessParams
from scenario import DT_H, INITIAL_ENERGY_KWH, LOAD_KW, PARAMS, PRICE_PER_KWH
from sensitivity import Scenario, build_scenarios, build_two_factor_scenarios, run_all, run_scenario, run_two_factor


@pytest.fixture(scope="module")
def results():
    return run_all()


# 1. 场景定义：单因素、其余保持不变 --------------------------------
def test_scenario_grid_shape_and_single_factor():
    scenarios = build_scenarios()
    assert len(scenarios) == 16
    assert {s.family for s in scenarios} == {"efficiency", "capacity", "power", "price_spread"}

    for scenario in scenarios:
        assert len(scenario.prices) == 24
        assert scenario.params.e_max_kwh >= 60.0  # 保证 50 kWh 落在 5%-95% 窗口内
        assert scenario.params.soc_min_frac == PARAMS.soc_min_frac
        assert scenario.params.soc_max_frac == PARAMS.soc_max_frac

    base = [s for s in scenarios if s.family == "efficiency" and s.label == "eta=0.95"][0]
    assert base.params.eta_charge == 0.95
    assert base.prices == PRICE_PER_KWH


# 2. 全部场景求解成功并通过复核 ------------------------------------
def test_all_scenarios_solved_and_validated(results):
    assert len(results) == 16
    for row in results:
        assert row["status"] == "ok", f"{row['case']}: {row['status']} {row['check']}"
        assert row["check"] == "ok"
        assert row["cost_yuan"] is not None


# 3. 效率单调性 ------------------------------------------------------
def test_cost_decreases_with_efficiency(results):
    rows = [r for r in results if r["family"] == "efficiency"]
    costs = [r["cost_yuan"] for r in rows]
    assert costs == sorted(costs, reverse=True)
    assert costs[0] > costs[-1]


# 4. 容量单调性 ------------------------------------------------------
def test_cost_decreases_with_capacity(results):
    rows = [r for r in results if r["family"] == "capacity"]
    costs = [r["cost_yuan"] for r in rows]
    assert costs == sorted(costs, reverse=True)


# 5. 功率上限单调性（不超过即封顶） ----------------------------------
def test_cost_is_non_increasing_with_power_limit(results):
    rows = [r for r in results if r["family"] == "power"]
    costs = [r["cost_yuan"] for r in rows]
    assert all(a >= b - 1e-9 for a, b in zip(costs, costs[1:]))


# 6. 峰谷差越大，节省越多 --------------------------------------------
def test_saving_grows_with_price_spread(results):
    rows = [r for r in results if r["family"] == "price_spread"]
    savings = [r["saving_yuan"] for r in rows]
    assert savings == sorted(savings)


# 7. 平坦电价时优化应退化为不动作 ------------------------------------
def test_flat_price_makes_optimiser_idle():
    flat = tuple(0.65 for _ in range(24))
    scenario = Scenario("price_spread", "flat", PARAMS, flat)
    row = run_scenario(scenario)
    assert row["status"] == "ok"

    no_storage_cost = 0.65 * sum(LOAD_KW) * DT_H
    assert row["cost_yuan"] == pytest.approx(no_storage_cost, abs=0.01)
    assert row["charged_kwh"] == pytest.approx(0.0, abs=0.01)


# 8. 不可行场景不得伪造数值 ------------------------------------------
def test_invalid_scenario_reports_failure_without_numbers():
    too_small = BessParams(
        e_max_kwh=52.0,  # 95% x 52 = 49.4 kWh < 初始 50 kWh
        p_charge_max_kw=20.0,
        p_discharge_max_kw=20.0,
        eta_charge=0.95,
        eta_discharge=0.95,
    )
    row = run_scenario(Scenario("capacity", "e_max=52kWh", too_small, PRICE_PER_KWH))
    assert row["status"] != "ok"
    assert row["cost_yuan"] is None
    assert row["saving_yuan"] is None


# 9. 初始/期末约束在所有场景保持一致 ---------------------------------
def test_initial_energy_is_fixed_across_scenarios():
    for scenario in build_scenarios():
        assert scenario.params.usable_min_kwh <= INITIAL_ENERGY_KWH <= scenario.params.usable_max_kwh
    assert DT_H == 1.0


# 10. 容量 x 功率二维网格 --------------------------------------------
@pytest.fixture(scope="module")
def two_factor():
    return run_two_factor()


def test_two_factor_grid_shape(two_factor):
    assert len(two_factor) == 16
    assert len(build_two_factor_scenarios()) == 16
    assert all(row["status"] == "ok" and row["check"] == "ok" for row in two_factor)


def test_two_factor_is_monotone_in_both_directions(two_factor):
    lookup = {row["case"]: row["cost_yuan"] for row in two_factor}
    capacities = (60, 100, 150, 200)
    powers = (10, 20, 30, 40)
    for power in powers:
        costs = [lookup[f"e={e}kWh,p={power}kW"] for e in capacities]
        assert costs == sorted(costs, reverse=True)
    for capacity in capacities:
        costs = [lookup[f"e={capacity}kWh,p={p}kW"] for p in powers]
        assert all(a >= b - 1e-9 for a, b in zip(costs, costs[1:]))


def test_small_capacity_saturates_beyond_30kw(two_factor):
    lookup = {row["case"]: row["cost_yuan"] for row in two_factor}
    assert lookup["e=100kWh,p=30kW"] == pytest.approx(lookup["e=100kWh,p=40kW"], abs=0.01)
    # 容量足够大时功率仍能继续带来收益
    assert lookup["e=200kWh,p=40kW"] < lookup["e=200kWh,p=30kW"] - 0.01
