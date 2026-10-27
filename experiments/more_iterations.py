"""Casos aislados para que el costo de recurso deje de ser lineal en A.

Con un solo diésel y el presupuesto amplio del PUS, el peor viento queda por
debajo de la demanda en todo el rango de disponibilidad. El costo es casi
lineal y un barrido backward deja el hiperplano justo: el RDDP cierra en dos
iteraciones.

Aquí se cambian solo datos de entrada (flota, costos, presupuesto del PUS) y
se corre un horizonte corto. No se toca el algoritmo.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from rddp.algorithm import RDDP
from rddp.class_pus import PUSGroup, PUSParameters
from rddp.class_rddp import RDDPConfig
from rddp.class_system import (
    BatteryFleet,
    BatteryUnit,
    DieselFleet,
    DieselUnit,
    Microgrid,
    WindFleet,
    WindPark,
)
from rddp.first_stage import FirstStageProblem
from rddp.recourse_stages import RecourseStage_Lower, RecourseStage_Upper

ROOT = Path(__file__).resolve().parents[1]
INICIO = "2025-01-06"
HOURS = 24
HORIZON = 6


def _tighten(group: PUSGroup, phi: float | None, psi: float | None) -> PUSGroup:
    if phi is None and psi is None:
        return group
    return replace(
        group,
        phi=group.phi if phi is None else float(phi),
        psi=group.psi if psi is None else float(psi),
    )


def _parks(n: int, horizon: int) -> tuple[WindPark, WindPark]:
    """Todas las turbinas fallan el último día: el mantenimiento es una salida."""
    failure = np.full(n, horizon, dtype=int)
    t0 = np.ones(n, dtype=int)
    return tuple(
        WindPark(
            prated=3.5,
            n_turbines=n,
            components=1,
            t_0=t0,
            t_failure=failure.copy(),
            t_up=failure.copy(),
            seed=seed,
        )
        for seed in (0, 1)
    )


def build(spec: dict, pus: PUSParameters):
    horizon = int(spec["horizon"])
    wind = WindFleet(
        parks=_parks(int(spec["n"]), horizon),
        maintenance_days=int(spec["maintenance_days"]),
        maintenance_crew=int(spec["maintenance_crew"]),
        max_crews=int(spec["max_crews"]),
        crew_cost=float(spec["crew_cost"]),
        v_pr=float(spec["v_pr"]),
        c_pr=float(spec["c_pr"]),
        v_co=float(spec["v_co"]),
        c_co=float(spec["c_co"]),
    )
    wind.assign_alpha_hat(horizon)
    battery = spec["battery"]
    grid = Microgrid(
        diesel=DieselFleet(units=tuple(DieselUnit(pmax=p, pmin=0.0, c_var=c) for p, c in spec["diesel"])),
        wind=wind,
        battery=BatteryFleet(units=(BatteryUnit(
            pch=battery["pch"], pdch=battery["pdch"], soc_max=battery["soc_max"],
            soc_min=0.0, eta=battery["eta"], soc_ini=battery["soc_ini"],
        ),)),
        c_ens=1000.0,
        horizon=horizon,
        hours_per_day=HOURS,
    )
    case_pus = replace(
        pus,
        wind=_tighten(pus.wind, spec.get("phi_wind"), spec.get("psi_wind")),
        demand=_tighten(pus.demand, spec.get("phi_demand"), spec.get("psi_demand")),
    )
    case_pus.validate_reconstruction(wind.n_parks, HOURS, horizon)
    if case_pus.dates is None or str(case_pus.dates[0]) != INICIO:
        raise ValueError("El inicio del horizonte no coincide con el PUS.")
    return grid, case_pus


def _profile(reconstruction, group, stage: int, theta: np.ndarray) -> np.ndarray:
    score = group.c + group.a * theta
    return reconstruction.forecast[stage] + reconstruction.b + reconstruction.L @ score


def diagnose(spec: dict, pus: PUSParameters) -> None:
    """Horas en diésel o vertimiento, en el centro y empujando la primera componente."""
    grid, case_pus = build(spec, pus)
    n = int(spec["n"])
    wind_group, demand_group = case_pus.wind, case_pus.demand
    cheap_mw = None
    if len(spec["diesel"]) > 1:
        cheap_mw = min(spec["diesel"], key=lambda unit: unit[1])[0]
    plans = {"llena": np.full(2, n), "un parque fuera": np.array([0.0, n])}
    print(f"  presupuesto viento phi={wind_group.phi:g} psi={wind_group.psi:g}; "
          f"demanda phi={demand_group.phi:g}")
    thetas = [np.zeros(wind_group.r)]
    for sign in (-1.0, 1.0):
        theta = np.zeros(wind_group.r)
        theta[0] = sign * min(1.0, wind_group.phi)
        thetas.append(theta)
    demand_theta = np.zeros(demand_group.r)
    demand_theta[0] = min(1.0, demand_group.phi)
    for label, availability in plans.items():
        diesel_hours = curtail_hours = expensive_hours = 0
        wind_energy = demand_energy = 0.0
        for stage in range(grid.horizon):
            candidates = [_profile(case_pus.wind_reconstruction, wind_group, stage, theta) for theta in thetas]
            wind = min(candidates, key=lambda series: float(series.sum())).reshape(2, HOURS)
            demand = _profile(case_pus.demand_reconstruction, demand_group, stage, demand_theta)
            available = wind * availability[:, None]
            total = available.sum(axis=0)
            diesel_hours += int(np.sum(total + 1e-6 < demand))
            curtail_hours += int(np.sum(total > demand + 1e-6))
            wind_energy += float(total.sum())
            demand_energy += float(demand.sum())
            if cheap_mw is not None:
                residual = demand - total
                expensive_hours += int(np.sum(residual > cheap_mw + 1e-6))
        print(f"  {label}: viento {wind_energy:.0f} MWh, demanda {demand_energy:.0f} MWh, "
              f"horas con déficit {diesel_hours}, horas con excedente {curtail_hours}"
              + (f", horas en el diésel caro {expensive_hours}" if cheap_mw is not None else ""))


CASES: dict[str, dict] = {
    # Mismo sistema que el quiebre, pero con el presupuesto original: el peor
    # viento cae a cero y la disponibilidad no cambia de tramo.
    "lineal": dict(
        horizon=HORIZON, n=16, maintenance_days=1, maintenance_crew=16, max_crews=1,
        crew_cost=0.0, v_pr=10.0, c_pr=500.0, v_co=50.0, c_co=3000.0,
        diesel=((100.0, 100.0),),
        battery=dict(pch=5.0, pdch=5.0, soc_max=15.0, eta=0.95, soc_ini=5.0),
    ),
    # Presupuesto chico: a flota llena el peor viento aún sobra; sacar un
    # parque entero devuelve el día al diésel. La pendiente de A cambia.
    "vertimiento": dict(
        horizon=HORIZON, n=16, maintenance_days=1, maintenance_crew=16, max_crews=1,
        crew_cost=0.0, v_pr=10.0, c_pr=500.0, v_co=50.0, c_co=3000.0,
        diesel=((100.0, 100.0),),
        battery=dict(pch=5.0, pdch=5.0, soc_max=15.0, eta=0.95, soc_ini=5.0),
        phi_wind=0.05, psi_wind=0.05, phi_demand=0.3, psi_demand=0.3,
    ),
    # Además hay un diésel barato chico y uno caro. El día con un parque
    # fuera cruza los dos tramos; el día lleno está en vertimiento.
    "orden_de_merito": dict(
        horizon=HORIZON, n=16, maintenance_days=1, maintenance_crew=16, max_crews=1,
        crew_cost=0.0, v_pr=10.0, c_pr=500.0, v_co=50.0, c_co=3000.0,
        diesel=((100.0, 80.0), (2.0, 15.0)),
        battery=dict(pch=5.0, pdch=5.0, soc_max=15.0, eta=0.95, soc_ini=5.0),
        phi_wind=0.05, psi_wind=0.05, phi_demand=0.3, psi_demand=0.3,
    ),
    # Presupuesto original. El diésel barato queda entre el residual de la
    # flota llena y el de un parque fuera, en el peor viento de ese presupuesto.
    "merito_phi_amplio": dict(
        horizon=HORIZON, n=16, maintenance_days=1, maintenance_crew=16, max_crews=1,
        crew_cost=0.0, v_pr=10.0, c_pr=500.0, v_co=50.0, c_co=3000.0,
        diesel=((100.0, 80.0), (16.5, 15.0)),
        battery=dict(pch=5.0, pdch=5.0, soc_max=15.0, eta=0.95, soc_ini=5.0),
    ),
}


def solve_case(name: str, spec: dict, pus: PUSParameters, max_iterations: int) -> dict:
    grid, case_pus = build(spec, pus)
    config = RDDPConfig(
        relative_gap=1e-3,
        absolute_gap=1e-2,
        max_iterations=max_iterations,
        upper_time_limit=300,
        upper_mip_gap=1e-4,
        verbose=True,
        nominal_replay=False,
        output_flag=0,
    )
    first = FirstStageProblem(grid, config)
    upper = [RecourseStage_Upper(grid, config, case_pus, stage) for stage in range(grid.horizon)]
    lower = [RecourseStage_Lower(grid, config, case_pus, stage) for stage in range(grid.horizon)]
    started = time.perf_counter()
    try:
        result = RDDP(grid, config, case_pus, first, upper, lower).solve()
    finally:
        for problem in (first, *upper, *lower):
            problem.model.dispose()
    elapsed = time.perf_counter() - started
    history = [
        {
            "iteration": step.iteration,
            "lower_bound": step.lower_bound,
            "upper_bound": step.upper_bound,
            "relative_gap": step.relative_gap,
            "n_cuts": step.n_cuts,
            "n_points": step.n_points,
            "maintenance_cost": step.first_stage_cost,
        }
        for step in result.history
    ]
    availability = np.asarray(result.plan.wind_availability)
    summary = {
        "case": name,
        "iterations": len(history),
        "optimal": bool(result.optimal),
        "stalled": bool(result.stalled),
        "relative_gap": result.relative_gap,
        "lower_bound": result.lower_bound,
        "upper_bound": result.upper_bound,
        "seconds": elapsed,
        "availability": availability.tolist(),
        "history": history,
        "phi_wind": case_pus.wind.phi,
        "diesel": spec["diesel"],
    }
    print(
        f"{name}: iteraciones={summary['iterations']} óptimo={summary['optimal']} "
        f"estancado={summary['stalled']} gap={result.relative_gap:.3%} "
        f"LB={result.lower_bound:.1f} UB={result.upper_bound:.1f} ({elapsed:.0f} s)"
    )
    print(f"  disponibilidad por parque y día:\n{np.array2string(availability, precision=0)}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", default=list(CASES))
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--max-iterations", type=int, default=8)
    args = parser.parse_args()
    unknown = [name for name in args.cases if name not in CASES]
    if unknown:
        raise SystemExit(f"Casos desconocidos: {unknown}. Opciones: {list(CASES)}")
    pus = PUSParameters.from_files()
    if args.diagnose:
        for name in args.cases:
            print(name)
            diagnose(CASES[name], pus)
        return
    summaries = []
    out = ROOT / "experiments" / "iteration_results.json"
    for name in args.cases:
        print(f"\n=== {name} ===")
        diagnose(CASES[name], pus)
        summaries.append(solve_case(name, CASES[name], pus, args.max_iterations))
        stored = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else []
        by_name = {item["case"]: item for item in stored}
        for item in summaries:
            by_name[item["case"]] = item
        out.write_text(json.dumps(list(by_name.values()), indent=2), encoding="utf-8")
    print("\nResumen")
    for summary in summaries:
        print(f"  {summary['case']}: {summary['iterations']} iteraciones, "
              f"óptimo={summary['optimal']}, gap={summary['relative_gap']:.3%}")


if __name__ == "__main__":
    main()
