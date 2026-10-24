"""Gráficos y exportación de resultados RDDP, sin depender de modelos Gurobi vivos."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from rddp.class_rddp import RDDPConfig, RDDPResult
from rddp.class_system import Microgrid


DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


def save_profile_plots(
    hourly: pd.DataFrame,
    output_dir: str | Path,
    prefix: str = "nominal",
    title: str = "Replay nominal (no es el peor caso)",
    park_names: tuple[str, ...] = (),
    show: bool = False,
) -> list[Path]:
    """Grafica perfiles horarios exportados; permite regenerarlos sin optimizar.

    available_wind_* ya incluye disponibilidad de turbinas (A/G).
    El detalle cubre hasta siete días desde la primera hora con excedente;
    si no hay excedentes, muestra los primeros siete días.
    """
    data = hourly.copy()
    if data.empty:
        raise ValueError("Se necesitan datos horarios para graficar perfiles.")
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="raise")
    data = data.sort_values("timestamp")
    park_columns = sorted(
        (c for c in data if c.startswith("available_wind_") and c != "available_wind_MW"),
        key=lambda c: int(c.split("_")[-2]),
    )
    if park_columns:
        names = list(park_names) if park_names else [f"Parque {c.split('_')[-2]}" for c in park_columns]
        if len(names) != len(park_columns):
            raise ValueError("Debe haber un nombre por perfil eólico.")
        available = data[park_columns].sum(axis=1)
    else:
        names = []
        available = data["available_wind_MW"]
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    surplus = available > data["demand_MW"] + 1e-6
    start = data.loc[surplus, "timestamp"].iloc[0].normalize() if surplus.any() else data["timestamp"].iloc[0]
    detail = (data["timestamp"] >= start) & (data["timestamp"] < start + pd.Timedelta(days=7))
    paths = []
    figures = []
    try:
        for suffix, mask in (("profiles", np.ones(len(data), dtype=bool)), ("profiles_detail", detail)):
            view = data.loc[mask]
            time = view["timestamp"]
            fig, axes = plt.subplots(len(park_columns) + 2, 1,
                figsize=(14, 3 * (len(park_columns) + 2)), sharex=True, squeeze=False)
            figures.append(fig)
            axes = axes[:, 0]
            axes[0].plot(time, view["demand_MW"], color="black", label="Demanda")
            axes[0].set_title("Perfil de demanda")
            for ax, column, name in zip(axes[1:-1], park_columns, names):
                index = column.split("_")[-2]
                used_column = f"wind_{index}_MW"
                ax.plot(time, view[column], color="tab:blue", label="Viento disponible (incluye A/G)")
                if used_column in view:
                    ax.plot(time, view[used_column], color="tab:orange", linestyle="--", label="Viento despachado")
                    ax.fill_between(time, view[used_column].to_numpy(), view[column].to_numpy(),
                        color="tab:orange", alpha=0.2, label="Vertimiento")
                ax.set_title(name)
            total = available.loc[mask]
            ax = axes[-1]
            ax.plot(time, view["demand_MW"], color="black", label="Demanda")
            ax.plot(time, total, color="tab:blue", label="Viento total disponible")
            ax.plot(time, view["wind_MW"], color="tab:orange", linestyle="--", label="Viento total despachado")
            ax.fill_between(time, view["wind_MW"].to_numpy(), total.to_numpy(),
                color="tab:orange", alpha=0.2, label="Vertimiento")
            ax.set_title("Demanda y oferta eólica total")
            for ax in axes:
                ax.set_ylabel("Potencia (MW)")
                ax.set_ylim(bottom=0)
                ax.grid(alpha=0.25)
                ax.legend(loc="upper right", fontsize="small")
            axes[-1].set_xlabel("Fecha / hora")
            window = "detalle de hasta 7 días" if suffix.endswith("detail") else "horizonte completo"
            fig.suptitle(f"{title} — {window}")
            fig.autofmt_xdate()
            fig.tight_layout(rect=(0, 0, 1, 0.97))
            path = directory / f"{prefix}_{suffix}.png"
            fig.savefig(path, dpi=160, bbox_inches="tight")
            paths.append(path)
            if not show:
                plt.close(fig)
        if show:
            plt.show()
        return paths
    finally:
        for fig in figures:
            plt.close(fig)


def save_results(
    result: RDDPResult,
    system: Microgrid,
    config: RDDPConfig,
    start_date: str,
    output_dir: str | Path = DEFAULT_RESULTS_DIR,
    show: bool = False,
    park_names: tuple[str, ...] = (),
) -> Path:
    """Crea una carpeta única con PNG, CSV y JSON; devuelve su ruta absoluta.

    show=True muestra las figuras al terminar (puede bloquear hasta cerrarlas).
    Los gráficos operativos corresponden solo al replay nominal, no al peor caso.
    Cada intervalo operativo se considera de una hora, como en el modelo.
    """
    days, hours = system.horizon, system.hours_per_day
    names = list(park_names) if park_names else [f"Parque {w + 1}" for w in range(system.wind.n_parks)]
    if len(names) != system.wind.n_parks:
        raise ValueError("Debe haber un nombre por parque.")
    dates = pd.date_range(start_date, periods=days, freq="D")
    if result.plan.wind_availability.shape != (len(names), days):
        raise ValueError("La disponibilidad del resultado no coincide con el horizonte.")
    if result.operation and (len(result.operation) != days or any(op.hours != hours for op in result.operation)):
        raise ValueError("El replay debe cubrir todos los días y horas del horizonte.")
    directory = Path(output_dir).resolve() / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    directory.mkdir(parents=True, exist_ok=False)
    figures = []

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(directory / f"{name}.png", dpi=160, bbox_inches="tight")
        figures.append(fig)
        if not show:
            plt.close(fig)

    try:
        history = pd.DataFrame([asdict(item) for item in result.history])
        history.to_csv(directory / "iterations.csv", index=False)
        if not history.empty:
            fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
            x = history["iteration"].to_numpy()
            axes[0].plot(x, history["lower_bound"], "o-", label="LB certificada")
            axes[0].plot(x, history["upper_bound"], "o-", label="UB certificada")
            axes[0].set(ylabel="Costo total", title="RDDP: evolución de cotas globales")
            axes[0].legend()
            axes[1].plot(x, 100 * history["relative_gap"], "o-", label="Gap relativo")
            axes[1].axhline(100 * config.relative_gap, color="tab:red", linestyle="--", label="Tolerancia relativa")
            axes[1].set(xlabel="Iteración", ylabel="Gap (%)")
            axes[1].legend()
            for ax in axes:
                ax.grid(alpha=0.25)
            save(fig, "convergence")

            fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
            axes[0].step(x, history["n_cuts"], where="mid", label="Cortes inferiores")
            axes[0].step(x, history["n_points"], where="mid", label="Puntos superiores")
            axes[0].set(ylabel="Cantidad acumulada", title="Refinamiento de las aproximaciones")
            axes[0].legend()
            axes[1].plot(x, history["oracle_slack"], "o-", color="tab:orange")
            axes[1].set(xlabel="Iteración", ylabel="Suma de holguras upper", title="Diagnóstico: no equivale al gap global")
            for ax in axes:
                ax.grid(alpha=0.25)
            save(fig, "refinement")

        plan_rows = []
        for w, name in enumerate(names):
            for d, date in enumerate(dates):
                plan_rows.append({"date": date, "day": d + 1, "park": name,
                    "available_turbines": result.plan.wind_availability[w, d],
                    "total_turbines": system.wind.G_r[w], "crews": result.plan.crews[w, d]})
        pd.DataFrame(plan_rows).to_csv(directory / "availability.csv", index=False)
        maintenance_rows = []
        for (j, w, d), active in sorted(result.plan.maintenance_active.items()):
            maintenance_rows.append({"date": dates[d], "day": d + 1, "park": names[w],
                "turbine": j + 1, "active": active,
                "start": result.plan.maintenance_start.get((j, w, d), 0.0)})
        pd.DataFrame(maintenance_rows, columns=["date", "day", "park", "turbine", "active", "start"]).to_csv(
            directory / "maintenance.csv", index=False)

        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        for w, name in enumerate(names):
            axes[0].step(dates, result.plan.wind_availability[w], where="mid", label=name)
            axes[1].step(dates, result.plan.crews[w], where="mid", label=name)
        axes[0].set(ylabel="Turbinas disponibles", title="Mejor plan asociado a la cota superior")
        axes[1].set(ylabel="Cuadrillas asignadas", xlabel="Fecha")
        for ax in axes:
            ax.grid(alpha=0.25)
            ax.legend()
        fig.autofmt_xdate()
        save(fig, "availability")

        keys = sorted({(j, w) for j, w, _ in result.plan.maintenance_active}, key=lambda key: (key[1], key[0]))
        if keys:
            matrix = np.array([[result.plan.maintenance_active.get((j, w, d), 0.) for d in range(days)] for j, w in keys])
            fig, ax = plt.subplots(figsize=(12, max(3, 0.3 * len(keys))))
            image = ax.imshow(matrix, aspect="auto", interpolation="nearest", vmin=0, vmax=1, cmap="Blues",
                              extent=(0.5, days + 0.5, len(keys) - 0.5, -0.5))
            ax.set_yticks(range(len(keys)), [f"{names[w]} · T{j + 1}" for j, w in keys])
            ax.set(xlabel="Día operativo (1-based)", title="Mantenimiento activo por turbina")
            fig.colorbar(image, ax=ax, label="Mantenimiento activo")
            save(fig, "maintenance")

        summary = {
            "lower_bound": float(result.lower_bound), "upper_bound": float(result.upper_bound),
            "relative_gap": float(result.relative_gap), "absolute_gap": float(result.upper_bound - result.lower_bound),
            "converged": bool(result.optimal), "stalled": bool(result.stalled),
            "stop_reason": "gap_tolerance" if result.optimal else "stalled" if result.stalled else "iteration_limit",
            "maintenance_cost_best_plan": float(result.first_stage_cost),
            "iterations": len(result.history), "cuts": result.n_cuts, "points": result.n_points,
            "oracle_slack": float(result.oracle_slack), "start_date": str(dates[0].date()),
            "end_date": str(dates[-1].date()), "operational_days": days,
            "operation_type": "nominal_replay" if result.operation else "not_available",
            "config": asdict(config),
        }
        if result.operation:
            hourly_rows, daily_rows = [], []
            for d, op in enumerate(result.operation):
                daily_cost = float(np.sum(op.diesel * system.diesel.c_var[:, None]))
                daily_rows.append({"date": dates[d], "diesel_MWh": float(op.diesel.sum()),
                    "wind_MWh": float(op.wind.sum()), "demand_MWh": float(op.demand.sum()),
                    "charge_MWh": float(op.charge.sum()), "discharge_MWh": float(op.discharge.sum()),
                    "diesel_cost": daily_cost})
                for h in range(hours):
                    row = {"timestamp": dates[d] + pd.Timedelta(hours=h), "day": d + 1, "hour": h,
                        "demand_MW": op.demand[h], "diesel_MW": op.diesel[:, h].sum(),
                        "wind_MW": op.wind[:, h].sum(), "charge_MW": op.charge[:, h].sum(),
                        "discharge_MW": op.discharge[:, h].sum(), "ens_MW": op.ens[h]}
                    for w, name in enumerate(names):
                        available = op.wind_available[w, h] * op.availability[w] / system.wind.G_r[w]
                        row[f"wind_{w + 1}_MW"] = op.wind[w, h]
                        row[f"available_wind_{w + 1}_MW"] = available
                    for b in range(system.battery.n_units):
                        row[f"soc_{b + 1}_MWh"] = op.soc[b, h]
                    hourly_rows.append(row)
            hourly, daily = pd.DataFrame(hourly_rows), pd.DataFrame(daily_rows)
            hourly.to_csv(directory / "nominal_hourly.csv", index=False)
            daily.to_csv(directory / "nominal_daily.csv", index=False)
            save_profile_plots(hourly, directory, park_names=tuple(names), show=show)
            summary["nominal_diesel_cost"] = float(daily["diesel_cost"].sum())
            summary["nominal_total_cost"] = float(result.first_stage_cost + daily["diesel_cost"].sum())

            fig, ax = plt.subplots(figsize=(13, 5))
            time = hourly["timestamp"]
            ax.plot(time, hourly["demand_MW"], color="black", label="Demanda", linewidth=1.2)
            for column, label in (("diesel_MW", "Diésel"), ("wind_MW", "Viento"),
                                  ("discharge_MW", "Descarga"), ("charge_MW", "Carga")):
                ax.plot(time, hourly[column], label=label, alpha=0.85)
            ax.set(ylabel="Potencia (MW)", xlabel="Fecha", title="Replay nominal: despacho horario (no es el peor caso)")
            ax.grid(alpha=0.25)
            ax.legend(ncol=5)
            fig.autofmt_xdate()
            save(fig, "nominal_dispatch")

            fig, ax = plt.subplots(figsize=(12, 5))
            ax.plot(dates, daily["diesel_MWh"], label="Diésel")
            ax.plot(dates, daily["wind_MWh"], label="Viento")
            ax.plot(dates, daily["demand_MWh"], "k--", label="Demanda")
            ax.set(ylabel="Energía (MWh)", xlabel="Fecha", title="Replay nominal: energía diaria")
            ax.legend()
            ax.grid(alpha=0.25)
            fig.autofmt_xdate()
            save(fig, "nominal_daily_energy")

            if system.battery.n_units:
                fig, axes = plt.subplots(system.battery.n_units, 1, figsize=(12, 3 * system.battery.n_units), squeeze=False)
                for b, ax in enumerate(axes[:, 0]):
                    ax.plot(time, hourly[f"soc_{b + 1}_MWh"], label=f"SOC batería {b + 1}")
                    ax.axhline(system.battery.soc_min[b], linestyle="--", color="gray", label="SOC mínimo")
                    ax.axhline(system.battery.soc_max[b], linestyle="--", color="tab:red", label="SOC máximo")
                    ax.set(ylabel="Energía (MWh)", title=f"Replay nominal: batería {b + 1}")
                    ax.grid(alpha=0.25)
                    ax.legend()
                fig.autofmt_xdate()
                save(fig, "nominal_soc")

        with (directory / "summary.json").open("w", encoding="utf-8") as file:
            json.dump(summary, file, ensure_ascii=False, indent=2, allow_nan=False)
        status = "convergencia" if result.optimal else "estancamiento" if result.stalled else "máximo de iteraciones"
        print(f"Resultados: {status}; LB={result.lower_bound:,.2f}, UB={result.upper_bound:,.2f}, "
              f"gap={result.relative_gap:.3%}\nArchivos guardados en: {directory}")
        if show:
            plt.show()
        return directory
    finally:
        for fig in figures:
            plt.close(fig)
