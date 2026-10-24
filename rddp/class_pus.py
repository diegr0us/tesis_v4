"""Parámetros del PUS calibrados en ``pca/pca.py`` y guardados en ``pca/pca.csv``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_COLUMNS = ("grupo", "componente", "c", "a", "s", "r", "phi", "psi")
_DEFAULT_CSV = Path(__file__).resolve().parents[1] / "pca" / "pca.csv"
_DEFAULT_NPZ = Path(__file__).resolve().parents[1] / "pca" / "reconstruction.npz"


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
class PCAReconstruction:
    """Base y sesgo fijos; pron?sticos diarios en orden parque-hora."""

    L: np.ndarray
    b: np.ndarray
    forecast: np.ndarray

    def __post_init__(self) -> None:
        for name in ("L", "b", "forecast"):
            value = _copy_array(getattr(self, name))
            if not np.isfinite(value).all():
                raise ValueError(f"{name} debe contener valores finitos.")
            object.__setattr__(self, name, value)
        if self.L.ndim != 2 or self.forecast.ndim != 2:
            raise ValueError("L y forecast deben ser matrices.")
        n, r = self.L.shape
        if min(n, r, self.forecast.shape[0]) < 1 or self.b.shape != (n,):
            raise ValueError("Dimensiones inv?lidas de la reconstrucci?n PCA.")
        if self.forecast.shape[1] != n:
            raise ValueError("El pron?stico debe tener las mismas coordenadas f?sicas que L.")
        if not np.allclose(self.L.T @ self.L, np.eye(r), atol=1e-6):
            raise ValueError("L debe ser una base ortonormal.")


@dataclass(frozen=True)
class PUSParameters:
    """Soporte hist?rico del CSV y reconstrucci?n opcional exportada por PCA."""

    wind: PUSGroup
    demand: PUSGroup
    wind_reconstruction: PCAReconstruction | None = None
    demand_reconstruction: PCAReconstruction | None = None
    dates: np.ndarray | None = None
    hours_per_day: int = 24
    wind_parks: tuple[str, ...] = ()

    def validate_reconstruction(self, n_parks: int, hours: int, horizon: int) -> None:
        wind, demand = self.wind_reconstruction, self.demand_reconstruction
        if wind is None or demand is None or self.dates is None:
            raise ValueError("Falta la reconstrucci?n PCA. Usa PUSParameters.from_files().")
        if self.hours_per_day != hours or len(self.wind_parks) != n_parks:
            raise ValueError("Los parques/horas del PUS no coinciden con el sistema.")
        if wind.L.shape != (n_parks * hours, self.wind.r) or demand.L.shape != (hours, self.demand.r):
            raise ValueError("Dimensiones de las bases incompatibles con el sistema/PUS.")
        dates = np.asarray(self.dates, dtype="datetime64[D]")
        if dates.ndim != 1 or len(dates) < horizon or np.isnat(dates).any():
            raise ValueError("No hay fechas v?lidas suficientes para el horizonte.")
        if np.any(np.diff(dates) != np.timedelta64(1, "D")):
            raise ValueError("Las fechas del PUS deben ser d?as consecutivos.")
        if wind.forecast.shape[0] != len(dates) or demand.forecast.shape[0] != len(dates):
            raise ValueError("Los grupos deben compartir las fechas del PUS.")

    @classmethod
    def from_files(cls, csv_path: str | Path | None = None,
                   reconstruction_path: str | Path = _DEFAULT_NPZ) -> PUSParameters:
        parameters = cls.from_csv(csv_path)
        path = Path(reconstruction_path)
        if not path.is_file():
            raise FileNotFoundError(f"Falta {path}. Ejecuta pca/pca.py para exportar la reconstrucci?n.")
        with np.load(path, allow_pickle=False) as data:
            if int(data["version"]) != 1:
                raise ValueError("Versi?n de reconstrucci?n no compatible.")
            reconstructions = {}
            for name, group in (("wind", parameters.wind), ("demand", parameters.demand)):
                # Evita mezclar la base de una corrida con el soporte de otra.
                for field in ("c", "a", "s", "r", "phi", "psi"):
                    saved = data[f"{name}_{field}"]
                    current = np.asarray(getattr(group, field))
                    if saved.shape != current.shape or not np.allclose(saved, current):
                        raise ValueError("CSV y reconstrucci?n PCA no corresponden a la misma calibraci?n.")
                reconstructions[f"{name}_reconstruction"] = PCAReconstruction(
                    L=data[f"{name}_L"], b=data[f"{name}_b"], forecast=data[f"{name}_forecast"])
            result = cls(wind=parameters.wind, demand=parameters.demand, **reconstructions,
                         dates=data["dates"].copy(), hours_per_day=int(data["hours_per_day"]),
                         wind_parks=tuple(data["wind_parks"].tolist()))
        result.validate_reconstruction(len(result.wind_parks), result.hours_per_day, 1)
        return result

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