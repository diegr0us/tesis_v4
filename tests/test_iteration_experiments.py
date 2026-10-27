"""Regresión aislada con los archivos PUS reales del repositorio."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

import main as baseline
from iteration_experiments import build_case, run_case, scale_pus
from rddp.class_pus import PUSParameters


class IterationExperimentsTests(unittest.TestCase):
    def test_pus_scaling_preserves_basis_and_original(self):
        pus = PUSParameters.from_files()
        scaled = scale_pus(pus, {"wind_scale": 2., "budget_scale": .1})
        np.testing.assert_allclose(scaled.wind.a, 2 * pus.wind.a)
        np.testing.assert_allclose(scaled.wind_reconstruction.L, pus.wind_reconstruction.L)
        np.testing.assert_allclose(scaled.wind_reconstruction.forecast, 2 * pus.wind_reconstruction.forecast)
        self.assertAlmostEqual(scaled.wind.phi, .1 * pus.wind.phi)
        self.assertFalse(np.shares_memory(scaled.wind.a, pus.wind.a))

    def test_additional_convergent_cases(self):
        config = replace(baseline.config, threads=1, nominal_replay=False,
                         verbose=False, upper_time_limit=10., max_iterations=8)
        for name in ("energy_4", "terminal_0", "battery_4_eta_08", "maintenance_battery_4"):
            with self.subTest(case=name), TemporaryDirectory() as directory:
                report = run_case(name, 3, config, Path(directory))
                self.assertTrue(report["optimal"])
                self.assertFalse(report["stalled"])
                self.assertGreater(report["iterations"], 2)
                self.assertTrue(report["trace"])
                if name == "terminal_0":
                    self.assertGreater(report["history"][2]["lower_bound"],
                                       report["history"][1]["lower_bound"] + 100.)
                if name == "maintenance_battery_4":
                    self.assertEqual(report["maintenance_turbines"], 2)

    def test_inputs_are_isolated(self):
        original = [park.t_failure.copy() for park in baseline.wind.parks]
        system = build_case("battery_4", 3)
        self.assertEqual(system.battery.units[0].soc_max, 160.)
        self.assertEqual(baseline.battery.units[0].soc_max, 40.)
        for before, park, copied in zip(original, baseline.wind.parks, system.wind.parks):
            np.testing.assert_array_equal(before, park.t_failure)
            self.assertFalse(np.shares_memory(park.t_failure, copied.t_failure))

    def test_larger_battery_converges_after_second_iteration(self):
        config = replace(baseline.config, threads=1, nominal_replay=False,
                         verbose=False, upper_time_limit=10., max_iterations=8)
        with TemporaryDirectory() as directory:
            base = run_case("baseline", 3, config, Path(directory))
            larger = run_case("battery_4", 3, config, Path(directory))
        self.assertTrue(base["optimal"])
        self.assertEqual(base["iterations"], 2)
        self.assertTrue(larger["optimal"])
        self.assertFalse(larger["stalled"])
        self.assertGreater(larger["iterations"], 2)
        second = larger["history"][1]
        self.assertGreater(second["relative_gap"], config.relative_gap)
        self.assertGreater(second["upper_bound"] - second["lower_bound"], config.absolute_gap)
        self.assertTrue(larger["bounds_checks_passed"])


if __name__ == "__main__":
    unittest.main()