"""Regresiones pequeñas con Gurobi: python -m unittest discover -s tests."""
import unittest
from types import SimpleNamespace

import numpy as np

from rddp.algorithm import RDDP
from rddp.class_pus import PUSGroup, PUSParameters, PCAReconstruction
from rddp.class_rddp import RDDPConfig
from rddp.class_system import Microgrid, DieselFleet, DieselUnit, BatteryFleet, BatteryUnit
from rddp.recourse_stages import RecourseStage_Lower


def example(days=3, capacity=20):
    wind = SimpleNamespace(n_parks=1, G_r=[2], maintenance_days=1,
        maintenance_crew=1, max_crews=1, crew_cost=0., J_r=lambda horizon: [])
    system = Microgrid(DieselFleet((DieselUnit(capacity, 0, 7),)), wind,
        BatteryFleet((BatteryUnit(2, 2, 4, 0, 1, 2, 2),)), 100, days, 2)
    group = PUSGroup(np.zeros(2), np.ones(2) * 0.5, 2, 2, 1., 1.)
    wind_data = PCAReconstruction(np.eye(2), np.zeros(2), np.full((days, 2), 2.))
    demand_data = PCAReconstruction(np.eye(2), np.zeros(2), np.full((days, 2), 5.))
    pus = PUSParameters(group, group, wind_data, demand_data,
        np.arange(days) + np.datetime64('2025-01-06'), 2, ('test',))
    config = RDDPConfig(max_iterations=10, upper_time_limit=15, upper_mip_gap=1e-7,
        relative_gap=1e-5, absolute_gap=1e-3, verbose=False, nominal_replay=True)
    return system, config, pus


class RDDPTests(unittest.TestCase):
    def test_exact_small_horizons(self):
        for days in (1, 3):
            with self.subTest(days=days):
                solver = RDDP(*example(days))
                try:
                    result = solver.solve()
                    self.assertTrue(result.optimal)
                    # p por turbina, A=2: y <= p·A. Peor caso ≈ 3.5 MWh diésel/día × 7.
                    self.assertAlmostEqual(result.upper_bound, 24.5 * days, delta=1e-3)
                    self.assertLessEqual(result.lower_bound, result.upper_bound + 1e-4)
                    self.assertEqual(len(result.operation), days)
                    self.assertEqual(len(result.worst_case), days)
                    for op in result.worst_case:
                        self.assertAlmostEqual(float(op.demand.sum()), 10.5, delta=1e-2)
                        self.assertAlmostEqual(float(op.wind_available.sum()), 3.5, delta=1e-2)
                    diesel = sum(float(np.sum(op.diesel) * 7) for op in result.worst_case)
                    self.assertAlmostEqual(diesel, 24.5 * days, delta=1e-2)
                    self.assertTrue(all(x.n_cuts > 0 for x in result.history))
                    self.assertTrue(all(a.lower_bound <= b.lower_bound for a, b in zip(result.history, result.history[1:])))
                    self.assertTrue(all(a.upper_bound >= b.upper_bound for a, b in zip(result.history, result.history[1:])))
                finally:
                    for problem in [solver.first, *solver.upper, *solver.lower]:
                        problem.model.dispose()

    def test_cut_includes_continuation_availability(self):
        system, config, pus = example()
        lower = RecourseStage_Lower(system, config, pus, 0)
        a = np.array([[1., 2., 1.]])
        soc = np.array([2.])
        wind, demand = np.array([[2., 3.]]), np.array([5., 6.])
        try:
            lower.add_states_constraint(soc, a, wind, demand)
            lower.add_cut_lower(30., np.array([-2., -1., -0.5, -0.2]))
            value = lower.solve().objective
            alpha, beta = lower.generate_cut()
            self.assertAlmostEqual(alpha + beta @ np.r_[soc, a.T.ravel()], value)
            for new_soc in (0.5, 3.):
                for new_a in (np.array([[0., 1., 2.]]), np.array([[2., 2., 0.]])):
                    lower.add_states_constraint(np.array([new_soc]), new_a, wind, demand)
                    evaluated = lower.solve().objective
                    self.assertLessEqual(alpha + beta @ np.r_[new_soc, new_a.T.ravel()], evaluated + 1e-6)
        finally:
            lower.model.dispose()

    def test_backup_rejects_insufficient_capacity(self):
        system, config, pus = example(capacity=1)
        # Use supplied models so resources remain accessible if initialization fails.
        from rddp.first_stage import FirstStageProblem
        from rddp.recourse_stages import RecourseStage_Upper
        first = FirstStageProblem(system, config)
        upper = [RecourseStage_Upper(system, config, pus, d) for d in range(system.horizon)]
        lower = [RecourseStage_Lower(system, config, pus, d) for d in range(system.horizon)]
        try:
            with self.assertRaisesRegex(ValueError, 'capacidad'):
                RDDP(system, config, pus, first, upper, lower)
        finally:
            for problem in [first, *upper, *lower]:
                problem.model.dispose()


if __name__ == '__main__':
    unittest.main()