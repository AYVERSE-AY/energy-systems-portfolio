"""IEEE 9-bus power flow and N-1 line outage screening.

This script intentionally uses pandapower directly rather than the PowerMCP
contingency tool. The installed PowerMCP version calls ``net.deepcopy()``,
which pandapowerNet does not implement; ``copy.deepcopy`` is the correct
operation.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pandapower as pp


MAX_ITERATION = 10
TOLERANCE_MVA = 1e-8
V_MIN = 0.90
V_MAX = 1.10
STRICT_V_MIN = 0.95
STRICT_V_MAX = 1.05
LOADING_LIMIT_PERCENT = 100.0


def run_power_flow(net: pp.pandapowerNet) -> dict[str, object]:
    """Run one AC power flow and collect the metrics used in the report."""
    pp.runpp(
        net,
        algorithm="nr",
        calculate_voltage_angles=True,
        max_iteration=MAX_ITERATION,
        tolerance_mva=TOLERANCE_MVA,
        numba=False,
    )

    vm = net.res_bus.vm_pu.dropna()
    loading = net.res_line.loading_percent.dropna()
    ppc = getattr(net, "_ppc", None)
    valid_system = len(vm) >= 2 and not loading.empty

    return {
        "converged": bool(net.converged),
        "iterations": ppc.get("iterations") if isinstance(ppc, dict) else None,
        "buses_with_results": int(len(vm)),
        "lines_with_results": int(len(loading)),
        "vmin_pu": float(vm.min()) if valid_system else None,
        "vmax_pu": float(vm.max()) if valid_system else None,
        "max_line_loading_percent": float(loading.max()) if valid_system else None,
        "worst_line": int(loading.idxmax()) if valid_system else None,
        "voltage_violations": int(((vm < V_MIN) | (vm > V_MAX)).sum())
        if valid_system
        else None,
        "strict_voltage_violations": int(
            ((vm < STRICT_V_MIN) | (vm > STRICT_V_MAX)).sum()
        )
        if valid_system
        else None,
        "line_overloads": int((loading > LOADING_LIMIT_PERCENT).sum())
        if valid_system
        else None,
    }


def main() -> None:
    base_net = pp.networks.case9()
    base_result = run_power_flow(copy.deepcopy(base_net))

    rows: list[dict[str, object]] = []
    for line_index in base_net.line.index:
        contingency_net = copy.deepcopy(base_net)
        contingency_net.line.at[line_index, "in_service"] = False

        row: dict[str, object] = {
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
        except Exception as exc:  # non-convergence and islanding are expected cases
            row.update(
                {
                    "converged": False,
                    "iterations": None,
                    "vmin_pu": None,
                    "vmax_pu": None,
                    "max_line_loading_percent": None,
                    "worst_line": None,
                    "voltage_violations": None,
                    "strict_voltage_violations": None,
                    "line_overloads": None,
                    "status": "error",
                    "error": str(exc),
                }
            )

        rows.append(row)

    results = pd.DataFrame(rows)
    results["severity_score"] = (
        (~results["converged"]).astype(int) * 1000
        + (results["status"] != "ok").astype(int) * 500
        + results["line_overloads"].fillna(0) * 100
        + results["voltage_violations"].fillna(0) * 10
        + results["max_line_loading_percent"].fillna(0)
        - results["vmin_pu"].fillna(V_MAX)
    )
    results = results.sort_values("severity_score", ascending=False)

    output_path = Path(__file__).with_name("n1_results.csv")
    results.to_csv(output_path, index=False)

    print("BASE CASE")
    for key, value in base_result.items():
        print(f"{key}: {value}")

    print("\nTOP CONTINGENCIES")
    columns = [
        "outaged_line",
        "from_bus",
        "to_bus",
        "status",
        "converged",
        "buses_with_results",
        "lines_with_results",
        "vmin_pu",
        "vmax_pu",
        "max_line_loading_percent",
        "voltage_violations",
        "strict_voltage_violations",
        "line_overloads",
        "error",
    ]
    print(results[columns].head(10).to_string(index=False))
    print(f"\nCSV written to: {output_path}")


if __name__ == "__main__":
    main()
