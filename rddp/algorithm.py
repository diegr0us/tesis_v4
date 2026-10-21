from rddp.class_system import Microgrid
from rddp.class_rddp import RDDPConfig
from rddp.class_pus import PUSParameters

import gurobipy as gp
import numpy as np

class RDDP:
    def __init__(
        self,
        system: Microgrid,
        config: RDDPConfig,
        pus: PUSParameters,
    ) -> None:
        self.system = system
        self.config = config
        self.pus = pus
        self.T = system.horizon + 1 # Numero de etapas








class QFuture:
    def __init__(self,
        Q_parameters: QParametersUpper | QParametersLower,
        iteration: int,
        future_cost: gp.Var,
        bound: str, #'lower' o 'upper'
        system: Microgrid,
    ) -> None:
        self.iteration = iteration
        self.T = system.horizon
        self.future_cost = future_cost

        if bound == "lower":
            self.l = Q_parameters.l
            self.ga = Q_parameters.ga
            self.a_down = Q_parameters.a_down
            self.gS = Q_parameters.gS

    def add_to_model(
        self,
        stage: int,
        model: gp.Model,
        a_r: gp.Var | np.ndarray, # En caso de ser primera etapa es variable sino es constante
        Sin: gp.Var,
        bound: str,
    ) -> None:
        if bound == "lower":
            for k in range(self.iteration):
                model.addConstr(
                    self.future_cost >= self.l[k][stage] + gp.quicksum(self.ga[stage][k][j] * (a_r[k][i] - self.a_down) for i in range(self.iteration)) + gp.quicksum(self.gS[k][stage][i] * (Sin - self.Sin) for i in range(self.iteration))
                )
        else:
            self.ga.add_to_model(model, self.future_cost, a_r, Sin)

class QParametersUpper:
    pass

class QParametersLower:
    pass