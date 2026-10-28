"""Dos barras, una línea sin pérdidas y déficit penalizado; modelos aislados."""
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
import argparse
import json

import gurobipy as gp
import numpy as np

import main as baseline
from ens_experiments import ENSLower, ENSUpper, ENSRDDP
from iteration_experiments import build_case
from rddp.class_pus import PUSParameters
from rddp.class_system import DieselFleet, DieselUnit
from rddp.first_stage import FirstStageProblem


class NetworkLower(ENSLower):
    def __init__(self, system, config, pus, stage, capacity):
        if system.wind.n_parks != 2 or not np.isfinite(capacity) or capacity < 0:
            raise ValueError("Se requieren dos parques y capacidad finita no negativa")
        super().__init__(system, config, pus, stage)
        self.capacity = capacity
        self.flow = self.model.addVars(self.H, lb=-capacity, ub=capacity, name="flow_0_to_1")
        # Barra 0: solo parque 0. Barra 1: parque 1 y todos los otros recursos.
        self.remote_balance = self.model.addConstrs(
            (self.y_r[0, h] - self.flow[h] >= 0 for h in range(self.H)), name="balance_bus_0")

    def add_states_constraint(self, *args):
        super().add_states_constraint(*args)
        self.model.update()
        for h in range(self.H):
            self.model.chgCoeff(self.balance[h], self.y_r[0, h], 0.)
            self.model.chgCoeff(self.balance[h], self.flow[h], 1.)

    def solve(self):
        result = super().solve()
        result.flow = np.array([self.flow[h].X for h in range(self.H)])
        result.remote_price = np.array([self.remote_balance[h].Pi for h in range(self.H)])
        result.local_price = np.array([self.balance[h].Pi for h in range(self.H)])
        return result


class NetworkUpper(ENSUpper):
    def __init__(self, system, config, pus, stage, capacity):
        super().__init__(system, config, pus, stage)
        H = system.hours_per_day
        self.remote_price = self.model.addVars(H, lb=0., ub=system.c_ens, name="price_bus_0")
        plus = self.model.addVars(H, lb=0., name="line_upper_dual")
        minus = self.model.addVars(H, lb=0., name="line_lower_dual")
        self.model.update()
        for h in range(H):
            row = self.model.getConstrByName(f"wind_generator_flexibility_constraint[0,{h}]")
            if row is None:
                raise RuntimeError("No se encontró la restricción dual del parque remoto")
            self.model.chgCoeff(row, self.lambda_balance[h], 0.)
            self.model.chgCoeff(row, self.remote_price[h], 1.)
        self.model.addConstrs((self.lambda_balance[h] - self.remote_price[h]
            - plus[h] + minus[h] == 0 for h in range(H)), name="flow_dual")
        self.objective_bounds -= capacity * gp.quicksum(plus[h] + minus[h] for h in range(H))


class NetworkRDDP(ENSRDDP):
    def _lower(self, d, soc, a, realization):
        result = super()._lower(d, soc, a, realization)
        t = self.trace[-1]
        cap = self.lower[d].capacity
        local_supply = (result.y_r[1] + result.y_nr.sum(axis=0) + result.flow
            + result.pi_minus.sum(axis=0) - result.pi_plus.sum(axis=0) + result.ens)
        violation = max(float(np.maximum(result.demand - local_supply, 0).max()),
                        float(np.maximum(result.flow - result.y_r[0], 0).max()),
                        float(np.maximum(np.abs(result.flow) - cap, 0).max()))
        t.update(flow=result.flow.tolist(), remote_price=result.remote_price.tolist(),
            local_price=result.local_price.tolist(), network_violation=violation,
            congested_hours=int(np.count_nonzero(np.abs(result.flow) >= cap - 1e-6)),
            price_separation_hours=int(np.count_nonzero(result.local_price - result.remote_price > 1e-5)))
        return result


def run_case(capacity, pmax, cost, days, variant, budget, config, directory):
    system = replace(build_case(variant, days),
        diesel=DieselFleet((DieselUnit(pmax, 0., 100.),)), c_ens=cost)
    pus = PUSParameters.from_files()
    pus = replace(pus, wind=replace(pus.wind, phi=pus.wind.phi * budget, psi=pus.wind.psi * budget),
        demand=replace(pus.demand, phi=pus.demand.phi * budget, psi=pus.demand.psi * budget))
    report = dict(capacity=capacity, pmax=pmax, c_ens=cost, days=days, variant=variant,
        budget_scale=budget, config=asdict(config), maintenance_turbines=len(system.wind.J_r(days)))
    problems, solver = [], None
    started = perf_counter()
    try:
        first = FirstStageProblem(system, config)
        problems.append(first)
        upper, lower = [], []
        for d in range(days):
            upper.append(NetworkUpper(system, config, pus, d, capacity))
            problems.append(upper[-1])
            lower.append(NetworkLower(system, config, pus, d, capacity))
            problems.append(lower[-1])
        solver = NetworkRDDP(system, config, pus, first, upper, lower)
        result = solver.solve()
        h = result.history
        report.update(iterations=len(h), optimal=result.optimal, stalled=result.stalled,
            relative_gap=result.relative_gap, history=[asdict(x) for x in h],
            availability=result.plan.wind_availability.tolist(),
            max_ens_above_demand=max(t['max_ens_above_demand'] for t in solver.trace))
        assert all(t['network_violation'] < 1e-5 for t in solver.trace)
        assert all(np.isfinite([x.lower_bound, x.upper_bound]).all() and x.lower_bound <= x.upper_bound + 1e-5 * max(1., abs(x.upper_bound)) for x in h)
        assert all(a.lower_bound <= b.lower_bound + 1e-6 and a.upper_bound >= b.upper_bound - 1e-6 for a, b in zip(h, h[1:]))
        report['checks_passed'] = True
        report['last_backward'] = [t for t in solver.trace if t['tag'] == f'iter {len(h)} · backward']
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        if solver is not None:
            report.update(trace=solver.trace, oracles=solver.oracle_trace)
        for problem in problems:
            problem.model.dispose()
        report['seconds'] = perf_counter() - started
        name = f'{variant}_line{capacity:g}_p{pmax:g}_cost{cost:g}_budget{budget:g}'
        (directory / f'{name}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print({k: v for k, v in report.items() if k in ('capacity', 'iterations', 'optimal', 'stalled', 'relative_gap', 'error', 'seconds', 'max_ens_above_demand')}, flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limits', type=float, nargs='+', default=[100., 5., 2., 1.])
    parser.add_argument('--pmax', type=float, default=15.)
    parser.add_argument('--cost', type=float, default=300.)
    parser.add_argument('--days', type=int, default=3)
    parser.add_argument('--budget-scale', type=float, default=1.)
    parser.add_argument('--variant', choices=['baseline', 'maintenance', 'battery_4'], default='baseline')
    parser.add_argument('--oracle-seconds', type=float, default=3.)
    parser.add_argument('--max-iterations', type=int, default=12)
    args = parser.parse_args()
    config = replace(baseline.config, threads=1, nominal_replay=False,
        upper_time_limit=args.oracle_seconds, max_iterations=args.max_iterations)
    directory = Path(__file__).resolve().parent / 'results' / datetime.now().strftime('network_%Y%m%d_%H%M%S_%f')
    directory.mkdir(parents=True)
    print(f'Resultados: {directory}', flush=True)
    for limit in args.limits:
        run_case(limit, args.pmax, args.cost, args.days, args.variant, args.budget_scale, config, directory)


if __name__ == '__main__':
    main()