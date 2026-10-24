"""Sensibilidad determinista: viento escalado, mantenimiento fijo y previsión perfecta."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import gurobipy as gp
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from rddp.class_rddp import RDDPConfig
from rddp.graphs import save_profile_plots
from rddp.recourse_stages import RecourseStage_Lower


ROOT = Path(__file__).resolve().parent


def dispatch(system, data: pd.DataFrame, factor: float):
    """Reutiliza el LP operativo con el horizonte completo como una sola etapa.

    La entrada eólica ya incluye A/G. No se aplican cortes robustos anteriores
    a perfiles modificados. El objetivo secundario evita ciclos sin beneficio.
    """
    if not np.isfinite(factor) or factor < 0 or data.empty:
        raise ValueError("Se requiere factor finito no negativo y datos no vacíos.")
    wind_columns = [c for c in data if c.startswith('available_wind_')]
    if not wind_columns:
        raise ValueError("Faltan columnas available_wind_*.")
    wind = data[wind_columns].to_numpy().T * factor
    demand = data['demand_MW'].to_numpy()
    flat = SimpleNamespace(diesel=system.diesel, battery=system.battery,
        wind=SimpleNamespace(n_parks=len(wind_columns), G_r=np.ones(len(wind_columns))),
        horizon=1, hours_per_day=len(data))
    problem = RecourseStage_Lower(flat, RDDPConfig(output_flag=0), None, 0)
    try:
        problem.add_states_constraint(system.battery.soc_ini,
            np.ones((len(wind_columns), 1)), wind, demand)
        # El LP original permite exceso de oferta. Aquí se explicita el balance
        # exacto y el vertimiento es disponible menos inyectado.
        for constraint in problem.balance.values():
            constraint.Sense = '='
        model = problem.model
        model.setObjectiveN(problem.operation_cost, 0, priority=2, abstol=0, reltol=0)
        throughput = gp.quicksum(problem.pi_plus.values()) + gp.quicksum(problem.pi_minus.values())
        model.setObjectiveN(throughput, 1, priority=1, abstol=0, reltol=0)
        model.optimize()
        if model.Status != gp.GRB.OPTIMAL:
            raise RuntimeError(f"Despacho no óptimo: {model.Status}")
        values = lambda variables, n: np.array([[variables[b, h].X for h in range(len(data))] for b in range(n)])
        b = system.battery.n_units
        charge = values(problem.pi_plus, b)
        discharge = values(problem.pi_minus, b)
        soc = values(problem.soc, b)
        diesel = values(problem.y_nr, system.diesel.n_units)
        wind_dispatch = values(problem.y_r, len(wind_columns))
        used = wind_dispatch.sum(axis=0)
        out = pd.DataFrame({'timestamp': data['timestamp'].to_numpy(), 'demand_MW': demand,
            'available_wind_MW': wind.sum(axis=0), 'wind_MW': used,
            'diesel_MW': diesel.sum(axis=0), 'charge_MW': charge.sum(axis=0),
            'discharge_MW': discharge.sum(axis=0), 'curtailment_MW': wind.sum(axis=0) - used})
        for w in range(len(wind_columns)):
            out[f'available_wind_{w + 1}_MW'] = wind[w]
            out[f'wind_{w + 1}_MW'] = wind_dispatch[w]
        for unit in range(b):
            out[f'soc_{unit + 1}_MWh'] = soc[unit]
        previous = np.column_stack((system.battery.soc_ini, soc[:, :-1]))
        balance = used + diesel.sum(axis=0) + discharge.sum(axis=0) - charge.sum(axis=0) - demand
        dynamics = soc - previous - system.battery.eta[:, None] * charge + discharge / system.battery.eta[:, None]
        if np.max(np.abs(balance)) > 1e-5 or np.max(np.abs(dynamics), initial=0) > 1e-5:
            raise AssertionError("Balance o dinámica SOC inconsistente.")
        net = demand - wind.sum(axis=0)
        no_battery_cost = float(np.maximum(net, 0).sum() * system.diesel.c_var[0])
        cost = float((diesel * system.diesel.c_var[:, None]).sum())
        metrics = {'factor': factor, 'diesel_MWh': float(diesel.sum()), 'diesel_cost': cost,
            'charge_MWh': float(charge.sum()), 'discharge_MWh': float(discharge.sum()),
            'soc_min_MWh': float(soc.min()), 'soc_max_MWh': float(soc.max()),
            'curtailment_MWh': float(out.curtailment_MW.sum()),
            'surplus_hours': int((net < -1e-6).sum()),
            'no_battery_cost': no_battery_cost, 'battery_savings': no_battery_cost - cost}
        return out, metrics
    finally:
        problem.model.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--factors', nargs='+', type=float, default=[1, 2, 4, 6, 8, 10, 15])
    args = parser.parse_args()
    import main as entry
    if entry.grid.diesel.n_units != 1:
        raise ValueError("La comparación sin batería supone un solo generador.")
    source = args.input or sorted((ROOT / 'results').glob('run_*/nominal_hourly.csv'))[-1]
    data = pd.read_csv(source)
    if data.demand_MW.max() > entry.grid.diesel.pmax[0]:
        raise ValueError("La comparación sin batería requiere respaldo suficiente.")
    directory = ROOT / 'results' / datetime.now().strftime('wind_sensitivity_%Y%m%d_%H%M%S_%f')
    directory.mkdir(parents=True)
    rows = []
    fig, axes = plt.subplots(len(args.factors), 1, figsize=(13, 2.5 * len(args.factors)), squeeze=False)
    try:
        for factor, ax in zip(args.factors, axes[:, 0]):
            hourly, metrics = dispatch(entry.grid, data, factor)
            hourly.to_csv(directory / f'factor_{factor:g}_hourly.csv', index=False)
            save_profile_plots(hourly, directory, prefix=f'factor_{factor:g}',
                title=f'Viento ×{factor:g}: sensibilidad determinista con previsión perfecta')
            rows.append(metrics)
            for col in hourly:
                if col.startswith('soc_'):
                    ax.plot(pd.to_datetime(hourly.timestamp), hourly[col], label=col)
            ax.set(title=f'Viento ×{factor:g}: despacho determinista con previsión perfecta', ylabel='SOC (MWh)')
            ax.set_ylim(entry.grid.battery.soc_min.min() - 1, entry.grid.battery.soc_max.max() + 1)
            ax.legend()
            ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(directory / 'soc_comparison.png', dpi=150)
    finally:
        plt.close(fig)
    summary = pd.DataFrame(rows)
    summary.to_csv(directory / 'comparison.csv', index=False)
    (directory / 'README.txt').write_text(
        f'Entrada: {source.resolve()}\nConfiguración física: main.py actual.\n'
        'Mantenimiento fijo incorporado en available_wind. Viento multiplicado sin recalibrar PCA.\n'
        'Prueba determinista con previsión perfecta; no es RDDP ni un certificado robusto.\n'
        'Períodos de una hora. Costo primario: diésel; secundario: minimizar carga+descarga.\n'
        'Factores altos son artificiales y no se limitan a la potencia nominal instalada.\n', encoding='utf-8')
    print(summary.to_string(index=False))
    print(f'Archivos: {directory}')


if __name__ == '__main__':
    main()