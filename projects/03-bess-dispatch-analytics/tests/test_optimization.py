"""优化调度测试：求最优解后必须独立验证约束，不能只信任求解器状态。"""

from __future__ import annotations

import math

import pytest

from bess_model import BessParams
from optimization import (
    InfeasibleProblem,
    InvalidInput,
    OptimizationError,
    purchase_cost,
    solve_dispatch,
)
from scenario import (
    CHARGE_KW,
    DISCHARGE_KW,
    DT_H,
    INITIAL_ENERGY_KWH,
    LOAD_KW,
    PARAMS,
    PRICE_PER_KWH,
    build_fair_baseline,
    build_no_storage,
)
from simulation import simulate

TOL = 1e-6


def solve_baseline(**overrides):
    kwargs = dict(
        load_kw=LOAD_KW,
        price_per_kwh=PRICE_PER_KWH,
        params=PARAMS,
        initial_energy_kwh=INITIAL_ENERGY_KWH,
        dt_h=DT_H,
        terminal_energy_kwh=INITIAL_ENERGY_KWH,
    )
    kwargs.update(overrides)
    return solve_dispatch(**kwargs)


# 1. 求解成功且约束成立 ------------------------------------------------
def test_optimal_solution_satisfies_all_constraints():
    result = solve_baseline()

    assert "kOptimal" in result.solver_status
    assert len(result.charge_kw) == len(LOAD_KW) == 24

    for t in range(24):
        c, d, g = result.charge_kw[t], result.discharge_kw[t], result.grid_kw[t]
        assert c >= -TOL and d >= -TOL
        assert c <= PARAMS.p_charge_max_kw + TOL
        assert d <= PARAMS.p_discharge_max_kw + TOL
        assert not (c > TOL and d > TOL), f"第 {t} 时段同时充放电"
        assert g == pytest.approx(LOAD_KW[t] + c - d, abs=TOL)
        assert g >= -TOL
        assert PARAMS.usable_min_kwh - TOL <= result.energy_kwh[t] <= PARAMS.usable_max_kwh + TOL

    assert result.energy_end_kwh == pytest.approx(INITIAL_ENERGY_KWH, abs=TOL)


def test_solver_result_matches_independent_simulation():
    result = solve_baseline()
    # 用项目自己的物理模型重放最优策略，能通过就说明约束真的成立
    replay = simulate(
        PARAMS,
        INITIAL_ENERGY_KWH,
        LOAD_KW,
        result.charge_kw,
        result.discharge_kw,
        DT_H,
    )
    assert replay.final_energy_kwh == pytest.approx(result.energy_end_kwh, abs=TOL)
    for t, record in enumerate(replay.periods):
        assert record.grid_kw == pytest.approx(result.grid_kw[t], abs=TOL)


# 2. 成本口径 ----------------------------------------------------------
def test_reported_cost_equals_independent_cost():
    result = solve_baseline()
    independent = purchase_cost(result.grid_kw, PRICE_PER_KWH, DT_H)
    assert result.purchase_cost == pytest.approx(independent, abs=1e-9)


def test_optimised_cost_is_not_worse_than_fair_baseline():
    result = solve_baseline()

    no_storage = build_no_storage()
    fair = build_fair_baseline()
    cost_no_storage = purchase_cost([r.grid_kw for r in no_storage.periods], PRICE_PER_KWH, DT_H)
    cost_fair = purchase_cost([r.grid_kw for r in fair.periods], PRICE_PER_KWH, DT_H)

    assert fair.final_energy_kwh == pytest.approx(INITIAL_ENERGY_KWH, abs=TOL)
    assert cost_fair <= cost_no_storage + 1e-9
    assert result.purchase_cost <= cost_fair + 1e-6


# 3. 不可行不得伪造结果 -------------------------------------------------
def test_infeasible_terminal_energy_raises():
    with pytest.raises(InfeasibleProblem):
        solve_dispatch(
            load_kw=[10.0, 10.0],
            price_per_kwh=[1.0, 1.0],
            params=BessParams(
                e_max_kwh=100.0,
                p_charge_max_kw=20.0,
                p_discharge_max_kw=20.0,
                eta_charge=0.95,
                eta_discharge=0.95,
            ),
            initial_energy_kwh=50.0,
            dt_h=1.0,
            terminal_energy_kwh=95.0,  # 两步最多入池 38 kWh，达不到 95
        )


def test_infeasible_raises_before_returning_any_result():
    with pytest.raises(OptimizationError):
        solve_dispatch(
            load_kw=[0.0],
            price_per_kwh=[1.0],
            params=BessParams(e_max_kwh=100.0, p_charge_max_kw=20.0, p_discharge_max_kw=20.0),
            initial_energy_kwh=95.0,
            dt_h=1.0,
            terminal_energy_kwh=5.0,  # 一步内不可能从 95 放到 5
        )


# 4. 输入校验 ----------------------------------------------------------
def test_length_mismatch_raises():
    with pytest.raises(InvalidInput):
        solve_baseline(price_per_kwh=PRICE_PER_KWH[:-1])


@pytest.mark.parametrize(
    "bad",
    [
        {"load_kw": [-1.0] * 24},
        {"load_kw": [math.nan] * 24},
        {"price_per_kwh": [0.5] * 23 + [-0.5]},
        {"dt_h": 0.0},
        {"dt_h": -1.0},
        {"initial_energy_kwh": 99.0},
        {"terminal_energy_kwh": 1.0},
    ],
)
def test_invalid_inputs_raise(bad):
    with pytest.raises(InvalidInput):
        solve_baseline(**bad)


# 5. 互斥与可复现 ------------------------------------------------------
def test_no_simultaneous_charge_discharge_with_flat_prices():
    flat = tuple(0.5 for _ in range(24))
    result = solve_baseline(price_per_kwh=flat)
    for c, d in zip(result.charge_kw, result.discharge_kw):
        assert not (c > TOL and d > TOL)


def test_solution_is_reproducible():
    first = solve_baseline()
    second = solve_baseline()
    assert first.purchase_cost == pytest.approx(second.purchase_cost, abs=1e-9)
    assert tuple(round(v, 9) for v in first.charge_kw) == tuple(
        round(v, 9) for v in second.charge_kw
    )


def test_optimiser_never_charges_at_peak_price_and_discharges_only_at_peak():
    result = solve_baseline()
    max_price = max(PRICE_PER_KWH)

    charging_hours = [t for t, c in enumerate(result.charge_kw) if c > TOL]
    discharging_hours = [t for t, d in enumerate(result.discharge_kw) if d > TOL]

    assert charging_hours, "优化结果应至少在某些时段充电"
    assert discharging_hours, "优化结果应至少在某些时段放电"
    # 峰段充电必然亏钱，最优解不应出现
    assert all(PRICE_PER_KWH[t] < max_price for t in charging_hours)
    # 放电只发生在最高电价时段
    assert all(PRICE_PER_KWH[t] == max_price for t in discharging_hours)
