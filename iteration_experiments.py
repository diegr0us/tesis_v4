"""Pruebas aisladas de convergencia con el PUS real, sin modificar main.py."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path
from time import perf_counter

import numpy as np

import main as baseline
from degradation.failure_box import FailureBox
from rddp.algorithm import RDDP
from rddp.class_pus import PUSParameters
from rddp.class_system import BatteryFleet, DieselFleet, DieselUnit
from rddp.first_stage import FirstStageProblem
from rddp.recourse_stages import RecourseStage_Lower, RecourseStage_Upper


CASES = {
    "baseline": (None, 100., 1.),
    "cheap_10": (10., 30., 1.),
    "cheap_20": (20., 30., 1.),
    "cheap_30": (30., 30., 1.),
    "battery_4": (None, 100., 4.),
    "cheap_20_battery_4": (20., 30., 4.),
}

# Cambios físicos independientes respecto del caso base de tres días.
VARIANTS = {
    "power_4": {"battery": {"pch": 40., "pdch": 40.}},
    "energy_4": {"battery": {"soc_max": 160.}},
    "soc_35": {"battery": {"soc_ini": 35.}},
    "terminal_0": {"battery": {"soc_final": 0.}},
    "energy_soc_4": {"battery": {"soc_max": 160., "soc_ini": 80.}},
    "battery_8": {"battery": {"pch": 80., "pdch": 80., "soc_max": 320., "soc_ini": 160.}},
    "battery_4_eta_08": {"battery": {"pch": 40., "pdch": 40., "soc_max": 160., "soc_ini": 80., "eta": .8}},
    "battery_4_terminal_0": {"battery": {"pch": 40., "pdch": 40., "soc_max": 160., "soc_ini": 80., "soc_final": 0.}},
    "wind_2": {"wind_scale": 2.},
    "demand_07": {"demand_scale": .7},
    "uncertainty_01": {"budget_scale": .1},
    "maintenance": {"maintenance": True},
    "maintenance_battery_4": {"maintenance": True, "battery": {"pch": 40., "pdch": 40., "soc_max": 160., "soc_ini": 80.}},
    "wind_2_budget_01": {"wind_scale": 2., "budget_scale": .1},
    "maintenance_wind_2_budget_01": {"maintenance": True, "wind_scale": 2., "budget_scale": .1},
    "demand_04_budget_01": {"demand_scale": .4, "budget_scale": .1},
}


class TracedRDDP(RDDP):
    """Observa los estados sin cambiar solves, cortes ni criterio de parada."""

    def __init__(self, *args):
        self.trace = []
        super().__init__(*args)

    def _lower(self, d, soc, a, realization):
        result = super()._lower(d, soc, a, realization)
        self.trace.append({"tag": self.lower[d].solve_tag, "day": d + 1,
            "soc_in": soc.tolist(), "soc_out": result.soc[:, -1].tolist(),
            "availability": a.tolist(), "objective": result.objective})
        return result


def scale_pus(pus, spec):
    """Escala perfiles y soporte conjuntamente, conservando la base ortonormal."""
    for name in ("wind", "demand"):
        factor = spec.get(f"{name}_scale", 1.)
        group = getattr(pus, name)
        rec = getattr(pus, f"{name}_reconstruction")
        budget = spec.get("budget_scale", 1.)
        pus = replace(pus, **{
            name: replace(group, c=group.c * factor, a=group.a * factor,
                          phi=group.phi * budget, psi=group.psi * budget),
            f"{name}_reconstruction": replace(rec, b=rec.b * factor, forecast=rec.forecast * factor),
        })
    return pus


def build_case(name, days):
    cheap_capacity, cheap_cost, battery_scale = CASES[name if name in CASES else "baseline"]
    spec = VARIANTS.get(name, {})
    parks = tuple(replace(park, alpha_hat=None) for park in baseline.wind.parks)
    wind = replace(baseline.wind, parks=parks,
                   maintenance_days=min(baseline.wind.maintenance_days, days))
    boxes = FailureBox()
    for park in wind.parks:
        for j in range(park.n_turbines):
            park.t_failure[j], park.t_up[j] = boxes.box(park.components, int(park.t_0[j]))
    if spec.get("maintenance"):
        # Solo dos turbinas requieren mantenimiento; cajas sintéticas declaradas.
        wind = replace(wind, maintenance_days=1, maintenance_crew=1)
        for park in wind.parks:
            park.t_failure[:] = days + 10
            park.t_up[:] = days + 10
            park.t_failure[0] = days
            park.t_up[0] = days
    wind.assign_alpha_hat(days)
    diesel = baseline.diesel if cheap_capacity is None else DieselFleet((
        DieselUnit(100., 0., 100.),
        DieselUnit(cheap_capacity, 0., cheap_cost),
    ))
    battery = BatteryFleet(tuple(replace(unit,
        pch=unit.pch * battery_scale, pdch=unit.pdch * battery_scale,
        soc_max=unit.soc_max * battery_scale, soc_ini=unit.soc_ini * battery_scale)
        for unit in baseline.battery.units))
    if "battery" in spec:
        battery = BatteryFleet(tuple(replace(unit, **spec["battery"]) for unit in battery.units))
    return replace(baseline.grid, wind=wind, diesel=diesel, battery=battery, horizon=days)


def run_case(name, days, config, directory):
    system = build_case(name, days)
    pus = scale_pus(PUSParameters.from_files(), VARIANTS.get(name, {}))
    pus.validate_reconstruction(system.wind.n_parks, system.hours_per_day, days)
    problems = []
    started = perf_counter()
    report = {"case": name, "days": days, "config": asdict(config),
              "overrides": VARIANTS.get(name, {}),
              "diesel": [asdict(unit) for unit in system.diesel.units],
              "battery": [asdict(unit) for unit in system.battery.units],
              "maintenance_turbines": len(system.wind.J_r(days))}
    try:
        first = FirstStageProblem(system, config)
        problems.append(first)
        upper, lower = [], []
        for stage in range(days):
            upper.append(RecourseStage_Upper(system, config, pus, stage))
            problems.append(upper[-1])
            lower.append(RecourseStage_Lower(system, config, pus, stage))
            problems.append(lower[-1])
        solver = TracedRDDP(system, config, pus, first, upper, lower)
        result = solver.solve()
        report["trace"] = solver.trace
        report.update(iterations=len(result.history), optimal=result.optimal,
            stalled=result.stalled, lower_bound=result.lower_bound,
            upper_bound=result.upper_bound, relative_gap=result.relative_gap,
            history=[asdict(item) for item in result.history],
            availability=result.plan.wind_availability.tolist())
        history = result.history
        assert all(np.isfinite([h.lower_bound, h.upper_bound, h.relative_gap]).all() for h in history)
        assert all(h.lower_bound <= h.upper_bound + 1e-5 * max(1., abs(h.upper_bound)) for h in history)
        assert all(a.lower_bound <= b.lower_bound + 1e-6 for a, b in zip(history, history[1:]))
        assert all(a.upper_bound >= b.upper_bound - 1e-6 for a, b in zip(history, history[1:]))
        report["bounds_checks_passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        for problem in problems:
            problem.model.dispose()
        report["seconds"] = perf_counter() - started
        (directory / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", choices=[*CASES, *VARIANTS], default=list(CASES))
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--oracle-seconds", type=float, default=10.)
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent / "results" / datetime.now().strftime("iterations_%Y%m%d_%H%M%S_%f")
    directory.mkdir(parents=True)
    config = replace(baseline.config, max_iterations=args.max_iterations,
        upper_time_limit=args.oracle_seconds, threads=1, nominal_replay=False)
    print(f"Resultados: {directory}", flush=True)
    for name in args.cases:
        print(f"\n=== {name} ===", flush=True)
        report = run_case(name, args.days, config, directory)
        print({k: report[k] for k in ("case", "iterations", "optimal", "stalled", "relative_gap", "seconds")}, flush=True)


if __name__ == "__main__":
    main()