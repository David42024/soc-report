# Fase 2 · Entrenamiento y experimentación del SOC

El módulo añade una página a Streamlit y reutiliza los manifiestos de Datos del SOC, la autenticación y bitácora de FastAPI, y el clasificador operativo LangFlow. El protocolo aplica al texto del Caso 06 las cuotas 70/15/15 y la validación anidada 5×3 del Promptuario.

## Supuestos y decisiones

- **SUPUESTO.** Cada objetivo se ejecuta por separado. Tipo y severidad conservan la taxonomía del backend. Activo usa coincidencia de la etiqueta revisada del manifiesto. La disponibilidad se verifica por objetivo.
- **SUPUESTO.** Las cuotas enteras por clase se calculan por mayor residuo. Se mantienen completos los grupos de incidentes, campañas y vínculos del manifiesto. Los grupos con posible solapamiento con la reserva se excluyen de Desarrollo y Validación hasta revisar su relación.
- **SUPUESTO.** La reserva independiente determina el 15 % de Prueba en datos reales. Si sus conteos por clase y los candidatos abiertos resultan incompatibles con las cuotas, la corrida se bloquea. El sello contiene huella, marca de archivo y agregados. El trabajador de Fase 2 recibe Desarrollo y Validación con texto protegido, junto con los metadatos del sello.
- **SUPUESTO.** El 15 % de Validación selecciona, por modelo, entre las configuraciones ganadoras de los cinco folds. Se vuelve a ajustar la configuración académica elegida exclusivamente en Desarrollo para guardar el artefacto. La métrica de Validación es de selección. La evaluación final corresponde a la Fase 3.
- **SUPUESTO.** Una corrida cloud ejecuta inferencia sin ejemplos de entrenamiento en el prompt. Usa las particiones para escoger configuraciones y reserva un máximo por solicitud que debe cubrir los intentos de respaldo. La instalación mantiene los límites monetarios en cero hasta que exista un presupuesto habilitado y autorizado.

## Uso

Desde la raíz del proyecto, activa FastAPI con su lanzador habitual y ejecuta en otra terminal el comando de Streamlit. Usa una cuenta de Analista o Administrador para iniciar una corrida. Gestor puede consultar resultados. [Abrir Streamlit](http://127.0.0.1:8502).

~~~powershell
.\.venv\Scripts\python.exe -m scripts.analytics --check
.\.venv\Scripts\python.exe -m scripts.analytics
~~~

En **Experimentación → Modelos académicos → Prueba técnica sintética**, selecciona los modelos, prepara la partición y pulsa **Iniciar ejecución**. La bitácora muestra el fold, el trial, la métrica y la duración. **Solicitar cancelación** se aplica en el siguiente límite seguro entre operaciones. **Reanudar** conserva los folds externos terminados en corridas académicas. Si la interrupción ocurre durante la medición de un fold externo, se requiere una corrida nueva para mantener una sola medición por fold. Las corridas cloud que se interrumpen requieren una autorización nueva.

Para verificar el mecanismo sin servidor ni proveedores, ejecuta el script local. Las entradas son sintéticas y están identificadas como prueba técnica.

~~~powershell
.\.venv\Scripts\python.exe -m scripts.soc_experiment --trials 5 --seed 42
~~~

Para consultar los datos reales, elige **Referencias humanas** y la versión del manifiesto. Los manifiestos históricos siguen disponibles. Publicar una versión nueva en **Datos del SOC** registra las etiquetas verificadas y vincula la copia protegida de candidatos por SHA-256. Si la reserva cambia de ruta, fecha de modificación o tamaño, la preparación exige volver a validar su manifiesto.

## Modelos, búsqueda y métricas

Cada fold externo reserva su evaluación de Desarrollo. Optuna busca la configuración en tres folds estratificados por grupo dentro del entrenamiento externo. El pipeline TF-IDF se ajusta de nuevo en cada subconjunto de entrenamiento. La configuración ganadora se vuelve a ajustar sobre todo el entrenamiento del fold externo y se mide una vez en su validación externa. Se guardan las huellas, soportes por clase, tiempos, resultado y configuración de cada trial y fold.

La configuración inicial usa n-gramas de 1 a 2, `min_df=1` para conservar términos raros, `max_df=1`, 10.000 características, TF sublineal, IDF suavizado y ponderación balanceada. Para regresión logística se ofrece LBFGS o SAGA. SVM lineal usa `dual="auto"`. Optuna busca `C` en escala logarítmica alrededor de 1 y el máximo de n-gramas dentro del intervalo seleccionado. El YAML fija semilla 42, cinco trials por fold, un trabajo concurrente y un hilo numérico por defecto. [Configuración](../config/analytics.yaml).

El objetivo es F1 macro con las clases de referencia presentes. La comparación resume las cinco mediciones externas con media, desviación estándar muestral y un intervalo t aproximado del 95 %, ajustado por la razón media entre validación y entrenamiento para reflejar el solapamiento. Cinco observaciones y grupos dependientes limitan la precisión del intervalo. Las figuras de búsqueda muestran el orden de los trials. Los estimadores usados aquí carecen de series de métricas por época. [Nadeau y Bengio, *Inference for the Generalization Error*](https://proceedings.neurips.cc/paper_files/paper/1999/file/7d12b66d3df6af8d429c1a357d8b9e1a-Paper.pdf).

### Inferencia experimental con LangFlow

El flujo existente usa Groq `openai/gpt-oss-20b` y activa Gemini `gemini-3-flash-preview` bajo su política técnica. El selector ofrece el prompt vigente y una variante versionada que prioriza evidencia explícita. La variante usa `tweaks` en la petición. El componente instalado fija el esfuerzo de razonamiento y la salida a 1.536 tokens por intento. Optuna compara prompts y umbrales de revisión registrados. Una salida inválida, una posible inyección o un puntaje inferior al umbral se contabilizan como casos para revisión. Gemini se atribuye por metadatos del flujo, con independencia del resultado de revisión. [Ejecución de flujos LangFlow](https://docs.langflow.org/api-flows-run).

El plan calcula el máximo de llamadas antes de autorizar el trabajo, con hasta tres intentos de proveedor por ejecución de LangFlow. Los topes del servidor se configuran en `SOC_EXPERIMENT_MAX_COST_PER_FLOW_USD` y `SOC_EXPERIMENT_MAX_RUN_BUDGET_USD`. El primero debe representar un límite conservador según la tarifa del proveedor, el tamaño de entrada, la salida máxima y los intentos. El operador confirma el presupuesto de la corrida en Streamlit. Antes de cada llamada se comprueban el JWT, el grafo y la reserva. Se registran solicitudes, proveedor observado, tiempos y techo de costo. El componente carece de telemetría de costo facturado. Las llamadas están deshabilitadas con los valores de entrega.

## Archivos y evidencias

- `src/training/settings.py`, `dataset.py`, `partition.py`, `demo.py`, `local.py`, `metrics.py`, `nested.py`, `runs.py` y `jobs.py` implementan preparación, entrenamiento, registro y trabajos.
- `src/inference/experimental.py` y `src/utils/langflow.py` reutilizan el flujo vigente con el contrato de ejecución experimental.
- `src/data/models.py`, `sources.py`, `manifest.py` y `workspace.py` vinculan las etiquetas y la copia protegida de Desarrollo/Validación al manifiesto. `backend/analytics_audit.py` amplía la bitácora JWT para consulta, inicio, cancelación y reanudación.
- `pages/04_Experimentacion.py`, `pages/00_Inicio.py`, `src/utils/streamlit_runtime.py` y `src/reports/training_presentation.py` integran controles, seguimiento, tablas y exportación PNG a 600 DPI.
- `config/analytics.yaml`, `config/prompts/soc_evidencia_explicita_v1.txt`, `src/utils/config.py` y `.env.example` versionan configuración y límites. `scripts/soc_experiment.py` reproduce la prueba técnica. `tests/analytics/test_experiment_*.py`, `test_data_page.py` y `conftest.py` incluyen pruebas de protocolo, presupuesto, transporte y página.

Cada directorio en `runs/phase2/` guarda `run.json`, `partition.json`, `state.json`, `events.jsonl`, `checkpoint.json` y `result.json` al completar. El resultado publicable incluye configuración, versiones, huellas, métricas y sellado. `work.json` y los modelos son artefactos locales de trabajo. Se conservan bajo los permisos de la carpeta de ejecuciones y quedan excluidos de Git. El informe descargable evita textos e identidades.

~~~powershell
New-Item -ItemType Directory -Force runs/phase2/verification | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --junitxml=runs/phase2/verification/repeticion.xml
node --test tests/ui-and-workflow.test.cjs
.\.venv\Scripts\python.exe -m pip check
~~~

## Evidencia técnica de ejecución

La corrida `20261111T022740399892Z_1c4e674e0162` ejecutó ambos modelos, con semilla 42 y cinco trials por fold externo. Tiene 160 registros sintéticos, cuatro clases y dos representaciones relacionadas por grupo. Cada clase se distribuyó en 28/6/6 registros, equivalentes a 70/15/15. [Resultado completo](../runs/phase2/20261111T022740399892Z_1c4e674e0162/result.json), [resumen verificable](../runs/phase2/verification/technical-run.json).

| Modelo | Fold 1 | Fold 2 | Fold 3 | Fold 4 | Fold 5 | Media | DE muestral | Intervalo aproximado 95 % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| TF-IDF y regresión logística | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 0,000 | [1,000, 1,000] |
| TF-IDF y SVM lineal | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 | 0,000 | [1,000, 1,000] |

**Cómo leerlo.** Cada celda de fold contiene el F1 macro de una única validación externa. La escala va de 0 a 1. **Hallazgo de la corrida.** Ambos modelos obtuvieron F1 de 1 en los cinco folds y en la selección con Validación. Se registraron 150 mediciones internas, 10 externas, cero llamadas a LangFlow y cero evaluaciones de Prueba. **Limitaciones.** Las plantillas sintéticas son deliberadamente separables y comparten vocabulario. El alcance de esta corrida es comprobar el procedimiento. La variabilidad y el intervalo degenerado corresponden a estas plantillas. [Figura exportada](../runs/phase2/verification/f1-externo-sintetico.png).

La reconciliación del manifiesto histórico con el piloto original verificó ocho referencias de tipo, dos por cada una de cuatro clases y dos grupos por clase. Severidad y activo tienen cero candidatos. La reserva conserva 160 decisiones pendientes y el archivo `holdout-reviewed.json` sigue ausente. La ejecución supervisada real permanece impedida por esos tamaños y por el sello pendiente. [Estado real de los datos](../runs/phase2/verification/real-readiness.json).

La comprobación de lectura de LangFlow confirmó la equivalencia del grafo persistido y el export, sus modelos y referencias de credenciales. El código instalado aplicó el ajuste del prompt sobre una copia local sin ejecutar nodos. Las pruebas cloud usan transporte HTTP interceptado. Los topes entregados son cero USD y las verificaciones de esta fase enviaron cero inferencias experimentales a proveedores. [Comprobación del grafo](../runs/phase2/verification/langflow-readonly.json).

## Integración operacional

Streamlit se recargó y respondió HTTP 200. FastAPI se recargó para habilitar los eventos nuevos. En una comprobación de salud los cinco servicios respondieron correctamente. El login operativo volvió a devolver HTTP 503 y continuó así en los seis intentos acotados posteriores a reiniciar el contenedor PostgreSQL del SOC. Se verificaron el contenedor y su carpeta de datos dentro del proyecto antes de ese reinicio. La aceptación del acceso con JWT en la base operativa queda pendiente. [Streamlit](../runs/phase2/verification/streamlit-health.json), [salud observada](../runs/phase2/verification/services.json), [incidencia operacional](../runs/phase2/verification/operational-verification.json).

Se cotejaron 16 archivos con la huella observada al inicio de la verificación. Incluyen originales, variables operativas, privacidad, prompt, componente, grafo y reglas de asignación/SLA. Las dos pruebas de n8n pasaron y `pip check` confirmó dependencias coherentes. [Integridad](../runs/phase2/verification/integrity.json), [workflow](../runs/phase2/verification/workflow.txt).

El monitor se verificó con cancelación y reanudación del trabajo mientras se navegaba entre modalidades. La comprobación detectó y permitió corregir una discrepancia de metadatos de paquetes entre hilos y un bloqueo de reemplazo de archivos en Windows. El gestor captura las versiones al iniciar y las conserva durante su vida. El código y la política se cotejan por corrida y reanudación. El registro sincroniza lecturas y escrituras y reintenta los bloqueos temporales de publicación. Los smoke tests mantienen estable el reloj de renovación de sus sesiones simuladas, y el vencimiento y RBAC se verifican en sus pruebas específicas. [Pruebas de recuperación del monitor](../runs/phase2/verification/runner-recovery.xml).

## Pruebas finales y aceptación

La batería final aprobó **200 pruebas y 102 subpruebas** en 385,00 segundos, con cero fallos, errores u omisiones. Incluye el recorrido completo con JWT emitido por el backend y auditoría comprobada en una base temporal, la cancelación y reanudación desde Streamlit, los controles de Prueba y la comprobación de los documentos usados en cada ajuste TF-IDF. Se conserva una advertencia de deprecación de Starlette/HTTPX. [JUnit final](../runs/phase2/verification/pytest-complete.xml).

El cierre verificó también la huella del SPEC, 16 archivos protegidos y las huellas de la corrida. El escaneo de 32 fuentes de esta fase contra las credenciales configuradas produjo cero coincidencias. [Resumen estructurado de verificación](../runs/phase2/verification/verification.json).

Las ejecuciones previas detectaron las correcciones del monitor y el vencimiento del tiempo de sesión de los smoke tests. Sus informes se conservan como historial local. El informe final citado corresponde al código corregido.

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Particiones reproducibles por grupos | Cumple en prueba controlada | Cuotas 28/6/6 por clase, pertenencias y huellas idénticas para la misma semilla. Los grupos permanecen disjuntos |
| Estructura anidada 5×3 | Cumple | Cinco folds externos, tres internos por fold y una medición externa por fold y modelo. Se rechazan planes incompletos |
| Optuna usa solo los datos permitidos | Cumple | Las pruebas interceptan cada ajuste TF-IDF y comprueban sus documentos contra el subconjunto de entrenamiento. La selección final usa Validación |
| Prueba sellada | Cumple | Cero evaluaciones de Prueba, copia de trabajo con Desarrollo/Validación y sello agregado, prueba de rechazo de cambios en la marca del archivo reservado |
| Modelos entrenables en una prueba técnica | Cumple | Ambas familias completas, 150 mediciones internas y 10 externas. Artefactos locales con hash |
| Groq y Gemini como inferencia | Cumple en el alcance comprobado | Uso de LangFlow, grafo cotejado y pruebas HTTP interceptadas. La corrida con proveedores reales requiere datos y presupuesto autorizados |
| Configuraciones, resultados y limitaciones registrados | Cumple | Semilla, política, software, hashes, trial, fold, estados, errores, puntos de control e informe descargable |
| Consumo sujeto a presupuesto | Cumple | Techos en cero y prueba de rechazo previo a cualquier HTTP sin autorización. Las verificaciones enviaron cero inferencias experimentales |
| Streamlit operativo durante la corrida | Cumple en base aislada y prueba técnica | Navegación entre modalidades, monitor en segundo plano y cancelación/reanudación comprobados. Servidor local HTTP 200 |
| Acceso a la base operativa con JWT | Pendiente | Login HTTP 503 tras recuperación recurrente de PostgreSQL, incluido el intento posterior al reinicio del contenedor |
| Experimentos supervisados sobre datos reales | Pendiente por datos | Ocho referencias de tipo en grupos insuficientes, cero referencias de severidad/activo y 160 decisiones reservadas pendientes |

**Cómo leerlo.** Cumple se refiere a la evidencia y el ámbito de cada fila. Los conteos de pruebas, folds, registros y solicitudes son unidades discretas. **Hallazgo de la verificación.** El protocolo técnico está ejecutado para ambas familias y Prueba permanece sellada. **Limitaciones.** La ejecución con datos reales depende de referencias y sello suficientes. El acceso operativo depende de recuperar la base PostgreSQL. La última comprobación informó FastAPI, Redis, LangFlow y n8n en estado OK y PostgreSQL en error, con React y Streamlit en HTTP 200. [Estado final del entorno](../runs/phase2/verification/services-final.json).

**Resultado de aceptación.** La Fase 2 queda implementada y aprobada en sus pruebas técnicas controladas. La verificación con la base operativa y la experimentación supervisada real conservan los pendientes documentados. La autorización de evaluación final pertenece a la Fase 3.
