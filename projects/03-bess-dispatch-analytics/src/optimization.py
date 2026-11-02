"""24-period MILP dispatch: minimise grid purchase cost with a BESS.

Model (dt hours, energy kWh, power kW, price per kWh)
-----------------------------------------------------
Variables per period t = 0..T-1
    c_t  >= 0     grid-side charging power
    d_t  >= 0     grid-side discharging power
    s_t           stored energy at end of period t
    u_t  in {0,1} 1 when charging is allowed in period t

Constraints
    s_t = s_{t-1} + eta_charge * c_t * dt - d_t * dt / eta_discharge   (s_{-1} = E0)
    0 <= c_t <= P_charge_max * u_t
    0 <= d_t <= P_discharge_max * (1 - u_t)          <- exclusivity, not assumed
    grid_t = load_t + c_t - d_t >= 0                 <- no export in this study
    SOC_min <= s_t <= SOC_max
    s_{T-1} = terminal_energy_kwh (when given)

Objective
    minimise sum_t price_t * dt * (c_t - d_t)
    (the load term is constant, so it is excluded from the solver objective and
    added back when reporting the total cost)

Solver: HiGHS via `highspy`. Non-optimal statuses raise :class:`OptimizationError`;
no fabricated results are returned on failure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import highspy
import numpy as np

from bess_model import BessParams, InvalidParameter


class OptimizationError(RuntimeError):
    """Solver failed or returned a non-optimal status."""


class InfeasibleProblem(OptimizationError):
    """The requested dispatch problem has no feasible schedule."""


class InvalidInput(InvalidParameter):
    """Malformed load/price input or inconsistent problem settings."""


@dataclass(frozen=True)
class OptimizationResult:
    dt_h: float
    period_prices: tuple[float, ...]
    charge_kw: tuple[float, ...]
    discharge_kw: tuple[float, ...]
    grid_kw: tuple[float, ...]
    energy_kwh: tuple[float, ...]
    energy_start_kwh: float
    energy_end_kwh: float
    purchase_cost: float
    solver_status: str
    peak_grid_kw: float = 0.0
    demand_charge_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        """Energy purchase cost plus demand charge."""
        return self.purchase_cost + self.demand_charge_cost

    @property
    def charged_kwh(self) -> float:
        return sum(self.charge_kw) * self.dt_h

    @property
    def discharged_kwh(self) -> float:
        return sum(self.discharge_kw) * self.dt_h

    @property
    def soc_start(self) -> float:
        return self.energy_start_kwh

    @property
    def soc_end(self) -> float:
        return self.energy_end_kwh


def _check_series(name: str, values: Sequence[float], allow_negative: bool = False) -> tuple[float, ...]:
    series = tuple(values)
    if not series:
        raise InvalidInput(f"{name} 不能为空")
    result: list[float] = []
    for index, value in enumerate(series):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidInput(f"{name}[{index}] 必须是数值，收到 {value!r}")
        value = float(value)
        if not math.isfinite(value):
            raise InvalidInput(f"{name}[{index}] 必须是有限值")
        if not allow_negative and value < 0:
            raise InvalidInput(f"{name}[{index}] 不能为负：{value}")
        result.append(value)
    return tuple(result)


def purchase_cost(grid_kw: Sequence[float], price_per_kwh: Sequence[float], dt_h: float) -> float:
    """Independent cost evaluation: sum(price * grid * dt)."""
    if len(grid_kw) != len(price_per_kwh):
        raise InvalidInput("grid_kw 与 price_per_kwh 长度必须一致")
    return float(sum(p * g * dt_h for p, g in zip(price_per_kwh, grid_kw)))


def build_grid_power(
    load_kw: Sequence[float],
    charge_kw: Sequence[float],
    discharge_kw: Sequence[float],
) -> tuple[float, ...]:
    return tuple(l + c - d for l, c, d in zip(load_kw, charge_kw, discharge_kw))


def solve_dispatch(
    load_kw: Sequence[float],
    price_per_kwh: Sequence[float],
    params: BessParams,
    initial_energy_kwh: float,
    dt_h: float = 1.0,
    terminal_energy_kwh: float | None = None,
    demand_charge_per_kw: float = 0.0,
) -> OptimizationResult:
    """Solve the MILP; raises on infeasible or non-optimal outcomes.

    ``demand_charge_per_kw`` adds a peak-demand term (元/kW, already expressed
    for this horizon): the objective becomes
    ``sum(price_t * grid_t * dt) + rate * max_t(grid_t)``.
    """
    load = _check_series("load_kw", load_kw)
    price = _check_series("price_per_kwh", price_per_kwh, allow_negative=False)
    if len(load) != len(price):
        raise InvalidInput(
            f"load_kw 与 price_per_kwh 长度必须一致：{len(load)} vs {len(price)}"
        )
    if dt_h <= 0 or not math.isfinite(dt_h):
        raise InvalidInput(f"dt_h 必须为正的有限值，收到 {dt_h}")
    if demand_charge_per_kw < 0 or not math.isfinite(demand_charge_per_kw):
        raise InvalidInput(f"需量电价必须为非负有限值，收到 {demand_charge_per_kw}")
    if not (params.usable_min_kwh <= initial_energy_kwh <= params.usable_max_kwh):
        raise InvalidInput(
            f"初始储能量 {initial_energy_kwh} kWh 超出可用区间 "
            f"[{params.usable_min_kwh}, {params.usable_max_kwh}]"
        )
    if terminal_energy_kwh is not None and not (
        params.usable_min_kwh <= terminal_energy_kwh <= params.usable_max_kwh
    ):
        raise InvalidInput(
            f"期末储能量 {terminal_energy_kwh} kWh 超出可用区间 "
            f"[{params.usable_min_kwh}, {params.usable_max_kwh}]"
        )

    periods = len(load)
    idx_c = np.arange(periods, dtype=np.int32)
    idx_d = np.arange(periods, 2 * periods, dtype=np.int32)
    idx_s = np.arange(2 * periods, 3 * periods, dtype=np.int32)
    idx_u = np.arange(3 * periods, 4 * periods, dtype=np.int32)

    lower = np.zeros(4 * periods + (1 if demand_charge_per_kw > 0 else 0))
    upper = np.zeros(4 * periods + (1 if demand_charge_per_kw > 0 else 0))
    lower[idx_c] = 0.0
    upper[idx_c] = params.p_charge_max_kw
    lower[idx_d] = 0.0
    upper[idx_d] = params.p_discharge_max_kw
    lower[idx_s] = params.usable_min_kwh
    upper[idx_s] = params.usable_max_kwh
    lower[idx_u] = 0.0
    upper[idx_u] = 1.0
    has_demand = demand_charge_per_kw > 0
    n_vars = 4 * periods + (1 if has_demand else 0)
    idx_peak = 4 * periods
    if has_demand:
        lower[idx_peak] = 0.0
        upper[idx_peak] = float(max(load)) + params.p_charge_max_kw
    if terminal_energy_kwh is not None:
        lower[idx_s[-1]] = terminal_energy_kwh
        upper[idx_s[-1]] = terminal_energy_kwh

    cost = np.zeros(n_vars)
    cost[idx_c] = [p * dt_h for p in price]
    cost[idx_d] = [-p * dt_h for p in price]
    if has_demand:
        cost[idx_peak] = demand_charge_per_kw

    eta_c_dt = params.eta_charge * dt_h
    dt_over_eta_d = dt_h / params.eta_discharge

    n_rows = 4 * periods + (periods if has_demand else 0)
    row_lower = np.empty(n_rows)
    row_upper = np.empty(n_rows)
    starts: list[int] = [0]
    indices: list[int] = []
    values: list[float] = []
    row_index = 0

    def add_row(coeffs: dict[int, float], low: float, high: float) -> None:
        nonlocal row_index
        row_lower[row_index] = low
        row_upper[row_index] = high
        for column, coefficient in coeffs.items():
            indices.append(column)
            values.append(coefficient)
        starts.append(len(indices))
        row_index += 1

    # 1) SOC recursion, equality rows
    for t in range(periods):
        coeffs = {
            int(idx_s[t]): 1.0,
            int(idx_c[t]): -eta_c_dt,
            int(idx_d[t]): dt_over_eta_d,
        }
        if t > 0:
            coeffs[int(idx_s[t - 1])] = -1.0
        rhs = initial_energy_kwh if t == 0 else 0.0
        add_row(coeffs, rhs, rhs)

    # 2) exclusivity: c_t <= Pc * u_t  and  d_t <= Pd * (1 - u_t)
    for t in range(periods):
        add_row(
            {int(idx_c[t]): 1.0, int(idx_u[t]): -params.p_charge_max_kw},
            -highspy.kHighsInf,
            0.0,
        )
        add_row(
            {int(idx_d[t]): 1.0, int(idx_u[t]): params.p_discharge_max_kw},
            -highspy.kHighsInf,
            params.p_discharge_max_kw,
        )

    # 3) no export: load_t + c_t - d_t >= 0
    for t in range(periods):
        add_row({int(idx_d[t]): 1.0, int(idx_c[t]): -1.0}, -highspy.kHighsInf, load[t])

    # 4) peak demand: peak >= grid_t
    if has_demand:
        for t in range(periods):
            add_row(
                {int(idx_peak): 1.0, int(idx_c[t]): -1.0, int(idx_d[t]): 1.0},
                load[t],
                highspy.kHighsInf,
            )

    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    highs.addVars(n_vars, lower, upper)
    highs.changeColsCost(n_vars, np.arange(n_vars, dtype=np.int32), cost)
    highs.changeColsIntegrality(
        periods,
        idx_u,
        np.full(periods, highspy.HighsVarType.kInteger),
    )
    highs.addRows(
        n_rows,
        row_lower,
        row_upper,
        len(indices),
        np.array(starts[:-1], dtype=np.int32),
        np.array(indices, dtype=np.int32),
        np.array(values, dtype=float),
    )

    highs.run()
    status = highs.getModelStatus()
    if status == highspy.HighsModelStatus.kInfeasible:
        raise InfeasibleProblem("线性规划/混合整数问题不可行：请检查负荷、SOC 窗口与期末约束")
    if status != highspy.HighsModelStatus.kOptimal:
        raise OptimizationError(f"求解器未得到最优解，状态={status}")

    solution = highs.getSolution().col_value
    charge = tuple(float(solution[i]) for i in idx_c)
    discharge = tuple(float(solution[i]) for i in idx_d)
    energy = tuple(float(solution[i]) for i in idx_s)
    grid = build_grid_power(load, charge, discharge)
    peak = max(grid) if grid else 0.0

    return OptimizationResult(
        dt_h=dt_h,
        period_prices=price,
        charge_kw=charge,
        discharge_kw=discharge,
        grid_kw=grid,
        energy_kwh=energy,
        energy_start_kwh=initial_energy_kwh,
        energy_end_kwh=energy[-1],
        purchase_cost=purchase_cost(grid, price, dt_h),
        solver_status=str(status),
        peak_grid_kw=peak,
        demand_charge_cost=demand_charge_per_kw * peak,
    )
