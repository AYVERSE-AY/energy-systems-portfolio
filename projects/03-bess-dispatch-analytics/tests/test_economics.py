"""年收益与静态回收期测试（示意投资假设，非市场数据）。"""

from __future__ import annotations

import pytest

from economics import (
    EconomicsInputError,
    annualize,
    capex_for,
    evaluate_baseline_case,
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
