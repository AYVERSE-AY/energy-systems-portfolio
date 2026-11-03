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
    print("\n示意假设：单日工况重复 365 天、无衰减、不谈贴现。")


if __name__ == "__main__":
    main()
