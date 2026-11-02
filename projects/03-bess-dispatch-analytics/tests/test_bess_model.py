"""单步 BESS 模型的边界测试（能量单位 kWh，功率 kW，时间 h）。"""

from __future__ import annotations

import math

import pytest

from bess_model import (
    BessModel,
    BessParams,
    InfeasibleRequest,
    InvalidParameter,
    Mode,
)


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


# 1. 正常充电 -------------------------------------------------------------
def test_normal_charge_uses_charge_efficiency():
    model = BessModel(make_params(), initial_energy_kwh=50.0)
    result = model.step(charge_kw=10.0, dt_h=1.0)

    assert result.mode is Mode.CHARGE
    assert result.energy_after_kwh == pytest.approx(59.5, rel=1e-12)
    assert result.energy_delta_kwh == pytest.approx(9.5, rel=1e-12)
    assert model.energy_kwh == pytest.approx(59.5, rel=1e-12)
    assert model.soc == pytest.approx(0.595, rel=1e-12)


# 2. 正常放电 -------------------------------------------------------------
def test_normal_discharge_divides_by_discharge_efficiency():
    model = BessModel(make_params(), initial_energy_kwh=50.0)
    result = model.step(discharge_kw=10.0, dt_h=1.0)

    assert result.mode is Mode.DISCHARGE
    expected = 50.0 - 10.0 / 0.95
    assert result.energy_after_kwh == pytest.approx(expected, rel=1e-12)
    assert model.energy_kwh == pytest.approx(expected, rel=1e-12)


# 3. 待机 ---------------------------------------------------------------
def test_idle_keeps_energy_unchanged():
    model = BessModel(make_params(), initial_energy_kwh=42.0)
    result = model.step(dt_h=0.25)

    assert result.mode is Mode.IDLE
    assert result.energy_after_kwh == pytest.approx(42.0, abs=0.0)
    assert result.energy_delta_kwh == 0.0


# 4. SOC 上限 -----------------------------------------------------------
def test_charge_beyond_upper_soc_is_rejected():
    model = BessModel(make_params(), initial_energy_kwh=90.0)
    with pytest.raises(InfeasibleRequest):
        model.step(charge_kw=10.0, dt_h=1.0)
    assert model.energy_kwh == pytest.approx(90.0, abs=0.0)  # 状态未被破坏


def test_charge_filling_to_upper_soc_is_exact_and_then_rejects():
    params = make_params()
    model = BessModel(params, initial_energy_kwh=90.0)
    fill_kw = (params.usable_max_kwh - 90.0) / (params.eta_charge * 1.0)

    result = model.step(charge_kw=fill_kw, dt_h=1.0)
    assert result.energy_after_kwh == pytest.approx(params.usable_max_kwh, rel=1e-12)

    with pytest.raises(InfeasibleRequest):
        model.step(charge_kw=0.1, dt_h=1.0)


# 5. SOC 下限 -----------------------------------------------------------
def test_discharge_below_lower_soc_is_rejected():
    model = BessModel(make_params(), initial_energy_kwh=6.0)
    with pytest.raises(InfeasibleRequest):
        model.step(discharge_kw=10.0, dt_h=1.0)
    assert model.energy_kwh == pytest.approx(6.0, abs=0.0)


def test_discharge_to_lower_soc_is_exact_and_then_rejects():
    params = make_params()
    model = BessModel(params, initial_energy_kwh=6.0)
    drain_kw = (6.0 - params.usable_min_kwh) * params.eta_discharge / 1.0

    result = model.step(discharge_kw=drain_kw, dt_h=1.0)
    assert result.energy_after_kwh == pytest.approx(params.usable_min_kwh, rel=1e-12)

    with pytest.raises(InfeasibleRequest):
        model.step(discharge_kw=0.1, dt_h=1.0)


# 6. 功率上限 -----------------------------------------------------------
def test_power_limits_are_enforced():
    model = BessModel(make_params(), initial_energy_kwh=50.0)
    with pytest.raises(InfeasibleRequest):
        model.step(charge_kw=20.5, dt_h=1.0)
    with pytest.raises(InfeasibleRequest):
        model.step(discharge_kw=20.5, dt_h=1.0)


def test_headroom_helpers_never_exceed_nameplate_power():
    params = make_params()
    model = BessModel(params, initial_energy_kwh=50.0)
    assert model.max_charge_kw(dt_h=0.25) == pytest.approx(20.0, rel=1e-12)
    assert model.max_discharge_kw(dt_h=0.25) == pytest.approx(20.0, rel=1e-12)

    # 用 helper 计算出的功率必须刚好可行，且不越 SOC 上限
    fresh = BessModel(params, initial_energy_kwh=90.0)
    kw = fresh.max_charge_kw(dt_h=1.0)
    assert 0.0 < kw < 20.0
    result = fresh.step(charge_kw=kw, dt_h=1.0)
    assert result.energy_after_kwh == pytest.approx(params.usable_max_kwh, rel=1e-9)


# 7. 效率 -------------------------------------------------------------
def test_round_trip_efficiency_matches_product():
    params = make_params(eta_charge=0.95, eta_discharge=0.90)
    model = BessModel(params, initial_energy_kwh=50.0)

    model.step(charge_kw=10.0, dt_h=1.0)  # 存进 9.5 kWh
    assert model.energy_kwh == pytest.approx(59.5, rel=1e-12)

    result = model.step(discharge_kw=10.0, dt_h=1.0)  # 取走 10/0.90 kWh
    assert result.energy_after_kwh == pytest.approx(59.5 - 10.0 / 0.90, rel=1e-12)
    assert params.eta_roundtrip == pytest.approx(0.855, rel=1e-12)


def test_round_trip_returns_the_same_energy_with_symmetric_power():
    params = make_params(eta_charge=0.95, eta_discharge=0.95)
    model = BessModel(params, initial_energy_kwh=50.0)

    model.step(charge_kw=1.0, dt_h=1.0)  # 电网购 1 kWh，入池 0.95 kWh
    assert model.energy_kwh == pytest.approx(50.95, rel=1e-12)

    out_kw = params.eta_roundtrip * 1.0  # 电网可取回 0.9025 kWh
    assert out_kw == pytest.approx(0.9025, rel=1e-12)
    model.step(discharge_kw=out_kw, dt_h=1.0)
    # 出池 0.9025 / 0.95 = 0.95 kWh，储能量回到初始值
    assert model.energy_kwh == pytest.approx(50.0, rel=1e-12)


# 8. 禁止同时充放电 -----------------------------------------------------
def test_simultaneous_charge_and_discharge_is_rejected():
    model = BessModel(make_params(), initial_energy_kwh=50.0)
    with pytest.raises(InfeasibleRequest):
        model.step(charge_kw=5.0, discharge_kw=5.0, dt_h=1.0)
    assert model.energy_kwh == pytest.approx(50.0, abs=0.0)


# 9. 零容量退化 ---------------------------------------------------------
def test_zero_capacity_only_allows_idle():
    params = make_params(e_max_kwh=0.0)
    model = BessModel(params, initial_energy_kwh=0.0)

    assert model.soc == 0.0
    assert model.max_charge_kw() == 0.0
    assert model.max_discharge_kw() == 0.0

    result = model.step(dt_h=0.25)
    assert result.mode is Mode.IDLE
    assert result.energy_after_kwh == 0.0

    with pytest.raises(InfeasibleRequest):
        model.step(charge_kw=1.0, dt_h=0.25)


# 10. 非法参数与无效请求 ------------------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        {"eta_charge": 0.0},
        {"eta_charge": 1.2},
        {"eta_discharge": -0.1},
        {"e_max_kwh": -1.0},
        {"p_charge_max_kw": -5.0},
        {"soc_min_frac": 0.9, "soc_max_frac": 0.1},
        {"soc_max_frac": 1.5},
    ],
)
def test_invalid_parameters_raise(overrides):
    with pytest.raises(InvalidParameter):
        make_params(**overrides)


def test_non_finite_parameters_raise():
    with pytest.raises(InvalidParameter):
        make_params(e_max_kwh=math.nan)
    with pytest.raises(InvalidParameter):
        make_params(eta_charge=math.inf)


def test_invalid_requests_raise():
    model = BessModel(make_params(), initial_energy_kwh=50.0)
    with pytest.raises(InvalidParameter):
        model.step(charge_kw=-1.0)
    with pytest.raises(InvalidParameter):
        model.step(discharge_kw=math.nan)
    with pytest.raises(InvalidParameter):
        model.step(charge_kw=1.0, dt_h=0.0)
    with pytest.raises(InvalidParameter):
        model.step(charge_kw=1.0, dt_h=-0.25)


def test_initial_energy_outside_window_raises():
    with pytest.raises(InvalidParameter):
        BessModel(make_params(), initial_energy_kwh=99.0)
    with pytest.raises(InvalidParameter):
        BessModel(make_params(), initial_energy_kwh=-1.0)
