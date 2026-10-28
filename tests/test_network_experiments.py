from dataclasses import replace
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

import main as baseline
from iteration_experiments import build_case
from rddp.class_pus import PUSParameters
from ens_experiments import ENSLower
from network_experiments import NetworkLower, NetworkUpper, run_case


class NetworkTests(unittest.TestCase):
    def test_congestion_can_increase_iterations(self):
        config = replace(baseline.config, threads=1, nominal_replay=False,
                         verbose=False, upper_time_limit=5., max_iterations=12)
        with TemporaryDirectory() as directory:
            loose = run_case(100., 10., 300., 3, 'maintenance', 0., config, Path(directory))
            tight = run_case(8., 10., 300., 3, 'maintenance', 0., config, Path(directory))
        for report in (loose, tight):
            self.assertNotIn('error', report)
            self.assertTrue(report['optimal'])
            self.assertTrue(report['checks_passed'])
            self.assertLessEqual(report['max_ens_above_demand'], 1e-6)
        self.assertGreater(tight['iterations'], loose['iterations'])
        self.assertEqual(sum(t['congested_hours'] for t in loose['last_backward']), 0)
        self.assertGreater(sum(t['price_separation_hours'] for t in tight['last_backward']), 0)

    def test_fixed_profile_duality_and_copperplate(self):
        system = build_case('baseline', 1)
        system = replace(system, c_ens=300.)
        config = replace(baseline.config, threads=1, verbose=False, upper_time_limit=10.)
        pus = PUSParameters.from_files()
        pus = replace(pus, wind=replace(pus.wind, phi=0., psi=0.),
                      demand=replace(pus.demand, phi=0., psi=0.))
        a = np.array([[10.], [10.]])
        soc = system.battery.soc_ini
        values = []
        for capacity in (0., 1., 100.):
            with self.subTest(capacity=capacity):
                lower = NetworkLower(system, config, pus, 0, capacity)
                upper = NetworkUpper(system, config, pus, 0, capacity)
                copper = ENSLower(system, config, pus, 0)
                try:
                    upper.add_states_constraint(soc, a)
                    adversary = upper.solve()
                    lower.add_states_constraint(soc, a, adversary.pwind, adversary.demand)
                    primal = lower.solve()
                    self.assertAlmostEqual(primal.objective, adversary.objective, delta=1e-3)
                    self.assertLessEqual(np.abs(primal.flow).max(), capacity + 1e-6)
                    lower.add_states_constraint(soc, a, adversary.pwind, adversary.demand)
                    self.assertAlmostEqual(lower.solve().objective, primal.objective, delta=1e-5)
                    values.append(primal.objective)
                    if capacity == 100.:
                        copper.add_states_constraint(soc, a, adversary.pwind, adversary.demand)
                        self.assertAlmostEqual(copper.solve().objective, primal.objective, delta=1e-5)
                finally:
                    for problem in (lower, upper, copper):
                        problem.model.dispose()
        self.assertGreater(values[0], values[-1])
        self.assertTrue(all(a >= b - 1e-5 for a, b in zip(values, values[1:])))


if __name__ == '__main__':
    unittest.main()