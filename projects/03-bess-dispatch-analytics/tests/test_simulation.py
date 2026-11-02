"""多时段仿真与基准场景测试（功率 kW、能量 kWh、步长 h）。"""

from __future__ import annotations

import math

import pytest

from bess_model import BessModel, BessParams, InfeasibleRequest
from scenario import CHARGE_KW, DISCHARGE_KW, DT_H, INITIAL_ENERGY_KWH, LOAD_KW, PARAMS, build_baseline
from simulation import InvalidSequence, simulate


def make_params(**overrides) -> BessParams:
    base = dict(
        e_max_kwh=100.0,
        p_charge_max_kw=20.0,
        p_discharge_max_kw=20.0,
        eta_charge=0.95,
        eta_discharge=0.95,
        soc_min_frac=0.05,
        soc_max_frac=0.95,
    )
    base.update(overrides)
    return BessParams(**base)


# 1. 多时段 SOC 连续递推 ------------------------------------------------
def test_soc_recursion_matches_sequential_model_steps():
    params = make_params()
    load = [10.0] * 6
    charge = [5.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    discharge = [0.0, 0.0, 3.0, 3.0, 0.0, 4.0]
    dt = 0.5

    result = simulate(params, 50.0, load, charge, discharge, dt)

    model = BessModel(params, initial_energy_kwh=50.0)
    for record, p_ch, p_dis in zip(result.periods, charge, discharge):
        expected = model.step(charge_kw=p_ch, discharge_kw=p_dis, dt_h=dt)
        assert record.energy_after_kwh == pytest.approx(expected.energy_after_kwh, rel=1e-12)
        assert record.soc_after == pytest.approx(model.soc, rel=1e-12)

    assert result.steps == 6


# 2. 序列长度校验 --------------------------------------------------------
def test_mismatched_lengths_raise():
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, [10.0] * 4, [1.0] * 3, [0.0] * 4, 1.0)
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, [10.0] * 4, [1.0] * 4, [0.0] * 3, 1.0)


def test_empty_sequence_raises():
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, [], [], [], 1.0)


# 3. 时间步长校验 --------------------------------------------------------
@pytest.mark.parametrize("dt", [0.0, -1.0, math.nan, math.inf])
def test_invalid_dt_raises(dt):
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, [10.0, 10.0], [0.0, 0.0], [0.0, 0.0], dt)


def test_non_hourly_dt_is_supported():
    params = make_params()
    # 15 分钟步长：4 步 = 1 小时；充电 8 kW 共 1 h，入池 0.95 * 8 * 1 = 7.6 kWh
    result = simulate(params, 50.0, [0.0] * 4, [8.0] * 4, [0.0] * 4, 0.25)

    assert result.steps == 4
    assert result.charged_from_grid_kwh == pytest.approx(8.0, rel=1e-12)
    assert result.battery_delta_kwh == pytest.approx(0.95 * 8.0, rel=1e-12)
    assert result.final_energy_kwh == pytest.approx(57.6, rel=1e-12)


# 4. 电网侧功率平衡 ------------------------------------------------------
def test_grid_side_power_balance_holds_each_period():
    result = build_baseline()
    for record in result.periods:
        assert record.grid_kw == pytest.approx(
            record.load_kw + record.charge_kw - record.discharge_kw, rel=1e-12
        )
        assert record.grid_kw >= 0.0


def test_grid_balance_sums_match_battery_and_losses():
    result = build_baseline()
    net_grid = result.charged_from_grid_kwh - result.discharged_to_grid_kwh

    # 电网净充电量 = 电池能量变化 + 转换损耗
    assert net_grid == pytest.approx(result.battery_delta_kwh + result.losses_kwh, rel=1e-12)
    # 效率 < 1 时，电网净量不能直接当作电池能量变化
    assert result.battery_delta_kwh != pytest.approx(net_grid, rel=1e-3)


# 5. 效率相关的能量变化 --------------------------------------------------
def test_battery_delta_accounts_for_efficiency():
    params = make_params()
    result = simulate(params, 50.0, [0.0] * 2, [10.0, 0.0], [0.0, 10.0], 1.0)

    expected_delta = params.eta_charge * 10.0 - 10.0 / params.eta_discharge
    assert result.battery_delta_kwh == pytest.approx(expected_delta, rel=1e-12)
    # 往返后储能量下降，但电网侧只看到 10 kWh 进、10 kWh 出
    assert result.charged_from_grid_kwh == pytest.approx(10.0, rel=1e-12)
    assert result.discharged_to_grid_kwh == pytest.approx(10.0, rel=1e-12)
    # 电网侧净量 = 10 - 10 = 0，全部差值是转换损耗
    net_grid = result.charged_from_grid_kwh - result.discharged_to_grid_kwh
    assert net_grid == pytest.approx(0.0, abs=1e-12)
    assert result.losses_kwh == pytest.approx(net_grid - expected_delta, rel=1e-12)


# 6. SOC 与功率边界 ------------------------------------------------------
def test_soc_bounds_are_enforced_across_periods():
    params = make_params()
    # 从 90 kWh 起连续大功率充电，第二步必然越过 95 kWh 上限
    with pytest.raises(InfeasibleRequest):
        simulate(params, 90.0, [0.0] * 3, [10.0] * 3, [0.0] * 3, 1.0)

    # 从 6 kWh 起连续放电，第二步跌破 5 kWh 下限
    with pytest.raises(InfeasibleRequest):
        simulate(params, 6.0, [0.0] * 3, [0.0] * 3, [10.0] * 3, 1.0)


def test_power_limit_is_enforced():
    with pytest.raises(InfeasibleRequest):
        simulate(make_params(), 50.0, [10.0], [25.0], [0.0], 1.0)
    with pytest.raises(InfeasibleRequest):
        simulate(make_params(), 50.0, [10.0], [0.0], [25.0], 1.0)


def test_simultaneous_charge_discharge_is_rejected():
    with pytest.raises(InfeasibleRequest):
        simulate(make_params(), 50.0, [10.0], [5.0], [5.0], 1.0)


# 7. 非法输入 -----------------------------------------------------------
@pytest.mark.parametrize(
    "bad_series",
    [
        [-1.0, 10.0],
        [math.nan, 10.0],
        [math.inf, 10.0],
    ],
)
def test_invalid_load_values_raise(bad_series):
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, bad_series, [0.0, 0.0], [0.0, 0.0], 1.0)


def test_negative_power_series_raise():
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, [0.0], [-1.0], [0.0], 1.0)
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, [0.0], [0.0], [-1.0], 1.0)


def test_non_numeric_series_raise():
    with pytest.raises(InvalidSequence):
        simulate(make_params(), 50.0, ["10"], [0.0], [0.0], 1.0)  # type: ignore[list-item]


# 8. 基准场景 -----------------------------------------------------------
def test_baseline_scenario_shape_and_inputs():
    assert len(LOAD_KW) == len(CHARGE_KW) == len(DISCHARGE_KW) == 24
    assert DT_H == 1.0
    assert INITIAL_ENERGY_KWH == 50.0

    result = build_baseline()
    assert result.steps == 24
    assert result.dt_h == pytest.approx(1.0)

    low = PARAMS.usable_min_kwh
    high = PARAMS.usable_max_kwh
    for record in result.periods:
        assert low - 1e-9 <= record.energy_after_kwh <= high + 1e-9
        assert record.charge_kw <= PARAMS.p_charge_max_kw
        assert record.discharge_kw <= PARAMS.p_discharge_max_kw
        assert not (record.charge_kw > 0 and record.discharge_kw > 0)


def test_baseline_totals_and_soc_window():
    result = build_baseline()

    assert result.charged_from_grid_kwh == pytest.approx(42.0, rel=1e-12)   # 6 h x 7 kW
    assert result.discharged_to_grid_kwh == pytest.approx(48.0, rel=1e-12)  # 4 h x 12 kW
    assert result.final_energy_kwh == pytest.approx(39.37368421052632, rel=1e-12)
    assert result.energy_max_kwh == pytest.approx(89.9, rel=1e-12)
    assert result.energy_min_kwh == pytest.approx(result.final_energy_kwh, rel=1e-12)
    # 首末 SOC 不相等（本基线不强制日终 SOC 回到初值）
    assert result.final_energy_kwh != pytest.approx(INITIAL_ENERGY_KWH, rel=1e-3)


def test_baseline_is_reproducible():
    first = build_baseline()
    second = build_baseline()
    assert first.to_rows() == second.to_rows()
    assert first.battery_delta_kwh == second.battery_delta_kwh
    assert first.losses_kwh == second.losses_kwh
