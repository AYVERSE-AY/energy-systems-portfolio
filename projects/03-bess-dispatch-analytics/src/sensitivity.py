"""Single-factor sensitivity analysis for the 24-hour MILP dispatch.

Every scenario changes exactly one thing against the base case (efficiency,
capacity, power limit or price spread); load, dt, initial and terminal storage
(50 kWh each) stay fixed. All numbers come from the real solver and are
re-checked with the physical model; example data only, no real-site claims.

Output: results/sensitivity_summary.csv (never overwrites other result files).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace

from bess_model import BessParams, InfeasibleRequest
from optimization import (
    InfeasibleProblem,
    InvalidInput,
    OptimizationError,
    purchase_cost,
    solve_dispatch,
)
from scenario import DT_H, INITIAL_ENERGY_KWH, LOAD_KW, PARAMS, PRICE_PER_KWH, RESULTS_DIR
from simulation import simulate

BASE_COST_FLAT = 0.65
BASE_COST_VALLEY = 0.35
BASE_COST_PEAK = 1.10
CHARGE_HOURS = range(1, 7)
DISCHARGE_HOURS = range(18, 22)
BASE_RULE_CHARGE_KW = 7.0


@dataclass(frozen=True)
class Scenario:
    family: str
    label: str
    params: BessParams
    prices: tuple[float, ...]


def _price_series(spread: float) -> tuple[float, ...]:
    valley = BASE_COST_FLAT - (BASE_COST_FLAT - BASE_COST_VALLEY) * spread
    peak = BASE_COST_FLAT + (BASE_COST_PEAK - BASE_COST_FLAT) * spread
    return (
        (valley,) * 7 + (BASE_COST_FLAT,) * 10 + (peak,) * 5 + (BASE_COST_FLAT,) * 2
    )


def build_scenarios() -> list[Scenario]:
    base_prices = PRICE_PER_KWH
    scenarios: list[Scenario] = []

    for eta in (0.85, 0.90, 0.95, 0.98):
        scenarios.append(
            Scenario(
                "efficiency",
                f"eta={eta:.2f}",
                replace(PARAMS, eta_charge=eta, eta_discharge=eta),
                base_prices,
            )
        )
    for capacity in (60.0, 100.0, 150.0, 200.0):
        scenarios.append(
            Scenario("capacity", f"e_max={capacity:.0f}kWh", replace(PARAMS, e_max_kwh=capacity), base_prices)
        )
    for power in (10.0, 20.0, 30.0, 40.0):
        scenarios.append(
            Scenario(
                "power",
                f"p_max={power:.0f}kW",
                replace(PARAMS, p_charge_max_kw=power, p_discharge_max_kw=power),
                base_prices,
            )
        )
    for spread, name in ((0.0, "flat"), (1.0, "base"), (1.2, "x1.2"), (1.5, "x1.5")):
        scenarios.append(
            Scenario("price_spread", f"spread={name}", PARAMS, _price_series(spread))
        )
    return scenarios


def build_two_factor_scenarios() -> list[Scenario]:
    """Capacity x power grid (each cell still uses the base prices and load)."""
    scenarios: list[Scenario] = []
    for capacity in (60.0, 100.0, 150.0, 200.0):
        for power in (10.0, 20.0, 30.0, 40.0):
            scenarios.append(
                Scenario(
                    "capacity_x_power",
                    f"e={capacity:.0f}kWh,p={power:.0f}kW",
                    replace(
                        PARAMS,
                        e_max_kwh=capacity,
                        p_charge_max_kw=power,
                        p_discharge_max_kw=power,
                    ),
                    PRICE_PER_KWH,
                )
            )
    return scenarios


def run_two_factor() -> list[dict[str, object]]:
    return [run_scenario(scenario) for scenario in build_two_factor_scenarios()]


def fair_rule_schedule(params: BessParams, prices: tuple[float, ...]) -> tuple[list[float], list[float]] | None:
    """Fixed rule scaled to the largest feasible power that returns to 50 kWh."""
    headroom = params.usable_max_kwh - INITIAL_ENERGY_KWH
    hours = len(CHARGE_HOURS)
    if headroom <= 0 or params.e_max_kwh <= 0:
        return None
    charge_kw = min(BASE_RULE_CHARGE_KW, params.p_charge_max_kw, headroom / (params.eta_charge * DT_H * hours))
    if charge_kw <= 0:
        return None
    discharge_kw = charge_kw * hours * params.eta_charge * params.eta_discharge / (
        len(DISCHARGE_HOURS) * DT_H
    )
    if discharge_kw > params.p_discharge_max_kw:
        return None
    charge = [charge_kw if t in CHARGE_HOURS else 0.0 for t in range(len(LOAD_KW))]
    discharge = [discharge_kw if t in DISCHARGE_HOURS else 0.0 for t in range(len(LOAD_KW))]
    return charge, discharge


VALIDATION_TOL = 1e-6


def _clamp_for_replay(series, limit: float, name: str, problems: list[str]):
    """Remove solver floating noise (<=1e-6); larger overshoot is a real violation."""
    cleaned = []
    for value in series:
        if value < 0:
            if -value > VALIDATION_TOL:
                problems.append(f"{name} 负值 {-value:.2e}")
            value = 0.0
        if value > limit:
            if value - limit > VALIDATION_TOL:
                problems.append(f"{name} 越限 {value:.6f} > {limit}")
            value = limit
        cleaned.append(value)
    return tuple(cleaned)


def _validate(params: BessParams, prices, result) -> list[str]:
    problems: list[str] = []
    charge = _clamp_for_replay(result.charge_kw, params.p_charge_max_kw, "充电功率", problems)
    discharge = _clamp_for_replay(
        result.discharge_kw, params.p_discharge_max_kw, "放电功率", problems
    )
    replay = simulate(params, INITIAL_ENERGY_KWH, LOAD_KW, charge, discharge, DT_H)
    if abs(replay.final_energy_kwh - INITIAL_ENERGY_KWH) > VALIDATION_TOL:
        problems.append("期末储能量不为 50 kWh")
    if abs(result.purchase_cost - purchase_cost(result.grid_kw, prices, DT_H)) > VALIDATION_TOL:
        problems.append("成本口径不一致")
    return problems


def run_scenario(scenario: Scenario) -> dict[str, object]:
    row: dict[str, object] = {
        "family": scenario.family,
        "case": scenario.label,
        "status": "",
        "cost_yuan": None,
        "fair_cost_yuan": None,
        "saving_yuan": None,
        "saving_pct": None,
        "charged_kwh": None,
        "discharged_kwh": None,
        "max_grid_kw": None,
        "min_grid_kw": None,
        "soc_swing_kwh": None,
        "check": "",
    }
    params = scenario.params
    prices = scenario.prices

    try:
        result = solve_dispatch(
            LOAD_KW, prices, params, INITIAL_ENERGY_KWH, DT_H, INITIAL_ENERGY_KWH
        )
    except (InfeasibleProblem, OptimizationError, InvalidInput) as exc:
        row["status"] = "invalid_or_infeasible"
        row["check"] = str(exc)[:60]
        return row

    schedule = fair_rule_schedule(params, prices)
    if schedule is None:
        row["status"] = "fair_baseline_infeasible"
        return row
    charge, discharge = schedule
    try:
        fair = simulate(params, INITIAL_ENERGY_KWH, LOAD_KW, charge, discharge, DT_H)
    except (InfeasibleRequest, ValueError) as exc:  # pragma: no cover - guarded above
        row["status"] = "fair_baseline_infeasible"
        row["check"] = str(exc)[:60]
        return row

    fair_cost = purchase_cost([r.grid_kw for r in fair.periods], prices, DT_H)
    saving = fair_cost - result.purchase_cost
    problems = _validate(params, prices, result)

    row.update(
        {
            "status": "ok",
            "cost_yuan": round(result.purchase_cost, 2),
            "fair_cost_yuan": round(fair_cost, 2),
            "saving_yuan": round(saving, 2),
            "saving_pct": round(100.0 * saving / fair_cost, 2) if fair_cost else None,
            "charged_kwh": round(result.charged_kwh, 2),
            "discharged_kwh": round(result.discharged_kwh, 2),
            "max_grid_kw": round(max(result.grid_kw), 2),
            "min_grid_kw": round(min(result.grid_kw), 2),
            "soc_swing_kwh": round(max(result.energy_kwh) - min(result.energy_kwh), 2),
            "check": "ok" if not problems else "; ".join(problems),
        }
    )
    return row


def run_all() -> list[dict[str, object]]:
    return [run_scenario(scenario) for scenario in build_scenarios()]


FIELDS = [
    "family",
    "case",
    "status",
    "cost_yuan",
    "fair_cost_yuan",
    "saving_yuan",
    "saving_pct",
    "charged_kwh",
    "discharged_kwh",
    "max_grid_kw",
    "min_grid_kw",
    "soc_swing_kwh",
    "check",
]


def main() -> None:
    rows = run_all()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / "sensitivity_summary.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    header = f"{'family':12s}{'case':16s}{'status':10s}{'cost':>9s}{'fair':>9s}{'save':>8s}{'save%':>7s}{'peak':>7s}"
    print(header)
    for row in rows:
        def fmt(value, spec=""):
            return "-" if value is None else f"{value:{spec}}"

        print(
            f"{row['family']:12s}{row['case']:16s}{row['status']:10s}"
            f"{fmt(row['cost_yuan']):>9s}{fmt(row['fair_cost_yuan']):>9s}"
            f"{fmt(row['saving_yuan']):>8s}{fmt(row['saving_pct']):>7s}{fmt(row['max_grid_kw']):>7s}"
        )
    print(f"\nCSV: {output}")
    print("示例数据，非真实电站收益。")


if __name__ == "__main__":
    main()
