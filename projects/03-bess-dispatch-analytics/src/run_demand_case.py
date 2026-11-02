"""Demand-charge case: energy cost + peak demand cost (示意数据).

Rates are expressed per kW for this one-day horizon: 30 元/kW·月 ÷ 30 天 ≈
1 元/kW·日 is used as the reference, plus 0 / 3 / 6 元/kW·日 for comparison.
The 30 元/kW·月 figure is a placeholder assumption, not a real tariff.
"""

from __future__ import annotations

from optimization import purchase_cost, solve_dispatch
from scenario import (
    DT_H,
    INITIAL_ENERGY_KWH,
    LOAD_KW,
    PARAMS,
    PRICE_PER_KWH,
    build_fair_baseline,
    build_no_storage,
)

RATES = (0.0, 1.0, 3.0, 6.0)


def case_metrics(energy_cost: float, grid: list[float], rate: float) -> dict[str, float]:
    peak = max(grid)
    return {
        "energy_yuan": energy_cost,
        "peak_kw": peak,
        "demand_yuan": rate * peak,
        "total_yuan": energy_cost + rate * peak,
    }


def run() -> list[dict[str, object]]:
    no_storage = build_no_storage()
    fair = build_fair_baseline()
    grid_no = [r.grid_kw for r in no_storage.periods]
    grid_fair = [r.grid_kw for r in fair.periods]
    energy_no = purchase_cost(grid_no, PRICE_PER_KWH, DT_H)
    energy_fair = purchase_cost(grid_fair, PRICE_PER_KWH, DT_H)

    rows: list[dict[str, object]] = []
    for rate in RATES:
        base = case_metrics(energy_no, grid_no, rate)
        fair_m = case_metrics(energy_fair, grid_fair, rate)

        energy_only = solve_dispatch(
            LOAD_KW, PRICE_PER_KWH, PARAMS, INITIAL_ENERGY_KWH, DT_H, INITIAL_ENERGY_KWH
        )
        eo = case_metrics(energy_only.purchase_cost, list(energy_only.grid_kw), rate)

        with_demand = solve_dispatch(
            LOAD_KW,
            PRICE_PER_KWH,
            PARAMS,
            INITIAL_ENERGY_KWH,
            DT_H,
            INITIAL_ENERGY_KWH,
            demand_charge_per_kw=rate,
        )
        wd = case_metrics(with_demand.purchase_cost, list(with_demand.grid_kw), rate)

        rows.append(
            {
                "rate_yuan_per_kw_day": rate,
                "no_storage_total": round(base["total_yuan"], 2),
                "fair_total": round(fair_m["total_yuan"], 2),
                "energy_only_total": round(eo["total_yuan"], 2),
                "energy_only_peak": round(eo["peak_kw"], 2),
                "demand_aware_total": round(wd["total_yuan"], 2),
                "demand_aware_peak": round(wd["peak_kw"], 2),
                "demand_aware_energy": round(wd["energy_yuan"], 2),
                "demand_aware_demand_charge": round(wd["demand_yuan"], 2),
                "saving_vs_fair": round(fair_m["total_yuan"] - wd["total_yuan"], 2),
            }
        )
    return rows


def main() -> None:
    rows = run()
    header = (
        f"{'rate':>6s}{'no-storage':>12s}{'fair':>9s}{'energy-only':>13s}"
        f"{'demand-aware':>14s}{'peak':>8s}{'saving':>9s}"
    )
    print(header)
    for row in rows:
        print(
            f"{row['rate_yuan_per_kw_day']:>6.1f}{row['no_storage_total']:>12.2f}"
            f"{row['fair_total']:>9.2f}{row['energy_only_total']:>13.2f}"
            f"{row['demand_aware_total']:>14.2f}{row['demand_aware_peak']:>8.2f}"
            f"{row['saving_vs_fair']:>9.2f}"
        )
    print("\n需量电价 30 元/kW·月 ÷ 30 天 ≈ 1 元/kW·日，为示意假设。")


if __name__ == "__main__":
    main()
