"""年收益与静态回收期测试（示意投资假设，非市场数据）。"""

from __future__ import annotations

import pytest

from economics import (
    EconomicsInputError,
    annualize,
    breakeven_unit_capex,
    capex_for,
    evaluate_baseline_case,
    payback_for_saving,
    report,
)
from scenario import PARAMS


def test_annual_saving_scales_with_days():
    result = annualize(10.0, 10_000.0, days_per_year=365)
    assert result.annual_saving_yuan == pytest.approx(3650.0)
    assert result.payback_years == pytest.approx(10_000.0 / 3650.0)


def test_payback_is_capex_over_annual_saving():
    result = annualize(17.1606, 126_000.0)
    assert result.annual_saving_yuan == pytest.approx(17.1606 * 365)
    assert result.payback_years == pytest.approx(126_000.0 / (17.1606 * 365))


def test_zero_or_negative_saving_has_no_payback():
    assert annualize(0.0, 1000.0).payback_years is None
    assert annualize(-5.0, 1000.0).payback_years is None


def test_capex_uses_both_capacity_and_power():
    capex = capex_for(PARAMS, capex_per_kwh=1000.0, capex_per_kw=200.0)
    expected = PARAMS.e_max_kwh * 1000.0 + max(
        PARAMS.p_charge_max_kw, PARAMS.p_discharge_max_kw
    ) * 200.0
    assert capex == pytest.approx(expected)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"capex_per_kwh": -1.0},
        {"capex_per_kw": -1.0},
    ],
)
def test_negative_unit_cost_raises(kwargs):
    with pytest.raises(EconomicsInputError):
        capex_for(PARAMS, **kwargs)


def test_invalid_days_and_capex_raise():
    with pytest.raises(EconomicsInputError):
        annualize(10.0, 1000.0, days_per_year=0)
    with pytest.raises(EconomicsInputError):
        annualize(10.0, -1.0)


def test_baseline_case_numbers():
    result = evaluate_baseline_case()
    assert result.daily_saving_yuan == pytest.approx(17.1606)
    assert result.annual_saving_yuan == pytest.approx(6263.619)
    assert result.capex_yuan == pytest.approx(126_000.0)
    assert result.payback_years == pytest.approx(20.12, abs=0.01)
    assert result.annual_profit_ratio == pytest.approx(0.0497, abs=0.001)


# 反算：达到目标回收期所需的元/kWh 单价 ------------------------------
def test_breakeven_unit_capex_matches_hand_calculation():
    expected_10 = (6263.619 * 10 - 6000.0) / 100.0
    assert breakeven_unit_capex(17.1606, 10.0) == pytest.approx(expected_10, abs=0.5)

    expected_15 = (6263.619 * 15 - 6000.0) / 100.0
    assert breakeven_unit_capex(17.1606, 15.0) == pytest.approx(expected_15, abs=0.5)


def test_breakeven_with_demand_saving_is_higher():
    base_10 = breakeven_unit_capex(17.1606, 10.0)
    demand_10 = breakeven_unit_capex(22.78, 10.0)
    assert demand_10 > base_10
    assert demand_10 == pytest.approx((22.78 * 365 * 10 - 6000.0) / 100.0, abs=0.5)


def test_breakeven_returns_none_when_unreachable():
    assert breakeven_unit_capex(0.0, 10.0) is None
    assert breakeven_unit_capex(-1.0, 10.0) is None
    assert breakeven_unit_capex(17.1606, 0.0) is None
    assert breakeven_unit_capex(1.0, 1.0, capex_per_kw=10_000.0) is None


def test_demand_scenario_payback_and_report():
    summary = report()
    assert summary["demand_payback_years"] == pytest.approx(15.15, abs=0.02)
    assert summary["breakeven_capex_10y"] == pytest.approx(566.4, abs=1.0)
    assert summary["breakeven_capex_demand_10y"] == pytest.approx(771.5, abs=1.0)
    assert payback_for_saving(0.0, 126_000.0) is None
