"""Validación primal-dual y del recourse de los experimentos ENS."""
from dataclasses import replace
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ens_experiments import ENSLower, ENSUpper, ENSRDDP, run_case
import main as baseline
from test_rddp import example
from rddp.first_stage import FirstStageProblem


class ENSTests(unittest.TestCase):
    def test_real_pus_converges_after_two_iterations(self):
        config = replace(baseline.config, threads=1, nominal_replay=False,
                         verbose=False, max_iterations=10, upper_time_limit=5.)
        with TemporaryDirectory() as directory:
            report = run_case(10., 300., 3, "baseline", config, Path(directory))
        self.assertNotIn("error", report)
        self.assertTrue(report["optimal"])
        self.assertGreater(report["iterations"], 2)
        self.assertLessEqual(report["max_ens_above_demand"], 1e-6)
        self.assertTrue(any(t["ens_MWh"] > 0 for t in report["trace"]))

    def test_fixed_realization_primal_dual(self):
        system, config, pus = example(days=1, capacity=1.)
        # Sin batería: dos horas, demanda=5, viento total=4, diésel=0.5.
        system = replace(system, diesel=replace(system.diesel,
            units=(replace(system.diesel.units[0], pmax=.5),)),
            battery=replace(system.battery, units=(replace(system.battery.units[0],
                pch=0., pdch=0., soc_max=0., soc_ini=0., soc_final=0.),)))
        pus = replace(pus, wind=replace(pus.wind, phi=0., psi=0.),
                      demand=replace(pus.demand, phi=0., psi=0.))
        lower, upper = ENSLower(system, config, pus, 0), ENSUpper(system, config, pus, 0)
        try:
            a, soc = np.array([[2.]]), np.array([0.])
            upper.add_states_constraint(soc, a)
            adversary = upper.solve()
            lower.add_states_constraint(soc, a, adversary.pwind, adversary.demand)
            result = lower.solve()
            self.assertAlmostEqual(result.objective, 107., places=5)
            np.testing.assert_allclose(result.ens, [.5, .5], atol=1e-6)
            self.assertAlmostEqual(result.objective, adversary.objective, places=5)
            for variable in upper.lambda_balance.values():
                self.assertEqual(variable.UB, system.c_ens)
            # Reconstruir el balance no puede perder ni duplicar ENS.
            lower.add_states_constraint(soc, a, adversary.pwind, adversary.demand)
            self.assertAlmostEqual(lower.solve().objective, 107., places=5)
        finally:
            lower.model.dispose()
            upper.model.dispose()

    def test_insufficient_diesel_is_feasible(self):
        system, config, pus = example(days=1, capacity=1.)
        config = replace(config, nominal_replay=False)
        first = FirstStageProblem(system, config)
        upper = [ENSUpper(system, config, pus, 0)]
        lower = [ENSLower(system, config, pus, 0)]
        try:
            solver = ENSRDDP(system, config, pus, first, upper, lower)
            result = solver.solve()
            self.assertTrue(result.optimal)
            self.assertGreater(max(t['ens_MWh'] for t in solver.trace), 0.)
            self.assertGreaterEqual(solver.backup[0] + 1e-5, result.upper_bound)
            self.assertLessEqual(result.lower_bound, result.upper_bound + 1e-5)
        finally:
            for problem in [first, *upper, *lower]:
                problem.model.dispose()


if __name__ == '__main__':
    unittest.main()