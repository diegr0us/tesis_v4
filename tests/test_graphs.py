"""Exportación de resultados sin interfaz gráfica ni optimización."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from rddp.class_rddp import RDDPConfig, RDDPResult, RDDPIteration, MaintenancePlan, DayOperation
from rddp.class_system import Microgrid, DieselFleet, DieselUnit, BatteryFleet, BatteryUnit
from rddp.graphs import save_results, save_profile_plots


class GraphTests(unittest.TestCase):
    def test_exports_with_and_without_operation(self):
        system = Microgrid(DieselFleet((DieselUnit(10, 0, 7),)),
            SimpleNamespace(n_parks=1, G_r=[2]),
            BatteryFleet((BatteryUnit(1, 1, 4, 0, 1, 2, 2),)), 100, 1, 2)
        plan = MaintenancePlan({(0, 0, 0): 1.}, {(0, 0, 0): 1.}, np.array([[1.]]), np.array([[1.]]))
        operation = DayOperation(np.ones((1, 2)), np.full((1, 2), 2.),
            np.zeros((1, 2)), np.zeros((1, 2)), np.full((1, 2), 2.),
            np.zeros(2), np.full(2, 3.), np.full((1, 2), 2.), np.array([1.]))
        result = RDDPResult(20., 30., 1/3, False, np.array([2., 1.]), 2., plan,
            (RDDPIteration(1, 20., 30., 1/3, 1, 1),), 1, 1, (operation,), True)
        with TemporaryDirectory() as temp:
            directory = save_results(result, system, RDDPConfig(), '2025-01-06', temp, park_names=('AB',))
            self.assertTrue((directory / 'maintenance.png').is_file())
            self.assertTrue((directory / 'nominal_soc.png').is_file())
            self.assertTrue((directory / 'nominal_profiles.png').is_file())
            self.assertTrue((directory / 'nominal_profiles_detail.png').is_file())
            for image in directory.glob('*.png'):
                self.assertEqual(image.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['nominal_diesel_cost'], 28.)
            self.assertEqual(summary['stop_reason'], 'stalled')
            hourly = pd.read_csv(directory / 'nominal_hourly.csv')
            self.assertEqual(len(hourly), 2)
            self.assertTrue(np.allclose(hourly['available_wind_1_MW'], 2.))
            second = save_results(replace(result, operation=()), system, RDDPConfig(), '2025-01-06', temp)
            self.assertNotEqual(second, directory)
            self.assertFalse((second / 'nominal_hourly.csv').exists())
            self.assertTrue((second / 'convergence.png').is_file())
            self.assertEqual(plt.get_fignums(), [])

    def test_profiles_from_aggregate_sensitivity_export(self):
        data = pd.DataFrame({"timestamp": pd.date_range('2025-01-06', periods=4, freq='h'),
            "demand_MW": [3., 3., 3., 3.], "available_wind_MW": [1., 5., 2., 4.],
            "wind_MW": [1., 3., 2., 3.]})
        with TemporaryDirectory() as temp:
            paths = save_profile_plots(data, temp, prefix='factor_2', title='Sensibilidad')
            self.assertEqual(len(paths), 2)
            for path in paths:
                self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(plt.get_fignums(), [])


if __name__ == '__main__':
    unittest.main()