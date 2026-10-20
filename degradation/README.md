# Box de falla

Cada componente tiene una CDF de vida remanente. `FailureBox` devuelve el intervalo central de esa distribución en el día en que se está.

El día es la fila de la CDF de ese componente: el instante del pronóstico de degradación. No es el día 1–364 del año del PCA.

## Qué hay en `degradation/data`

| Archivo | Qué guarda |
|---|---|
| `cdf_<i>_<j>.xlsx` | CDF de la vida remanente del componente `j`. Sin encabezado, forma `(n_días, 500)`. |
| `pmf_<i>_<j>.xlsx` | Masa de la misma distribución. El box no la usa. |
| `degradation_signals.xlsx` | Las 19 señales de sensor de las que salieron los componentes. |

`i` (1–19) es la señal de origen. `j` (1–100) es el componente. Hay un `cdf_*_<j>.xlsx` por cada `j`.

La fila `t` es 1-based. La columna `k` es 1-based: vida remanente de `k` días. El soporte llega a 500 días. Cada componente tiene su propio largo: el más corto tiene 82 días y el más largo 283. El componente 1 tiene 134.

## El intervalo

Con \(\alpha = 0.1\) el box cubre el 90 % central de la fila de ese día:

```text
t_dw = min{k : F(k) >= α/2}
t_up = min{k : F(k) >= 1 − α/2}
```

`k` sale de `searchsorted(fila, cuantil, side="left") + 1`. `t_dw` y `t_up` son días de vida remanente contados desde el día consultado.

Si \(F(500)\) no alcanza \(1 - \alpha/2\), la consulta falla. El extremo no se recorta en 500.

## Cargarlo

Desde la raíz del repositorio, con el entorno `tesis`:

```python
from degradation.failure_box import FailureBox

boxes = FailureBox()
t_dw, t_up = boxes.box(1, 1)  # 36 y 281
boxes.n_days(1)               # 134
```

`box` recibe el componente 1–100 y el día 1–`n_days(componente)` y devuelve `(t_dw, t_up)`. Esos dos enteros son el box. Para usarlos después se guarda la tupla y se desempaqueta, o se indexa:

```python
intervalo = boxes.box(1, 1)
t_dw, t_up = intervalo             # 36, 281
piso, techo = intervalo[0], intervalo[1]
```

El valor queda en la tupla que devolvió `box`. `FailureBox(alpha=0.1)` es el valor por defecto. La primera consulta de un componente lee su Excel; las siguientes usan esa CDF en memoria.
