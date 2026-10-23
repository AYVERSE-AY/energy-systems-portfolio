"""IEEE 9-bus AC power flow and N-1 line outage screening.

The screening runs pandapower directly. PowerMCP's contingency tool is not
used because the installed version calls a non-existent
``pandapowerNet.deepcopy()``; ``copy.deepcopy(net)`` is the correct operation.

Solver convergence, result validity and operating-limit compliance are three
different concepts and are reported separately:

* ``converged``      -- the solver reported convergence;
* ``status``         -- whether the results cover the whole in-service network
                        (topology connectivity + result coverage);
* ``voltage_violations`` / ``line_overloads`` -- limit compliance, evaluated
                        only on the buses and lines that actually have results.

Outputs
-------
data/n1_results.csv   one row per outaged line
data/base_case.json   base-case metrics (so the report figures are traceable)
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pandapower as pp
import pandas as pd

MAX_ITERATION = 10
TOLERANCE_MVA = 1e-8
V_MIN = 0.90
V_MAX = 1.10
STRICT_V_MIN = 0.95
STRICT_V_MAX = 1.05
LOADING_LIMIT_PERCENT = 100.0

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial_coverage_islanded"
STATUS_ISLANDED = "islanded_no_valid_results"
STATUS_ERROR = "error"


def connected_components(net: pp.pandapowerNet) -> list[list[int]]:
    """Group buses connected by in-service branches (lines and transformers)."""
    parent: dict[int, int] = {int(bus): int(bus) for bus in net.bus.index}

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_left] = root_right

    for frame, pairs in (
        (net.line, ("from_bus", "to_bus")),
        (net.trafo, ("hv_bus", "lv_bus")),
    ):
        in_service = frame[frame.in_service] if not frame.empty else frame
        for _, row in in_service.iterrows():
            union(int(row[pairs[0]]), int(row[pairs[1]]))
    for _, row in net.trafo3w[net.trafo3w.in_service].iterrows():
        union(int(row.hv_bus), int(row.mv_bus))
        union(int(row.hv_bus), int(row.lv_bus))

    groups: dict[int, list[int]] = {}
    for bus in net.bus.index:
        groups.setdefault(find(int(bus)), []).append(int(bus))
    return sorted(groups.values(), key=len, reverse=True)


def slack_buses(net: pp.pandapowerNet) -> list[int]:
    buses: list[int] = []
    if not net.ext_grid.empty:
        buses.extend(int(bus) for bus in net.ext_grid.bus)
    return buses


def islanded_buses(net: pp.pandapowerNet, components: list[list[int]]) -> list[int]:
    """Buses in a topology partition that contains no slack source."""
    sources = set(slack_buses(net))
    islanded: list[int] = []
    for group in components:
        if not sources.intersection(group):
            islanded.extend(group)
    return sorted(islanded)


def run_power_flow(net: pp.pandapowerNet) -> dict[str, object]:
    """Run one AC power flow and collect the metrics used in the report."""
    try:
        pp.runpp(
            net,
            algorithm="nr",
            calculate_voltage_angles=True,
            max_iteration=MAX_ITERATION,
            tolerance_mva=TOLERANCE_MVA,
            numba=False,
        )
    except Exception as exc:  # non-convergence and islanding are expected cases
        return {
            "converged": False,
            "iterations": None,
            "buses_total": int(len(net.bus)),
            "lines_total": int(len(net.line)),
            "buses_with_results": 0,
            "lines_with_results": 0,
            "vmin_pu": None,
            "vmax_pu": None,
            "vmin_bus": None,
            "vmax_bus": None,
            "max_line_loading_percent": None,
            "worst_line": None,
            "voltage_violations": None,
            "strict_voltage_violations": None,
            "line_overloads": None,
            "islanded_buses": [],
            "status": STATUS_ERROR,
            "error": f"{type(exc).__name__}: {exc}",
        }

    vm = net.res_bus.vm_pu.dropna()
    loading = net.res_line.loading_percent.dropna()
    components = connected_components(net)
    buses_solved = int(len(vm))
    lines_solved = int(len(loading))

    if buses_solved < 2 or lines_solved == 0:
        status = STATUS_ISLANDED
    elif len(components) > 1 or buses_solved < int(len(net.bus)):
        status = STATUS_PARTIAL
    else:
        status = STATUS_OK

    metrics_available = status != STATUS_ISLANDED

    return {
        "converged": bool(net.converged),
        "iterations": net._ppc.get("iterations") if isinstance(net._ppc, dict) else None,
        "buses_total": int(len(net.bus)),
        "lines_total": int(len(net.line)),
        "buses_with_results": buses_solved,
        "lines_with_results": lines_solved,
        "vmin_pu": float(vm.min()) if metrics_available and buses_solved else None,
        "vmax_pu": float(vm.max()) if metrics_available and buses_solved else None,
        "vmin_bus": int(vm.idxmin()) if metrics_available and buses_solved else None,
        "vmax_bus": int(vm.idxmax()) if metrics_available and buses_solved else None,
        "max_line_loading_percent": float(loading.max())
        if metrics_available and lines_solved
        else None,
        "worst_line": int(loading.idxmax()) if metrics_available and lines_solved else None,
        "voltage_violations": int(((vm < V_MIN) | (vm > V_MAX)).sum())
        if metrics_available and buses_solved
        else None,
        "strict_voltage_violations": int(
            ((vm < STRICT_V_MIN) | (vm > STRICT_V_MAX)).sum()
        )
        if metrics_available and buses_solved
        else None,
        "line_overloads": int((loading > LOADING_LIMIT_PERCENT).sum())
        if metrics_available and lines_solved
        else None,
        "islanded_buses": islanded_buses(net, components),
        "status": status,
        "error": "",
    }


def bus_label(net: pp.pandapowerNet, bus_index: int) -> str:
    """Human-readable bus number (pandapower case9 names buses "1".."9")."""
    name = net.bus.at[bus_index, "name"] if "name" in net.bus else None
    return str(name) if name is not None and str(name) != "nan" else str(bus_index + 1)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    base_net = pp.networks.case9()
    base_result = run_power_flow(copy.deepcopy(base_net))

    base_payload = {
        "case": "pandapower.networks.case9",
        "pandapower_version": pp.__version__,
        "settings": {
            "algorithm": "nr",
            "max_iteration": MAX_ITERATION,
            "tolerance_mva": TOLERANCE_MVA,
            "calculate_voltage_angles": True,
            "numba": False,
        },
        "network": {
            "buses": int(len(base_net.bus)),
            "lines": int(len(base_net.line)),
            "loads": int(len(base_net.load)),
            "gens": int(len(base_net.gen)),
            "ext_grids": int(len(base_net.ext_grid)),
            "slack_bus_labels": [bus_label(base_net, b) for b in slack_buses(base_net)],
        },
        "results": {
            key: value
            for key, value in base_result.items()
            if key not in {"error", "status", "islanded_buses"}
        },
    }
    (DATA_DIR / "base_case.json").write_text(
        json.dumps(base_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    rows: list[dict[str, object]] = []
    for line_index in base_net.line.index:
        contingency_net = copy.deepcopy(base_net)
        contingency_net.line.at[line_index, "in_service"] = False

        row: dict[str, object] = {
            "outaged_line": int(line_index),
            "from_bus": int(base_net.line.at[line_index, "from_bus"]),
            "to_bus": int(base_net.line.at[line_index, "to_bus"]),
            "from_bus_label": bus_label(base_net, int(base_net.line.at[line_index, "from_bus"])),
            "to_bus_label": bus_label(base_net, int(base_net.line.at[line_index, "to_bus"])),
        }
        row.update(run_power_flow(contingency_net))
        rows.append(row)

    results = pd.DataFrame(rows).sort_values("outaged_line").reset_index(drop=True)
    results["islanded_buses"] = results["islanded_buses"].apply(
        lambda buses: " ".join(str(bus) for bus in buses)
    )
    results.to_csv(DATA_DIR / "n1_results.csv", index=False)

    print("BASE CASE")
    for key, value in base_payload["results"].items():
        print(f"  {key}: {value}")

    print("\nN-1 RESULTS (ordered by outaged line)")
    columns = [
        "outaged_line",
        "from_bus_label",
        "to_bus_label",
        "status",
        "converged",
        "iterations",
        "buses_with_results",
        "lines_with_results",
        "vmin_pu",
        "max_line_loading_percent",
        "voltage_violations",
        "strict_voltage_violations",
        "line_overloads",
        "islanded_buses",
    ]
    print(results[columns].to_string(index=False))
    print(f"\nCSV written to: {DATA_DIR / 'n1_results.csv'}")
    print(f"Base case written to: {DATA_DIR / 'base_case.json'}")


if __name__ == "__main__":
    main()
