from rddp.class_system import Microgrid
from rddp.class_rddp import RDDPConfig

class RDDP:
    def __init__(self, system: Microgrid, config: RDDPConfig, PUSParameters) -> None:
        self.system = system
        self.config = config
        self.PUSParameters = PUSParameters
        self.T = system.horizon + 1 # Numero de etapas
        