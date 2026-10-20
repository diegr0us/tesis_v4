"""Box de vida remanente a partir de las CDF en degradation/data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


CDF_SUPPORT_DAYS = 500
N_COMPONENTS = 100
DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_ALPHA = 0.1


class FailureBox:
    """Intervalo central de vida remanente de un componente en un día.

    ``day`` es 1-based: la fila de ``cdf_<señal>_<componente>.xlsx``. El par
    ``(t_dw, t_up)`` son días de vida remanente contados desde ese día.
    """

    def __init__(self, data_dir: Path | None = None, alpha: float = DEFAULT_ALPHA):
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"α tiene que estar en (0, 1); se recibió {alpha}.")
        self.data_dir = DATA_DIR if data_dir is None else Path(data_dir)
        self.alpha = float(alpha)
        self._index: dict[int, Path] | None = None
        self._cdf: dict[int, np.ndarray] = {}

    def box(self, component: int, day: int) -> tuple[int, int]:
        """Vida remanente ``(t_dw, t_up)`` del componente en ese día."""
        cdf = self._cdf_of(component)
        n_days = int(cdf.shape[0])
        row = int(day)
        if not 1 <= row <= n_days:
            raise ValueError(
                f"El componente {int(component)} tiene días 1–{n_days}; se pidió {row}."
            )
        try:
            return rld_box(cdf[row - 1], self.alpha)
        except ValueError as error:
            raise ValueError(f"Componente {int(component)}, día {row}: {error}") from error

    def n_days(self, component: int) -> int:
        """Días de pronóstico de ese componente, las filas de su CDF."""
        return int(self._cdf_of(component).shape[0])

    def _paths(self) -> dict[int, Path]:
        if self._index is None:
            self._index = build_component_index(self.data_dir)
        return self._index

    def _cdf_of(self, component: int) -> np.ndarray:
        component = int(component)
        index = self._paths()
        if component not in index:
            available = sorted(index)
            raise ValueError(
                f"El componente {component} no está en {self.data_dir} "
                f"(hay {available[0]}–{available[-1]})."
            )
        if component not in self._cdf:
            self._cdf[component] = load_cdf(index[component])
        return self._cdf[component]


def build_component_index(data_dir: Path) -> dict[int, Path]:
    """Mapa componente ``j`` → ``cdf_<señal>_<j>.xlsx``. La señal de origen se descarta."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise ValueError(f"No existe el directorio de degradación: {data_dir}")

    index: dict[int, Path] = {}
    for path in sorted(data_dir.glob("cdf_*_*.xlsx")):
        parts = path.stem.split("_")
        if len(parts) != 3:
            raise ValueError(
                f"Nombre inesperado '{path.name}': se espera cdf_<señal>_<componente>.xlsx."
            )
        component = int(parts[2])
        if not 1 <= component <= N_COMPONENTS:
            raise ValueError(
                f"'{path.name}': componente {component} fuera de 1…{N_COMPONENTS}."
            )
        if component in index:
            raise ValueError(
                f"Componente {component} duplicado: '{index[component].name}' y '{path.name}'."
            )
        index[component] = path

    if not index:
        raise ValueError(f"Sin archivos cdf_*_*.xlsx en {data_dir}")
    return index


def load_cdf(path: Path) -> np.ndarray:
    """CDF de un componente, forma ``(n_días, 500)``. Fila = día, columna = vida remanente."""
    cdf = pd.read_excel(path, header=None).to_numpy(dtype=float)
    if cdf.ndim != 2 or cdf.shape[1] != CDF_SUPPORT_DAYS:
        raise ValueError(
            f"'{Path(path).name}': se esperaban {CDF_SUPPORT_DAYS} columnas, "
            f"se leyó forma {cdf.shape}."
        )
    return cdf


def rld_box(cdf_row: np.ndarray, alpha: float) -> tuple[int, int]:
    """Box central de cobertura ``1 - α`` de una fila de la CDF.

    ``t_dw = min{k : F(k) >= α/2}`` y ``t_up = min{k : F(k) >= 1 - α/2}``,
    con ``k`` 1-based.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"α tiene que estar en (0, 1); se recibió {alpha}.")

    row = np.asarray(cdf_row, dtype=float)
    if row.ndim != 1 or row.size == 0:
        raise ValueError(f"Se esperaba una fila 1-D no vacía; se recibió forma {row.shape}.")

    lower_quantile = alpha / 2.0
    upper_quantile = 1.0 - alpha / 2.0
    maximum = float(row[-1])
    if maximum < upper_quantile:
        raise ValueError(
            f"El soporte de {row.size} días no cubre el cuantil 1−α/2 = {upper_quantile:.6f}: "
            f"F({row.size}) = {maximum:.6f}. Usa un α mayor que {2.0 * (1.0 - maximum):.4f}."
        )

    lower = int(np.searchsorted(row, lower_quantile, side="left")) + 1
    upper = int(np.searchsorted(row, upper_quantile, side="left")) + 1
    return lower, upper
