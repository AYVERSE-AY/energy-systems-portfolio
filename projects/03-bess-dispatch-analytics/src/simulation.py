"""Multi-period BESS simulation built on the single-step model.

Units: load / charge / discharge / grid power in kW, energy in kWh, ``dt_h`` in h.
Sign convention follows :mod:`bess_model`: charge and discharge are
**non-negative grid-side** powers, so grid-side balance is

    p_grid[t] = load_kw[t] + charge_kw[t] - discharge_kw[t]

while the battery-internal recursion (with losses) is

    E[t+1] = E[t] + eta_charge * charge_kw[t] * dt - discharge_kw[t] * dt / eta_discharge

``p_grid`` is therefore **not** the battery energy change: the difference is the
conversion loss.  Infeasible requests propagate as the exceptions defined by
:mod:`bess_model`; nothing is clipped silently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from bess_model import BessModel, BessModelError, BessParams, Mode


class InvalidSequence(BessModelError):
    """Input time series is malformed (length, sign, finiteness, dt)."""


@dataclass(frozen=True)
class PeriodRecord:
    step: int
    load_kw: float
    charge_kw: float
    discharge_kw: float
    grid_kw: float
    mode: str
    energy_before_kwh: float
    energy_after_kwh: float
    soc_before: float
    soc_after: float


@dataclass(frozen=True)
class SimulationResult:
    dt_h: float
    periods: tuple[PeriodRecord, ...]
    initial_energy_kwh: float
    final_energy_kwh: float
    energy_min_kwh: float
    energy_max_kwh: float
    charged_from_grid_kwh: float
    discharged_to_grid_kwh: float
    battery_delta_kwh: float
    losses_kwh: float

    @property
    def steps(self) -> int:
        return len(self.periods)

    def to_rows(self) -> list[dict[str, float | int | str]]:
        return [
            {
                "step": r.step,
                "load_kw": r.load_kw,
                "charge_kw": r.charge_kw,
                "discharge_kw": r.discharge_kw,
                "grid_kw": r.grid_kw,
                "mode": r.mode,
                "energy_before_kwh": r.energy_before_kwh,
                "energy_after_kwh": r.energy_after_kwh,
                "soc_before": r.soc_before,
                "soc_after": r.soc_after,
            }
            for r in self.periods
        ]


def _as_series(name: str, values: Sequence[float], *, allow_negative: bool) -> tuple[float, ...]:
    series = tuple(values)
    if not series:
        raise InvalidSequence(f"{name} 不能为空序列")
    result: list[float] = []
    for index, value in enumerate(series):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidSequence(f"{name}[{index}] 必须是数值，收到 {value!r}")
        value = float(value)
        if not math.isfinite(value):
            raise InvalidSequence(f"{name}[{index}] 必须是有限值，收到 {value}")
        if not allow_negative and value < 0:
            raise InvalidSequence(f"{name}[{index}] 不能为负：{value}")
        result.append(value)
    return tuple(result)


def simulate(
    params: BessParams,
    initial_energy_kwh: float,
    load_kw: Sequence[float],
    charge_kw: Sequence[float],
    discharge_kw: Sequence[float],
    dt_h: float,
) -> SimulationResult:
    """Run a full period sequence. Any infeasible step raises; no clipping."""
    if dt_h <= 0 or not math.isfinite(dt_h):
        raise InvalidSequence(f"dt_h 必须为正的有限值，收到 {dt_h}")

    load = _as_series("load_kw", load_kw, allow_negative=False)
    charge = _as_series("charge_kw", charge_kw, allow_negative=False)
    discharge = _as_series("discharge_kw", discharge_kw, allow_negative=False)

    lengths = {len(load), len(charge), len(discharge)}
    if len(lengths) != 1:
        raise InvalidSequence(
            "负荷/充电/放电序列长度必须一致："
            f"load={len(load)}, charge={len(charge)}, discharge={len(discharge)}"
        )

    model = BessModel(params, initial_energy_kwh=initial_energy_kwh)
    records: list[PeriodRecord] = []
    charged_from_grid = 0.0
    discharged_to_grid = 0.0
    losses = 0.0

    for step, (p_load, p_charge, p_discharge) in enumerate(zip(load, charge, discharge)):
        soc_before = model.soc
        energy_before = model.energy_kwh
        result = model.step(charge_kw=p_charge, discharge_kw=p_discharge, dt_h=dt_h)

        charged_from_grid += p_charge * dt_h
        discharged_to_grid += p_discharge * dt_h
        # Conversion loss: what the grid supplied minus what the battery kept,
        # plus what the battery released minus what the grid received.
        losses += p_charge * dt_h * (1.0 - params.eta_charge)
        losses += p_discharge * dt_h * (1.0 / params.eta_discharge - 1.0)

        records.append(
            PeriodRecord(
                step=step,
                load_kw=p_load,
                charge_kw=p_charge,
                discharge_kw=p_discharge,
                grid_kw=p_load + p_charge - p_discharge,
                mode=result.mode.value if isinstance(result.mode, Mode) else str(result.mode),
                energy_before_kwh=energy_before,
                energy_after_kwh=result.energy_after_kwh,
                soc_before=soc_before,
                soc_after=model.soc,
            )
        )

    energies = [r.energy_after_kwh for r in records]
    return SimulationResult(
        dt_h=float(dt_h),
        periods=tuple(records),
        initial_energy_kwh=records[0].energy_before_kwh,
        final_energy_kwh=records[-1].energy_after_kwh,
        energy_min_kwh=min([records[0].energy_before_kwh, *energies]),
        energy_max_kwh=max([records[0].energy_before_kwh, *energies]),
        charged_from_grid_kwh=charged_from_grid,
        discharged_to_grid_kwh=discharged_to_grid,
        battery_delta_kwh=records[-1].energy_after_kwh - records[0].energy_before_kwh,
        losses_kwh=losses,
    )
