"""Compare no-storage, fixed-rule and optimised dispatch on the 24-hour scenario.

Writes two new result files (never overwrites results/baseline_dispatch.csv):
    results/baseline_fair_dispatch.csv    fixed rule scaled to end at 50 kWh
    results/optimized_dispatch.csv        MILP optimum, also ending at 50 kWh

Cost convention: purchase_cost = sum_t price_t * grid_t * dt  (元).
Saving = cost(fair baseline) - cost(optimised); positive means the optimiser saves.
"""

from __future__ import annotations

import csv
from pathlib import Path

from bess_model import BessParams
from optimization import purchase_cost, solve_dispatch
from scenario import (
    CHARGE_KW,
    DISCHARGE_KW,
    DT_H,
    INITIAL_ENERGY_KWH,
    LOAD_KW,
    PARAMS,
    PRICE_PER_KWH,
    RESULTS_DIR,
    build_baseline,
    build_fair_baseline,
    build_no_storage,
)
from simulation import SimulationResult


def metrics(result: SimulationResult, label: str) -> dict[str, object]:
    grid = [record.grid_kw for record in result.periods]
    cost = purchase_cost(grid, PRICE_PER_KWH, result.dt_h)
    return {
        "case": label,
        "cost_yuan": round(cost, 2),
        "max_grid_kw": round(max(grid), 2),
        "min_grid_kw": round(min(grid), 2),
        "charged_kwh": round(result.charged_from_grid_kwh, 2),
        "discharged_kwh": round(result.discharged_to_grid_kwh, 2),
        "soc_start_kwh": round(result.initial_energy_kwh, 2),
        "soc_end_kwh": round(result.final_energy_kwh, 2),
    }


def optimized_metrics() -> tuple[dict[str, object], object]:
    result = solve_dispatch(
        LOAD_KW,
        PRICE_PER_KWH,
        PARAMS,
        initial_energy_kwh=INITIAL_ENERGY_KWH,
        dt_h=DT_H,
        terminal_energy_kwh=INITIAL_ENERGY_KWH,
    )
    grid = list(result.grid_kw)
    return (
        {
            "case": "optimized (MILP)",
            "cost_yuan": round(result.purchase_cost, 2),
            "max_grid_kw": round(max(grid), 2),
            "min_grid_kw": round(min(grid), 2),
            "charged_kwh": round(result.charged_kwh, 2),
            "discharged_kwh": round(result.discharged_kwh, 2),
            "soc_start_kwh": round(result.energy_start_kwh, 2),
            "soc_end_kwh": round(result.energy_end_kwh, 2),
        },
        result,
    )


def write_simulation_csv(result: SimulationResult, path: Path) -> None:
    rows = result.to_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_optimized_csv(result, path: Path) -> None:
    rows = [
        {
            "step": t,
            "load_kw": LOAD_KW[t],
            "price_yuan_per_kwh": PRICE_PER_KWH[t],
            "charge_kw": round(result.charge_kw[t], 6),
            "discharge_kw": round(result.discharge_kw[t], 6),
            "grid_kw": round(result.grid_kw[t], 6),
            "energy_kwh": round(result.energy_kwh[t], 6),
            "soc": round(result.energy_kwh[t] / PARAMS.e_max_kwh, 6),
        }
        for t in range(len(LOAD_KW))
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    no_storage = build_no_storage()
    baseline = build_baseline()
    fair = build_fair_baseline()
    opt_metrics, opt_result = optimized_metrics()

    write_simulation_csv(fair, RESULTS_DIR / "baseline_fair_dispatch.csv")
    write_optimized_csv(opt_result, RESULTS_DIR / "optimized_dispatch.csv")

    rows = [
        metrics(no_storage, "no storage"),
        metrics(baseline, "fixed rule (ends 39.37)"),
        metrics(fair, "fixed rule, fair (ends 50)"),
        opt_metrics,
    ]

    header = ["case", "cost_yuan", "max_grid_kw", "min_grid_kw", "charged_kwh",
              "discharged_kwh", "soc_start_kwh", "soc_end_kwh"]
    widths = [26, 10, 11, 11, 11, 13, 13, 11]
    print("".join(f"{h:<{w}}" for h, w in zip(header, widths)))
    for row in rows:
        print("".join(f"{str(row[h]):<{w}}" for h, w in zip(header, widths)))

    cost_fair = rows[2]["cost_yuan"]
    cost_opt = rows[3]["cost_yuan"]
    saving = float(cost_fair) - float(cost_opt)
    print()
    print(f"fair baseline cost = {cost_fair:.2f} 元")
    print(f"optimised cost     = {cost_opt:.2f} 元")
    print(f"saving             = {saving:.2f} 元 ({saving / float(cost_fair) * 100:.2f} %)  [正=节省]")
    print(f"solver status      = {opt_result.solver_status}")
    print(f"CSV: {RESULTS_DIR / 'baseline_fair_dispatch.csv'}")
    print(f"CSV: {RESULTS_DIR / 'optimized_dispatch.csv'}")


if __name__ == "__main__":
    main()
