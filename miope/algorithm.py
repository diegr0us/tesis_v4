"""Plan de mantenimiento miope: un MIP, sin despacho ni costo futuro."""
from __future__ import annotations

import numpy as np
from miope.class_system import Microgrid
from miope.class_rddp import RDDPConfig, RDDPResult, RDDPIteration, MaintenancePlan
from miope.first_stage import FirstStageProblem


class RDDP:
    def __init__(self, system: Microgrid, config: RDDPConfig, first_stage=None) -> None:
        self.system, self.config = system, config
        self.T = system.horizon
        self.first = first_stage if first_stage is not None else FirstStageProblem(system, config)
        self._solved = False

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

    def solve(self) -> RDDPResult:
        if self._solved:
            raise RuntimeError("Crea una instancia nueva para resolver otro plan.")
        self._solved = True
        self.first.solve_tag = "mantenimiento miope"
        self.first.solve()
        lb = float(self.first.model.ObjBound)
        ub = float(self.first.model.ObjVal)
        if not np.isfinite(lb) or not np.isfinite(ub):
            raise RuntimeError("El mantenimiento miope no devolvió cotas finitas.")
        a, cost, plan = self._snapshot()
        gap = ub - lb
        if gap < -1e-6 * max(1.0, abs(ub)):
            raise RuntimeError("LB > UB en el mantenimiento miope.")
        relative = max(0.0, gap) / max(1.0, abs(ub))
        optimal = gap <= self.config.absolute_gap or relative <= self.config.relative_gap
        history = (RDDPIteration(1, lb, ub, relative, 0, 0, cost, 0.0),)
        if self.config.verbose:
            print(f"Mantenimiento miope: LB={lb:.6f} UB={ub:.6f} gap={relative:.3%} "
                  f"costo={cost:.6f}", flush=True)
        return RDDPResult(
            lb, ub, relative, optimal, a.T.reshape(-1), cost, plan,
            history, 0, 0, (), False, 0.0, (),
        )
