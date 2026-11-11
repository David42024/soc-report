# Fase 7 · Optimización con Optuna UI

## Alcance, fuentes y decisiones

La página `Optimización Optuna` amplía el mismo `ExperimentManager`, `RunStore`, adaptadores y `run_nested` de Fase 2. No crea un segundo motor de entrenamiento ni un servicio Optuna Dashboard separado. Los estudios avanzados permanecen en `runs/phase2/<ejecución>/`, junto con su partición, resultados, artefacto y bitácora. Las configuraciones y candidatas derivadas se versionan en `runs/phase7/`.

Se leyeron completos el SPEC definitivo v2.1 y el Promptuario, además del código y resultados de Fases 0–6. Se conservan Groq principal, Gemini ante fallos técnicos elegibles, React, FastAPI, PostgreSQL, Redis, LangFlow y n8n. La clasificación productiva conserva su prompt, modelos, política de respaldo, revisión y SLA. La matriz general con evidencia y pendientes está en [CUMPLIMIENTO_FASES_0_A_7.md](CUMPLIMIENTO_FASES_0_A_7.md).

SUPUESTOS adoptados y comunicados antes de implementar:

1. El límite de trials corresponde a **cada estudio interno de un fold externo**. La demostración de 10 trials por fold contiene 50 trials en cinco estudios, con tres folds internos por trial completo.
2. Cada estudio avanzado utiliza una familia académica o la configuración LLM. La comparación de familias conserva el módulo de Fase 2 y puede usar estudios separados.
3. Se adopta un objetivo escalar, con posibilidad de penalizaciones explícitas predefinidas. No se añade selección automática de un frente de Pareto ni poda multiobjetivo sin una definición validada de preferencias.
4. La demostración usa el generador técnico sintético **ya existente en Fase 2**. No descarga, sustituye ni modifica datasets originales. Los resultados sintéticos verifican implementación y carecen de validez como exactitud real.
5. Para LLM se optimizan únicamente versiones de prompts y umbrales ya admitidos por el adaptador. El flujo actual mantiene fijos la salida JSON estricta y los parámetros de generación. No se inventa compatibilidad con temperatura, límites de tokens o parámetros de pesos no expuestos por ese contrato.
6. La búsqueda cloud permanece bloqueada por los topes monetarios en cero y la falta actual de referencias humanas suficientes. Una autorización anterior para un caso público individual no autoriza una búsqueda sobre otros reportes.

## Configuración y validación

La interfaz permite elegir modelo, fuente, manifiesto, objetivo supervisado, espacio de búsqueda, sampler, pruner, trials, duración, métrica, dirección, semilla, concurrencia y CPU. El editor JSON contiene distribuciones de datos, sin funciones ejecutables. Se muestran los rangos, categorías y escalas antes de preparar y autorizar el estudio.

Se admiten `float`, `int` y `categorical`, pasos numéricos compatibles y escalas logarítmicas positivas. Los tipos se contrastan con el pipeline: valores enteros para conteos, categorías booleanas para opciones lógicas y solvers efectivos para regresión logística. Se rechazan parámetros ajenos o sin efecto, extremos no finitos, orden inválido, pasos que ajustarían silenciosamente los límites y combinaciones incompatibles de n-gramas.

Los samplers son TPE, Random y Grid. Grid requiere categorías finitas explícitas, ejecución secuencial, suficientes combinaciones para el presupuesto de trials y cardinalidad bajo el límite del servidor. TPE y Random usan semillas determinísticas por número de trial y fold, delegando el muestreo a Optuna. La prueba de recuperación compara la secuencia completa con una interrumpida y reabierta. Con varios workers, el orden de resultados puede cambiar la historia de TPE; no se promete reproducibilidad exacta del orden paralelo.

Los pruners son Nop, Median y Successive Halving. Solo reciben medias acumuladas de los internos, antes de conocer la medición externa. Son tres pasos de CV y no épocas de aprendizaje. Su utilidad es limitada con tan pocos pasos; una poda tardía puede ahorrar poco. La semántica de Median se basa en la comparación del mismo paso con trials previos completos, conforme a [Optuna 5.0 MedianPruner](https://optuna.readthedocs.io/en/v5.0.0/reference/generated/optuna.pruners.MedianPruner.html).

Los máximos efectivos están en `config/analytics.yaml`: 100 trials por fold bajo la política de entrenamiento actual, hasta 7200 s acumulados, dos trials locales simultáneos, un hilo numérico por ajuste y dos hilos totales autorizados. LangFlow conserva una sola solicitud experimental a la vez, intervalo entre llamadas, máximo de intentos y presupuesto conservador de Fase 2. El límite temporal y la cancelación son cooperativos: una llamada o ajuste en curso puede terminar antes del siguiente límite seguro.

El plan preparado incorpora una huella de la configuración avanzada, además de partición y presupuesto. Cambiar el sampler, espacio u otro parámetro después de preparar exige una nueva previsualización. La aprobación cloud se excluye de esa normalización para permitir únicamente la confirmación posterior del plan revisado.

## Objetivos y separación de datos

Se mantiene Desarrollo 70 %, Validación 15 % y Prueba 15 %, con grupos disjuntos y estratificación. Cada uno de los cinco folds externos contiene tres internos. El vectorizador y clasificador se ajustan solo con el entrenamiento correspondiente. Optuna observa únicamente métricas internas. La medición externa se realiza una vez, se almacena y queda fuera del sampler y pruner.

Los ganadores de los cinco estudios internos pasan al 15 % independiente de Validación de Fase 2. Esa comparación selecciona la configuración candidata; no se elige por el mayor resultado externo. El artefacto académico final se ajusta en Desarrollo. Prueba permanece sellado y no se utiliza para ajustar parámetros, umbrales o métricas.

Los objetivos disponibles son F1 macro, balanced accuracy, recall crítico, FNR crítico, kappa cuadrático de severidad, latencia media observada de solicitud LLM y F1 penalizado. Las fórmulas de clasificación reutilizan los conteos y métricas de Fase 3; el F1 que consumen los reportes antiguos se conserva separado del objetivo elegido.

Las métricas críticas requieren el objetivo de severidad y referencias críticas en las particiones. La FNR crítica incluye derivaciones a revisión para impedir presentar esas omisiones como aciertos. El kappa usado para búsqueda requiere cobertura completa; no se optimiza un kappa condicionado a descartar los casos difíciles. F1 y balanced accuracy se maximizan; errores y latencia se minimizan. Una dirección incompatible se rechaza.

El objetivo penalizado es `F1_macro − λ × FNR_crítica − γ × tasa_revisión`, con pesos acotados declarados antes de comenzar. Es una función de utilidad explícita, no un contraste de significancia. Las unidades de sus tres términos son adimensionales. Los pesos no se ajustan contra el conjunto de Prueba.

La latencia LLM utiliza tiempos observados de las predicciones del adaptador. Si se reutiliza una predicción protegida en caché, conserva su tiempo observado; no se inventa una nueva llamada de duración cero. El contador de llamadas nuevas y los costos observados nuevos se registran por separado. Un costo facturado ausente conserva `null`; los topes en USD son reservas conservadoras, no facturas. El costo no se ofrece como objetivo disponible sin telemetría apropiada.

## Persistencia, recuperación y control

Se utiliza **Optuna 5.0.0**, ya fijado en los requisitos. `JournalStorage` con `JournalFileBackend` y `JournalFileOpenLock` conserva estados, distribuciones, parámetros, valores intermedios y métricas internas. El bloqueo por creación exclusiva evita requerir privilegios de enlaces simbólicos en este Windows. Es almacenamiento local de experimentos, separado de PostgreSQL operacional. El mecanismo se apoya en las APIs públicas documentadas de [JournalFileOpenLock](https://optuna.readthedocs.io/en/v5.0.0/reference/generated/optuna.storages.journal.JournalFileOpenLock.html) y en las restricciones de [paralelismo y almacenamiento de Optuna](https://optuna.readthedocs.io/en/stable/faq.html).

La recuperación conserva trials completos, fallidos y podados. Los RUNNING de una interrupción real se registran como FAIL, sin borrarlos ni inventar su valor final. El presupuesto total cuenta también esos intentos. TPE y Random reconstruyen su semilla por trial; no cargan pickles de samplers subidos por usuarios.

Los folds externos terminados no se repiten. Si se interrumpe una medición externa después de marcarla pendiente, la reanudación se bloquea y exige una ejecución nueva. Una cancelación antes de esa medición permite recuperar estudios y continuar con el presupuesto restante. Un tiempo acumulado agotado no se renueva silenciosamente al reanudar. Los trabajos cloud con llamadas efectuadas requieren una configuración y autorización nuevas, conservando su historial.

El monitor se actualiza mediante fragmentos de Streamlit y trabajadores de Fase 2. Muestra trial, estado, parámetros, objetivo parcial/completo, duración, mejor valor provisional, fallos, podas, llamadas y logs. La CPU observada por trial corresponde al hilo Python y excluye otros hilos nativos; los límites numéricos se presentan aparte. La inspección de journal y el cálculo de figuras se ejecutan en tareas de fondo.

Los estudios estándar pueden abrirse sin la interfaz propia:

```python
import optuna
from optuna.storages import JournalStorage
from optuna.storages.journal import JournalFileBackend, JournalFileOpenLock

path = "runs/phase2/<ejecucion>/optuna.journal"
store = JournalStorage(JournalFileBackend(path, lock_obj=JournalFileOpenLock(path)))
study = optuna.load_study(study_name="tfidf_logreg-outer-1", storage=store)
frame = study.trials_dataframe()
```

## Visualización e interpretación

La inspección conserva cada fold por separado. Incluye historial de mejor resultado completo, importancia fANOVA, coordenadas paralelas, slices, contorno cuando la geometría lo permite, distribución de objetivos y estabilidad de parámetros entre ganadores. No se agrupan trials de distintos folds como si fueran mediciones independientes de un mismo conjunto de validación.

fANOVA exige al menos diez trials completos y variación real del objetivo. Usa un bosque con semilla fija; su importancia depende de cobertura y capacidad de aproximar las respuestas. Se interpreta como diagnóstico exploratorio, sin causalidad o significancia demostrada, según las limitaciones de [Optuna FanovaImportanceEvaluator](https://optuna.readthedocs.io/en/v5.0.0/reference/generated/optuna.importance.FanovaImportanceEvaluator.html).

Los contornos requieren dos parámetros numéricos, suficientes puntos no colineales y un objetivo variable. Interpolan dentro del soporte observado; su escala de color se limita a los valores observados. Otros parámetros pueden variar entre puntos, por lo que la proyección no aísla efectos. Si faltan condiciones se muestra «No aplicable» con la razón.

Las coordenadas paralelas reescalan cada eje y explican los códigos de categorías y el uso de logaritmos. La distribución de valores de trials es adaptativa y no se interpreta como un intervalo de generalización. La estabilidad entre cinco ganadores es descriptiva y reconoce el solapamiento entre entrenamientos.

Cada tabla y figura tiene título, variables/unidades, leyenda pertinente, «Cómo leerlo», hallazgo calculado y limitaciones. Las figuras de demostración llevan etiqueta sintética, usan la paleta y dimensiones configuradas y se exportan a PNG de 600 DPI. Las guías y tablas también se conservan en la evidencia JSON.

## Configuraciones, transferencia y seguridad

Se pueden guardar y cargar configuraciones YAML/JSON validadas y versionadas. El importador limita el tamaño, utiliza `safe_load`, rechaza objetos ejecutables y campos desconocidos y vuelve a aplicar los límites del servidor. Una autorización cloud importada se restablece a falso.

La candidata contiene dataset, partición, ejecución Fase 2, resultado de origen, métrica y valor de selección, hiperparámetros, fecha y propietario. Para LLM conserva el prompt/hash y los modelos del artefacto de origen, y restablece presupuesto y autorización. La candidata fija los valores escogidos y se puede transferir a **Experimentación**, donde el mismo motor prepara y ejecuta una corrida explícita con ellos. Preparar, seleccionar o exportar una candidata no cambia la producción.

Se conservan JWT, RBAC y auditoría de FastAPI. Analista y Administrador pueden iniciar/gestionar según autoría y exportar configuraciones; Gestor consulta resultados; Auditor conserva su acceso a bitácora. Las publicaciones se retiran si no se confirma su auditoría. El estado `opt_*` y la transferencia `exp_*` se eliminan al salir de sesión. No se añaden credenciales a artefactos ni modelos deserializables al importador.

Los datos originales, taxonomía, fuentes de asignación, SLA, prompt productivo, componente cloud y configuración operativa permanecen conservados. Los nuevos parámetros LLM usan únicamente el adaptador experimental y sus ajustes por petición.

## Archivos modificados y justificación

```text
src/optimization/
  contracts.py        distribuciones, objetivos y compatibilidad de espacios
  settings.py         límites y valores iniciales externos
  studies.py          Optuna estándar persistente y recuperación de trials
  search.py           envoltura de configuración de los adaptadores de Fase 2
  analysis.py         aplicabilidad e importancia fANOVA
  workspace.py        configuración, inspección y candidata con autorización
src/training/
  runs.py             opciones avanzadas y huellas conservadas por corrida
  jobs.py             límites, plan vinculado, monitor concurrente y el mismo gestor
  nested.py           persistencia, poda y objetivo separado en el mismo 5×3
  metrics.py          reutilización de métricas de Fase 3 en internos/externos
  local.py            métricas adicionales del mismo ajuste
src/inference/experimental.py  métricas y consumo de las predicciones ya obtenidas
src/reports/optimization_presentation.py  tablas y figuras interpretadas
src/utils/config.py             política tipada de Optuna
src/utils/streamlit_runtime.py  recurso sobre el gestor compartido y limpieza privada
backend/analytics_audit.py      acciones acotadas de configuración y exportación
config/analytics.yaml           página, espacios y límites
pages/09_Optuna.py              interfaz avanzada y seguimiento
pages/04_Experimentacion.py     consumo explícito de candidatas versionadas
scripts/soc_optimize.py         corrida técnica local usando el motor existente
scripts/verify_optimization.py  evidencia reproducible con FastAPI/JWT aislados
tests/analytics/test_optimization.py
tests/analytics/test_experiment_cloud.py
docs/FASE_7.md
docs/CUMPLIMIENTO_FASES_0_A_7.md
README.md
```

No se añadieron dependencias. Las modificaciones previas de otras fases presentes en el directorio se conservaron. Las ejecuciones, journals, modelos y figuras quedan en `runs/`, excluido de Git.

## Ejecución y verificación

Desde la raíz del repositorio, en PowerShell:

```powershell
.venv/Scripts/python.exe -m scripts.analytics --check
.venv/Scripts/python.exe -m scripts.analytics
# Abrir http://127.0.0.1:8502 → Optimización Optuna.

.venv/Scripts/python.exe -m scripts.soc_optimize --trials 10
.venv/Scripts/python.exe -m scripts.verify_optimization
.venv/Scripts/python.exe -m pytest tests/analytics/test_optimization.py -q
.venv/Scripts/python.exe -m pytest -q
node --test tests/ui-and-workflow.test.cjs
.venv/Scripts/python.exe -m pip check
```

La regresión general que exporta PDF en este Windows utiliza las variables existentes `WEASYPRINT_DLL_DIRECTORIES=C:/Program Files/Tesseract-OCR` y `FONTCONFIG_FILE=<raíz>/.venv/soc-runtime/fonts.conf`.

La CLI técnica está restringida a modelos locales y fuente sintética. El verificador utiliza FastAPI real en proceso, JWT y SQLite aislado; sus solicitudes HTTP internas no salen a proveedores. Las búsquedas LLM no se ejecutaron en esta fase.

## Resultados verificables y aceptación

### Estudio técnico reproducible

Ejecución Fase 2: `20261111T164235045807Z_26495e268d11`. Fuente sintética existente, objetivo tipo de incidente, semilla 42, TPE secuencial, sin poda en esta demostración. La cancelación y los pruners se verificaron en pruebas separadas. La [evidencia completa](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/verification.json) contiene las huellas del dataset y de la partición, los conteos, las guías y las acciones auditadas.

| Variable del estudio sintético | Valor | Unidad o escala |
|---|---:|---|
| Folds externos / internos por externo | 5 / 3 | Folds |
| Trials por estudio interno / total | 10 / 50 | Trials |
| Completos / podados / fallidos | 50 / 0 / 0 | Trials |
| Duración observada del trabajo | 19,406 | s |
| Media externa de F1 macro | 0,933333 | Adimensional, de 0 a 1 |
| Desviación estándar muestral entre externos | 0,149071 | Adimensional |
| IC 95 % aproximado con corrección por solapamiento | [0,655658; 1,000000] | Adimensional |
| F1 macro de la candidata en Validación | 1,000000 | Adimensional, de 0 a 1 |
| Evaluaciones de Prueba / solicitudes cloud | 0 / 0 | Evaluaciones / solicitudes |

**Cómo leerlo.** Cada fila identifica una variable; la unidad y los nombres distinguen validación interna, medición externa y selección independiente. F1 mayor indica mejor clasificación en esta fuente sintética. **Hallazgo calculado.** Los 50 trials terminaron y la media de las cinco mediciones externas fue 0,933333; Prueba permaneció sin evaluar. **Limitaciones.** Son datos sintéticos, cinco externos con entrenamientos solapados y un intervalo aproximado, acotado al soporte de F1. El intervalo no acredita rendimiento real ni significancia. Los 19,406 s corresponden al trabajo experimental local y no al SLA de inferencia productiva. Tres verificaciones consecutivas conservaron las mismas huellas, estados y media externa.

Configuración guardada: `20261111T164234762450Z_b6f042369694`. Candidata: `20261111T164255272076Z_789caa8c86dd`. Sus archivos de demostración son [search.yaml](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/search.yaml) y [candidate.json](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/candidate.json). La configuración elegida en Validación usa `C=0.000697790775590612`, `max_df=0.5`, `max_features=10` y n-gramas de 1 a 2; el artefacto conserva los demás valores y la referencia de origen. La transferencia a Fase 2 se probó mediante su interfaz y gestor existentes.

Se exportaron siete figuras con interpretación y límites: [historial](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/history_plot.png), [importancia](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/importance_plot.png), [coordenadas paralelas](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/parallel_plot.png), [slice](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/slice_plot.png), [contorno](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/contour_plot.png), [distribución](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/distribution_plot.png) y [estabilidad entre folds](../runs/phase7/verification/20261111T164233Z_integration_deb584dd/stability.png). La comprobación independiente de metadatos PNG registró 599,9988 DPI, equivalente a 600 por cuantización del formato; las siete cumplen la tolerancia de 1 DPI.

### Pruebas ejecutadas

| Comprobación | Resultado verificable | Evidencia |
|---|---|---|
| Regresión Python completa | 284 pruebas y 102 subpruebas superadas; cero fallos, errores u omisiones | [JUnit final](../runs/phase7/verification/final-regression.xml) |
| Espacios, samplers y recuperación | Validación de tipos/rangos/pasos; TPE, Random y Grid; secuencia conservada al reabrir; orden de claves independiente | `tests/analytics/test_optimization.py` y regresión final |
| Cancelación, poda, tiempo y recursos | Historial conservado, presupuesto acumulado, externos no repetidos y paralelismo limitado | Misma suite; [verificación focalizada](../runs/phase7/verification/final-focused.xml) |
| Adaptador cloud existente | Reutilización de clientes, métricas, latencia almacenada, proveedor/modelo efectivo y consumo nuevo separados; proveedores simulados | [Cinco pruebas cloud](../runs/phase7/verification/cloud-final.xml) y regresión final |
| Streamlit y API aislada real | Navegación, recuperación, figuras, transferencia a Fase 2; JWT, RBAC y auditoría | [Pruebas de interfaz](../runs/phase7/verification/ui.xml) y regresión final |
| Interfaz con backend operacional | Analista autenticado; seis tablas, siete figuras y auditorías confirmadas al guardar configuración y candidata | [Comprobación operacional](../runs/phase7/verification/operational-ui.json) |
| Flujo y plazos determinísticos n8n | Dos pruebas Node superadas | `node --test tests/ui-and-workflow.test.cjs` |
| CLI con valores inválidos explícitos | `--trials 0` y `--timeout 0` rechazados con código 2 antes de iniciar trabajo | [Evidencia CLI](../runs/phase7/verification/cli-rejections.json) |
| Integridad, privacidad y archivos grandes | Siete originales y ambos documentos conservan sus huellas; cero coincidencias de secretos configurados en 243 archivos inspeccionados; ningún archivo Git superior a 5 MB; `runs/` ignorado | [Integridad](../runs/phase7/verification/integrity.json) |
| Dependencias y comprobación estática | `pip check`, compilación Python y `git diff --check` superados | [Aceptación consolidada](../runs/phase7/verification/acceptance.json) |

**Cómo leerlo.** Cada fila es una comprobación, con resultado y referencia reproducible; los conteos son pruebas, archivos o elementos de interfaz según se indica. Las suites focalizadas forman parte de la regresión y no se suman nuevamente al total. **Hallazgo de la verificación.** La regresión final no contiene fallos y la interfaz también funcionó con autenticación y auditoría del backend operacional. **Limitaciones.** Las pruebas de fallos cloud de esta fase usan dobles controlados; no constituyen una campaña nueva de llamadas facturadas. El escaneo de valores de credenciales comprueba esos valores concretos y no demuestra ausencia universal de información sensible.

La comprobación operacional preservó los siete reportes existentes y la huella de su contenido. FastAPI, PostgreSQL, Redis, LangFlow y n8n respondieron correctamente en esa captura. Streamlit y FastAPI también devolvieron HTTP 200 en la comprobación de cierre. Los servicios se mantuvieron en la interfaz local `127.0.0.1`; se verificó HTTP 200 desde n8n hacia `host.docker.internal:8000/health`. Esta evidencia puntual no resuelve las recaídas anteriores de PostgreSQL ni demuestra disponibilidad sostenida. Los diagnósticos activos de Groq/Gemini permanecieron pendientes en esta captura; no se enviaron reportes a proveedores externos.

### Criterios de aceptación de Fase 7

| Criterio | Estado técnico | Evidencia y alcance |
|---|---|---|
| Optuna integrado con Fase 2 | Cumple | Mismos gestor, partición, adaptadores y `run_nested`; transferencia de candidata probada |
| Espacios configurables y válidos | Cumple | Validaciones tipadas, compatibilidad y límites probados antes de ejecutar |
| Trials ejecutados y registrados | Cumple | 50 trials completos en journal estándar y resultados versionados |
| Estudios recuperables | Cumple | Reapertura, secuencia secuencial y conservación de interrupciones/cancelaciones probadas |
| Separación que evita fuga | Cumple en pruebas controladas | 5×3, ajuste por entrenamiento, búsqueda interna, selección con Validación y cero uso de Prueba |
| Visualizaciones interpretables | Cumple | Siete figuras, guías dinámicas, condiciones de aplicabilidad y PNG a 600 DPI verificados |
| Mejor configuración exportable | Cumple | Configuración y candidata versionadas, auditadas y consumibles en Experimentación |
| Sin alteración automática del clasificador productivo | Cumple | Huellas conservadas, reportes intactos y ausencia de despliegue; prueba sin solicitudes cloud |
| Pruebas automatizadas satisfactorias | Cumple | Regresión final, dos pruebas Node y comprobación operacional |

**Cómo leerlo.** Cada estado se refiere a la capacidad de Fase 7 y al alcance explícito de su evidencia, sin extrapolar a calidad predictiva real. **Hallazgo de aceptación.** Los nueve criterios técnicos tienen evidencia satisfactoria. **Limitaciones y pendientes.** No se ejecutó búsqueda real o cloud, no se acreditaron métricas reales ni costos facturados y no existe todavía un holdout humano final suficiente. La calibración probabilística de la confianza LLM, una campaña representativa de calidad/latencia y la disponibilidad sostenida mantienen sus pendientes generales. La producción conserva su política y solo una decisión posterior explícita podría promover una candidata.

La Fase 7 queda implementada y técnicamente aceptada en el alcance probado. La [matriz general de Fases 0–7](CUMPLIMIENTO_FASES_0_A_7.md) distingue los módulos implementados, sus pruebas y los requisitos empíricos o ampliaciones del SPEC que siguen pendientes.
