"""Compare BESS charge, discharge and standby modes on the IEEE 9-bus case.

The storage is placed at bus index 8 (bus name 9). Positive p_mw means
charging (a load); negative p_mw means discharging (generation).
"""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pandapower as pp

from n1_analysis import run_power_flow


STORAGE_BUS = 8
STORAGE_P_MW = 20.0
STORAGE_E_MWH = 80.0
MODES = {
    "standby": 0.0,
    "charge_20mw": 20.0,
    "discharge_20mw": -20.0,
}


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


def empty_failure_row() -> dict[str, object]:
    return {
        "converged": False,
        "iterations": None,
        "buses_with_results": 0,
        "lines_with_results": 0,
        "vmin_pu": None,
        "vmax_pu": None,
        "max_line_loading_percent": None,
        "worst_line": None,
        "voltage_violations": None,
        "strict_voltage_violations": None,
        "line_overloads": None,
    }


def main() -> None:
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
            }
            try:
                row.update(run_power_flow(contingency_net))
                row["status"] = (
                    "ok"
                    if row["vmin_pu"] is not None
                    and row["max_line_loading_percent"] is not None
                    else "islanded_or_no_valid_results"
                )
                row["error"] = ""
            except Exception as exc:
                row.update(empty_failure_row())
                row["status"] = "error"
                row["error"] = str(exc)
            rows.append(row)

    results = pd.DataFrame(rows)
    base = pd.DataFrame(base_rows)

    output_path = Path(__file__).with_name("storage_n1_results.csv")
    results.to_csv(output_path, index=False)
    base.to_csv(Path(__file__).with_name("storage_base_results.csv"), index=False)

    print("STORAGE BASE CASES")
    print(
        base[
            [
                "storage_mode",
                "storage_p_mw",
                "converged",
                "vmin_pu",
                "vmax_pu",
                "max_line_loading_percent",
                "voltage_violations",
                "strict_voltage_violations",
                "line_overloads",
            ]
        ].to_string(index=False)
    )

    valid = results[results["status"] == "ok"]
    summary = (
        valid.groupby("storage_mode")
        .agg(
            worst_vmin_pu=("vmin_pu", "min"),
            worst_loading_percent=("max_line_loading_percent", "max"),
            voltage_violation_cases=("voltage_violations", lambda s: int((s > 0).sum())),
            strict_voltage_violation_cases=(
                "strict_voltage_violations",
                lambda s: int((s > 0).sum()),
            ),
            overload_cases=("line_overloads", lambda s: int((s > 0).sum())),
        )
        .reset_index()
    )
    invalid_counts = (
        results[results["status"] != "ok"]
        .groupby("storage_mode")
        .size()
        .rename("invalid_or_islanded_cases")
        .reset_index()
    )
    summary = summary.merge(invalid_counts, on="storage_mode", how="left")
    summary["invalid_or_islanded_cases"] = summary[
        "invalid_or_islanded_cases"
    ].fillna(0)

    print("\nN-1 SUMMARY BY STORAGE MODE")
    print(summary.to_string(index=False))

    critical = results[
        (results["outaged_line"].isin([6, 7, 8]))
        & (results["status"] == "ok")
    ]
    print("\nCRITICAL OUTAGES: LINES 6, 7, 8")
    print(
        critical[
            [
                "storage_mode",
                "outaged_line",
                "from_bus",
                "to_bus",
                "vmin_pu",
                "max_line_loading_percent",
                "voltage_violations",
                "strict_voltage_violations",
                "line_overloads",
            ]
        ].to_string(index=False)
    )
    print(f"\nCSV written to: {output_path}")


if __name__ == "__main__":
    main()
