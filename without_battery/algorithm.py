"""RDDP: maestro inferior, trayectoria forward y refinamiento backward."""
from __future__ import annotations

import numpy as np
from without_battery.class_system import Microgrid
from without_battery.class_pus import PUSParameters
from without_battery.class_rddp import RDDPConfig, RDDPResult, RDDPIteration, MaintenancePlan, DayOperation
from without_battery.first_stage import FirstStageProblem
from without_battery.recourse_stages import RecourseStage_Lower, RecourseStage_Upper


class RDDP:
    def __init__(self, system: Microgrid, config: RDDPConfig, pus: PUSParameters,
                 first_stage=None, upper_stages=None, lower_stages=None) -> None:
        if config.ub_method != "bilinear":
            raise NotImplementedError("Solo está implementado el oráculo bilineal.")
        self.system, self.config, self.pus = system, config, pus
        self.T = system.horizon
        self.first = first_stage if first_stage is not None else FirstStageProblem(system, config)
        self.upper = upper_stages if upper_stages is not None else [
            RecourseStage_Upper(system, config, pus, d) for d in range(self.T)]
        self.lower = lower_stages if lower_stages is not None else [
            RecourseStage_Lower(system, config, pus, d) for d in range(self.T)]
        if len(self.upper) != self.T or len(self.lower) != self.T:
            raise ValueError("Se requiere un upper y un lower por día.")
        self.points = [[] for _ in range(self.T)]
        self.cuts = [[] for _ in range(self.T)]
        self.backup = self._initial_bounds()
        for d in range(self.T - 1):
            self.upper[d].initialize_upper_bound(self.backup[d + 1])
        self._solved = False

    def _initial_bounds(self):
        """Política factible: servir la demanda con diésel, sin viento.

        La demanda está acotada por la caja PCA y el diésel llega hasta pmax.
        Esto certifica recourse completo y una cota constante para toda A.
        """
        s = self.system
        if not s.diesel.n_units or np.any(s.diesel.c_var < 0):
            raise ValueError("El respaldo requiere diésel y costos no negativos.")
        capacity = float(sum(s.diesel.pmax))
        cost = float(max(s.diesel.c_var))
        daily = []
        for d, upper in enumerate(self.upper):
            upper.model.update()
            demand_max = np.array([upper.demand[h].UB for h in range(s.hours_per_day)])
            if not np.isfinite(demand_max).all() or np.any(demand_max < 0):
                raise ValueError("Soporte de demanda inválido.")
            if np.any(demand_max > capacity + 1e-9):
                raise ValueError(f"Día {d}: el respaldo sin viento excede la capacidad diésel.")
            daily.append(cost * float(sum(demand_max)))
        return np.cumsum(daily[::-1])[::-1]

    def _upper(self, d, a):
        if d < self.T - 1:
            self.upper[d].add_convex_hull_restrictions(self.points[d + 1], a)
        self.upper[d].add_states_constraint(a)
        result = self.upper[d].solve()
        if result.bound is None or not np.isfinite(result.bound):
            raise RuntimeError(f"Día {d}: oráculo sin cota superior finita.")
        return result

    def _lower(self, d, a, realization):
        self.lower[d].add_states_constraint(a, realization.pwind, realization.demand)
        return self.lower[d].solve()

    def _add_cut(self, d, a, value):
        state = a.T.reshape(-1)
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

    def _add_point(self, d, a, bound):
        value = min(float(bound), float(self.backup[d]))
        if value >= self.backup[d] - self.config.cut_tolerance:
            return False
        for i, (pa, old) in enumerate(self.points[d]):
            if np.array_equal(pa, a):
                if value >= old - self.config.cut_tolerance:
                    return False
                self.points[d][i] = (a.copy(), value)
                return True
        self.points[d].append((a.copy(), value))
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

    def _operation(self, dispatch, a, d):
        return DayOperation(
            dispatch.y_r, dispatch.y_nr, np.zeros(self.system.hours_per_day),
            dispatch.demand, dispatch.pwind, a[:, d],
        )

    def _replay(self, a):
        """Centro PCA si es admisible; nunca se recorta una reconstrucción negativa."""
        from types import SimpleNamespace
        profiles = []
        for d in range(self.T):
            values = []
            for group, rec in ((self.pus.wind, self.pus.wind_reconstruction),
                               (self.pus.demand, self.pus.demand_reconstruction)):
                value = rec.forecast[d] + rec.b + rec.L @ group.c
                if np.any(value < 0):
                    raise ValueError(
                        "Centro PCA no admisible: desactiva nominal_replay o define una realización factible."
                    )
                values.append(value)
            profiles.append(SimpleNamespace(
                pwind=values[0].reshape(self.system.wind.n_parks, -1),
                demand=values[1],
            ))
        operations = []
        for d, realization in enumerate(profiles):
            self.lower[d].solve_tag = "replay nominal"
            operations.append(self._operation(self._lower(d, a, realization), a, d))
        return tuple(operations)

    def _worst_case(self, a):
        """Realización adversa y despacho del plan, con las cotas finales.

        Cada día el oráculo elige viento y demanda y el LP inferior despacha
        esa realización. Si el oráculo termina con holgura, la trayectoria usa
        su incumbente.
        """
        operations = []
        for d in range(self.T):
            self.upper[d].solve_tag = "peor caso"
            self.lower[d].solve_tag = "peor caso"
            adversary = self._upper(d, a)
            operations.append(self._operation(self._lower(d, a, adversary), a, d))
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
            self.first.solve_tag = f"iter {iteration} · maestro"
            self.first.solve()
            master_bound = float(self.first.model.ObjBound)
            if not np.isfinite(master_bound):
                raise RuntimeError("El maestro no devolvió una cota inferior finita.")
            lb = max(lb, master_bound)
            a, maintenance, plan = self._snapshot()
            # El forward fija el estado de cada predecesor para poder instalar el corte.
            changed = False
            for d in range(self.T - 1):
                tag = f"iter {iteration} · forward"
                self.upper[d].solve_tag = tag
                self.lower[d].solve_tag = tag
                adversary = self._upper(d, a)
                dispatch = self._lower(d, a, adversary)
                if self.config.cuts_in_forward:
                    changed |= self._add_cut(d, a, dispatch.objective)
                    changed |= self._add_point(d, a, adversary.bound)
            slack = 0.0
            for d in reversed(range(self.T)):
                tag = f"iter {iteration} · backward"
                self.upper[d].solve_tag = tag
                self.lower[d].solve_tag = tag
                adversary = self._upper(d, a)
                slack += max(0.0, adversary.bound - adversary.objective)
                changed |= self._add_point(d, a, adversary.bound)
                dispatch = self._lower(d, a, adversary)
                changed |= self._add_cut(d, a, dispatch.objective)
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
        worst_case = self._worst_case(a) if self.config.worst_case_replay else ()
        return RDDPResult(lb, ub, history[-1].relative_gap, optimal,
            a.T.reshape(-1), cost, plan,
            tuple(history), sum(map(len, self.cuts)), sum(map(len, self.points)),
            operation, stalled, slack, worst_case)
