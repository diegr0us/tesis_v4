from types import SimpleNamespace
import unittest

import numpy as np
import pandas as pd

from rddp.class_system import BatteryFleet, BatteryUnit, DieselFleet, DieselUnit
from wind_sensitivity import dispatch


class WindSensitivityTests(unittest.TestCase):
    def test_surplus_charges_and_offsets_later_diesel(self):
        system = SimpleNamespace(diesel=DieselFleet((DieselUnit(100, 0, 100),)),
            battery=BatteryFleet((BatteryUnit(10, 10, 40, 0, .95, 20),)))
        data = pd.DataFrame({'timestamp': ['2025-01-06 00:00', '2025-01-06 01:00'],
            'demand_MW': [10., 10.], 'available_wind_1_MW': [5., 0.]})
        _, base = dispatch(system, data, 1)
        hourly, scaled = dispatch(system, data, 4)
        self.assertAlmostEqual(base['charge_MWh'], 0.)
        self.assertAlmostEqual(base['discharge_MWh'], 0.)
        self.assertGreater(scaled['charge_MWh'], 0.)
        self.assertGreater(scaled['battery_savings'], 0.)
        self.assertGreater(hourly.soc_1_MWh.iloc[0], 20.)
        self.assertAlmostEqual(hourly.soc_1_MWh.iloc[-1], 20.)
        self.assertTrue(np.all(hourly.curtailment_MW >= -1e-6))