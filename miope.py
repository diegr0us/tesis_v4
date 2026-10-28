"""Plan de mantenimiento sin despacho. No lee el PUS ni arma el recurso."""
from __future__ import annotations

from contextlib import contextmanager
from io import StringIO
from pathlib import Path
import sys
from typing import Iterator

import numpy as np
import types

# El script se llama igual que el paquete. Sin esto, Python importa este
# archivo y no el directorio miope/.
_package = types.ModuleType("miope")
_package.__path__ = [str(Path(__file__).resolve().parent / "miope")]
_package.__package__ = "miope"
sys.modules["miope"] = _package

from degradation.failure_box import FailureBox
from miope.algorithm import RDDP
from miope.class_rddp import RDDPConfig, RDDPResult
from miope.class_system import (
    BatteryFleet,
    BatteryUnit,
    DieselFleet,
    DieselUnit,
    Microgrid,
    WindFleet,
    WindPark,
)
from miope.graphs import save_results


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


RELATIVE_GAP = 0.001
ABSOLUTE_GAP = 0.001

RESULTS_DIR = Path(__file__).resolve().parent / "results" / "miope"
SHOW_GRAPHS = False
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
# t_0 = 1. Los días de falla no coinciden entre parques.
# Parque 0: 19, 27, 35, 43, 51 y 37, 40, 45, 48, 50.
# Parque 1: 24, 32, 39, 46, 52 y 36, 38, 42, 47, 49.
components_by_park = (
    np.array([61, 14, 11, 3, 34, 27, 65, 54, 30, 12], dtype=int),
    np.array([68, 17, 7, 15, 78, 1, 36, 93, 29, 48], dtype=int),
)

wind = WindFleet(
    parks=(
        WindPark(
            prated=3.5,
            n_turbines=n_turbines[0],
            components=components_by_park[0],
            t_0=np.ones(n_turbines[0], dtype=int),
        ),
        WindPark(
            prated=3.5,
            n_turbines=n_turbines[1],
            components=components_by_park[1],
            t_0=np.ones(n_turbines[1], dtype=int),
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
    relative_gap=RELATIVE_GAP,
    absolute_gap=ABSOLUTE_GAP,
    verbose=True,
    output_flag=1,
)


def load_failure_boxes() -> None:
    """Carga el box de falla y el costo robusto. No abre pronósticos ni el despacho."""
    boxes = FailureBox()
    for park in range(wind.n_parks):
        for turbine in range(int(wind.n_turbines[park])):
            t_dw, t_up = boxes.box(
                int(wind.components[park][turbine]), int(wind.t_0[park][turbine])
            )
            wind.t_failure[park][turbine] = t_dw
            wind.t_up[park][turbine] = t_up
    wind.assign_alpha_hat(grid.horizon)


def main() -> RDDPResult:
    with capture_console() as log:
        load_failure_boxes()
        solver = RDDP(grid, config)
        try:
            result = solver.solve()
            print(f"LB={result.lower_bound:.6f} UB={result.upper_bound:.6f} "
                  f"gap={result.relative_gap:.3%} costo={result.first_stage_cost:.6f}")
            directory = save_results(
                result, grid, config, INICIO, output_dir=RESULTS_DIR, show=SHOW_GRAPHS,
            )
            (directory / "console.txt").write_text(log.getvalue(), encoding="utf-8")
            return result
        finally:
            solver.first.model.dispose()


if __name__ == "__main__":
    result = main()
