"""RDDP: maestro inferior, trayectoria forward y refinamiento backward."""
from __future__ import annotations

import numpy as np
import gurobipy as gp
from rddp.class_system import Microgrid
from rddp.class_pus import PUSParameters
from rddp.class_rddp import RDDPConfig, RDDPResult, RDDPIteration, MaintenancePlan, DayOperation
from rddp.first_stage import FirstStageProblem
from rddp.recourse_stages import RecourseStage_Lower, RecourseStage_Upper


class RDDP:
    def __init__(self, system: Microgrid, config: RDDPConfig, pus: PUSParameters,
                 first_stage=None, upper_stages=None, lower_stages=None) -> None:
        if config.ub_method != "bilinear":
            raise NotImplementedError("Solo est? implementado el or?culo bilineal.")
        self.system, self.config, self.pus = system, config, pus
        self.T = system.horizon
        self.first = first_stage if first_stage is not None else FirstStageProblem(system, config)
        self.upper = upper_stages if upper_stages is not None else [
            RecourseStage_Upper(system, config, pus, d) for d in range(self.T)]
        self.lower = lower_stages if lower_stages is not None else [
            RecourseStage_Lower(system, config, pus, d) for d in range(self.T)]
        if len(self.upper) != self.T or len(self.lower) != self.T:
            raise ValueError("Se requiere un upper y un lower por d?a.")
        self.points = [[] for _ in range(self.T)]
        self.cuts = [[] for _ in range(self.T)]
        self.backup = self._initial_bounds()
        for d in range(self.T - 1):
            self.upper[d].initialize_upper_bound(self.backup[d + 1])
        self._solved = False

    def _initial_bounds(self):
        """Pol?tica factible: no usar viento/bater?a, salvo carga terminal.

        Desde cualquier SOC en su caja se puede cargar hasta soc_final en el
        ?ltimo d?a. Demanda acotada por la caja PCA; despacho di?sel hasta pmax.
        Esto certifica recourse completo y una cota constante para toda A.
        """
        s, b = self.system, self.system.battery
        if not s.diesel.n_units or np.any(s.diesel.c_var < 0):
            raise ValueError("El respaldo requiere di?sel y costos no negativos.")
        if (np.any(b.eta <= 0) or np.any(b.eta > 1) or np.any(b.soc_min > b.soc_max)
                or np.any(b.soc_ini < b.soc_min) or np.any(b.soc_ini > b.soc_max)
                or np.any(b.soc_final < b.soc_min) or np.any(b.soc_final > b.soc_max)):
            raise ValueError("SOC/eficiencias fuera del dominio del respaldo.")
        required_charge = (b.soc_final - b.soc_min) / (b.eta * s.hours_per_day)
        if np.any(required_charge > b.pch + 1e-9):
            raise ValueError("No se puede garantizar SOC terminal desde soc_min en un d?a.")
        capacity = float(sum(s.diesel.pmax))
        cost = float(max(s.diesel.c_var))
        daily = []
        for d, upper in enumerate(self.upper):
            upper.model.update()
            demand_max = np.array([upper.demand[h].UB for h in range(s.hours_per_day)])
            if not np.isfinite(demand_max).all() or np.any(demand_max < 0):
                raise ValueError("Soporte de demanda inv?lido.")
            charge = float(sum(required_charge)) if d == self.T - 1 else 0.0
            if np.any(demand_max + charge > capacity + 1e-9):
                raise ValueError(f"D?a {d}: el respaldo sin viento excede la capacidad di?sel.")
            daily.append(cost * float(sum(demand_max + charge)))
        return np.cumsum(daily[::-1])[::-1]

    def _upper(self, d, soc, a):
        if d < self.T - 1:
            self.upper[d].add_convex_hull_restrictions(self.points[d + 1], a)
        self.upper[d].add_states_constraint(soc, a)
        result = self.upper[d].solve()
        if result.bound is None or not np.isfinite(result.bound):
            raise RuntimeError(f"D?a {d}: or?culo sin cota superior finita.")
        return result

    def _lower(self, d, soc, a, realization):
        self.lower[d].add_states_constraint(soc, a, realization.pwind, realization.demand)
        return self.lower[d].solve()

    def _add_cut(self, d, soc, a, value):
        state = np.concatenate((soc, a.T.reshape(-1)))
        old = max([0.0] + [alpha + beta @ state for alpha, beta in self.cuts[d]])
        if value <= old + self.config.cut_tolerance:
            return False
        alpha, beta = self.lower[d].generate_cut()
        self.cuts[d].append((alpha, beta.copy()))
        if d == 0:
            self.first.add_cut_lower(alpha, beta)
        else:
            self.lower[d - 1].add_cut_lower(alpha, beta)
        return True

    def _add_point(self, d, soc, a, bound):
        value = min(float(bound), float(self.backup[d]))
        if value >= self.backup[d] - self.config.cut_tolerance:
            return False
        for i, (pa, ps, old) in enumerate(self.points[d]):
            if np.array_equal(pa, a) and np.array_equal(ps, soc):
                if value >= old - self.config.cut_tolerance:
                    return False
                self.points[d][i] = (a.copy(), soc.copy(), value)
                return True
        self.points[d].append((a.copy(), soc.copy(), value))
        return True

    def _snapshot(self):
        s = self.system
        a = np.array([[self.first.A_r[w, d].X for d in range(self.T)]
                      for w in range(s.wind.n_parks)])
        plan = MaintenancePlan(
            {key: v.X for key, v in self.first.v_r.items()},
            {key: v.X for key, v in self.first.m_r.items()}, a.copy(),
            np.array([[self.first.x_crew[w, d].X for d in range(self.T)]
                      for w in range(s.wind.n_parks)]))
        return a, float(self.first.maintenance_cost.getValue()), plan

    def _replay(self, a):
        """Centro PCA si es admisible; nunca se recorta una reconstrucci?n negativa."""
        from types import SimpleNamespace
        profiles = []
        for d in range(self.T):
            values = []
            for group, rec in ((self.pus.wind, self.pus.wind_reconstruction),
                               (self.pus.demand, self.pus.demand_reconstruction)):
                value = rec.forecast[d] + rec.b + rec.L @ group.c
                if np.any(value < 0):
                    raise ValueError("Centro PCA no admisible: desactiva nominal_replay o define una realizaci?n factible.")
                values.append(value)
            profiles.append(SimpleNamespace(pwind=values[0].reshape(self.system.wind.n_parks, -1),
                                            demand=values[1]))
        soc = self.system.battery.soc_ini.copy()
        operations = []
        for d, realization in enumerate(profiles):
            r = self._lower(d, soc, a, realization)
            operations.append(DayOperation(r.y_r, r.y_nr, r.pi_plus, r.pi_minus, r.soc,
                np.zeros(self.system.hours_per_day), r.demand, r.pwind, a[:, d]))
            soc = r.soc[:, -1].copy()
        return tuple(operations)

    def solve(self) -> RDDPResult:
        if self._solved:
            raise RuntimeError("Crea una instancia nueva para iniciar otra corrida RDDP.")
        self._solved = True
        lb, ub = -np.inf, np.inf
        history = []
        best = None
        optimal = stalled = False
        slack = 0.0
        for iteration in range(1, self.config.max_iterations + 1):
            self.first.solve()
            master_bound = float(self.first.model.ObjBound)
            if not np.isfinite(master_bound):
                raise RuntimeError("El maestro no devolvi? una cota inferior finita.")
            lb = max(lb, master_bound)
            a, maintenance, plan = self._snapshot()
            incoming = []
            soc = self.system.battery.soc_ini.copy()
            # Forward visita estados; la ?ltima realizaci?n no es necesaria para backward.
            changed = False
            for d in range(self.T):
                incoming.append(soc.copy())
                if d == self.T - 1:
                    break
                adversary = self._upper(d, soc, a)
                dispatch = self._lower(d, soc, a, adversary)
                if self.config.cuts_in_forward:
                    changed |= self._add_cut(d, soc, a, dispatch.objective)
                    changed |= self._add_point(d, soc, a, adversary.bound)
                soc = dispatch.soc[:, -1].copy()
            # Asegura que el lower predecesor tenga estado incluso con T=1.
            slack = 0.0
            for d in reversed(range(self.T)):
                adversary = self._upper(d, incoming[d], a)
                slack += max(0.0, adversary.bound - adversary.objective)
                changed |= self._add_point(d, incoming[d], a, adversary.bound)
                dispatch = self._lower(d, incoming[d], a, adversary)
                changed |= self._add_cut(d, incoming[d], a, dispatch.objective)
                if d == 0:
                    candidate = maintenance + min(adversary.bound, self.backup[0])
                    if candidate < ub:
                        ub = candidate
                        best = (a.copy(), maintenance, plan)
            gap = ub - lb
            if gap < -1e-6 * max(1.0, abs(ub)):
                raise RuntimeError("LB > UB: revisar cortes y certificados del solver.")
            relative = max(0.0, gap) / max(1.0, abs(ub))
            optimal = gap <= self.config.absolute_gap or relative <= self.config.relative_gap
            stalled = self.config.stop_on_stall and not changed and not optimal
            history.append(RDDPIteration(iteration, lb, ub, relative,
                sum(map(len, self.cuts)), sum(map(len, self.points)), maintenance, slack))
            if self.config.verbose:
                print(f"RDDP {iteration}: LB={lb:.6f} UB={ub:.6f} gap={relative:.3%} "
                      f"cortes={history[-1].n_cuts} puntos={history[-1].n_points}", flush=True)
            if optimal or stalled:
                break
        assert best is not None
        a, cost, plan = best
        operation = self._replay(a) if self.config.nominal_replay else ()
        return RDDPResult(lb, ub, history[-1].relative_gap, optimal,
            np.concatenate((self.system.battery.soc_ini, a.T.reshape(-1))), cost, plan,
            tuple(history), sum(map(len, self.cuts)), sum(map(len, self.points)),
            operation, stalled, slack)
