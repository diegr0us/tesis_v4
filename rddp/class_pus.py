"""Parámetros del PUS calibrados en ``pca/pca.py`` y guardados en ``pca/pca.csv``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_COLUMNS = ("grupo", "componente", "c", "a", "s", "r", "phi", "psi")
_DEFAULT_CSV = Path(__file__).resolve().parents[1] / "pca" / "pca.csv"


def _copy_array(value) -> np.ndarray:
    return np.array(value, dtype=float, copy=True)


def _same_int(values: pd.Series, group: str, name: str) -> int:
    numbers = values.to_numpy()
    if numbers.size == 0 or not np.all(numbers == numbers[0]):
        raise ValueError(f"En {group}, {name} tiene que ser el mismo en todos los componentes.")
    number = float(numbers[0])
    if not np.isfinite(number) or number != int(number):
        raise ValueError(f"En {group}, {name} tiene que ser un entero; se recibió {numbers[0]}.")
    return int(number)


def _same_float(values: pd.Series, group: str, name: str) -> float:
    numbers = values.to_numpy(dtype=float)
    if numbers.size == 0 or not np.isfinite(numbers).all() or not np.allclose(numbers, numbers[0]):
        raise ValueError(f"En {group}, {name} tiene que ser el mismo en todos los componentes.")
    return float(numbers[0])


@dataclass(frozen=True)
class PUSGroup:
    """Soporte y presupuestos de un grupo en coordenadas PCA.

    El soporte es ``z = c + a ⊙ θ``, con ``θ ∈ [-1, 1]^r``.
    ``phi`` acota la suma de ``|θ|`` y ``psi`` el par de mayor magnitud
    entre las primeras ``s`` componentes.
    """

    c: np.ndarray
    a: np.ndarray
    s: int
    r: int
    phi: float
    psi: float

    def __post_init__(self) -> None:
        c = _copy_array(self.c).reshape(-1)
        a = _copy_array(self.a).reshape(-1)
        r = int(self.r)
        s = int(self.s)
        phi = float(self.phi)
        psi = float(self.psi)
        if c.shape != a.shape or c.size != r:
            raise ValueError(
                f"c y a tienen que tener r = {r} componentes; se recibió c {c.shape}, a {a.shape}."
            )
        if not np.isfinite(c).all() or not np.isfinite(a).all():
            raise ValueError("c y a tienen que ser finitos.")
        if np.any(a <= 0.0):
            raise ValueError("Hay un componente con ancho nulo.")
        if r < 1:
            raise ValueError(f"r tiene que ser al menos 1; se recibió {r}.")
        if s != 0 and not 2 <= s <= r:
            raise ValueError(f"s tiene que ser 0 o estar entre 2 y r; se recibió s = {s}, r = {r}.")
        if not np.isfinite(phi) or not np.isfinite(psi) or phi < 0.0 or psi < 0.0:
            raise ValueError(f"phi y psi tienen que ser finitos y >= 0; se recibió {phi}, {psi}.")
        object.__setattr__(self, "c", c)
        object.__setattr__(self, "a", a)
        object.__setattr__(self, "r", r)
        object.__setattr__(self, "s", s)
        object.__setattr__(self, "phi", phi)
        object.__setattr__(self, "psi", psi)


def _group(frame: pd.DataFrame, name: str) -> PUSGroup:
    rows = frame.loc[frame["grupo"] == name].sort_values("componente")
    if rows.empty:
        raise ValueError(f"El archivo no tiene el grupo {name}.")
    r = _same_int(rows["r"], name, "r")
    components = rows["componente"].to_numpy()
    if not np.array_equal(components, np.arange(1, r + 1)):
        raise ValueError(f"En {name}, los componentes tienen que ser 1..{r}.")
    return PUSGroup(
        c=rows["c"].to_numpy(dtype=float),
        a=rows["a"].to_numpy(dtype=float),
        s=_same_int(rows["s"], name, "s"),
        r=r,
        phi=_same_float(rows["phi"], name, "phi"),
        psi=_same_float(rows["psi"], name, "psi"),
    )


@dataclass(frozen=True)
class PUSParameters:
    """PUS de viento y de demanda, leídos de ``pca/pca.csv``."""

    wind: PUSGroup
    demand: PUSGroup

    @classmethod
    def from_csv(cls, path: str | Path | None = None) -> PUSParameters:
        """Carga viento y demanda. Sin ruta, usa ``pca/pca.csv`` del proyecto."""
        csv_path = _DEFAULT_CSV if path is None else Path(path)
        frame = pd.read_csv(csv_path)
        missing = [column for column in _COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"{csv_path} no tiene las columnas {missing}.")
        return cls(wind=_group(frame, "viento"), demand=_group(frame, "demanda"))

# Ejemplo de uso
# pus = PUSParameters.from_csv()
#pus.wind.c      # centro, forma (5,)
#pus.wind.a      # semiancho
#pus.wind.s, pus.wind.r, pus.wind.phi, pus.wind.psi
#pus.demand.c    # forma (11,)