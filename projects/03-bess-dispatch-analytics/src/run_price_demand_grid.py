"""Price-spread x demand-charge grid: how the two revenue drivers interact.

Both dimensions are scenario knobs of our own example tariff, not market data.
For every cell: rebuild the fair fixed-rule baseline under the same tariff,
re-solve the MILP with the demand term, and report the saving.
"""

from __future__ import annotations

import csv

from bess_model import BessParams
from optimization import purchase_cost, solve_dispatch
from scenario import DT_H, INITIAL_ENERGY_KWH, LOAD_KW, PARAMS, RESULTS_DIR
from sensitivity import _price_series, fair_rule_schedule
from simulation import simulate

SPREADS = (0.0, 0.5, 1.0, 1.5)
RATES = (0.0, 1.0, 3.0, 6.0)


def cell(spread: float, rate: float) -> dict[str, object]:
    prices = _price_series(spread)
    schedule = fair_rule_schedule(PARAMS, prices)
    if schedule is None:
        raise RuntimeError(f"spread={spread}: fair baseline infeasible")
    charge, discharge = schedule
    fair = simulate(PARAMS, INITIAL_ENERGY_KWH, LOAD_KW, charge, discharge, DT_H)
    fair_grid = [r.grid_kw for r in fair.periods]
    fair_total = purchase_cost(fair_grid, prices, DT_H) + rate * max(fair_grid)

    result = solve_dispatch(
        LOAD_KW,
        prices,
        PARAMS,
        INITIAL_ENERGY_KWH,
        DT_H,
        INITIAL_ENERGY_KWH,
        demand_charge_per_kw=rate,
    )
    opt_total = result.total_cost
    return {
        "spread": spread,
        "rate": rate,
        "opt_total": round(opt_total, 2),
        "fair_total": round(fair_total, 2),
        "saving": round(fair_total - opt_total, 2),
        "saving_pct": round(100.0 * (fair_total - opt_total) / fair_total, 2),
        "peak_kw": round(result.peak_grid_kw, 2),
        "status": "ok",
    }


def run() -> list[dict[str, object]]:
    return [cell(spread, rate) for spread in SPREADS for rate in RATES]


def main() -> None:
    rows = run()
    lookup = {(r["spread"], r["rate"]): r for r in rows}

    for metric, title in (("saving_pct", "saving vs fair baseline (%)"),
                          ("peak_kw", "optimised peak grid (kW)")):
        print(f"\n{title}")
        print("spread\\rate" + "".join(f"{r:>9.1f}" for r in RATES))
        for spread in SPREADS:
            line = f"{spread:>10.1f} "
            for rate in RATES:
                line += f"{lookup[(spread, rate)][metric]:>9.2f}"
            print(line)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / "price_demand_grid.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV: {output}")
    print("示例电价结构，非真实市场数据。")


if __name__ == "__main__":
    main()
