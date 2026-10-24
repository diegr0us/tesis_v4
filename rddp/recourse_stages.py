import gurobipy as gp
import numpy as np
from rddp.class_system import Microgrid
from rddp.class_rddp import RDDPConfig
from rddp.class_pus import PUSParameters


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
        y_r: np.ndarray |None,
        y_nr: np.ndarray |None,
        pi_plus: np.ndarray |None,
        pi_minus: np.ndarray |None,
        soc: np.ndarray |None,
        future_cost: float |None,
        pwind: np.ndarray |None,
        demand: np.ndarray |None,
        objective: float | None = None,
        bound: float | None = None,
        status: int | None = None,
    ) -> None:
        self.y_r = y_r
        self.y_nr = y_nr
        self.pi_plus = pi_plus
        self.pi_minus = pi_minus
        self.soc = soc
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
        self.model = model = gp.Model()
        _configure(model, config, stage, system)
        model.Params.Method = config.lp_method
        self.stage = stage
        self.cuts = []
        self.pus = pus
        self.cut_data = []
        self.state = None

        # Restricciones que dependen del estado y cambian en cada iteración
        self.wind_limits = None # depende de la incertidumbre y del estado
        self.balance = None # depende de la incertidumbre
        self.soc_in = None # depende del estado

        # Restricciones que no cambian en cada iteración
        diesel = system.diesel
        self.wind = wind = system.wind
        self.battery = battery = system.battery
        G_nr = diesel.n_units
        W = wind.n_parks
        B = battery.n_units
        self.H = H = system.hours_per_day

        self.y_r = model.addVars(W, H, lb=0.0, name="y_r")
        self.y_nr = model.addVars(G_nr, H, lb=0.0, name="y_nr")
        self.pi_plus = model.addVars(B, H, lb=0.0, name="pi_plus")
        self.pi_minus = model.addVars(B, H, lb=0.0, name="pi_minus")
        self.soc = model.addVars(B, H, lb=-gp.GRB.INFINITY, name="soc")

        # Limite generador convencional
        model.addConstrs(
            (
                self.y_nr[g, h] <= float(diesel.pmax[g])
                for g in range(G_nr)
                for h in range(H)
            ),
            name="conventional_generator_output_constraint",
        )

        last_day = self.stage == system.horizon - 1
        model.addConstrs(
            (
                self.soc[b, h]
                == self.soc[b, h - 1]
                + float(battery.eta[b]) * self.pi_plus[b, h]
                - self.pi_minus[b, h] / float(battery.eta[b])
                for b in range(B)
                for h in range(1, H)
            ),
            name="soc_intra_day",
        )
        if last_day:
            model.addConstrs(
                (self.soc[b, H - 1] >= float(battery.soc_final[b]) for b in range(B)),
                name="soc_final",
            )
        model.addConstrs(
            (self.soc[b, h] >= float(battery.soc_min[b]) for b in range(B) for h in range(H)),
            name="soc_min",
        )
        model.addConstrs(
            (self.soc[b, h] <= float(battery.soc_max[b]) for b in range(B) for h in range(H)),
            name="soc_max",
        )
        model.addConstrs(
            (self.pi_plus[b, h] <= float(battery.pch[b]) for b in range(B) for h in range(H)),
            name="battery_charge_limit",
        )
        model.addConstrs(
            (self.pi_minus[b, h] <= float(battery.pdch[b]) for b in range(B) for h in range(H)),
            name="battery_discharge_limit",
        )

        self.future_cost = model.addVar(ub=0.0 if last_day else gp.GRB.INFINITY, name="future_cost")
        self.operation_cost = gp.quicksum(
            float(diesel.c_var[g]) * self.y_nr[g, h] for g in range(G_nr) for h in range(H)
        )
        model.setObjective(self.operation_cost + self.future_cost, gp.GRB.MINIMIZE)


    def add_states_constraint(self, soc_in: np.ndarray, availability, pwind: np.ndarray, demand: np.ndarray) -> None:
        """Fija el estado entrante y la realización; pwind es potencia total del parque."""
        model = self.model
        battery = self.battery
        wind = self.wind
        H = self.H
        G_nr = self.system.diesel.n_units
        W = wind.n_parks
        B = battery.n_units
        soc_in = _array(soc_in, (B,), "soc_in")
        availability = _availability(self.system, availability)
        self.pwind = pwind = _array(pwind, (W, H), "pwind")
        self.demand = demand = _array(demand, (H,), "demand")
        self.incoming_soc = soc_in.copy()
        self.availability = availability.copy()
        self.state = [self.soc[b, H - 1] for b in range(B)]
        self.state += [float(availability[w, d]) for d in range(self.system.horizon) for w in range(W)]
        # Restriccion de inicio de dia en bateria
        if self.soc_in is not None:
            model.remove(self.soc_in)
        self.soc_in = model.addConstrs(
            (
                self.soc[b, 0]
                == soc_in[b]
                + float(battery.eta[b]) * self.pi_plus[b, 0]
                - self.pi_minus[b, 0] / float(battery.eta[b])
                for b in range(battery.n_units)
            ),
            name="soc_day_start",
        )
        # Restriccion de disponibilidad de turbinas eolicas dependiente de la incertidumbre

        if self.wind_limits is not None:
            model.remove(self.wind_limits)
        self.wind_limits = model.addConstrs(
            (
                self.y_r[w, h] <= pwind[w, h] * availability[w, self.stage] / wind.G_r[w]
                for w in range(wind.n_parks)
                    for h in range(H)
            ),
            name="wind_limits",
        )
        # Restriccion de balance de potencia
        if self.balance is not None:
            model.remove(self.balance)
        self.balance = model.addConstrs(
            (
                gp.quicksum(self.y_r[w, h] for w in range(W))
                + gp.quicksum(self.y_nr[g, h] for g in range(G_nr))
                + gp.quicksum(-self.pi_plus[b, h] + self.pi_minus[b, h] for b in range(B))
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
        B = self.battery.n_units
        W, T = self.wind.n_parks, self.system.horizon
        beta = np.zeros(B + W * T)
        for b in range(B):
            beta[b] = self.soc_in[b].Pi
        for w in range(W):
            beta[B + self.stage * W + w] = sum(
                self.wind_limits[w, h].Pi * self.pwind[w, h] / self.wind.G_r[w]
                for h in range(self.H)
            )
        for cut, (_, slope) in zip(self.cuts, self.cut_data):
            beta[B:] += cut.Pi * slope[B:]
        state = np.concatenate((self.incoming_soc, self.availability.T.reshape(-1)))
        alpha = float(self.model.ObjVal - beta @ state)
        return alpha, beta

    def solve(self) -> RecourseStageSolution:
        """Actualiza el modelo, con los cortes ya agregados, y lo resuelve."""
        if self.state is None:
            raise ValueError("Primero fija el estado y la realización.")
        self.model.update()
        self.model.optimize()
        if self.model.Status != gp.GRB.OPTIMAL:
            raise RuntimeError(f"El LP no alcanzó un óptimo; status={self.model.Status}.")
        return RecourseStageSolution(
            y_r=_values(self.y_r, self.wind.n_parks, self.H),
            y_nr=_values(self.y_nr, self.system.diesel.n_units, self.H),
            pi_plus=_values(self.pi_plus, self.battery.n_units, self.H),
            pi_minus=_values(self.pi_minus, self.battery.n_units, self.H),
            soc=_values(self.soc, self.battery.n_units, self.H),
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
        self.model = model = gp.Model()
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
        self.battery = battery = system.battery
        G_nr = diesel.n_units
        W = fleet.n_parks
        B = battery.n_units
        H = self.system.hours_per_day
        T = system.horizon
        self.last_day = last_day = stage == T - 1
        self.availability = None
        self.incoming_soc = None

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
        self.kappa_Sin = model.addVars(B, lb=-gp.GRB.INFINITY, name="kappa_Sin") if not last_day else None
        self.hull_restrictions = []
        self.initial_upper_bound = None

        lambda_pmax = model.addVars(G_nr, H, lb=0.0, name="lambda_pnr_max")
        self.lambda_wind = lambda_wind = model.addVars(W, H, lb=0.0, name="lambda_pw_max_curve")
        self.lambda_balance = lambda_balance = model.addVars(H, lb=0.0, name="lambda_bal")
        self.lambda_soc = lambda_soc = model.addVars(B, H, lb=-gp.GRB.INFINITY, name="lambda_soc")
        lambda_charge = model.addVars(B, H, lb=0.0, name="lambda_battery_ch")
        lambda_discharge = model.addVars(B, H, lb=0.0, name="lambda_battery_dch")
        lambda_soc_max = model.addVars(B, H, lb=0.0, name="lambda_soc_smax")
        lambda_soc_min = model.addVars(B, H, lb=0.0, name="lambda_soc_smin")
        lambda_final = model.addVars(B, lb=0.0, name="lambda_soc_final") if last_day else None
        kappa_Sin = self.kappa_Sin

        # Columnas del primal: sin ENS ni cotas artificiales de precio.
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

        model.addConstrs(
            (
                -lambda_balance[h]
                - float(self.battery.eta[b]) * lambda_soc[b, h]
                - lambda_charge[b, h]
                <= 0.0
                for b in range(B)
                for h in range(H)
            ),
            name="battery_charge_constraint",
        )
        model.addConstrs(
            (
                lambda_balance[h]
                + lambda_soc[b, h] / float(battery.eta[b])
                - lambda_discharge[b, h]
                <= 0.0
                for b in range(B)
                for h in range(H)
            ),
            name="battery_discharge_constraint",
        )
        model.addConstrs(
            (
                lambda_soc[b, h]
                - lambda_soc[b, h + 1]
                + lambda_soc_min[b, h]
                - lambda_soc_max[b, h]
                == 0.0
                for b in range(B)
                for h in range(H - 1)
            ),
            name="soc_dual_intra_day",
        )

        if last_day:
            assert lambda_final is not None
            model.addConstrs(
                (
                    lambda_soc[b, H - 1]
                    + lambda_soc_min[b, H - 1]
                    - lambda_soc_max[b, H - 1]
                    + lambda_final[b]
                    == 0.0
                    for b in range(B)
                ),
                name="soc_dual_final",
            )

        else:
            assert kappa_Sin is not None
            model.addConstrs(
                (lambda_soc[b, H - 1] + lambda_soc_min[b, H - 1]
                 - lambda_soc_max[b, H - 1] - kappa_Sin[b] == 0.0
                 for b in range(B)),
                name="soc_dual_continuation",
            )

        self.objective_bounds = -gp.quicksum(
            float(diesel.pmax[g]) * lambda_pmax[g, h]
            for g in range(G_nr) for h in range(H)
        ) + gp.quicksum(
            float(battery.soc_min[b]) * lambda_soc_min[b, h]
            - float(battery.soc_max[b]) * lambda_soc_max[b, h]
            - float(battery.pch[b]) * lambda_charge[b, h]
            - float(battery.pdch[b]) * lambda_discharge[b, h]
            for b in range(B) for h in range(H)
        )
        if last_day:
            assert lambda_final is not None
            self.objective_bounds += gp.quicksum(
                float(battery.soc_final[b]) * lambda_final[b] for b in range(B)
            )
        model.ModelSense = gp.GRB.MAXIMIZE

    def initialize_upper_bound(self, bound: float) -> None:
        """Envolvente de puntos y respaldo constante en la caja (A,SOC).

        Impone kappa_0 + max_{s en caja} kappa's <= bound mediante
        auxiliares positivos. Equivale a incluir todos los vértices de la
        caja a altura bound, sin enumerarlos. El llamador justifica bound.
        """
        if self.last_day or self.initial_upper_bound is not None:
            raise ValueError("El respaldo se inicializa una vez en etapas no terminales.")
        if not np.isfinite(bound) or bound < 0:
            raise ValueError("El respaldo debe ser finito y no negativo.")
        k0, ka, ks = self.kappa_0, self.kappa_a, self.kappa_Sin
        assert k0 is not None and ka is not None and ks is not None
        expression = gp.LinExpr(k0)
        for w in range(self.system.wind.n_parks):
            for d in range(self.system.horizon):
                positive = self.model.addVar(lb=0.0, name=f"backup_A_positive[{w},{d}]")
                self.model.addConstr(positive >= ka[w, d])
                expression += float(self.system.wind.G_r[w]) * positive
        for b in range(self.battery.n_units):
            positive = self.model.addVar(lb=0.0, name=f"backup_SOC_positive[{b}]")
            self.model.addConstr(positive >= ks[b])
            expression += float(self.battery.soc_min[b]) * ks[b]
            expression += float(self.battery.soc_max[b] - self.battery.soc_min[b]) * positive
        self.model.addConstr(expression <= bound, name="initial_upper_envelope")
        self.initial_upper_bound = float(bound)

    # Restricciones de la envoltura convexa, depende de la iteración
    def add_convex_hull_restrictions(self, points: list[tuple[np.ndarray, np.ndarray, float]], availability: np.ndarray) -> None:
        """Reemplaza puntos (A_r[W,T], SOC_entrante[B], valor) de la etapa siguiente."""
        if self.last_day:
            raise ValueError("La etapa terminal no tiene envolvente de continuación.")
        kappa_0, kappa_a, kappa_Sin = self.kappa_0, self.kappa_a, self.kappa_Sin
        assert kappa_0 is not None and kappa_a is not None and kappa_Sin is not None
        availability = _availability(self.system, availability)
        validated = []
        for a, soc, value in points:
            a = _availability(self.system, a)
            soc = _array(soc, (self.battery.n_units,), "SOC del punto")
            if not np.isfinite(value):
                raise ValueError("El valor del punto debe ser finito.")
            validated.append((a, soc, float(value)))
        self.model.remove(self.hull_restrictions)
        self.hull_restrictions = []
        W = self.system.wind.n_parks
        T = self.system.horizon
        B = self.system.battery.n_units
        for p, (a, soc, value) in enumerate(validated):
            self.hull_restrictions.append(self.model.addConstr(
                kappa_0
                + gp.quicksum(kappa_a[w, d] * a[w, d] for w in range(W) for d in range(T))
                + gp.quicksum(kappa_Sin[b] * soc[b] for b in range(B)) <= value,
                name=f"hull_restriction_{p}",
            ))
        self.availability = availability
        if self.incoming_soc is not None:
            self._set_objective()

    def add_states_constraint(self, soc_in: np.ndarray, availability: np.ndarray) -> None:
        """Fija el estado; la incertidumbre sigue siendo variable en el objetivo."""
        soc_in = _array(soc_in, (self.battery.n_units,), "soc_in")
        availability = _availability(self.system, availability)
        self.incoming_soc = soc_in
        self.availability = availability
        self._set_objective()

    def _set_objective(self) -> None:
        availability, incoming_soc = self.availability, self.incoming_soc
        if availability is None or incoming_soc is None:
            raise ValueError("Primero fija la disponibilidad y el SOC entrante.")
        W = self.system.wind.n_parks
        B = self.battery.n_units
        H = self.system.hours_per_day
        T = self.system.horizon
        self.objective_operation = self.objective_bounds + gp.quicksum(
            self.demand[h] * self.lambda_balance[h] for h in range(H)
        ) - gp.quicksum(
            self.pwind[w, h] * self.lambda_wind[w, h]
            * float(availability[w, self.stage] / self.system.wind.G_r[w])
            for w in range(W) for h in range(H)
        ) + gp.quicksum(
            float(incoming_soc[b]) * self.lambda_soc[b, 0] for b in range(B)
        )
        # kappa_S entra en la ecuación dual del SOC saliente, no como costo del SOC entrante.
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
        if self.incoming_soc is None:
            raise ValueError("Primero fija el estado con add_states_constraint.")
        if not self.last_day and not self.hull_restrictions and self.initial_upper_bound is None:
            raise ValueError("Faltan puntos de la envolvente superior de la etapa siguiente.")
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
            y_r=None, y_nr=None, pi_plus=None, pi_minus=None, soc=None,
            future_cost=None,
            pwind=_values(self.pwind, self.system.wind.n_parks, self.system.hours_per_day),
            demand=np.array([self.demand[h].X for h in range(self.system.hours_per_day)]),
            objective=self.model.ObjVal,
            bound=self.model.ObjBound,
            status=self.model.Status,
        )
