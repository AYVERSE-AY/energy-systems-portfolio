"""Annual saving and static payback time for the BESS case (示意假设).

Assumptions (all explicitly placeholders, not market data):
    * the single analysed day repeats 365 times a year (no seasonality, no degradation)
    * capex is a flat unit price per kWh of usable capacity, no O&M, no discounting
    * saving comes only from the dispatch comparison against the fair fixed rule

Static payback = capex / annual saving, in years. A non-positive annual saving has no
payback, which is reported as ``None`` instead of an infinite number.
"""

from __future__ import annotations

from dataclasses import dataclass

from scenario import PARAMS

DAYS_PER_YEAR = 365
CAPEX_PER_KWH = 1200.0  # 元/kWh，示意假设
CAPEX_PER_KW = 300.0  # 元/kW，示意假设


class EconomicsInputError(ValueError):
    """Invalid economic input (negative capex, non-finite values)."""


@dataclass(frozen=True)
class EconomicsResult:
    daily_saving_yuan: float
    annual_saving_yuan: float
    capex_yuan: float
    payback_years: float | None
    days_per_year: int
    capex_per_kwh: float
    capex_per_kw: float

    @property
    def annual_profit_ratio(self) -> float:
        """Annual saving divided by capex (simple return rate, no discounting)."""
        return self.annual_saving_yuan / self.capex_yuan if self.capex_yuan else 0.0


def capex_for(params, capex_per_kwh: float = CAPEX_PER_KWH, capex_per_kw: float = CAPEX_PER_KW) -> float:
    if capex_per_kwh < 0 or capex_per_kw < 0:
        raise EconomicsInputError("投资单价不能为负")
    power_kw = max(params.p_charge_max_kw, params.p_discharge_max_kw)
    return params.e_max_kwh * capex_per_kwh + power_kw * capex_per_kw


def annualize(
    daily_saving_yuan: float,
    capex_yuan: float,
    days_per_year: int = DAYS_PER_YEAR,
) -> EconomicsResult:
    if days_per_year <= 0:
        raise EconomicsInputError(f"days_per_year 必须为正：{days_per_year}")
    if capex_yuan < 0:
        raise EconomicsInputError(f"投资额不能为负：{capex_yuan}")

    annual = daily_saving_yuan * days_per_year
    payback = capex_yuan / annual if annual > 0 else None
    return EconomicsResult(
        daily_saving_yuan=daily_saving_yuan,
        annual_saving_yuan=annual,
        capex_yuan=capex_yuan,
        payback_years=payback,
        days_per_year=days_per_year,
        capex_per_kwh=CAPEX_PER_KWH,
        capex_per_kw=CAPEX_PER_KW,
    )


def evaluate_baseline_case() -> EconomicsResult:
    """Use the verified phase-2 daily saving (17.16 元) and the default capex."""
    return annualize(17.1606, capex_for(PARAMS))


def breakeven_unit_capex(
    daily_saving_yuan: float,
    target_years: float,
    params=None,
    capex_per_kw: float = CAPEX_PER_KW,
) -> float | None:
    """元/kWh unit price that just reaches ``target_years`` payback.

    The per-kW cost is held fixed; the remaining budget is divided by capacity.
    Returns ``None`` when the annual saving is non-positive, the target is
    non-positive, or the per-kW cost alone exceeds the affordable capex
    (i.e. even free cells cannot hit the target).
    """
    if params is None:
        from scenario import PARAMS as params  # local import keeps module importable alone

    if daily_saving_yuan <= 0 or target_years <= 0:
        return None

    annual = daily_saving_yuan * DAYS_PER_YEAR
    affordable_capex = annual * target_years
    power_kw = max(params.p_charge_max_kw, params.p_discharge_max_kw)
    residual = affordable_capex - power_kw * capex_per_kw
    if residual <= 0 or params.e_max_kwh <= 0:
        return None
    return residual / params.e_max_kwh


def payback_for_saving(daily_saving_yuan: float, capex_yuan: float) -> float | None:
    """Static payback in years, or ``None`` when the saving is non-positive."""
    return annualize(daily_saving_yuan, capex_yuan).payback_years


def report() -> dict[str, float | None]:
    """Summary used by the report and the console output."""
    base = evaluate_baseline_case()
    demand = annualize(22.78, base.capex_yuan)
    return {
        "daily_saving": base.daily_saving_yuan,
        "annual_saving": base.annual_saving_yuan,
        "capex": base.capex_yuan,
        "payback_years": base.payback_years,
        "demand_payback_years": demand.payback_years,
        "breakeven_capex_10y": breakeven_unit_capex(base.daily_saving_yuan, 10.0),
        "breakeven_capex_15y": breakeven_unit_capex(base.daily_saving_yuan, 15.0),
        "breakeven_capex_demand_10y": breakeven_unit_capex(22.78, 10.0),
    }


def main() -> None:
    result = evaluate_baseline_case()
    print(f"日节省        = {result.daily_saving_yuan:.2f} 元")
    print(f"年节省(365 天) = {result.annual_saving_yuan:.2f} 元")
    print(f"投资额        = {result.capex_yuan:.2f} 元"
          f"（{result.capex_per_kwh:.0f} 元/kWh + {result.capex_per_kw:.0f} 元/kW）")
    if result.payback_years is None:
        print("静态回收期    = 不可回收（日节省 <= 0）")
    else:
        print(f"静态回收期    = {result.payback_years:.2f} 年")
    print(f"年收益/投资    = {result.annual_profit_ratio * 100:.2f} %")

    summary = report()
    print("\n反算：达到目标回收期所需的电池单价（元/kWh，功率成本固定 300 元/kW）")
    for target, key in ((10.0, "breakeven_capex_10y"), (15.0, "breakeven_capex_15y")):
        value = summary[key]
        print(f"  仅峰谷套利、{target:.0f} 年回收 → "
              + ("不可达" if value is None else f"{value:.1f} 元/kWh"))
    value = summary["breakeven_capex_demand_10y"]
    print("  叠加需量电费(1 元/kW·日)、10 年回收 → "
          + ("不可达" if value is None else f"{value:.1f} 元/kWh"))
    print(f"  叠加需量电费后的回收期 = {summary['demand_payback_years']:.2f} 年")
    print("\n示意假设：单日工况重复 365 天、无衰减、不谈贴现、无运维与补贴。")


if __name__ == "__main__":
    main()
