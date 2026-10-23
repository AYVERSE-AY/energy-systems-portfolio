"""Compare BESS charge, discharge and standby modes on the IEEE 9-bus case.

The storage is placed at bus index 8 (bus name 9). Positive p_mw means
charging (a load); negative p_mw means discharging (generation).

Solver convergence, result validity (topology connectivity + result coverage)
and operating-limit compliance are reported separately, mirroring the
classification used in project 01.

Outputs
-------
data/storage_base_results.csv   one row per operating mode (base case)
data/storage_n1_results.csv     one row per operating mode and outaged line
"""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pandapower as pp

from n1_analysis import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    bus_label,
    run_power_flow,
)

STORAGE_BUS = 8
STORAGE_P_MW = 20.0
STORAGE_E_MWH = 80.0
MODES = {
    "standby": 0.0,
    "charge_20mw": 20.0,
    "discharge_20mw": -20.0,
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def make_network(mode_p_mw: float) -> tuple[pp.pandapowerNet, int]:
    net = pp.networks.case9()
    storage_index = pp.create_storage(
        net,
        bus=STORAGE_BUS,
        p_mw=mode_p_mw,
        q_mvar=0.0,
        max_e_mwh=STORAGE_E_MWH,
        soc_percent=50.0,
        name=f"BESS_{abs(STORAGE_P_MW):.0f}MW_{STORAGE_E_MWH:.0f}MWh",
    )
    return net, storage_index


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    base_rows: list[dict[str, object]] = []

    for mode, p_mw in MODES.items():
        base_net, storage_index = make_network(p_mw)
        base_result = run_power_flow(copy.deepcopy(base_net))
        base_rows.append(
            {
                "storage_mode": mode,
                "storage_p_mw": p_mw,
                "storage_bus_index": STORAGE_BUS,
                "storage_bus_name": int(base_net.bus.at[STORAGE_BUS, "name"]),
                **base_result,
            }
        )

        for line_index in base_net.line.index:
            contingency_net = copy.deepcopy(base_net)
            contingency_net.line.at[line_index, "in_service"] = False
            row: dict[str, object] = {
                "storage_mode": mode,
                "storage_p_mw": p_mw,
                "outaged_line": int(line_index),
                "from_bus": int(base_net.line.at[line_index, "from_bus"]),
                "to_bus": int(base_net.line.at[line_index, "to_bus"]),
                "from_bus_label": bus_label(
                    base_net, int(base_net.line.at[line_index, "from_bus"])
                ),
                "to_bus_label": bus_label(
                    base_net, int(base_net.line.at[line_index, "to_bus"])
                ),
            }
            row.update(run_power_flow(contingency_net))
            rows.append(row)

    results = pd.DataFrame(rows).sort_values(["storage_mode", "outaged_line"], ignore_index=True)
    base = pd.DataFrame(base_rows)
    results["islanded_buses"] = results["islanded_buses"].apply(
        lambda buses: " ".join(str(bus) for bus in buses)
    )

    results.to_csv(DATA_DIR / "storage_n1_results.csv", index=False)
    base.to_csv(DATA_DIR / "storage_base_results.csv", index=False)

    print("STORAGE BASE CASES")
    print(
        base[
            [
                "storage_mode",
                "storage_p_mw",
                "converged",
                "iterations",
                "vmin_pu",
                "vmax_pu",
                "max_line_loading_percent",
                "voltage_violations",
                "strict_voltage_violations",
                "line_overloads",
            ]
        ].to_string(index=False)
    )

    valid = results[results["status"] == STATUS_OK]
    summary = (
        valid.groupby("storage_mode")
        .agg(
            ok_cases=("outaged_line", "size"),
            worst_vmin_pu=("vmin_pu", "min"),
            worst_loading_percent=("max_line_loading_percent", "max"),
            voltage_violation_cases=("voltage_violations", lambda s: int((s > 0).sum())),
            strict_voltage_violation_cases=(
                "strict_voltage_violations",
                lambda s: int((s > 0).sum()),
            ),
            overload_cases=("line_overloads", lambda s: int((s > 0).sum())),
        )
        .reindex(list(MODES))
        .reset_index()
    )
    for status, column in (
        (STATUS_PARTIAL, "partial_cases"),
        ("islanded_no_valid_results", "invalid_cases"),
        (STATUS_ERROR, "error_cases"),
    ):
        counts = (
            results[results["status"] == status]
            .groupby("storage_mode")
            .size()
            .reindex(list(MODES))
            .fillna(0)
            .astype(int)
            .reset_index(name=column)
        )
        summary = summary.merge(counts, on="storage_mode", how="left")
    summary[["partial_cases", "invalid_cases", "error_cases"]] = summary[
        ["partial_cases", "invalid_cases", "error_cases"]
    ].fillna(0)

    print("\nN-1 SUMMARY BY STORAGE MODE (metrics over full-coverage cases only)")
    print(summary.to_string(index=False))

    partial = results[results["status"] == STATUS_PARTIAL]
    print("\nPARTIAL-COVERAGE CASES (one bus islanded; metrics cover the energised island only)")
    print(
        partial[
            [
                "storage_mode",
                "outaged_line",
                "from_bus_label",
                "to_bus_label",
                "islanded_buses",
                "vmin_pu",
                "max_line_loading_percent",
                "strict_voltage_violations",
                "line_overloads",
            ]
        ].to_string(index=False)
    )

    critical = results[results["outaged_line"].isin([6, 7, 8])]
    print("\nCRITICAL OUTAGES: LINES 6, 7, 8")
    print(
        critical[
            [
                "storage_mode",
                "outaged_line",
                "from_bus_label",
                "to_bus_label",
                "status",
                "vmin_pu",
                "max_line_loading_percent",
                "voltage_violations",
                "strict_voltage_violations",
                "line_overloads",
            ]
        ].to_string(index=False)
    )

    print(f"\nCSV written to: {DATA_DIR / 'storage_n1_results.csv'}")
    print(f"Base case written to: {DATA_DIR / 'storage_base_results.csv'}")


if __name__ == "__main__":
    main()
