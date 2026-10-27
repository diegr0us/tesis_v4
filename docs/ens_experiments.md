# Pruebas aisladas: potencia diésel reducida y déficit penalizado

Ejecutor: `c:\Users\diego_c\GitHub Local\tesis_v4\ens_experiments.py`.
No modifica main.py ni los modelos originales. Subclases agregan e>=0 al
balance, c_ens*e al costo y cotas lambda_balance/lambda_wind<=c_ens al upper.
El respaldo permite cubrir demanda y carga terminal con déficit penalizado.
No se utiliza el replay original, que reportaría ENS cero.

## Alcance físico

Es una relajación con déficit sin cota superior, no ENS restringida por e<=D.
Se registra cualquier exceso sobre demanda en todos los solves lower.
Ausencia de excesos observados NO prueba equivalencia global con el modelo
físico restringido, ni certifica todos los estados de la envolvente superior.
Las cotas y la convergencia reportadas corresponden a la relajación.
Los diagnósticos del último backward son soluciones locales por día, no una
trayectoria operativa concatenada ni el costo de un replay de la política.

## Configuración

Tres días del PUS real original; batería original P=10, E=40, SOC inicial/final=20,
eta=0.95; diésel de costo 100. Tolerancia relativa=0.001, absoluta=0.001,
upper_mip_gap=0.00001, un hilo. No se fuerza un mínimo de iteraciones.

| pmax | c_ens | segundos/oráculo | iteraciones | gap final (%) | resultado |
|---:|---:|---:|---:|---:|---|
| 10 | 300 | 5 | 3 | 0.000915 | convergencia |
| 10 | 1000 | 5 | 3 | 0.000726 | convergencia |
| 10 | 3000 | 5 | 2 | 0.000911 | convergencia |
| 12 | 300 | 5 | 2 | 0 | convergencia |
| 15 | 300 | 5 | 4 | 0.001469 | convergencia |
| 15 | 300 | 1 | 5 | 1.409173 | estancamiento |
| 20 | 300 | 1 | 4 | 9.710392 | estancamiento |
| 15 | 1000 | 1 | 5 | 2.375214 | estancamiento |

El barrido de 1 s también se estancó para pmax=30 y 100, con c_ens=300 y 1000,
y para pmax=20/c_ens=1000. Más iteraciones no certifican mejor solución.

### Caso de cuatro iteraciones: pmax=15, c_ens=300

| iteración | LB | UB | gap (%) | cortes | puntos |
|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 184035.185092 | 100 | 3 | 3 |
| 2 | 182836.199946 | 184034.634163 | 0.651 | 6 | 5 |
| 3 | 183134.647684 | 183586.174589 | 0.246 | 9 | 7 |
| 4 | 183577.101849 | 183579.798020 | 0.001469 | 10 | 9 |

Se refinaron ambas cotas. En los solves locales del último backward hubo ENS
en 19, 18 y 17 horas (días 1, 2, 3), con diésel saturado en las 24 horas.
No se observó déficit superior a demanda. A pmax=12, ENS aparece en las 24
horas de cada solve y el algoritmo converge en dos iteraciones: reducir más
la capacidad puede dejar el problema en un único régimen marginal.
Esta comparación es consistente con cambios de régimen y almacenamiento;
no demuestra por sí sola quiebres respecto de disponibilidad, que aquí es fija.

## Variantes

- Con dos fallas sintéticas (una turbina por parque al final del horizonte,
  mantenimiento de un día), pmax=10/c_ens=300 y 1000 convergieron en tres
  iteraciones; gaps 0.000670 % y 0.000820 %. No se observaron excesos e>D.
- Batería x4, pmax=10/c_ens=1000: tres iteraciones pero máximo e-D=29.612642.
  Se excluye como ejemplo de ENS física válida.
- Control determinista (phi=psi=0), pmax=5/c_ens=1000: cuatro iteraciones,
  gap prácticamente cero. No equivale al PUS robusto original.

## Reproducción y archivos

```powershell
python 'c:\Users\diego_c\GitHub Local\tesis_v4\ens_experiments.py' --pmax 15 --costs 300 --oracle-seconds 5 --max-iterations 10
python 'c:\Users\diego_c\GitHub Local\tesis_v4\ens_experiments.py' --pmax 10 --costs 300 1000 3000 --oracle-seconds 5
```

El número exacto de iteraciones de casos limitados por tiempo puede variar.
Cada ejecución crea una carpeta nueva bajo results con configuración, historia,
trayectorias, ENS horaria y estado/valor/cota de cada oráculo.

Caso de cuatro iteraciones y comparación pmax=12:
`c:\Users\diego_c\GitHub Local\tesis_v4\results\ens_20261026_081241_421870`.
Comparación de penalizaciones pmax=10:
`c:\Users\diego_c\GitHub Local\tesis_v4\results\ens_20261026_081224_047577`.
Mantenimiento:
`c:\Users\diego_c\GitHub Local\tesis_v4\results\ens_20261026_081231_425734`.

Tests: igualdad primal-dual de un caso analítico, reconstrucción repetida del
balance sin perder ENS, recourse con capacidad insuficiente y convergencia
en más de dos iteraciones con PUS real.