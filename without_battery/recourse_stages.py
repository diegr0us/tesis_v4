import gurobipy as gp
import numpy as np
from without_battery.class_system import Microgrid
from without_battery.class_rddp import RDDPConfig, announce_solve
from without_battery.class_pus import PUSParameters


def _array(value, shape, name):
    result = np.array(value, dtype=float, copy=True)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(f"{name} debe tener forma {shape} y valores finitos.")
    return result


def _availability(system, value):
    """A_r[w, d]: número de turbinas disponibles, no fracción ni perfil horario."""
    result = _array(value, (system.wind.n_parks, system.horizon), "availability")
    if np.any(result < 0) or np.any(result > np.asarray(system.wind.G_r)[:, None]):
        raise ValueError("availability debe estar entre 0 y G_r por parque.")
    return result


def _configure(model, config, stage, system):
    if not isinstance(stage, (int, np.integer)) or not 0 <= stage < system.horizon:
        raise ValueError("stage debe ser un día operativo entre 0 y horizon - 1.")
    model.Params.OutputFlag = config.output_flag
    model.Params.Threads = config.threads
    if config.time_limit is not None:
        model.Params.TimeLimit = config.time_limit


def _values(variables, rows, columns):
    return np.array([
        variables[i, h].X for i in range(rows) for h in range(columns)
    ]).reshape(rows, columns)


class RecourseStageSolution:
    def __init__(
        self,
        y_r: np.ndarray | None,
        y_nr: np.ndarray | None,
        future_cost: float | None,
        pwind: np.ndarray | None,
        demand: np.ndarray | None,
        objective: float | None = None,
        bound: float | None = None,
        status: int | None = None,
    ) -> None:
        self.y_r = y_r
        self.y_nr = y_nr
        self.future_cost = future_cost
        self.pwind = pwind
        self.demand = demand
        self.objective = objective
        self.bound = bound
        self.status = status


class RecourseStage_Lower:
    """Problema que resuelve usando la aproximacion de costo futuro inferior.
    Es un LP con incertidumbre fija. Cambia en cada iteración.
    En cada iteración se agrega un corte de la forma θ >= alpha + beta' x_1
    """
    def __init__(
        self,
        system: Microgrid,
        config: RDDPConfig,
        pus: PUSParameters,
        stage: int,
    ) -> None:
        self.system = system
        self.config = config
        self.model = model = gp.Model(f"lower día {stage + 1}/{system.horizon}")
        self.solve_tag = ""
        _configure(model, config, stage, system)
        model.Params.Method = config.lp_method
        self.stage = stage
        self.cuts = []
        self.pus = pus
        self.cut_data = []
        self.state = None

        # Restricciones que dependen de la realización y cambian en cada iteración
        self.wind_limits = None
        self.balance = None

        diesel = system.diesel
        self.wind = wind = system.wind
        G_nr = diesel.n_units
        W = wind.n_parks
        self.H = H = system.hours_per_day

        self.y_r = model.addVars(W, H, lb=0.0, name="y_r")
        self.y_nr = model.addVars(G_nr, H, lb=0.0, name="y_nr")

        model.addConstrs(
            (
                self.y_nr[g, h] <= float(diesel.pmax[g])
                for g in range(G_nr)
                for h in range(H)
            ),
            name="conventional_generator_output_constraint",
        )

        last_day = self.stage == system.horizon - 1
        self.future_cost = model.addVar(ub=0.0 if last_day else gp.GRB.INFINITY, name="future_cost")
        self.operation_cost = gp.quicksum(
            float(diesel.c_var[g]) * self.y_nr[g, h] for g in range(G_nr) for h in range(H)
        )
        model.setObjective(self.operation_cost + self.future_cost, gp.GRB.MINIMIZE)


    def add_states_constraint(self, availability, pwind: np.ndarray, demand: np.ndarray) -> None:
        """Fija la disponibilidad y la realización; pwind es potencia por turbina."""
        model = self.model
        wind = self.wind
        H = self.H
        G_nr = self.system.diesel.n_units
        W = wind.n_parks
        availability = _availability(self.system, availability)
        self.pwind = pwind = _array(pwind, (W, H), "pwind")
        self.demand = demand = _array(demand, (H,), "demand")
        self.availability = availability.copy()
        self.state = [
            float(availability[w, d])
            for d in range(self.system.horizon)
            for w in range(W)
        ]
        # Parque disponible = p (por turbina) * A (turbinas disponibles).

        if self.wind_limits is not None:
            model.remove(self.wind_limits)
        self.wind_limits = model.addConstrs(
            (
                self.y_r[w, h] <= pwind[w, h] * availability[w, self.stage]
                for w in range(wind.n_parks)
                    for h in range(H)
            ),
            name="wind_limits",
        )
        if self.balance is not None:
            model.remove(self.balance)
        self.balance = model.addConstrs(
            (
                gp.quicksum(self.y_r[w, h] for w in range(W))
                + gp.quicksum(self.y_nr[g, h] for g in range(G_nr))
                >= float(demand[h])
                for h in range(H)
            ),
            name="power_balance_constraint",
        )
        # Reemplazar las restricciones de los cortes usando el estado actualizado.
        # cut_data conserva todos los cortes acumulados y sus coeficientes originales.
        if self.cuts:
            model.remove(self.cuts)
        self.cuts = []
        for alpha, slope in self.cut_data:
            cut = model.addConstr(
                self.future_cost
                >= float(alpha) + gp.quicksum(
                    float(slope[i]) * self.state[i] for i in range(slope.size)
                ),
                name=f"cut_{len(self.cuts)}",
            )
            self.cuts.append(cut)

    def add_cut_lower(self, alpha: float, beta: np.ndarray) -> gp.Constr:
        """Agrega θ >= alpha + beta' x_1 y actualiza el modelo para un corte inferior."""
        slope = np.asarray(beta, dtype=float).reshape(-1)
        if self.stage == self.system.horizon - 1:
            raise ValueError("La etapa terminal tiene costo futuro cero y no admite cortes.")
        if self.state is None:
            raise ValueError("Primero fija el estado con add_states_constraint.")
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
        self.cut_data.append((float(alpha), slope.copy()))
        self.model.update()
        return cut

    def generate_cut(self) -> tuple[float, np.ndarray]:
        """Corte sobre el estado entrante; usar inmediatamente después del LP óptimo."""
        if self.model.Status != gp.GRB.OPTIMAL:
            raise RuntimeError("Se necesitan duales de un LP óptimo para generar el corte.")
        W, T = self.wind.n_parks, self.system.horizon
        beta = np.zeros(W * T)
        for w in range(W):
            beta[self.stage * W + w] = sum(
                self.wind_limits[w, h].Pi * self.pwind[w, h]
                for h in range(self.H)
            )
        for cut, (_, slope) in zip(self.cuts, self.cut_data):
            beta += cut.Pi * slope
        state = self.availability.T.reshape(-1)
        alpha = float(self.model.ObjVal - beta @ state)
        return alpha, beta

    def solve(self) -> RecourseStageSolution:
        """Actualiza el modelo, con los cortes ya agregados, y lo resuelve."""
        if self.state is None:
            raise ValueError("Primero fija el estado y la realización.")
        announce_solve(self.model.ModelName, int(self.model.Params.OutputFlag), self.solve_tag)
        self.model.update()
        self.model.optimize()
        if self.model.Status != gp.GRB.OPTIMAL:
            raise RuntimeError(f"El LP no alcanzó un óptimo; status={self.model.Status}.")
        return RecourseStageSolution(
            y_r=_values(self.y_r, self.wind.n_parks, self.H),
            y_nr=_values(self.y_nr, self.system.diesel.n_units, self.H),
            future_cost=self.future_cost.X,
            pwind=self.pwind.copy(),
            demand=self.demand.copy(),
            objective=self.model.ObjVal,
            bound=self.model.ObjVal,
            status=self.model.Status,
        )



class RecourseStage_Upper:
    """Problema que resuelve usando la aproximacion de costo futuro superior.
    Se dualiza el problema inner obtenido un problema bilineal.
    En cada iteración se agrega un punto para la convex hull del costo futuro
    """
    def __init__(
        self,
        system: Microgrid,
        config: RDDPConfig,
        pus: PUSParameters,
        stage: int,
    ) -> None:
        self.system = system
        self.config = config
        self.model = model = gp.Model(f"upper día {stage + 1}/{system.horizon}")
        self.solve_tag = ""
        _configure(model, config, stage, system)
        model.Params.NonConvex = 2
        model.Params.MIPGap = config.upper_mip_gap
        if config.upper_mip_gap_abs is not None:
            model.Params.MIPGapAbs = config.upper_mip_gap_abs
        if config.upper_time_limit is not None:
            model.Params.TimeLimit = config.upper_time_limit
        self.stage = stage
        self.pus = pus

        # Restricciones del problema dualizado
        diesel = system.diesel
        fleet = system.wind
        G_nr = diesel.n_units
        W = fleet.n_parks
        H = self.system.hours_per_day
        T = system.horizon
        self.last_day = last_day = stage == T - 1
        self.availability = None

        self.pwind = model.addVars(W, H, lb=-gp.GRB.INFINITY, name="pwind")
        self.demand = model.addVars(H, lb=-gp.GRB.INFINITY, name="demand")

        # PUS histórico de pca.py: z = c + a*theta, |theta| <= 1.
        # No se usa el soporte FM ni se recalibran c/a/phi/psi por día.
        pus.validate_reconstruction(W, H, T)
        self.theta = {}
        self.theta_abs = {}
        self.pca_scores = {}
        for name, group, reconstruction in (
            ("wind", pus.wind, pus.wind_reconstruction),
            ("demand", pus.demand, pus.demand_reconstruction),
        ):
            assert reconstruction is not None
            theta = model.addVars(group.r, lb=-1.0, ub=1.0, name=f"theta_{name}")
            magnitude = model.addVars(group.r, lb=0.0, ub=1.0, name=f"abs_theta_{name}")
            scores = model.addVars(group.r, lb=-gp.GRB.INFINITY, name=f"score_{name}")
            self.theta[name], self.theta_abs[name], self.pca_scores[name] = theta, magnitude, scores
            # Epígrafe de |theta|: exacto en proyección porque solo entra en cotas superiores.
            model.addConstrs((magnitude[j] >= theta[j] for j in range(group.r)), name=f"abs_positive_{name}")
            model.addConstrs((magnitude[j] >= -theta[j] for j in range(group.r)), name=f"abs_negative_{name}")
            model.addConstr(gp.quicksum(magnitude[j] for j in range(group.r)) <= group.phi,
                            name=f"budget_total_{name}")
            model.addConstrs(
                (magnitude[i] + magnitude[j] <= group.psi
                 for i in range(group.s) for j in range(i + 1, group.s)),
                name=f"budget_pairs_{name}",
            )
            model.addConstrs(
                (scores[j] == float(group.c[j]) + float(group.a[j]) * theta[j]
                 for j in range(group.r)), name=f"score_reconstruction_{name}",
            )
            # u_d = forecast_d + b + L*z. Un único vector de scores eólicos
            # conserva la dependencia entre parques y horas del mismo día.
            for i in range(reconstruction.L.shape[0]):
                value = self.pwind[i // H, i % H] if name == "wind" else self.demand[i]
                center = float(reconstruction.forecast[stage, i] + reconstruction.b[i])
                model.addConstr(
                    value == center + gp.quicksum(
                        float(reconstruction.L[i, j]) * scores[j] for j in range(group.r)
                    ), name=f"physical_reconstruction_{name}[{i}]",
                )
                # Cotas implícitas de la caja histórica, no límites nominales ni FM.
                midpoint = center + float(reconstruction.L[i] @ group.c)
                radius = float(np.abs(reconstruction.L[i]) @ group.a)
                # max se evalúa entre constantes en Python, no entre variables del modelo.
                value.LB = max(0.0, midpoint - radius)
                value.UB = midpoint + radius

        # Restricciones de la envoltura convexa
        self.kappa_0 = model.addVar(lb=-gp.GRB.INFINITY, name="kappa_0") if not last_day else None
        self.kappa_a = model.addVars(W, T, lb=-gp.GRB.INFINITY, name="kappa_a") if not last_day else None
        self.hull_restrictions = []
        self.initial_upper_bound = None
        self._state_ready = False

        lambda_pmax = model.addVars(G_nr, H, lb=0.0, name="lambda_pnr_max")
        self.lambda_wind = lambda_wind = model.addVars(W, H, lb=0.0, ub = float(diesel.pmax[0]), name="lambda_pw_max_curve")
        self.lambda_balance = lambda_balance = model.addVars(H, lb=0.0, ub = float(diesel.pmax[0]), name="lambda_bal")

        # Columnas del primal: viento y diésel, sin ENS.
        model.addConstrs(
            (
                -lambda_wind[w, h] + lambda_balance[h] <= 0.0
                for w in range(W)
                for h in range(H)
            ),
            name="wind_generator_flexibility_constraint",
        )
        model.addConstrs(
            (
                -lambda_pmax[g, h] + lambda_balance[h] <= float(diesel.c_var[g])
                for g in range(G_nr)
                for h in range(H)
            ),
            name="conventional_generator_flexibility_constraint",
        )

        self.objective_bounds = -gp.quicksum(
            float(diesel.pmax[g]) * lambda_pmax[g, h]
            for g in range(G_nr) for h in range(H)
        )
        model.ModelSense = gp.GRB.MAXIMIZE

    def initialize_upper_bound(self, bound: float) -> None:
        """Envolvente de puntos y respaldo constante en la caja de A.

        Impone kappa_0 + max_{A en caja} kappa_A'A <= bound mediante
        auxiliares positivos. Equivale a incluir todos los vértices de
        0 <= A <= G_r a altura bound, sin enumerarlos. El llamador justifica bound.
        """
        if self.last_day or self.initial_upper_bound is not None:
            raise ValueError("El respaldo se inicializa una vez en etapas no terminales.")
        if not np.isfinite(bound) or bound < 0:
            raise ValueError("El respaldo debe ser finito y no negativo.")
        k0, ka = self.kappa_0, self.kappa_a
        assert k0 is not None and ka is not None
        expression = gp.LinExpr(k0)
        for w in range(self.system.wind.n_parks):
            for d in range(self.system.horizon):
                positive = self.model.addVar(lb=0.0, name=f"backup_A_positive[{w},{d}]")
                self.model.addConstr(positive >= ka[w, d])
                expression += float(self.system.wind.G_r[w]) * positive
        self.model.addConstr(expression <= bound, name="initial_upper_envelope")
        self.initial_upper_bound = float(bound)

    def add_convex_hull_restrictions(self, points: list[tuple[np.ndarray, float]], availability: np.ndarray) -> None:
        """Reemplaza puntos (A_r[W,T], valor) de la etapa siguiente."""
        if self.last_day:
            raise ValueError("La etapa terminal no tiene envolvente de continuación.")
        kappa_0, kappa_a = self.kappa_0, self.kappa_a
        assert kappa_0 is not None and kappa_a is not None
        availability = _availability(self.system, availability)
        validated = []
        for a, value in points:
            a = _availability(self.system, a)
            if not np.isfinite(value):
                raise ValueError("El valor del punto debe ser finito.")
            validated.append((a, float(value)))
        self.model.remove(self.hull_restrictions)
        self.hull_restrictions = []
        W = self.system.wind.n_parks
        T = self.system.horizon
        for p, (a, value) in enumerate(validated):
            self.hull_restrictions.append(self.model.addConstr(
                kappa_0
                + gp.quicksum(kappa_a[w, d] * a[w, d] for w in range(W) for d in range(T))
                <= value,
                name=f"hull_restriction_{p}",
            ))
        self.availability = availability
        if self._state_ready:
            self._set_objective()

    def add_states_constraint(self, availability: np.ndarray) -> None:
        """Fija la disponibilidad; la incertidumbre sigue siendo variable en el objetivo."""
        self.availability = _availability(self.system, availability)
        self._state_ready = True
        self._set_objective()

    def _set_objective(self) -> None:
        availability = self.availability
        if availability is None:
            raise ValueError("Primero fija la disponibilidad.")
        W = self.system.wind.n_parks
        H = self.system.hours_per_day
        T = self.system.horizon
        self.objective_operation = self.objective_bounds + gp.quicksum(
            self.demand[h] * self.lambda_balance[h] for h in range(H)
        ) - gp.quicksum(
            self.pwind[w, h] * self.lambda_wind[w, h]
            * float(availability[w, self.stage])
            for w in range(W) for h in range(H)
        )
        self.objective_hull = gp.LinExpr()
        if not self.last_day:
            kappa_0, kappa_a = self.kappa_0, self.kappa_a
            assert kappa_0 is not None and kappa_a is not None
            self.objective_hull = kappa_0 + gp.quicksum(
                kappa_a[w, d] * float(availability[w, d])
                for w in range(W) for d in range(T)
            )
        self.model.setObjective(self.objective_operation + self.objective_hull, gp.GRB.MAXIMIZE)

    def solve(self) -> RecourseStageSolution:
        """Devuelve la realización adversa, no un despacho primal del dual."""
        if not self._state_ready:
            raise ValueError("Primero fija el estado con add_states_constraint.")
        if not self.last_day and not self.hull_restrictions and self.initial_upper_bound is None:
            raise ValueError("Faltan puntos de la envolvente superior de la etapa siguiente.")
        announce_solve(self.model.ModelName, int(self.model.Params.OutputFlag), self.solve_tag)
        self.model.update()
        self.model.optimize()
        if self.model.SolCount == 0 or self.model.Status in (
            gp.GRB.INFEASIBLE, gp.GRB.INF_OR_UNBD, gp.GRB.UNBOUNDED,
        ):
            raise RuntimeError(
                f"El oráculo no tiene solución utilizable; status={self.model.Status}. "
                "Revisa la factibilidad del despacho para el PUS y la cobertura de la envolvente."
            )
        return RecourseStageSolution(
            y_r=None, y_nr=None,
            future_cost=None,
            pwind=_values(self.pwind, self.system.wind.n_parks, self.system.hours_per_day),
            demand=np.array([self.demand[h].X for h in range(self.system.hours_per_day)]),
            objective=self.model.ObjVal,
            bound=self.model.ObjBound,
            status=self.model.Status,
        )
