from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _as_array(value: Any, dtype: Any = float) -> np.ndarray:
    return np.asarray(value, dtype=dtype)

@dataclass(frozen=True)
class DieselUnit:
    pmax: float
    pmin: float
    c_var: float
    c_on: float = 0.0
    c_fix: float = 0.0

@dataclass(frozen=True)
class DieselFleet:
    units: tuple[DieselUnit, ...]

    @property
    def n_units(self) -> int:
        return len(self.units)

    @property
    def pmax(self) -> np.ndarray:
        return _as_array([unit.pmax for unit in self.units])

    @property
    def pmin(self) -> np.ndarray:
        return _as_array([unit.pmin for unit in self.units])

    @property
    def c_var(self) -> np.ndarray:
        return _as_array([unit.c_var for unit in self.units])

    @property
    def c_on(self) -> np.ndarray:
        return _as_array([unit.c_on for unit in self.units])

    @property
    def c_fix(self) -> np.ndarray:
        return _as_array([unit.c_fix for unit in self.units])


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} tiene que ser un entero positivo; se recibió {value}.")
    number = int(value)
    if number < 1:
        raise ValueError(f"{name} tiene que ser un entero positivo; se recibió {number}.")
    return number


def _finite_cost(value: Any, name: str, *, strictly_positive: bool) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} tiene que ser numérico; se recibió {value}.") from error
    if not np.isfinite(number):
        raise ValueError(f"{name} tiene que ser finito; se recibió {value}.")
    if strictly_positive and number <= 0.0:
        raise ValueError(f"{name} tiene que ser > 0; se recibió {number}.")
    if not strictly_positive and number < 0.0:
        raise ValueError(f"{name} tiene que ser >= 0; se recibió {number}.")
    return number


def robust_alpha_hat(
    t_dw: Any,
    t_up: Any,
    horizon: int,
    v_pr: float,
    c_pr: float,
    v_co: float,
    c_co: float,
) -> np.ndarray:
    """Costo robusto de iniciar el mantenimiento, uno por turbina y día.

    ``t_dw[j]`` y ``t_up[j]`` son el box de falla de la turbina ``j``, en días
    1-based desde el pronóstico. La columna ``t - 1`` es el día físico ``t``.

    Para cada realización entera ``tau`` del box,

    ``alpha_t(tau) = v_pr (tau - t) + c_pr`` si ``tau > t``,
    y ``v_co (t - tau) + c_co`` si ``tau <= t``.

    ``alpha_hat[j, t]`` es el máximo de esa pieza sobre el box. La forma
    cerrada evalúa la preventiva en ``t_up`` y la correctiva en ``t_dw``:

    - ``t < t_dw``: preventiva;
    - ``t_dw <= t < t_up``: el máximo de las dos;
    - ``t >= t_up``: correctiva.
    """
    horizon = _positive_int(horizon, "El horizonte")
    lower = np.asarray(t_dw, dtype=float).reshape(-1)
    upper = np.asarray(t_up, dtype=float).reshape(-1)
    if lower.shape != upper.shape:
        raise ValueError(
            f"t_dw tiene {lower.size} turbinas y t_up tiene {upper.size}."
        )
    if lower.size == 0:
        raise ValueError("alpha_hat necesita al menos una turbina.")
    if not np.isfinite(lower).all() or not np.isfinite(upper).all():
        raise ValueError("Los límites del box de falla tienen que ser finitos.")
    if np.any(lower != np.floor(lower)) or np.any(upper != np.floor(upper)):
        raise ValueError("Los límites del box de falla tienen que ser días enteros.")
    if np.any(lower < 1.0):
        raise ValueError("t_dw cuenta días desde 1.")
    if np.any(lower > upper):
        raise ValueError("Cada turbina necesita t_dw <= t_up.")

    days = np.arange(1, horizon + 1, dtype=float)[None, :]
    lower = lower[:, None]
    upper = upper[:, None]
    preventive = v_pr * (upper - days) + c_pr
    corrective = v_co * (days - lower) + c_co
    mixed = np.maximum(preventive, corrective)
    return np.where(days < lower, preventive, np.where(days < upper, mixed, corrective))


@dataclass(frozen=True)
class WindPark:
    """Parque eólico. ``components`` y ``alpha_hat`` son propios de cada turbina.

    La fila ``i`` de ``alpha_hat`` es el costo robusto de iniciar el
    mantenimiento de esa turbina en cada día del horizonte. Sale de su box
    ``[t_failure, t_up]`` y no se comparte con las otras turbinas del parque.
    """

    prated: float
    n_turbines: int
    components: int | np.ndarray | None = None
    t_0: np.ndarray | None = None
    t_failure: np.ndarray | None = None
    t_up: np.ndarray | None = None
    alpha_hat: np.ndarray | None = None
    seed: int = 0

    def __post_init__(self) -> None:
        n_turbines = int(self.n_turbines)
        if n_turbines < 1:
            raise ValueError(
                f"Un parque necesita al menos una turbina; se recibió {n_turbines}."
            )
        object.__setattr__(self, "n_turbines", n_turbines)

        object.__setattr__(
            self, "components", _turbine_components(self.components, n_turbines, self.seed)
        )

        if self.t_0 is None:
            raise ValueError("Cada parque necesita t_0: un día de pronóstico por turbina.")
        days = np.asarray(self.t_0, dtype=int).reshape(-1)
        if days.size == 1:
            days = np.full(n_turbines, int(days[0]), dtype=int)
        if days.size != n_turbines:
            raise ValueError(
                f"t_0 tiene {days.size} días y el parque tiene {n_turbines} turbinas."
            )
        if np.any(days < 1):
            raise ValueError(f"t_0 cuenta días desde 1; se recibió {days.tolist()}.")
        object.__setattr__(self, "t_0", days.copy())

        object.__setattr__(self, "t_failure", _turbine_days(self.t_failure, n_turbines, "t_failure"))
        object.__setattr__(self, "t_up", _turbine_days(self.t_up, n_turbines, "t_up"))
        if self.alpha_hat is not None:
            costs = np.asarray(self.alpha_hat, dtype=float)
            if costs.ndim != 2 or costs.shape[0] != n_turbines:
                raise ValueError(
                    f"alpha_hat tiene que tener una fila por turbina; se recibió forma {costs.shape}."
                )
            if not np.isfinite(costs).all():
                raise ValueError("alpha_hat tiene que ser finito.")
            object.__setattr__(self, "alpha_hat", costs.copy())

    def assign_alpha_hat(
        self,
        horizon: int,
        v_pr: float,
        c_pr: float,
        v_co: float,
        c_co: float,
    ) -> None:
        """Calcula ``alpha_hat`` con forma ``(n_turbinas, horizonte)``."""
        if np.any(self.t_failure < 1) or np.any(self.t_up < 1):
            raise ValueError(
                "Cada turbina necesita su box [t_failure, t_up] antes de calcular alpha_hat."
            )
        costs = robust_alpha_hat(
            self.t_failure,
            self.t_up,
            horizon,
            v_pr,
            c_pr,
            v_co,
            c_co,
        )
        object.__setattr__(self, "alpha_hat", costs)

    @property
    def park_rated(self) -> float:
        return float(self.n_turbines) * float(self.prated)


def _turbine_components(value: Any, n_turbines: int, seed: int) -> np.ndarray:
    """Un componente 1–100 por turbina. Un escalar se copia a todo el parque."""
    if value is None:
        component = int(np.random.default_rng(seed).integers(1, 101))
        return np.full(n_turbines, component, dtype=int)
    components = np.asarray(value, dtype=int).reshape(-1)
    if components.size == 1:
        components = np.full(n_turbines, int(components[0]), dtype=int)
    if components.size != n_turbines:
        raise ValueError(
            f"components tiene {components.size} valores y el parque tiene {n_turbines} turbinas."
        )
    if np.any((components < 1) | (components > 100)):
        raise ValueError(
            f"Cada componente tiene que estar entre 1 y 100; se recibió {components.tolist()}."
        )
    return components.copy()


def _turbine_days(value: Any, n_turbines: int, name: str) -> np.ndarray:
    if value is None:
        return np.zeros(n_turbines, dtype=int)
    days = np.asarray(value, dtype=int).reshape(-1)
    if days.size != n_turbines:
        raise ValueError(
            f"{name} tiene {days.size} valores y el parque tiene {n_turbines} turbinas."
        )
    return days.copy()


@dataclass(frozen=True)
class WindFleet:
    """Flota eólica.

    ``maintenance_days`` es la duración del mantenimiento (Y) y
    ``maintenance_crew`` es cuántas turbinas puede atender una cuadrilla el
    mismo día (N_CREW). ``max_crews`` es cuántas cuadrillas pueden trabajar el
    mismo día (M_CREW) y ``crew_cost`` es el costo diario de cada una.
    Los coeficientes del costo robusto son comunes: lo que cambia por turbina
    es el box de falla, y con él ``alpha_hat``.
    """

    parks: tuple[WindPark, ...]
    maintenance_days: int = 7
    maintenance_crew: int = 4
    crew_cost: float = 1000.0
    max_crews: int = 2
    v_pr: float = 10.0
    c_pr: float = 500.0
    v_co: float = 50.0
    c_co: float = 3000.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "maintenance_days", _positive_int(self.maintenance_days, "maintenance_days")
        )
        object.__setattr__(
            self, "maintenance_crew", _positive_int(self.maintenance_crew, "maintenance_crew")
        )
        object.__setattr__(
            self, "max_crews", _positive_int(self.max_crews, "max_crews")
        )
        object.__setattr__(
            self, "crew_cost", _finite_cost(self.crew_cost, "crew_cost", strictly_positive=False)
        )
        object.__setattr__(self, "v_pr", _finite_cost(self.v_pr, "v_pr", strictly_positive=True))
        object.__setattr__(self, "c_pr", _finite_cost(self.c_pr, "c_pr", strictly_positive=False))
        object.__setattr__(self, "v_co", _finite_cost(self.v_co, "v_co", strictly_positive=True))
        object.__setattr__(self, "c_co", _finite_cost(self.c_co, "c_co", strictly_positive=False))

    def assign_alpha_hat(self, horizon: int) -> None:
        """Costo robusto de cada turbina. Exige el box de falla ya cargado."""
        horizon = _positive_int(horizon, "El horizonte")
        if self.maintenance_days > horizon:
            raise ValueError(
                f"maintenance_days ({self.maintenance_days}) no cabe en el horizonte ({horizon})."
            )
        for park in self.parks:
            park.assign_alpha_hat(horizon, self.v_pr, self.c_pr, self.v_co, self.c_co)

    @property
    def n_parks(self) -> int:
        return len(self.parks)

    @property
    def n_turbines_total(self) -> int:
        return int(sum(park.n_turbines for park in self.parks))

    @property
    def prated(self) -> np.ndarray:
        return _as_array([park.prated for park in self.parks])

    @property
    def n_turbines(self) -> np.ndarray:
        return _as_array([park.n_turbines for park in self.parks], dtype=int)

    @property
    def G_r(self) -> list[int]:
        """Número de turbinas por parque, |G_w^r|."""
        return [int(park.n_turbines) for park in self.parks]

    def J_r(self, horizon: int) -> list[tuple[int, int]]:
        """Turbinas con falla dentro del horizonte: pares (j, w)."""
        horizon = _positive_int(horizon, "El horizonte")
        return [
            (j, w)
            for w, park in enumerate(self.parks)
            for j in range(park.n_turbines)
            if int(park.t_failure[j]) <= horizon
        ]

    @property
    def components(self) -> tuple[np.ndarray, ...]:
        return tuple(park.components for park in self.parks)

    @property
    def t_0(self) -> tuple[np.ndarray, ...]:
        return tuple(park.t_0 for park in self.parks)

    @property
    def t_failure(self) -> tuple[np.ndarray, ...]:
        return tuple(park.t_failure for park in self.parks)

    @property
    def t_up(self) -> tuple[np.ndarray, ...]:
        return tuple(park.t_up for park in self.parks)

    @property
    def alpha_hat(self) -> tuple[np.ndarray, ...]:
        missing = [i for i, park in enumerate(self.parks) if park.alpha_hat is None]
        if missing:
            raise ValueError(
                "alpha_hat todavía no está calculado. "
                "Hay que cargar el box de falla y llamar a assign_alpha_hat."
            )
        return tuple(park.alpha_hat for park in self.parks)

    @property
    def park_rated(self) -> np.ndarray:
        return _as_array([park.park_rated for park in self.parks])


@dataclass(frozen=True)
class Microgrid:
    diesel: DieselFleet
    wind: WindFleet
    c_ens: float
    horizon: int
    hours_per_day: int = 24



