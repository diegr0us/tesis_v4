# Experimentos de dos barras y una línea

Ejecutor aislado: `c:\Users\diego_c\GitHub Local\tesis_v4\network_experiments.py`.
Barra 0: parque 0. Barra 1: parque 1, demanda completa, diésel, batería y
déficit penalizado. Línea sin pérdidas con -F<=f<=F. Balances >= permiten
descartar energía; no es flujo AC ni un estudio de redes malladas.
La variable de déficit no tiene cota por demanda; la convergencia se refiere
a esa relajación. No se observaron excesos sobre demanda en los casos corridos,
pero esto no certifica equivalencia global con ENS físicamente limitada.

## Validación

Tests con perfiles fijos verifican igualdad primal-dual para F=0,1,100,
equivalencia al despacho agregado para línea holgada, costo no creciente al
ampliar la línea y reconstrucción repetida del balance. Una regresión compara
convergencia con F=100 y F=8 en el caso determinista con mantenimiento.
El ejecutor verifica cotas ordenadas/monótonas y factibilidad nodal/flujo.

## Comparación controlada que aumenta iteraciones

Tres días, diésel pmax=10/costo=100, c_ens=300, batería original,
tolerancias relativa=0.001 y absoluta=0.001. Una turbina por parque requiere
mantenimiento de un día (fallas sintéticas al final del horizonte).
Se fijan phi=psi=0: es el centro del PUS real, NO la incertidumbre original.
Solo cambia F entre filas.

| F | Iteraciones | Gap final % | Horas congestionadas días 1/2/3 |
|---:|---:|---:|---|
| 100 | 2 | ~0 | 0/0/0 |
| 10 | 3 | ~0 | 4/5/7 |
| 8 | 4 | ~0 | 7/7/10 |
| 5 | 3 | ~0 | 16/13/19 |
| 2 | 3 | 0.036839 | 24/24/24 |

Congestión y separación de precios se cuentan en solves locales del último
backward, no en un replay concatenado. El plan final fue igual en todas estas
filas: disponibilidades [[10,9,10],[9,10,10]]. No se debe atribuir el aumento
solo a cambios de base por mantenimiento: también cambian SOC y aproximaciones.

F=8: LB/UB por iteración:
1: 3030 / 37216.199216;
2: 36713.435777 / 36926.337915;
3: 36861.030415 / 36926.337915;
4: 36861.030415 / 36861.030417.
Los cortes acumulados son 3,6,7,7 y los puntos 3,6,8,10.

Resultados:
`c:\Users\diego_c\GitHub Local\tesis_v4\results\network_20261027_225929_438186`.

## PUS original

Con diésel de 10 y c_ens=300, F=100,2,1 convergieron todos en 3 iteraciones,
tanto sin mantenimiento como con las dos fallas sintéticas. Sin mantenimiento
los gaps finales (%) fueron 0.000690, ~0 y 0.0000204 respectivamente.
Hubo congestión para F=2 y F=1, pero no aumentó el número de iteraciones.

Resultados sin/con mantenimiento:
`c:\Users\diego_c\GitHub Local\tesis_v4\results\network_20261027_225909_162737`;
`c:\Users\diego_c\GitHub Local\tesis_v4\results\network_20261027_225933_937762`.

Con pmax=15, PUS original y 3 s/oráculo, F=100,5,2,1 se estancaron en
5,8,6,5 iteraciones con gaps aproximados de 0.247 %, 0.247 %, 0.245 %,
0.246 %. No constituyen convergencias ni evidencia limpia de efecto de red.

Control adicional sin incertidumbre ni mantenimiento, pmax=5: F=100,10,5,2,1
convergieron en 5,5,2,3,3 iteraciones. Refuerza la no monotonía.

## Reproducción

```powershell
python 'c:\Users\diego_c\GitHub Local\tesis_v4\network_experiments.py' --limits 100 10 8 5 2 --pmax 10 --budget-scale 0 --variant maintenance --max-iterations 20
python 'c:\Users\diego_c\GitHub Local\tesis_v4\network_experiments.py' --limits 100 2 1 --pmax 10 --oracle-seconds 5
```

No se alteran main.py, rddp ni los archivos históricos. Cada corrida guarda
JSON con parámetros, cotas, oráculos, SOC, flujo y precios por barra.