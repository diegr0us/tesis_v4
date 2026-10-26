from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from pathlib import Path
import sys
from typing import Iterator

import numpy as np

from degradation.failure_box import FailureBox
from rddp.algorithm import RDDP
from rddp.graphs import save_results
from rddp.first_stage import FirstStageProblem
from rddp.recourse_stages import RecourseStage_Lower, RecourseStage_Upper
from rddp.class_rddp import RDDPConfig, RDDPResult
from rddp.class_pus import PUSParameters
from rddp.class_system import (
    BatteryFleet,
    BatteryUnit,
    DieselFleet,
    DieselUnit,
    Microgrid,
    WindFleet,
    WindPark,
)


class _Tee:
    """Replica escritura a varios streams (consola + buffer)."""

    def __init__(self, *streams) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


@contextmanager
def capture_console() -> Iterator[StringIO]:
    """Muestra stdout/stderr en consola y los acumula para guardar al final."""
    buffer = StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = _Tee(old_out, buffer)  # type: ignore[assignment]
    sys.stderr = _Tee(old_err, buffer)  # type: ignore[assignment]
    try:
        yield buffer
    finally:
        sys.stdout, sys.stderr = old_out, old_err

UB_METHOD = "bilinear"
# (UB - LB) / max(1, |UB|)
RELATIVE_GAP = 0.001
# UB - LB, en las mismas unidades del costo. Basta que se cumpla esta o la relativa.
ABSOLUTE_GAP = 0.001
MAX_ITERATIONS = 50
UPPER_TIME_LIMIT = 3600  # 1 hora
# MIPGap de Gurobi en el oráculo bilineal de la cota superior (1 %).
UPPER_MIP_GAP = 0.00001

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SHOW_GRAPHS = False  # True abre las figuras; los archivos siempre se guardan.
HOURS_PER_DAY = 24
N_DAYS = 85
INICIO = "2025-01-06"

diesel = DieselFleet(
    units=(
        DieselUnit(pmax=100, pmin=0, c_var=100),
    )
)

battery = BatteryFleet(
    units=(
        BatteryUnit(
            pch=10,
            pdch=10,
            soc_max=40,
            soc_min=0,
            eta=0.95,
            soc_ini=20,
        ),
    )
)

n_turbines = (10, 10)

wind = WindFleet(
    parks=(
        WindPark(
            prated=3.5,
            n_turbines=n_turbines[0],
            t_0=np.ones(n_turbines[0], dtype=int),
            seed=0,
        ),
        WindPark(
            prated=3.5,
            n_turbines=n_turbines[1],
            t_0=np.ones(n_turbines[1], dtype=int),
            seed=1,
        ),
    ),
    maintenance_days=4,
    maintenance_crew=3,
    max_crews=1,
    crew_cost=1000.0,
)

grid = Microgrid(
    diesel=diesel,
    wind=wind,
    battery=battery,
    c_ens=1000.0,
    horizon=N_DAYS,
    hours_per_day=HOURS_PER_DAY,
)

config = RDDPConfig(
    ub_method=UB_METHOD,
    relative_gap=RELATIVE_GAP,
    absolute_gap=ABSOLUTE_GAP,
    max_iterations=MAX_ITERATIONS,
    upper_time_limit=UPPER_TIME_LIMIT,
    upper_mip_gap=UPPER_MIP_GAP,
    verbose=True,
    output_flag=1,
)


def initialize_problems() -> tuple[FirstStageProblem, list[RecourseStage_Upper], list[RecourseStage_Lower]]:
    """Carga los datos e inicializa los modelos, sin ejecutar la solución RDDP."""
    boxes = FailureBox()
    for park in range(wind.n_parks):
        for turbine in range(int(wind.n_turbines[park])):
            t_dw, t_up = boxes.box(int(wind.components[park]), int(wind.t_0[park][turbine]))
            wind.t_failure[park][turbine] = t_dw
            wind.t_up[park][turbine] = t_up
    wind.assign_alpha_hat(grid.horizon)

    pus = PUSParameters.from_files()
    pus.validate_reconstruction(wind.n_parks, HOURS_PER_DAY, grid.horizon)
    if pus.dates is None or str(pus.dates[0]) != INICIO:
        raise ValueError("El inicio del horizonte no coincide con los pronósticos del PUS.")
    first_stage = FirstStageProblem(system=grid, config=config)

    # Índice stage = 0,...,horizon-1: día operativo stage+1 (etapa stage+2 en docs).
    # Cada modelo se construye una vez y se reutiliza durante las iteraciones.
    upper_stages = [
        RecourseStage_Upper(system=grid, config=config, pus=pus, stage=stage)
        for stage in range(grid.horizon)
    ]
    lower_stages = [
        RecourseStage_Lower(system=grid, config=config, pus=pus, stage=stage)
        for stage in range(grid.horizon)
    ]

    # Los estados, realizaciones, cortes y puntos se incorporan en las iteraciones.
    # El upper ya contiene el PUS histórico y la reconstrucción PCA diaria.
    print(
        f"Modelos inicializados: 1 primera etapa, {len(upper_stages)} upper "
        f"y {len(lower_stages)} lower. "
        "No se ha ejecutado la optimización."
    )
    return first_stage, upper_stages, lower_stages


def main() -> RDDPResult:
    with capture_console() as log:
        first_stage, upper_stages, lower_stages = initialize_problems()
        try:
            result = RDDP(grid, config, upper_stages[0].pus,
                          first_stage, upper_stages, lower_stages).solve()
            print(f"LB={result.lower_bound:.6f} UB={result.upper_bound:.6f} "
                  f"gap={result.relative_gap:.3%} convergencia={result.optimal} "
                  f"estancado={result.stalled}")
            directory = save_results(
                result, grid, config, INICIO, output_dir=RESULTS_DIR,
                show=SHOW_GRAPHS, park_names=upper_stages[0].pus.wind_parks,
            )
            (directory / "console.txt").write_text(log.getvalue(), encoding="utf-8")
            return result
        finally:
            for problem in [first_stage, *upper_stages, *lower_stages]:
                problem.model.dispose()


if __name__ == "__main__":
    result = main()
