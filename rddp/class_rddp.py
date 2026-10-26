"""Configuración y resultados del esquema RDDP."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _copy_array(value) -> np.ndarray:
    return np.array(value, dtype=float, copy=True)


def announce_solve(model_name: str, output_flag: int, tag: str = "") -> None:
    """Identifica el modelo en consola, justo antes del log de Gurobi."""
    if not output_flag:
        return
    label = f"{tag} | {model_name}" if tag else model_name
    print(f"\n>>> Resolviendo {label}", flush=True)


@dataclass(frozen=True)
class RDDPConfig:
    """Tolerancias, límites y método del oráculo de la cota superior.

    ``ub_method`` admite ``bilinear``, ``vertex`` y ``kkt``. Hoy solo corre
    ``bilinear``: los otros dos quedan reservados y el algoritmo avisa si se
    piden. ``lp_method = 1`` pide el simplex dual, que devuelve una base y con
    ella el subgradiente del corte. ``nominal_replay`` arma, al cerrar la
    corrida, el despacho del plan final en el centro de cada PUS.
    ``verbose`` muestra las cotas y el número de cortes/puntos por iteración.
    ``output_flag=1`` deja el log de Gurobi y antepone una línea con la fase,
    la iteración y el modelo (primera etapa, upper o lower, y el día).
    ``cuts_in_forward=False`` sigue el esquema de docs:
    forward explora y backward agrega los cortes; True permite anticiparlos.

    Los puntos superiores usan ObjBound del oráculo (o el respaldo certificado
    si es menor). La suma de holguras de los oráculos es un diagnóstico, no
    un certificado de convergencia por estancamiento. ``upper_mip_gap`` es relativo al
    objetivo completo, que incluye el costo futuro; ``upper_mip_gap_abs`` fija
    la holgura en unidades de costo por etapa y no crece con el horizonte.
    ``price_cap`` y ``polish_xi`` son opciones heredadas no utilizadas por
    esta implementación. Las cotas de la caja PCA se aplican siempre,
    independientemente de ``pus_bounds``. ``stop_on_stall`` corta la corrida
    cuando una iteración no agrega cortes ni mejora puntos, sin declararla óptima.
    """

    ub_method: str = "bilinear"
    relative_gap: float = 1e-3
    absolute_gap: float = 1e-2
    max_iterations: int = 25
    time_limit: float | None = None
    output_flag: int = 0
    threads: int = 0
    verbose: bool = True
    nominal_replay: bool = True
    cut_tolerance: float = 1e-6
    cuts_in_forward: bool = False
    first_stage_mip_gap: float = 1e-6
    upper_mip_gap: float = 1e-4
    upper_mip_gap_abs: float | None = None
    upper_time_limit: float | None = None
    price_cap: bool = True
    pus_bounds: bool = True
    stop_on_stall: bool = True
    polish_xi: bool = True
    lp_method: int = 1

    def __post_init__(self) -> None:
        if self.ub_method not in {"bilinear", "vertex", "kkt"}:
            raise ValueError(
                "ub_method tiene que ser bilinear, vertex o kkt; "
                f"se recibió {self.ub_method}."
            )
        if self.relative_gap < 0 or self.absolute_gap < 0 or self.cut_tolerance < 0:
            raise ValueError("Las tolerancias no pueden ser negativas.")
        if self.upper_mip_gap < 0 or (self.upper_mip_gap_abs is not None and self.upper_mip_gap_abs < 0):
            raise ValueError("Las tolerancias del oráculo no pueden ser negativas.")
        if self.max_iterations < 1:
            raise ValueError("max_iterations tiene que ser al menos 1.")
        if self.lp_method not in {-1, 0, 1, 2, 3, 4, 5}:
            raise ValueError(f"lp_method={self.lp_method} no es un método de Gurobi.")
        if self.threads < 0:
            raise ValueError("threads tiene que ser >= 0 (0 deja el valor de Gurobi).")


@dataclass(frozen=True)
class DayRealization:
    """Escenario de un día: coordenadas del PUS y perfiles que ve el despacho.

    ``p_wind`` es la potencia disponible por turbina, max(0, u), con forma
    (parques, horas). ``demand`` es la demanda horaria en MW.
    w = centro + semiancho · δ
    u = μ̂ + ρ · g · η + b + L · w
    """

    eta_wind: np.ndarray
    delta_wind: np.ndarray
    eta_demand: np.ndarray
    delta_demand: np.ndarray
    p_wind: np.ndarray
    demand: np.ndarray

    def __post_init__(self) -> None:
        eta_wind = _copy_array(self.eta_wind).reshape(-1)
        delta_wind = _copy_array(self.delta_wind).reshape(-1)
        eta_demand = _copy_array(self.eta_demand).reshape(-1)
        delta_demand = _copy_array(self.delta_demand).reshape(-1)
        p_wind = _copy_array(self.p_wind)
        demand = _copy_array(self.demand).reshape(-1)
        if p_wind.ndim != 2 or p_wind.shape[1] != demand.shape[0]:
            raise ValueError(
                f"p_wind tiene forma {p_wind.shape} y demand tiene {demand.shape}."
            )
        if np.any(p_wind < -1e-8):
            raise ValueError("La potencia eólica disponible no puede ser negativa.")
        object.__setattr__(self, "eta_wind", eta_wind)
        object.__setattr__(self, "delta_wind", delta_wind)
        object.__setattr__(self, "eta_demand", eta_demand)
        object.__setattr__(self, "delta_demand", delta_demand)
        object.__setattr__(self, "p_wind", p_wind)
        object.__setattr__(self, "demand", demand)

    @property
    def hours(self) -> int:
        return int(self.demand.shape[0])


@dataclass(frozen=True)
class MaintenancePlan:
    """Plan de la etapa 1. La disponibilidad tiene forma (parques, días)."""

    maintenance_start: dict[tuple[int, int, int], float]
    maintenance_active: dict[tuple[int, int, int], float]
    wind_availability: np.ndarray
    crews: np.ndarray


@dataclass(frozen=True)
class FirstStageResult:
    """Solución de la etapa 1.

    ``objective`` es el valor del incumbente. ``bound`` es la cota válida para
    el problema robusto: ObjBound si se minimizó la cota inferior, y el
    incumbente si se minimizó la cota superior.
    """

    bound: float
    objective: float
    cost: float
    state: np.ndarray
    plan: MaintenancePlan
    status: int


@dataclass(frozen=True)
class DayOperation:
    """Despacho horario de un día.

    Las potencias están en MW y cada período dura una hora, así que la suma
    horaria es energía en MWh. ``soc`` es la energía al cierre de cada hora.
    ``wind`` es la potencia inyectada por el parque y ``wind_available`` es la
    potencia incierta por turbina; el disponible del parque es p·A.
    """

    wind: np.ndarray
    diesel: np.ndarray
    charge: np.ndarray
    discharge: np.ndarray
    soc: np.ndarray
    ens: np.ndarray
    demand: np.ndarray
    wind_available: np.ndarray
    availability: np.ndarray

    def __post_init__(self) -> None:
        wind = _copy_array(self.wind)
        diesel = _copy_array(self.diesel)
        charge = _copy_array(self.charge)
        discharge = _copy_array(self.discharge)
        soc = _copy_array(self.soc)
        ens = _copy_array(self.ens).reshape(-1)
        demand = _copy_array(self.demand).reshape(-1)
        wind_available = _copy_array(self.wind_available)
        availability = _copy_array(self.availability).reshape(-1)
        hours = int(demand.shape[0])
        aligned = (
            wind.ndim == 2
            and wind.shape[1] == hours
            and wind_available.shape == wind.shape
            and availability.shape == (wind.shape[0],)
            and diesel.ndim == 2
            and diesel.shape[1] == hours
            and charge.ndim == 2
            and charge.shape[1] == hours
            and discharge.shape == charge.shape
            and soc.shape == charge.shape
            and ens.shape == (hours,)
        )
        if not aligned:
            raise ValueError("El despacho no alinea viento, diésel, batería, ENS y demanda.")
        object.__setattr__(self, "wind", wind)
        object.__setattr__(self, "diesel", diesel)
        object.__setattr__(self, "charge", charge)
        object.__setattr__(self, "discharge", discharge)
        object.__setattr__(self, "soc", soc)
        object.__setattr__(self, "ens", ens)
        object.__setattr__(self, "demand", demand)
        object.__setattr__(self, "wind_available", wind_available)
        object.__setattr__(self, "availability", availability)

    @property
    def hours(self) -> int:
        return int(self.demand.shape[0])


@dataclass(frozen=True)
class LowerDayResult:
    """LP de un día con la incertidumbre fija y la cota inferior del futuro.

    El corte es θ >= alpha + beta' x, válido en el estado entrante.
    ``state_out`` es None el último día. ``operation`` es el despacho de
    esa solución.
    """

    objective: float
    state_out: np.ndarray | None
    alpha: float
    beta: np.ndarray
    operation: DayOperation | None = None


@dataclass(frozen=True)
class UpperDayResult:
    """Oráculo de la cota superior de un día.

    ``bound`` es una sobreestimación válida del máximo (ObjBound de Gurobi).
    ``value`` es el incumbente y puede quedar por debajo de ese máximo.
    """

    value: float
    bound: float
    realization: DayRealization
    status: int


@dataclass(frozen=True)
class RDDPIteration:
    """Cotas globales registradas al terminar el backward de una iteración.

    ``oracle_slack`` es la suma diagnóstica de ObjBound − incumbente de los
    oráculos de esa pasada backward; no reemplaza el gap global.
    """

    iteration: int
    lower_bound: float
    upper_bound: float
    relative_gap: float
    n_cuts: int
    n_points: int
    first_stage_cost: float = 0.0
    oracle_slack: float = 0.0


@dataclass(frozen=True)
class RDDPResult:
    """Plan de mantenimiento, cotas y el despacho asociado.

    ``operation`` recorre el horizonte en el centro de cada PUS (theta = 0),
    con el plan final y las cotas de costo futuro de la última iteración.
    ``stalled`` indica que la última iteración no agregó cortes ni puntos.
    """

    lower_bound: float
    upper_bound: float
    relative_gap: float
    optimal: bool
    first_stage_state: np.ndarray
    first_stage_cost: float
    plan: MaintenancePlan
    history: tuple[RDDPIteration, ...] = field(default_factory=tuple)
    n_cuts: int = 0
    n_points: int = 0
    operation: tuple[DayOperation, ...] = field(default_factory=tuple)
    stalled: bool = False
    oracle_slack: float = 0.0
