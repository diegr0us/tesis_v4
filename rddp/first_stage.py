import gurobipy as gp
import numpy as np
from rddp.class_system import Microgrid
from rddp.class_rddp import RDDPConfig

class FirstStageSolution:
    def __init__(
        self,
        v_r,
        m_r,
        a_r,
        A_r,
        x_crew,
        maintenance_cost,
        future_cost,
    ) -> None:
        self.v_r = v_r
        self.m_r = m_r
        self.a_r = a_r
        self.A_r = A_r
        self.x_crew = x_crew
        self.maintenance_cost = maintenance_cost
        self.future_cost = future_cost

class FirstStageProblem:
    """min costo de mantenimiento + θ. El modelo se arma una vez.

    Cada corte es θ >= alpha + beta' x_1 y queda en el mismo problema.
    ``solve`` actualiza y resuelve; se puede llamar de nuevo tras otro corte.
    """

    def __init__(
        self,
        system: Microgrid,
        config: RDDPConfig,
    ) -> None:
        self.system = system
        self.config = config
        self.model = model = gp.Model()
        model.Params.OutputFlag = config.output_flag
        model.Params.Threads = config.threads
        model.Params.MIPGap = config.first_stage_mip_gap
        if config.time_limit is not None:
            model.Params.TimeLimit = config.time_limit
        self.cuts = []
        # Conjuntos y parámetros de Notation RDDP thesis.md.
        # d = 0,...,D-1 en Python corresponde al día físico d+1 del documento.
        battery = system.battery
        Sin = battery.soc_ini
        wind = system.wind
        W = wind.n_parks
        D = system.horizon
        Y = wind.maintenance_days
        G_r = wind.G_r
        J_r = wind.J_r(D)
        turbines_by_park = [sum(1 for _, ww in J_r if ww == w) for w in range(W)]
        turbine_days = [(j, w, d) for j, w in J_r for d in range(D)]
        start_days = range(D - Y + 1)
        start_keys = [(j, w, d) for j, w in J_r for d in start_days]

        # v^r: inicio; m^r: mantenimiento activo; a^r: disponibilidad.
        # A_r agrega a^r por parque; x_crew representa c_{w,d} del documento.
        self.v_r = v_r = model.addVars(start_keys, vtype=gp.GRB.BINARY, name="v") if start_keys else {}
        self.m_r = m_r = model.addVars(turbine_days, vtype=gp.GRB.BINARY, name="m") if turbine_days else {}
        self.a_r = a_r = model.addVars(turbine_days, vtype=gp.GRB.BINARY, name="a") if turbine_days else {}
        self.A_r = A_r = model.addVars(W, D, lb=0.0, name="A_r")
        self.x_crew = x_crew = model.addVars(W, D, vtype=gp.GRB.BINARY, name="x_crew")

        # (2)–(3): exactamente un inicio por turbina, con término dentro de D.
        model.addConstrs(
            (gp.quicksum(v_r[j, w, d] for d in start_days) == 1 for j, w in J_r),
            name="maint_once",
        )
        # (4): m^r es la suma de los inicios de los últimos Y días.
        model.addConstrs(
            (
                m_r[j, w, d]
                == gp.quicksum(v_r[j, w, k] for k in start_days if d - Y < k <= d)
                for j, w, d in turbine_days
            ),
            name="maint_status",
        )
        # (5): antes de la falla basta no estar en mantenimiento; después de
        # la falla hace falta haberlo terminado. t_failure está en días 1-based.
        model.addConstrs(
            (
                a_r[j, w, d] == 1 - m_r[j, w, d]
                for j, w, d in turbine_days
                if d + 1 < int(wind.t_failure[w][j])
            ),
            name="availability_before",
        )
        model.addConstrs(
            (
                a_r[j, w, d]
                == gp.quicksum(v_r[j, w, k] for k in start_days if k <= d) - m_r[j, w, d]
                for j, w, d in turbine_days
                if d + 1 >= int(wind.t_failure[w][j])
            ),
            name="availability_after",
        )
        # A_{w,d} = |G_w^r| - |J_w^r| + sum_j a^r_{j,w,d}, el factor de (8).
        # El estado conserva este total, porque las turbinas de un parque
        # tienen la misma potencia y el despacho solo necesita su suma.
        model.addConstrs(
            (
                A_r[w, d]
                == G_r[w] - turbines_by_park[w] + gp.quicksum(a_r[j, w, d] for j, ww in J_r if ww == w)
                for w in range(W)
                for d in range(D)
            ),
            name="wind_farm_availability_constraint",
        )
        # (6)–(7): capacidad de una cuadrilla y número de cuadrillas por día.
        model.addConstrs(
            (
                gp.quicksum(m_r[j, w, d] for j, ww in J_r if ww == w)
                <= wind.maintenance_crew * x_crew[w, d]
                for w in range(W)
                for d in range(D)
            ),
            name="crew_constraint",
        )
        model.addConstrs(
            (gp.quicksum(x_crew[w, d] for w in range(W)) <= wind.max_crews for d in range(D)),
            name="crew_max_constraint",
        )

        # q_1'x_1 = costo robusto de mantenimiento + costo de cuadrillas.
        self.maintenance_cost = maintenance_cost = gp.LinExpr()
        if J_r:
            alpha_hat = wind.alpha_hat
            maintenance_cost += gp.quicksum(
                float(alpha_hat[w][j, d]) * v_r[j, w, d] for j, w, d in start_keys
            )
        maintenance_cost += gp.quicksum(
            wind.crew_cost * x_crew[w, d] for w in range(W) for d in range(D)
        )

        # x_1 que recibe Q_2: SOC inicial, luego A_{w,d} por día y parque.
        self.state = [float(soc) for soc in np.atleast_1d(Sin)]
        self.state += [A_r[w, d] for d in range(D) for w in range(W)]
        self.future_cost = future_cost = model.addVar(vtype=gp.GRB.CONTINUOUS, name="FutureCost")

        model.setObjective(maintenance_cost + future_cost, gp.GRB.MINIMIZE)
        model.update()

    def add_cut_lower(self, alpha: float, beta: np.ndarray) -> gp.Constr:
        """Agrega θ >= alpha + beta' x_1 y actualiza el modelo para un corte inferior."""
        slope = np.asarray(beta, dtype=float).reshape(-1)
        if not np.isfinite(alpha) or not np.isfinite(slope).all():
            raise ValueError("El corte debe tener coeficientes finitos.")
        if slope.size != len(self.state):
            raise ValueError(
                f"El corte tiene {slope.size} pendientes y el estado tiene {len(self.state)}."
            )
        cut = self.model.addConstr(
            self.future_cost
            >= float(alpha) + gp.quicksum(float(slope[i]) * self.state[i] for i in range(slope.size)),
            name=f"cut_{len(self.cuts)}",
        )
        self.cuts.append(cut)
        self.model.update()
        return cut

    def solve(self) -> FirstStageSolution:
        """Actualiza el modelo, con los cortes ya agregados, y lo resuelve."""
        self.model.update()
        self.model.optimize()
        if self.model.SolCount == 0 or self.model.Status in (
            gp.GRB.INFEASIBLE, gp.GRB.INF_OR_UNBD, gp.GRB.UNBOUNDED,
        ):
            raise RuntimeError(f"Primera etapa sin solución utilizable: {self.model.Status}.")
        return FirstStageSolution(
            v_r=self.v_r,
            m_r=self.m_r,
            a_r=self.a_r,
            A_r=self.A_r,
            x_crew=self.x_crew,
            maintenance_cost=self.maintenance_cost,
            future_cost=self.future_cost,
        )


