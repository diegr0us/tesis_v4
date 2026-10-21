import gurobipy as gp
import numpy as np
from rddp.class_system import Microgrid
from rddp.class_rddp import RDDPConfig
from rddp.class_pus import PUSParameters

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
    ) -> None:
        self.y_r = y_r
        self.y_nr = y_nr
        self.pi_plus = pi_plus
        self.pi_minus = pi_minus
        self.soc = soc
        self.future_cost = future_cost
        self.pwind = pwind
        self.demand = demand


class RecourseStage_Lower:
    """Problema que resuelve usando la aproximacion de costo futuro superior.
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
        self.stage = stage
        self.cuts = []
        self.pus = pus
        
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

        self.future_cost = model.addVar(vtype=gp.GRB.CONTINUOUS, name="future_cost")
        disel_cost = gp.quicksum(
            float(diesel.c_var[g]) * self.y_nr[g, h] for g in range(G_nr) for h in range(H)
        )
        model.setObjective(self.future_cost, gp.GRB.MINIMIZE)

    
    def add_states_constraint(self, soc_in: np.ndarray, availability, pwind: np.ndarray, demand: np.ndarray) -> gp.Constr:
        model = self.model
        battery = self.battery
        wind = self.wind
        H = self.H
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
                self.y_r[w, h] <= pwind[w, h] * availability[w, h]
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
                + self.phi[h]
                >= float(demand[h])
                for h in range(H)
            ),
            name="power_balance_constraint",
        )
    
    def add_cut_lower(self, alpha: float, beta: np.ndarray) -> gp.Constr:
        """Agrega θ >= alpha + beta' x_1 y actualiza el modelo para un corte inferior."""
        slope = np.asarray(beta, dtype=float).reshape(-1)
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
    
    def solve(self) -> RecourseStageSolution:
        """Actualiza el modelo, con los cortes ya agregados, y lo resuelve."""
        self.model.update()
        self.model.optimize()
        return RecourseStageSolution(
            y_r=self.y_r,
            y_nr=self.y_nr,
            pi_plus=self.pi_plus,
            pi_minus=self.pi_minus,
            soc=self.soc,
            future_cost=self.future_cost,
        )



class RecourseStage_Upper:
    """Problema que resuelve usando la aproximacion de costo futuro inferior.
    Se dualiza el problema inner obtenido un problema bilineal.
    En cada iteración se agrega un punto para la convex hull del costo futuro
    """
    def __init__(
        self,
        system: Microgrid,
        config: RDDPConfig,
        pus: PUSParameters,
        stage: int,
    ) -> RecourseStageSolution:
        self.system = system
        self.config = config
        self.model = model = gp.Model() 
        self.stage = stage
        self.pus = pus

        # Restricciones del problema dualizado
        diesel = system.diesel
        fleet = system.wind
        battery = system.battery
        G_nr = diesel.n_units
        W = fleet.n_parks
        B = battery.n_units
        H = self.system.hours_per_day
        penalty = float(system.c_ens)
        
        # Restricciones de la envoltura convexa, depende de la iteración
        self.convex_hull_restrictions = []
        self.convex_hull_variables = []

        lambda_pmax = model.addVars(G_nr, H, lb=0.0, ub=penalty, name="lambda_pnr_max")
        lambda_wind = model.addVars(W, H, lb=0.0, ub=price, name="lambda_pw_max_curve")
        lambda_rated = model.addVars(W, H, lb=0.0, ub=price, name="lambda_pw_max_rated")
        lambda_balance = model.addVars(H, lb=0.0, ub=price, name="lambda_bal")
        lambda_soc = model.addVars(B, H, lb=-gp.GRB.INFINITY, name="lambda_soc")
        lambda_charge = model.addVars(B, H, lb=0.0, name="lambda_battery_ch")
        lambda_discharge = model.addVars(B, H, lb=0.0, name="lambda_battery_dch")
        lambda_soc_max = model.addVars(B, H, lb=0.0, name="lambda_soc_smax")
        lambda_soc_min = model.addVars(B, H, lb=0.0, name="lambda_soc_smin")
        last_day = self.stage == self.system.horizon - 1
        lambda_final = model.addVars(B, lb=0.0, name="lambda_soc_final") if last_day else None

        # Columnas del primal. Las de y_r, y_nr y phi recuperan las del oráculo ARO,
        # sin el mínimo técnico porque el diésel ya no tiene commitment.
        model.addConstrs(
            (
                -lambda_wind[w, h] - lambda_rated[w, h] + lambda_balance[h] <= 0.0
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
        # Restricciones de la envoltura convexa, depende de la iteración
        def add_convex_hull_restrictions(self):
        else:
            # Dual de min sum_j lambda_j u_j + M mu:
            # sum_j lambda_j s_j + z = s_out, sum_j lambda_j + mu = 1,
            # mu lb <= z <= mu ub. Cada punto nuevo añade nu·s_j + omega <= u_j.
            dimension = future.dimension
            nu = model.addVars(dimension, lb=-gp.GRB.INFINITY, name="nu")
            kappa_hi = model.addVars(dimension, lb=0.0, name="kappa_hi")
            kappa_lo = model.addVars(dimension, lb=0.0, name="kappa_lo")
            omega = model.addVar(lb=-gp.GRB.INFINITY, name="omega")
            model.addConstrs(
                (nu[k] - kappa_hi[k] + kappa_lo[k] == 0.0 for k in range(dimension)),
                name="future_residual",
            )
            model.addConstr(
                gp.quicksum(float(future.ub[k]) * kappa_hi[k] - float(future.lb[k]) * kappa_lo[k]
                            for k in range(dimension)) + omega <= future.big_m,
                name="future_box",
            )
            # ν entra con el signo de la igualdad z + Σ λ x = soc: el multiplicador
            # resta en la columna del SOC terminal.
            model.addConstrs(
                (
                    lambda_soc[b, H - 1]
                    + lambda_soc_min[b, H - 1]
                    - lambda_soc_max[b, H - 1]
                    - nu[b]
                    == 0.0
                    for b in range(B)
                ),
                name="soc_dual_future",
            )