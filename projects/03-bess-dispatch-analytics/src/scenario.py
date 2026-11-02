"""Reproducible baseline scenario for the 24-hour BESS simulation.

All numbers below are **example data (示意数据)** written for testing the model,
not measured load, not a real tariff, and not a real dispatch result.

Scenario definition (fixed, so results are repeatable)
    dt_h            = 1.0 h, 24 periods
    load            = fixed 24-value profile (example data)
    strategy        = fixed rule: charge 7 kW in hours 01-06, discharge 12 kW in
                      hours 18-21, idle otherwise (no optimisation)
    initial energy  = 50 kWh (SOC 50 %)
    final SOC       = free (no end-of-horizon SOC constraint in this baseline)

Run:  python src/scenario.py   (writes results/baseline_dispatch.csv)
"""

from __future__ import annotations

import csv
from pathlib import Path

from bess_model import BessParams
from simulation import SimulationResult, simulate

DT_H = 1.0
PERIODS = 24

# 示例数据：示意负荷曲线（kW）
LOAD_KW = (
    30.0, 28.0, 27.0, 26.0, 30.0, 38.0, 45.0,   # 00-06 夜间低谷
    52.0, 58.0, 61.0, 63.0, 62.0,               # 07-11 上午
    60.0, 58.0, 57.0, 60.0, 66.0,               # 12-16 午后
    74.0, 78.0, 80.0, 76.0, 68.0,               # 17-21 晚高峰
    55.0, 42.0,                                 # 22-23
)

# 给定充放电策略（非优化）：示例规则
CHARGE_KW = tuple(7.0 if 1 <= hour <= 6 else 0.0 for hour in range(PERIODS))
DISCHARGE_KW = tuple(12.0 if 18 <= hour <= 21 else 0.0 for hour in range(PERIODS))

PARAMS = BessParams(
    e_max_kwh=100.0,
    p_charge_max_kw=20.0,
    p_discharge_max_kw=20.0,
    eta_charge=0.95,
    eta_discharge=0.95,
    soc_min_frac=0.05,
    soc_max_frac=0.95,
)
INITIAL_ENERGY_KWH = 50.0

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# 示例分时电价（元/kWh，示意数据，不代表任何真实地区电价）
PRICE_PER_KWH = (
    (0.35,) * 7      # 00-06 谷段
    + (0.65,) * 10   # 07-16 平段
    + (1.10,) * 5    # 17-21 峰段
    + (0.65,) * 2    # 22-23 平段
)
assert len(PRICE_PER_KWH) == PERIODS


def build_baseline() -> SimulationResult:
    """Run the fixed baseline scenario (deterministic, no random input)."""
    return simulate(
        PARAMS,
        INITIAL_ENERGY_KWH,
        LOAD_KW,
        CHARGE_KW,
        DISCHARGE_KW,
        DT_H,
    )


def build_no_storage() -> SimulationResult:
    """Reference case: no charging or discharging at all."""
    zeros = (0.0,) * PERIODS
    return simulate(PARAMS, INITIAL_ENERGY_KWH, LOAD_KW, zeros, zeros, DT_H)


def fair_discharge_kw() -> float:
    """Discharge power that returns the battery to 50 kWh after 4 peak hours."""
    stored_gain = sum(CHARGE_KW) * DT_H * PARAMS.eta_charge
    discharge_hours = sum(1 for value in DISCHARGE_KW if value > 0)
    return stored_gain * PARAMS.eta_discharge / (discharge_hours * DT_H)


def build_fair_baseline() -> SimulationResult:
    """Same fixed rule as the baseline, scaled so the final energy is 50 kWh.

    The original baseline ends at 39.37 kWh, which would bias any cost
    comparison against the optimiser (which is required to end at 50 kWh).
    This variant keeps the same charge hours and the same discharge hours,
    only adjusting the discharge power to close the daily energy balance.
    """
    discharge_kw = fair_discharge_kw()
    discharge = tuple(discharge_kw if value > 0 else 0.0 for value in DISCHARGE_KW)
    return simulate(PARAMS, INITIAL_ENERGY_KWH, LOAD_KW, CHARGE_KW, discharge, DT_H)


def write_csv(result: SimulationResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = result.to_rows()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    assert len(LOAD_KW) == len(CHARGE_KW) == len(DISCHARGE_KW) == PERIODS

    result = build_baseline()
    output = RESULTS_DIR / "baseline_dispatch.csv"
    write_csv(result, output)

    print(f"periods={result.steps}  dt_h={result.dt_h}")
    print(
        f"energy: start={result.initial_energy_kwh:.2f} kWh  "
        f"end={result.final_energy_kwh:.2f} kWh  "
        f"min={result.energy_min_kwh:.2f}  max={result.energy_max_kwh:.2f}"
    )
    print(
        f"grid: charged={result.charged_from_grid_kwh:.2f} kWh  "
        f"discharged={result.discharged_to_grid_kwh:.2f} kWh"
    )
    print(
        f"battery delta={result.battery_delta_kwh:.2f} kWh  "
        f"losses={result.losses_kwh:.2f} kWh"
    )
    print(f"CSV: {output}")


if __name__ == "__main__":
    main()
