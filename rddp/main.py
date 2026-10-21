from __future__ import annotations

from pathlib import Path

import numpy as np

from degradation.failure_box import FailureBox
from rddp.algorithm import RDDP
from rddp.class_rddp import RDDPConfig
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

UB_METHOD = "bilinear"
# (UB - LB) / max(1, |UB|)
RELATIVE_GAP = 0.05
# UB - LB, en las mismas unidades del costo. Basta que se cumpla esta o la relativa.
ABSOLUTE_GAP = 0.05
MAX_ITERATIONS = 50
UPPER_TIME_LIMIT = 3600  # 1 hora
# MIPGap de Gurobi en el oráculo bilineal de la cota superior (0.1 %).
UPPER_MIP_GAP = 0.01

PLOT_DIR = Path(__file__).resolve().parents[1] / "rddp_plots"
HOURS_PER_DAY = 24
N_DAYS = 90
INICIO = "2026-01-01"

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
    maintenance_days=1,
    maintenance_crew=1,
    max_crews=2,
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
    output_flag=0,
)


def main() -> None:
    boxes = FailureBox()
    for park in range(wind.n_parks):
        for turbine in range(int(wind.n_turbines[park])):
            t_dw, t_up = boxes.box(int(wind.components[park]), int(wind.t_0[park][turbine]))
            wind.t_failure[park][turbine] = t_dw
            wind.t_up[park][turbine] = t_up
    wind.assign_alpha_hat(grid.horizon)

    pus = PUSParameters.from_csv()
    result = RDDP(system=grid, pus=pus, config=config).solve()
    print(
        f"LB={result.lower_bound:.6g}  UB={result.upper_bound:.6g}  "
        f"gap={100.0 * result.relative_gap:.3f}%  óptimo={result.optimal}  "
        f"cortes={result.n_cuts}  puntos={result.n_points}"
    )


if __name__ == "__main__":
    main()
