"""Single-step BESS model: energy balance, SOC recursion and power limits.

Conventions (fixed here, referenced by tests and later dispatch code)
---------------------------------------------------------------------
Units
    energy  : kWh
    power   : kW
    time    : h  (``dt_h``, default 0.25 h = 15 min, the typical C&I step)

Sign convention
    ``charge_kw`` and ``discharge_kw`` are **non-negative** grid-side powers.
    A step is either charging, discharging or idle -- never both.  Idle means
    both are exactly zero.

Energy balance (grid side -> stored energy)
    E_next = E_t + eta_charge * charge_kw * dt_h - discharge_kw * dt_h / eta_discharge

    Charging : stored gain  = eta_charge * P * dt          (grid pays P * dt)
    Discharging: stored loss = P * dt / eta_discharge      (grid receives P * dt)

Policy for infeasible requests
    The model **rejects** (raises :class:`InfeasibleRequest`) any request that
    would violate the power limit or the SOC window.  User input is never
    silently clipped.  Callers that want automatic clipping must clamp first
    with :meth:`BessModel.max_charge_kw` / :meth:`BessModel.max_discharge_kw`,
    which return the feasible headroom for the current state and step.

State of charge
    ``soc`` is the fraction of nameplate energy (0..1).  The usable window is
    ``[soc_min * e_max, soc_max * e_max]``; ``e_max == 0`` degenerates to an
    idle-only device without division by zero.

Simplification（简化假设，非设备实测参数）
    Charge and discharge efficiencies are modelled as **constants** independent
    of power, state of charge and temperature.  Defaults (0.95 / 0.95, i.e. a
    round-trip of 0.9025) are placeholder assumptions for a generic
    lithium-ion BESS, not values taken from any datasheet.  A real deployment
    must calibrate them; no manufacturer data is claimed here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

DEFAULT_DT_H = 0.25
BOUNDS_EPS_KWH = 1e-9


class BessModelError(ValueError):
    """Base class for model input errors."""


class InvalidParameter(BessModelError):
    """A physical parameter is outside its valid range."""


class InfeasibleRequest(BessModelError):
    """The requested charge/discharge violates power or SOC limits."""


class Mode(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


def _check_finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InvalidParameter(f"{name} 必须是数值，收到 {value!r}")
    if not math.isfinite(value):
        raise InvalidParameter(f"{name} 必须是有限值，收到 {value!r}")
    return float(value)


@dataclass(frozen=True)
class BessParams:
    """Nameplate parameters. Energy in kWh, power in kW, efficiencies in (0, 1]."""

    e_max_kwh: float
    p_charge_max_kw: float
    p_discharge_max_kw: float
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    soc_min_frac: float = 0.05
    soc_max_frac: float = 0.95

    def __post_init__(self) -> None:
        object.__setattr__(self, "e_max_kwh", _check_finite("e_max_kwh", self.e_max_kwh))
        object.__setattr__(
            self, "p_charge_max_kw", _check_finite("p_charge_max_kw", self.p_charge_max_kw)
        )
        object.__setattr__(
            self,
            "p_discharge_max_kw",
            _check_finite("p_discharge_max_kw", self.p_discharge_max_kw),
        )
        object.__setattr__(self, "eta_charge", _check_finite("eta_charge", self.eta_charge))
        object.__setattr__(
            self, "eta_discharge", _check_finite("eta_discharge", self.eta_discharge)
        )
        object.__setattr__(self, "soc_min_frac", _check_finite("soc_min_frac", self.soc_min_frac))
        object.__setattr__(self, "soc_max_frac", _check_finite("soc_max_frac", self.soc_max_frac))

        if self.e_max_kwh < 0:
            raise InvalidParameter(f"e_max_kwh 不能为负：{self.e_max_kwh}")
        if self.p_charge_max_kw < 0 or self.p_discharge_max_kw < 0:
            raise InvalidParameter("充放电功率上限不能为负")
        for name in ("eta_charge", "eta_discharge"):
            value = getattr(self, name)
            if not 0.0 < value <= 1.0:
                raise InvalidParameter(f"{name} 必须在 (0, 1] 内：{value}")
        if not 0.0 <= self.soc_min_frac < self.soc_max_frac <= 1.0:
            raise InvalidParameter(
                "SOC 区间必须满足 0 <= soc_min_frac < soc_max_frac <= 1："
                f"{self.soc_min_frac} / {self.soc_max_frac}"
            )

    @property
    def usable_min_kwh(self) -> float:
        return self.soc_min_frac * self.e_max_kwh

    @property
    def usable_max_kwh(self) -> float:
        return self.soc_max_frac * self.e_max_kwh

    @property
    def eta_roundtrip(self) -> float:
        return self.eta_charge * self.eta_discharge


@dataclass(frozen=True)
class StepResult:
    """Outcome of one time step."""

    mode: Mode
    energy_before_kwh: float
    energy_after_kwh: float
    charge_kw: float
    discharge_kw: float
    dt_h: float

    @property
    def energy_delta_kwh(self) -> float:
        return self.energy_after_kwh - self.energy_before_kwh


class BessModel:
    """Stateful single-step model. All powers are grid-side and non-negative."""

    def __init__(self, params: BessParams, initial_energy_kwh: float | None = None) -> None:
        self.params = params
        if initial_energy_kwh is None:
            initial_energy_kwh = 0.5 * (params.usable_min_kwh + params.usable_max_kwh)
        energy = _check_finite("initial_energy_kwh", initial_energy_kwh)
        self._check_energy_window(energy, context="初始储能量")
        self._energy_kwh = energy

    # --- state -----------------------------------------------------------
    @property
    def energy_kwh(self) -> float:
        return self._energy_kwh

    @property
    def soc(self) -> float:
        if self.params.e_max_kwh == 0:
            return 0.0
        return self._energy_kwh / self.params.e_max_kwh

    # --- validation helpers ---------------------------------------------
    def _check_energy_window(self, energy_kwh: float, context: str) -> None:
        low = self.params.usable_min_kwh
        high = self.params.usable_max_kwh
        if energy_kwh < low - BOUNDS_EPS_KWH or energy_kwh > high + BOUNDS_EPS_KWH:
            raise InvalidParameter(
                f"{context} {energy_kwh:.6f} kWh 超出可用区间 [{low:.6f}, {high:.6f}]"
            )

    @staticmethod
    def _check_dt(dt_h: float) -> float:
        dt = _check_finite("dt_h", dt_h)
        if dt <= 0:
            raise InvalidParameter(f"dt_h 必须为正：{dt}")
        return dt

    # --- feasibility helpers --------------------------------------------
    def max_charge_kw(self, dt_h: float = DEFAULT_DT_H) -> float:
        """Largest feasible grid-side charging power for the current state."""
        dt = self._check_dt(dt_h)
        p = self.params
        if p.e_max_kwh == 0:
            return 0.0
        headroom = max(p.usable_max_kwh - self._energy_kwh, 0.0)
        return min(p.p_charge_max_kw, headroom / (p.eta_charge * dt))

    def max_discharge_kw(self, dt_h: float = DEFAULT_DT_H) -> float:
        """Largest feasible grid-side discharging power for the current state."""
        dt = self._check_dt(dt_h)
        p = self.params
        if p.e_max_kwh == 0:
            return 0.0
        available = max(self._energy_kwh - p.usable_min_kwh, 0.0)
        return min(p.p_discharge_max_kw, available * p.eta_discharge / dt)

    # --- the step --------------------------------------------------------
    def step(
        self,
        *,
        charge_kw: float = 0.0,
        discharge_kw: float = 0.0,
        dt_h: float = DEFAULT_DT_H,
    ) -> StepResult:
        """Advance one step. Raises on invalid or infeasible requests."""
        dt = self._check_dt(dt_h)
        p_charge = _check_finite("charge_kw", charge_kw)
        p_discharge = _check_finite("discharge_kw", discharge_kw)
        if p_charge < 0 or p_discharge < 0:
            raise InvalidParameter(
                f"充放电功率必须以非负数表示：charge_kw={p_charge}, discharge_kw={p_discharge}"
            )
        if p_charge > 0 and p_discharge > 0:
            raise InfeasibleRequest(
                f"同一时刻不允许同时充放电：charge_kw={p_charge}, discharge_kw={p_discharge}"
            )

        p = self.params
        energy_before = self._energy_kwh

        if p.e_max_kwh == 0 and (p_charge > 0 or p_discharge > 0):
            raise InfeasibleRequest("零容量储能只能待机")

        if p_charge > p.p_charge_max_kw:
            raise InfeasibleRequest(
                f"充电功率 {p_charge} kW 超过上限 {p.p_charge_max_kw} kW"
            )
        if p_discharge > p.p_discharge_max_kw:
            raise InfeasibleRequest(
                f"放电功率 {p_discharge} kW 超过上限 {p.p_discharge_max_kw} kW"
            )

        stored_gain = p.eta_charge * p_charge * dt
        stored_loss = p_discharge * dt / p.eta_discharge
        energy_after = energy_before + stored_gain - stored_loss

        if energy_after > p.usable_max_kwh + BOUNDS_EPS_KWH:
            raise InfeasibleRequest(
                f"充电请求会超出 SOC 上限：{energy_after:.6f} > {p.usable_max_kwh:.6f} kWh"
            )
        if energy_after < p.usable_min_kwh - BOUNDS_EPS_KWH:
            raise InfeasibleRequest(
                f"放电请求会跌破 SOC 下限：{energy_after:.6f} < {p.usable_min_kwh:.6f} kWh"
            )

        energy_after = min(max(energy_after, p.usable_min_kwh), p.usable_max_kwh)

        if p_charge > 0:
            mode = Mode.CHARGE
        elif p_discharge > 0:
            mode = Mode.DISCHARGE
        else:
            mode = Mode.IDLE

        self._energy_kwh = energy_after
        return StepResult(
            mode=mode,
            energy_before_kwh=energy_before,
            energy_after_kwh=energy_after,
            charge_kw=p_charge,
            discharge_kw=p_discharge,
            dt_h=dt,
        )
