"""Experimentos aislados con déficit penalizado sin cota superior (ENS relajada)."""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path
from time import perf_counter

import gurobipy as gp
import numpy as np

import main as baseline
from iteration_experiments import build_case
from rddp.algorithm import RDDP
from rddp.class_pus import PUSParameters
from rddp.class_system import DieselFleet, DieselUnit
from rddp.first_stage import FirstStageProblem
from rddp.recourse_stages import RecourseStage_Lower, RecourseStage_Upper


class ENSLower(RecourseStage_Lower):
    def __init__(self, system, config, pus, stage):
        super().__init__(system, config, pus, stage)
        self.ens = self.model.addVars(self.H, lb=0., name="ens")
        self.operation_cost += system.c_ens * gp.quicksum(self.ens.values())
        self.model.setObjective(self.operation_cost + self.future_cost, gp.GRB.MINIMIZE)

    def add_states_constraint(self, soc_in, availability, pwind, demand):
        super().add_states_constraint(soc_in, availability, pwind, demand)
        self.model.update()
        for h in range(self.H):
            self.model.chgCoeff(self.balance[h], self.ens[h], 1.)

    def solve(self):
        result = super().solve()
        result.ens = np.array([self.ens[h].X for h in range(self.H)])
        return result


class ENSUpper(RecourseStage_Upper):
    def __init__(self, system, config, pus, stage):
        super().__init__(system, config, pus, stage)
        # Columna primal e >= 0 con costo c_ens: lambda_balance <= c_ens.
        # lambda_wind puede elegirse igual a lambda_balance en un óptimo.
        for var in (*self.lambda_balance.values(), *self.lambda_wind.values()):
            var.UB = system.c_ens


class ENSRDDP(RDDP):
    def __init__(self, *args):
        self.trace = []
        self.oracle_trace = []
        super().__init__(*args)

    def _initial_bounds(self):
        # Respaldo factible de la relajación: todo déficit se paga a c_ens;
        # cargar desde soc_min hasta el SOC final en el último día.
        s, b = self.system, self.system.battery
        if not np.isfinite(s.c_ens) or s.c_ens <= 0:
            raise ValueError("c_ens debe ser finito y positivo")
        if (np.any(b.eta <= 0) or np.any(b.eta > 1) or np.any(b.soc_min > b.soc_max)
                or np.any(b.soc_ini < b.soc_min) or np.any(b.soc_ini > b.soc_max)
                or np.any(b.soc_final < b.soc_min) or np.any(b.soc_final > b.soc_max)
                or np.any(s.diesel.c_var < 0) or np.any(s.diesel.pmax < 0)):
            raise ValueError("Datos físicos/costos fuera del dominio")
        charge = (b.soc_final - b.soc_min) / (b.eta * s.hours_per_day)
        if np.any(charge > b.pch + 1e-9):
            raise ValueError("La carga terminal no cabe en un día")
        daily = []
        for d, upper in enumerate(self.upper):
            upper.model.update()
            demand = np.array([upper.demand[h].UB for h in range(s.hours_per_day)])
            if not np.isfinite(demand).all() or np.any(demand < 0):
                raise ValueError("Soporte de demanda inválido")
            extra = float(charge.sum()) if d == self.T - 1 else 0.
            daily.append(float(s.c_ens * np.sum(demand + extra)))
        return np.cumsum(daily[::-1])[::-1]

    def _upper(self, d, soc, a):
        result = super()._upper(d, soc, a)
        self.oracle_trace.append({"tag": self.upper[d].solve_tag, "day": d + 1,
            "value": result.objective, "bound": result.bound, "status": result.status})
        return result

    def _lower(self, d, soc, a, realization):
        result = super()._lower(d, soc, a, realization)
        diesel = result.y_nr.sum(axis=0)
        balance = result.y_r.sum(axis=0) + diesel + result.pi_minus.sum(axis=0) - result.pi_plus.sum(axis=0) + result.ens
        self.trace.append({"tag": self.lower[d].solve_tag, "day": d + 1,
            "soc_in": soc.tolist(), "soc_out": result.soc[:, -1].tolist(),
            "ens": result.ens.tolist(), "demand": result.demand.tolist(),
            "diesel": diesel.tolist(), "availability": a.tolist(),
            "ens_MWh": float(result.ens.sum()),
            "ens_hours": int(np.count_nonzero(result.ens > 1e-6)),
            "saturated_hours": int(np.count_nonzero(diesel >= self.system.diesel.pmax.sum() - 1e-6)),
            "max_ens_above_demand": float(np.maximum(result.ens - result.demand, 0).max()),
            "max_balance_violation": float(np.maximum(result.demand - balance, 0).max())})
        return result

    def _replay(self, availability):
        raise ValueError("Este experimento usa nominal_replay=False; no exportar ENS cero ficticia")


def run_case(pmax, cost, days, variant, config, directory, budget_scale=1.):
    system = build_case(variant, days)
    system = replace(system, diesel=DieselFleet((DieselUnit(pmax, 0., 100.),)), c_ens=cost)
    pus = PUSParameters.from_files()
    if budget_scale != 1.:
        pus = replace(pus, wind=replace(pus.wind, phi=pus.wind.phi * budget_scale, psi=pus.wind.psi * budget_scale),
                      demand=replace(pus.demand, phi=pus.demand.phi * budget_scale, psi=pus.demand.psi * budget_scale))
    pus.validate_reconstruction(system.wind.n_parks, system.hours_per_day, days)
    name = f"{variant}_p{pmax:g}_ens{cost:g}_d{days}"
    report = {"case": name, "pmax": pmax, "c_ens": cost, "days": days, "budget_scale": budget_scale,
              "variant": variant, "config": asdict(config),
              "battery": [asdict(unit) for unit in system.battery.units],
              "maintenance_turbines": len(system.wind.J_r(days)),
              "formulation": "nonnegative unbounded deficit, not demand-capped ENS"}
    problems, solver = [], None
    start = perf_counter()
    try:
        first = FirstStageProblem(system, config)
        problems.append(first)
        upper, lower = [], []
        for d in range(days):
            upper.append(ENSUpper(system, config, pus, d))
            problems.append(upper[-1])
            lower.append(ENSLower(system, config, pus, d))
            problems.append(lower[-1])
        solver = ENSRDDP(system, config, pus, first, upper, lower)
        result = solver.solve()
        report.update(iterations=len(result.history), optimal=result.optimal,
            stalled=result.stalled, lower_bound=result.lower_bound, upper_bound=result.upper_bound,
            relative_gap=result.relative_gap, history=[asdict(h) for h in result.history])
        h = result.history
        assert all(np.isfinite([x.lower_bound, x.upper_bound, x.relative_gap]).all() for x in h)
        assert all(x.lower_bound <= x.upper_bound + 1e-5 * max(1., abs(x.upper_bound)) for x in h)
        assert all(a.lower_bound <= b.lower_bound + 1e-6 and a.upper_bound >= b.upper_bound - 1e-6 for a, b in zip(h, h[1:]))
        assert all(t["max_balance_violation"] < 1e-5 for t in solver.trace)
        report["checks_passed"] = True
        report["max_ens_above_demand"] = max(t["max_ens_above_demand"] for t in solver.trace)
        # Último backward: diagnóstico de solves locales, NO una trayectoria
        # operativa concatenable ni evaluación del plan incumbente final.
        tag = f"iter {len(h)} · backward"
        report["last_backward_diagnostics"] = [t for t in solver.trace if t["tag"] == tag]
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if solver is not None:
            report["trace"] = solver.trace
            report["oracles"] = solver.oracle_trace
        for problem in problems:
            problem.model.dispose()
        report["seconds"] = perf_counter() - start
        (directory / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({k: v for k, v in report.items() if k in ("case", "iterations", "optimal", "stalled", "relative_gap", "max_ens_above_demand", "error", "seconds")}, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pmax", type=float, nargs="+", default=[100., 30., 20., 15., 10.])
    parser.add_argument("--costs", type=float, nargs="+", default=[300., 1000., 3000.])
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--variant", choices=["baseline", "battery_4", "maintenance", "maintenance_battery_4"], default="baseline")
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--oracle-seconds", type=float, default=1.)
    parser.add_argument("--budget-scale", type=float, default=1.)
    args = parser.parse_args()
    config = replace(baseline.config, threads=1, nominal_replay=False,
                     max_iterations=args.max_iterations, upper_time_limit=args.oracle_seconds)
    directory = Path(__file__).resolve().parent / "results" / datetime.now().strftime("ens_%Y%m%d_%H%M%S_%f")
    directory.mkdir(parents=True)
    print(f"Resultados: {directory}", flush=True)
    for cost in args.costs:
        for capacity in args.pmax:
            run_case(capacity, cost, args.days, args.variant, config, directory, args.budget_scale)


if __name__ == "__main__":
    main()