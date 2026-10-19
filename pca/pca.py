from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HOURS_PER_DAY = 24
HISTORICAL_YEARS = (2023, 2024)
DEFAULT_VARIANCE_THRESHOLD = 0.95

# El pronóstico empieza el lunes 6 de enero de 2025.
# Cada hora se compara con el mismo día de la semana:
#   2023, misma semana: lunes 6 ene 2025 <-> lunes 2 ene 2023
#   2024, semana + 1:   lunes 6 ene 2025 <-> lunes 8 ene 2024
# 2024 no trae el 29 de febrero. Ese jueves se omite solo en el bloque de 2024.
ORIGIN_FORECAST = pd.Timestamp("2025-01-06")
ORIGIN_HISTORICAL = {
    2023: pd.Timestamp("2023-01-02"),
    2024: pd.Timestamp("2024-01-08"),
}

forecast = pd.read_csv(
    ROOT / "forecast" / "wind_power_forecast_2025.csv",
    parse_dates=["source_timestamp"],
)
demand_forecast = pd.read_csv(
    ROOT / "forecast" / "demand_forecast_2025.csv",
    parse_dates=["source_timestamp"],
)
if not forecast["source_timestamp"].equals(demand_forecast["source_timestamp"]):
    raise ValueError("Viento y demanda pronosticados no comparten las mismas horas")

forecast_time = pd.DatetimeIndex(forecast["source_timestamp"])
hat_p_AB = forecast["wind_ab_median_MW"].to_numpy(dtype=float)
hat_p_KA = forecast["wind_ka_median_MW"].to_numpy(dtype=float)
hat_d = demand_forecast["demand_median_MW"].to_numpy(dtype=float)


def _historical_index(origin):
    day_offset = forecast_time.normalize() - ORIGIN_FORECAST
    return pd.DatetimeIndex(origin + day_offset + pd.to_timedelta(forecast_time.hour, unit="h"))


def _aligned_historical(relative_path, column, origin):
    frame = pd.read_csv(ROOT / relative_path, parse_dates=["source_timestamp"])
    series = frame.set_index("source_timestamp").sort_index()[column]
    return series.reindex(_historical_index(origin)).to_numpy(dtype=float)


p_historical_AB = {
    year: _aligned_historical(
        f"historical_data/wind_power_{year}.csv", "wind_ab_MW", ORIGIN_HISTORICAL[year]
    )
    for year in HISTORICAL_YEARS
}
p_historical_KA = {
    year: _aligned_historical(
        f"historical_data/wind_power_{year}.csv", "wind_ka_MW", ORIGIN_HISTORICAL[year]
    )
    for year in HISTORICAL_YEARS
}
d_historical = {
    year: _aligned_historical(
        f"historical_data/demand_{year}.csv", "demand", ORIGIN_HISTORICAL[year]
    )
    for year in HISTORICAL_YEARS
}

if not np.array_equal(_historical_index(ORIGIN_HISTORICAL[2023]).dayofweek, forecast_time.dayofweek):
    raise ValueError("El histórico no cae en el mismo día de la semana que el pronóstico")

# Cada año conserva los días completos que sí están en su archivo.
day_index = np.arange(len(forecast_time)) // HOURS_PER_DAY
keep = {}
dias_sin_par = {}
for year in HISTORICAL_YEARS:
    missing_hour = (
        np.isnan(p_historical_AB[year])
        | np.isnan(p_historical_KA[year])
        | np.isnan(d_historical[year])
    )
    incomplete_days = np.unique(day_index[missing_hour])
    keep[year] = ~np.isin(day_index, incomplete_days)
    dias_sin_par[year] = pd.DatetimeIndex(
        forecast_time.normalize()[np.isin(day_index, incomplete_days)]
    ).unique()

horizonte = {year: int(keep[year].sum() // HOURS_PER_DAY) for year in HISTORICAL_YEARS}
n_columnas = sum(horizonte.values())


def _daily_matrix(values, mask):
    """Pasa las horas conservadas a una matriz (24, días)."""
    n_days = int(mask.sum() // HOURS_PER_DAY)
    return values[mask].reshape(n_days, HOURS_PER_DAY).T


hat_p_blocks = []
p_historical_blocks = []
hat_d_blocks = []
d_historical_blocks = []
for year in HISTORICAL_YEARS:
    mask = keep[year]
    hat_p_blocks.append(np.vstack([_daily_matrix(hat_p_AB, mask), _daily_matrix(hat_p_KA, mask)]))
    p_historical_blocks.append(
        np.vstack([_daily_matrix(p_historical_AB[year], mask), _daily_matrix(p_historical_KA[year], mask)])
    )
    hat_d_blocks.append(_daily_matrix(hat_d, mask))
    d_historical_blocks.append(_daily_matrix(d_historical[year], mask))

hat_p = np.hstack(hat_p_blocks)
p_historical = np.hstack(p_historical_blocks)
hat_d_days = np.hstack(hat_d_blocks)
d_historical_days = np.hstack(d_historical_blocks)

# e^{\tilde P}_k en R^{48}: horas 1..24 de AB y después horas 1..24 de KA.
# e^{\tilde D}_k en R^{24}. Columnas: días de 2023 y después los de 2024.
e_p = p_historical - hat_p
e_d = d_historical_days - hat_d_days

if e_p.shape != (HOURS_PER_DAY * 2, n_columnas):
    raise ValueError(f"e_p tiene forma {e_p.shape}")
if e_d.shape != (HOURS_PER_DAY, n_columnas):
    raise ValueError(f"e_d tiene forma {e_d.shape}")

# T_q son las columnas de e_q y N_q^train = |T_q|.
# b^q = (1 / N_q^train) * suma_k e^q_k
# x^q_k = e^q_k - b^q
n_train_p = e_p.shape[1]
n_train_d = e_d.shape[1]
b_p = e_p.mean(axis=1)
b_d = e_d.mean(axis=1)
x_p = e_p - b_p[:, None]
x_d = e_d - b_d[:, None]

if b_p.shape != (e_p.shape[0],) or x_p.shape != e_p.shape:
    raise ValueError(f"Sesgo eólico: b_p {b_p.shape}, x_p {x_p.shape}")
if b_d.shape != (e_d.shape[0],) or x_d.shape != e_d.shape:
    raise ValueError(f"Sesgo de demanda: b_d {b_d.shape}, x_d {x_d.shape}")

# X^q en R^{N_train x n_q}, con filas (x^q_k)^T.
# X^q = U^q Σ^q (V^q)^T. sigma_q es la diagonal de Σ^q.
# L^q = V^q[:, 1:r_q] y los puntajes de entrenamiento son X^q L^q,
# cuya fila k es (L^q)^T x^q_k.
X_p = x_p.T
X_d = x_d.T
U_p, sigma_p, Vt_p = np.linalg.svd(X_p, full_matrices=False)
U_d, sigma_d, Vt_d = np.linalg.svd(X_d, full_matrices=False)
V_p = Vt_p.T
V_d = Vt_d.T


def _components_for_variance(sigma, threshold=DEFAULT_VARIANCE_THRESHOLD):
    """Menor r cuya varianza acumulada alcanza el umbral."""
    explained = np.cumsum(sigma**2)
    explained /= explained[-1]
    return int(np.searchsorted(explained, threshold, side="left") + 1)


r_p = _components_for_variance(sigma_p)
r_d = _components_for_variance(sigma_d)
L_p = V_p[:, :r_p]
L_d = V_d[:, :r_d]
scores_p = X_p @ L_p
scores_d = X_d @ L_d

if L_p.shape != (X_p.shape[1], r_p) or not np.allclose(L_p.T @ L_p, np.eye(r_p)):
    raise ValueError("L_p no es una base ortonormal")
if L_d.shape != (X_d.shape[1], r_d) or not np.allclose(L_d.T @ L_d, np.eye(r_d)):
    raise ValueError("L_d no es una base ortonormal")
if scores_p.shape != (n_train_p, r_p) or scores_d.shape != (n_train_d, r_d):
    raise ValueError(f"Puntajes: scores_p {scores_p.shape}, scores_d {scores_d.shape}")
explained_p = float(np.sum(sigma_p[:r_p] ** 2) / np.sum(sigma_p**2))
explained_d = float(np.sum(sigma_d[:r_d] ** 2) / np.sum(sigma_d**2))
if explained_p < DEFAULT_VARIANCE_THRESHOLD or explained_d < DEFAULT_VARIANCE_THRESHOLD:
    raise ValueError(f"Varianza retenida: viento {explained_p}, demanda {explained_d}")
