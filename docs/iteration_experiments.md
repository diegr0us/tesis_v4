# Pruebas aisladas de iteraciones

## Ampliación: parámetros separados y trazas de SOC

El ejecutor ahora registra cada solve lower (fase, día, SOC entrante/saliente,
disponibilidad y objetivo) mediante una subclase observadora, sin cambiar el
algoritmo. Todas las pruebas conservan las tolerancias anteriores.

Resultados a tres días, cambiando respecto de la batería base (P=10, E=40,
SOC inicial/final=20, eta=0.95):

| Caso | Cambios | Iteraciones | Gap final (%) |
|---|---|---:|---:|
| power_4 | pch=pdch=40 | 2 | 0.077135 |
| energy_4 | soc_max=160 | 3 | 0.000674 |
| soc_35 | soc_ini=35; final implícito=35 | 2 | 0 |
| terminal_0 | soc_final=0 | 3 | 0 |
| energy_soc_4 | soc_max=160, soc_ini=80; final=80 | 2 | 0.000138 |
| battery_8 | pch=pdch=80, soc_max=320, soc_ini/final=160 | 3 | ~0 |
| battery_4_eta_08 | batería x4 y eta=0.8 | 3 | ~0 |
| battery_4_terminal_0 | batería x4 y soc_final=0 | 3 | ~0 |
| wind_2 | perfil y soporte eólico x2 | 2 | 0.000768 |
| demand_07 | perfil y soporte de demanda x0.7 | 2 | 0.000748 |
| uncertainty_01 | phi y psi de ambos grupos x0.1 | 2 | 0.000686 |
| maintenance | dos fallas sintéticas al día final, mantenimiento de un día | 2 | 0 |
| maintenance_battery_4 | anterior y batería x4 | 3 | 0.000288 |

Los seis casos nuevos con tres iteraciones se repitieron con límite de 10 s
por oráculo y convergieron sin estancamiento. Resultados de la repetición:
`c:\Users\diego_c\GitHub Local\tesis_v4\results\iterations_20261025_224625_669002`.

Las cajas sintéticas del caso maintenance afectan una turbina por parque:
t_failure=t_up=horizon; las demás se sitúan en horizon+10. Se usa una cuadrilla,
capacidad de una turbina y duración de un día. No se modifican archivos de fallas.
El escalado de viento/demanda multiplica forecast, b, c y a; conserva L y no
recalibra datos históricos. Son escenarios de sensibilidad, no nuevos pronósticos.

### Mecanismo observado

SOC al final de cada día del forward (el último día no se resuelve en forward):

| Caso | Iteración | Día 1 | Día 2 |
|---|---:|---:|---:|
| Base | 1 | 0 | 0 |
| Base | 2 | 20 | 20 |
| Batería x4 | 1 | 0 | 0 |
| Batería x4 | 2 | 160 | 160 |
| Batería x4 | 3 | 80 | 80 |

Las aproximaciones iniciales hacen visitar extremos distintos del SOC. El
backward refina los estados entrantes guardados del forward, no vuelve a
generar toda la trayectoria después de cada corte. En batería x4, la segunda
pasada aumenta los cortes de 3 a 5; la tercera mejora la UB con más puntos,
manteniendo la LB. No debe interpretarse como prueba de más quiebres en A.

En terminal_0, la UB ya vale 131052.552486 desde la primera iteración. La LB
de la segunda es 130847.289328, y los cortes añadidos en ese backward se
incorporan al maestro al comenzar la tercera: LB=UB=131052.552486. Este caso
es evidencia de una mejora inferior adicional, no solo de la envolvente superior.

### Horizonte y combinaciones

A seis días: base=2, batería x4=3, terminal_0=2, batería x4 con final cero=3,
mantenimiento con batería x4=3. Todos convergieron. En terminal_0 el gap de
la segunda iteración es 0.085566 %, ya inferior a la tolerancia relativa;
una mayor cantidad de días no implica más iteraciones.

Combinar viento x2 con presupuestos x0.1 convergió en 2; añadir mantenimiento
a esa combinación se estancó en 3 con gap 1.728 % bajo límite de 2 s/oráculo.
Demanda x0.4 y presupuestos x0.1 convergió en una sola iteración con costo
prácticamente cero. No se encontró aquí un caso convergente de más de 3 iteraciones.

Reproducción de los casos adicionales:

```powershell
python 'c:\Users\diego_c\GitHub Local\tesis_v4\iteration_experiments.py' --cases energy_4 terminal_0 battery_8 battery_4_eta_08 battery_4_terminal_0 maintenance_battery_4 --max-iterations 10 --oracle-seconds 10
```

Validación: cuatro tests del ejecutor (incluidos subcasos de convergencia,
aislamiento y escalado PUS) y tres tests de RDDP pasaron.

## Barrido inicial

Se ejecutó el PUS real sobre sus primeros tres días, sin modificar el algoritmo
ni main.py. Tolerancias conservadas: relativa 0.001, absoluta 0.001 y MIPGap
del oráculo 0.00001. Para acotar el barrido: un hilo, 3 segundos por oráculo,
15 iteraciones máximas y sin replay nominal. La duración de mantenimiento se
recorta de 4 a 3 días; no hay turbinas con mantenimiento requerido en este horizonte.

| Caso | Iteraciones | Gap final (%) | Resultado |
|---|---:|---:|---|
| Base | 2 | 0.000674 | Convergencia |
| Diésel económico adicional 10 MW, costo 30 | 2 | 0.000042 | Convergencia |
| Diésel económico adicional 20 MW, costo 30 | 6 | 7.142406 | Estancamiento |
| Diésel económico adicional 30 MW, costo 30 | 5 | 1.589118 | Estancamiento |
| Batería x4 | 3 | 0.001204 | Convergencia |
| Diésel económico 20 MW y batería x4 | 8 | 1.638056 | Estancamiento |

El generador original de 100 MW y costo 100 se conserva como primera unidad
en todos los casos de esta tabla. Los casos estancados no prueban convergencia;
el límite corto del oráculo puede dejar holgura en las cotas superiores.

## Caso confirmado

Cambiar pch/pdch de 10 a 40, soc_max de 40 a 160 y soc_ini de 20 a 80.
Se mantienen eta=0.95 y soc_min=0. El SOC final implícito también pasa a 80.
En la iteración 2: LB=132952.552486, UB=133363.520581, gap=0.308156 %.
En la iteración 3: LB=132952.552486, UB=132954.153600, gap=0.001204 %.
Los cortes acumulados pasan por 3, 5, 5 y los puntos por 3, 5, 7.
La LB ya está estable en la segunda iteración: el cierre final ocurre por la UB.
Esto demuestra refinamiento adicional ligado al almacenamiento, no demuestra
quiebres de costo respecto de un plan de mantenimiento variable.

Reproducción en PowerShell:

```powershell
python 'c:\Users\diego_c\GitHub Local\tesis_v4\iteration_experiments.py' --cases baseline battery_4 --days 3 --max-iterations 8 --oracle-seconds 10
```

El script guarda parámetros, cotas, cortes, puntos, holgura del oráculo y tiempos
en JSON, en una carpeta nueva bajo el directorio results del proyecto.
El barrido original está en
`c:\Users\diego_c\GitHub Local\tesis_v4\results\iterations_20261025_222854_564293`.

## Limitaciones detectadas

- Un ensayo inicial sustituyendo el generador por unidades de 20 y 80 MW,
  con costos 100 y 300, falló con LB > UB. En
  `c:\Users\diego_c\GitHub Local\tesis_v4\rddp\recourse_stages.py`,
  lambda_balance y lambda_wind están acotados por diesel.pmax[0], una potencia,
  no por una cota justificada de precio dual. No se corrigió el núcleo aquí.
- c_ens no entra en el objetivo del despacho implementado.
- La comparación de 85 días fue interrumpida antes de completar la primera
  iteración; no hay conclusión experimental para ese horizonte.
- Pasaron las dos regresiones nuevas, las tres de RDDP y las dos de gráficos.
  La suite completa falla al importar una prueba existente porque falta
  el módulo wind_sensitivity.