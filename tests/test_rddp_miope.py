"""El mantenimiento miope ignora el despacho: python -m unittest tests.test_rddp_miope."""
import tempfile
import unittest
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")

from rddp_miope.algorithm import RDDP
from rddp_miope.class_rddp import RDDPConfig
from rddp_miope.class_system import (
    BatteryFleet,
    BatteryUnit,
    DieselFleet,
    DieselUnit,
    Microgrid,
    WindFleet,
    WindPark,
)
from rddp_miope.graphs import save_results


# Día 0 es el más barato para las dos. La cuadrilla admite una por día,
# así que la segunda toma su siguiente día barato.
ALPHA = np.array([
    [10.0, 100.0, 100.0],
    [10.0, 20.0, 100.0],
])
CREW_COST = 5.0


def system(c_var: float) -> Microgrid:
    wind = WindFleet(
        parks=(
            WindPark(
                prated=3.5,
                n_turbines=2,
                t_0=np.ones(2, dtype=int),
                t_failure=np.array([1, 1]),
                t_up=np.array([1, 1]),
                alpha_hat=ALPHA,
            ),
        ),
        maintenance_days=1,
        maintenance_crew=1,
        max_crews=1,
        crew_cost=CREW_COST,
    )
    return Microgrid(
        DieselFleet((DieselUnit(100, 0, c_var),)),
        wind,
        BatteryFleet((BatteryUnit(10, 10, 40, 0, 0.95, 20),)),
        1000.0,
        3,
        2,
    )


def starts(plan) -> dict[tuple[int, int], int]:
    return {
        (j, w): d
        for (j, w, d), value in plan.maintenance_start.items()
        if value > 0.5
    }


class MyopicMaintenanceTests(unittest.TestCase):
    def test_schedule_ignores_diesel_cost(self):
        config = RDDPConfig(verbose=False, output_flag=0)
        expected = {(0, 0): 0, (1, 0): 1}
        expected_cost = 10.0 + 20.0 + 2 * CREW_COST
        costs = []
        plans = []
        for c_var in (1.0, 1.0e6):
            solver = RDDP(system(c_var), config)
            try:
                result = solver.solve()
                self.assertTrue(result.optimal)
                self.assertEqual(result.n_cuts, 0)
                self.assertEqual(result.n_points, 0)
                self.assertEqual(result.operation, ())
                self.assertEqual(result.worst_case, ())
                self.assertEqual(starts(result.plan), expected)
                self.assertAlmostEqual(result.first_stage_cost, expected_cost)
                self.assertAlmostEqual(result.upper_bound, expected_cost)
                self.assertAlmostEqual(result.lower_bound, expected_cost, delta=1e-4)
                names = [var.VarName for var in solver.first.model.getVars()]
                self.assertFalse(any(name.startswith("FutureCost") for name in names))
                self.assertFalse(any(name.startswith("y_") for name in names))
                costs.append(result.first_stage_cost)
                plans.append(starts(result.plan))
            finally:
                solver.first.model.dispose()
        self.assertEqual(plans[0], plans[1])
        self.assertAlmostEqual(costs[0], costs[1])

    def test_save_skips_iterative_figures(self):
        config = RDDPConfig(verbose=False, output_flag=0)
        solver = RDDP(system(100.0), config)
        try:
            result = solver.solve()
            with tempfile.TemporaryDirectory() as folder:
                directory = save_results(
                    result, solver.system, config, "2025-01-06",
                    output_dir=Path(folder), show=False,
                )
                self.assertTrue((directory / "maintenance.csv").is_file())
                self.assertTrue((directory / "availability.csv").is_file())
                self.assertFalse((directory / "convergence.png").exists())
                self.assertFalse((directory / "refinement.png").exists())
                self.assertFalse(any(directory.glob("*dispatch*")))
                self.assertFalse(any(directory.glob("*hourly*")))
        finally:
            solver.first.model.dispose()


if __name__ == "__main__":
    unittest.main()
