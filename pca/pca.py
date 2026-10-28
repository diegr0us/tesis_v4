from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HOURS_PER_DAY = 24
HISTORICAL_YEARS = (2023, 2024)
DEFAULT_VARIANCE_THRESHOLD = 0.95
# Fracción de la varianza retenida que entra al presupuesto de a pares.
PAIRWISE_VARIANCE_THRESHOLD = 0.90

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
    ROOT / "forecast" / "wind_forecast_2025.csv",
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

########################################################
# Calculo del soporte de PUS en coordenadas PCA usando quantiles hisotoricos
########################################################

z_dw_p = np.quantile(scores_p, 0.10, axis=0)  # (5,)
z_up_p = np.quantile(scores_p, 0.90, axis=0)  # (5,)
z_dw_d = np.quantile(scores_d, 0.10, axis=0)  # (11,)
z_up_d = np.quantile(scores_d, 0.90, axis=0)  # (11,)

# centros del uncertainty set
c_p = (z_up_p + z_dw_p) / 2  # (5,)
c_d = (z_up_d + z_dw_d) / 2  # (11,)

# radios del uncertainty set
a_p = (z_up_p - z_dw_p) / 2  # (5,)
a_d = (z_up_d - z_dw_d) / 2  # (11,)

#finalmente el support set es:
# z = c + a * theta

########################################################
# Calibración de los budgets
########################################################

def _componentes_pares(sigma, r, threshold=PAIRWISE_VARIANCE_THRESHOLD):
    """Menor s, con 2 ≤ s ≤ r, que junta el umbral de la varianza retenida."""
    if r < 2:
        return 0
    retenida = np.cumsum(sigma[:r] ** 2)
    retenida /= retenida[-1]
    s = int(np.searchsorted(retenida, threshold, side="left") + 1)
    return min(max(s, 2), r)


def _presupuestos(scores, c, a, s,integer = False):
    """θ = (z - c) / a, sin recortar. B suma todas; C el par mayor entre las primeras s."""
    if np.any(a <= 0):
        raise ValueError("Hay un componente con ancho nulo")
    theta = (scores - c) / a
    magnitud = np.abs(theta)
    B = magnitud.sum(axis=1)
    if s < 2:
        C = np.zeros(magnitud.shape[0])
    else:
        dos_mayores = np.partition(magnitud[:, :s], -2, axis=1)[:, -2:]
        C = dos_mayores.sum(axis=1)
    if integer:
        Phi = float(np.ceil(np.quantile(B, 0.90)))
        Psi = float(np.ceil(np.quantile(C, 0.90)))
    else:
        Phi = float(np.quantile(B, 0.90))
        Psi = float(np.quantile(C, 0.90))
    return theta, B, C, Phi, Psi


s_p = _componentes_pares(sigma_p, r_p)
s_d = _componentes_pares(sigma_d, r_d)
theta_p, B_p, C_p, Phi_p, Psi_p = _presupuestos(scores_p, c_p, a_p, s_p, integer=True)
theta_d, B_d, C_d, Phi_d, Psi_d = _presupuestos(scores_d, c_d, a_d, s_d, integer=True)

Phi_p = r_p - 1
Psi_p = 1.5
Phi_d = r_d - 1
Psi_d = 1.8

########################################################
# Graficos de los support sets
########################################################

import matplotlib.pyplot as plt

def _soporte_mw(L, c, a, b, hat):
    """Imagen de la caja z = c + a⊙θ, θ∈[-1, 1]^r, en MW: hat + b + L z.

    El ancho de la hora i es sum_j |L_ij| a_j.
    """
    centro = hat + b + L @ c
    radio = np.abs(L) @ a
    return centro - radio, centro, centro + radio


# El soporte del error no depende del día. Se ancla al pronóstico medio
# para ver el conjunto como potencia y demanda, en MW.
hat_p_medio = hat_p.mean(axis=1)
hat_d_medio = hat_d_days.mean(axis=1)
lo_p, centro_p, hi_p = _soporte_mw(L_p, c_p, a_p, b_p, hat_p_medio)
lo_d, centro_d, hi_d = _soporte_mw(L_d, c_d, a_d, b_d, hat_d_medio)

horas = np.arange(1, HOURS_PER_DAY + 1)
fig, axes = plt.subplots(3, 1, figsize=(8, 9), sharex=True)
paneles = (
    (
        axes[0],
        "Viento AB",
        lo_p[:HOURS_PER_DAY],
        centro_p[:HOURS_PER_DAY],
        hi_p[:HOURS_PER_DAY],
        hat_p_medio[:HOURS_PER_DAY],
    ),
    (
        axes[1],
        "Viento KA",
        lo_p[HOURS_PER_DAY:],
        centro_p[HOURS_PER_DAY:],
        hi_p[HOURS_PER_DAY:],
        hat_p_medio[HOURS_PER_DAY:],
    ),
    (axes[2], "Demanda", lo_d, centro_d, hi_d, hat_d_medio),
)
for ax, titulo, lo, centro, hi, pronostico in paneles:
    ax.fill_between(horas, lo, hi, alpha=0.3, label="soporte")
    ax.plot(horas, centro, label="centro")
    ax.plot(horas, pronostico, linestyle="--", label="pronóstico medio")
    ax.set_ylabel("MW")
    ax.set_title(titulo)
    ax.legend()
axes[-1].set_xlabel("Hora")
fig.tight_layout()

filas = []
for grupo, c, a, s, r, phi, psi in (
    ("viento", c_p, a_p, s_p, r_p, Phi_p, Psi_p),
    ("demanda", c_d, a_d, s_d, r_d, Phi_d, Psi_d),
):
    for componente, (centro, radio) in enumerate(zip(c, a, strict=True), start=1):
        filas.append(
            {
                "grupo": grupo,
                "componente": componente,
                "c": centro,
                "a": radio,
                "s": s,
                "r": r,
                "phi": phi,
                "psi": psi,
            }
        )
pd.DataFrame(filas).to_csv(Path(__file__).resolve().parent / "pca.csv", index=False)

# Exportar la reconstrucción sin modificar soporte, PCA ni calibración histórica.
# Una fila por día; viento apilado por parque y luego por hora (AB, KA).
reconstruction = {
    "version": np.array(1),
    "hours_per_day": np.array(HOURS_PER_DAY),
    "dates": forecast_time[::HOURS_PER_DAY].to_numpy(dtype="datetime64[D]"),
    "wind_parks": np.array(["AB", "KA"]),
    "wind_L": L_p, "wind_b": b_p,
    "demand_L": L_d, "demand_b": b_d,
    "wind_forecast": np.hstack([
        hat_p_AB.reshape(-1, HOURS_PER_DAY), hat_p_KA.reshape(-1, HOURS_PER_DAY),
    ]),
    "demand_forecast": hat_d.reshape(-1, HOURS_PER_DAY),
}
for name, c, a, s, r, phi, psi in (
    ("wind", c_p, a_p, s_p, r_p, Phi_p, Psi_p),
    ("demand", c_d, a_d, s_d, r_d, Phi_d, Psi_d),
):
    for field, value in (("c", c), ("a", a), ("s", s), ("r", r), ("phi", phi), ("psi", psi)):
        reconstruction[f"{name}_{field}"] = np.asarray(value)
np.savez_compressed(Path(__file__).resolve().parent / "reconstruction.npz", **reconstruction)

# Leer los datos
#parametros = pd.read_csv("pca/pca.csv")
#viento = parametros[parametros["grupo"] == "viento"]
#demanda = parametros[parametros["grupo"] == "demanda"]

#c_p = viento["c"].to_numpy()
#a_p = viento["a"].to_numpy()
#s_p = int(viento["s"].iloc[0])
#r_p = int(viento["r"].iloc[0])
#phi_p = float(viento["phi"].iloc[0])
#psi_p = float(viento["psi"].iloc[0])

plt.show()
