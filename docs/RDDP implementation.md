# Ejecución RDDP

## Gráficos y archivos de salida

`main.py` llama a `rddp.graphs.save_results()` al terminar. Cada corrida crea
una carpeta `results/run_<fecha>_<hora>_<microsegundos>` para no sobrescribir
resultados anteriores. `SHOW_GRAPHS=True` abre las figuras al finalizar;
el valor predeterminado False solo guarda los archivos.

Se exportan gráficos PNG de cotas/gap, refinamiento, disponibilidad y
mantenimiento (cuando hay turbinas en mantenimiento). Si existe replay
nominal, también se exportan despacho horario, energía diaria y SOC.
Los CSV conservan iteraciones, disponibilidad, mantenimiento y despacho
nominal; `summary.json` incluye las cotas, motivo de parada y configuración.
El costo nominal se identifica por separado y no se interpreta como UB.
Si `nominal_replay=False`, se omiten las salidas operativas.

Desde la raíz del proyecto, ejecutar `python main.py` en el entorno
Conda `tesis`. `initialize_problems()` solo construye modelos; `main()`
ejecuta el algoritmo, devuelve `RDDPResult` y libera los modelos.

El horizonte operativo usa índices Python `0,...,D-1`. El estado numérico
es `[SOC, A.T.reshape(-1)]`, con A igual al número de turbinas disponibles.
Los cortes producidos por el día d se instalan en el predecesor; el corte
del día 0 se instala en el maestro. Los puntos del día d representan su
costo sobre el estado entrante, no sobre el SOC de salida.

## Inicialización superior

La política de respaldo ignora el viento y sirve la demanda con diésel.
Mantiene el SOC y, en el último día, carga lo necesario para alcanzar el
SOC final. Se comprueba que esto sea posible desde cualquier SOC de la
caja y con las cotas horarias de demanda de la caja PCA. El costo usa el
mayor costo variable diésel. Si la carga terminal o la capacidad diésel
no permiten certificar esta política, la inicialización falla de forma
explícita; no se usa una constante arbitraria.

Para una cota M y caja [l,u], el respaldo en la envolvente dual impone
`kappa_0 + sum(l*kappa + (u-l)*positive) <= M`, con
`positive >= kappa` y `positive >= 0`. Es equivalente a incorporar todos
los vértices de la caja a altura M sin enumerarlos. Se conserva este
respaldo al añadir puntos superiores. Garantiza cobertura incluso para
planes A no visitados. La caja usa 0 <= A[w,d] <= G[w] y los límites SOC.

## Iteraciones y certificados

Forward resuelve upper y luego lower con la realización obtenida, y guarda
los estados entrantes. Backward los recorre en orden inverso y transmite
inmediatamente los nuevos puntos/cortes a los predecesores.

LB usa ObjBound del maestro. UB incluye mantenimiento más la cota superior
del oráculo raíz, manteniendo el plan fijo. Los puntos usan ObjBound, no
el incumbente de la maximización. Se guarda el mejor plan asociado a UB.
Estancamiento o máximo de iteraciones no implican convergencia; `optimal`
significa que se alcanzó el gap absoluto o relativo configurado.

El replay nominal es un despacho separado con theta=0 y los cortes
inferiores finales; no es una política robusta certificada ni el cálculo
de UB. Si ese centro tiene valores negativos se reporta el problema,
sin recortar el perfil. Puede desactivarse con `nominal_replay=False`.

## Límites y validación

- `time_limit`: límite por resolución del maestro/lower, no de toda la corrida.
- `upper_time_limit`: límite por oráculo upper.
- `price_cap` y `polish_xi`: opciones heredadas sin efecto actualmente.
- Las cotas implícitas del PUS se aplican siempre, independientemente de `pus_bounds`.
- `python -m unittest discover -s tests -v` ejecuta las regresiones con Gurobi.
- Se validaron casos controlados de uno y tres días y una corrida de dos
  días con los datos reales. La corrida completa de 85 días no se ejecutó
  como parte de la implementación.