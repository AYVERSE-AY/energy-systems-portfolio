"""Power-flow metrics and N-1 validity checks shared by the BESS study.

This module mirrors the metric and classification logic of
`projects/01-ieee9-loadflow-n1/src/n1_analysis.py` (kept as a local copy so each
project directory stays runnable on its own).

Three concepts are reported separately: solver convergence (`converged`),
result validity (`status`, derived from topology connectivity plus result
coverage) and operating-limit compliance (`voltage_violations`,
`strict_voltage_violations`, `line_overloads`).
"""

from __future__ import annotations

import pandapower as pp

MAX_ITERATION = 10
TOLERANCE_MVA = 1e-8
V_MIN = 0.90
V_MAX = 1.10
STRICT_V_MIN = 0.95
STRICT_V_MAX = 1.05
LOADING_LIMIT_PERCENT = 100.0

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


def bus_label(net: pp.pandapowerNet, bus_index: int) -> str:
    """Human-readable bus number (pandapower case9 names buses "1".."9")."""
    name = net.bus.at[bus_index, "name"] if "name" in net.bus else None
    return str(name) if name is not None and str(name) != "nan" else str(bus_index + 1)


def run_power_flow(net: pp.pandapowerNet) -> dict[str, object]:
    """Run one AC power flow and classify the result."""
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
