# Fase 3 · Evaluación estadística del SOC

La evaluación usa la configuración que ganó en Validación para cada familia de la Fase 2. Recupera el modelo local ajustado en Desarrollo o el prompt, el umbral y el grafo seleccionados en LangFlow. La corrida final queda vinculada al manifiesto y al sello de Prueba. [Datos del SOC](FASE_1.md) · [Experimentación](FASE_2.md).

## Supuestos del protocolo

- **SUPUESTO · Unidad independiente.** Un grupo reúne las representaciones del mismo incidente, campaña o fuente vinculada. El manifiesto de Fase 1 resuelve esos vínculos. La verificación de Prueba exige al menos cinco grupos por clase para publicar medidas reales. Los intervalos y contrastes exigen al menos 20 grupos totales, y los intervalos exigen cinco por clase. Los contrastes de aciertos exigen seis unidades con diferencia. Son pisos de reporte y el poder estadístico depende del diseño y la distribución observada. [Política versionada](../config/analytics.yaml).
- **SUPUESTO · Activos textuales.** La coincidencia es exacta después de normalizar Unicode NFKC, mayúsculas y espacios. La puntuación, los acentos y el orden se conservan. Una equivalencia entre sinónimos o alias de inventario requerirá un catálogo acordado y congelado con las referencias. El contrato actual de revisión independiente verifica el tipo de incidente. Severidad y activo quedan pendientes de referencias independientes por campo.
- **SUPUESTO · Diferencia operacional.** La comparación señala magnitudes de al menos cinco puntos porcentuales de exactitud. La señal es descriptiva y se interpreta junto con subclasificación crítica, cobertura, latencia y costo. El umbral de Holm del 5 % se presenta por separado. No se estima impacto sobre el SLA a partir de la exactitud.

## Ejecución y controles

1. En [Streamlit](http://127.0.0.1:8502), abre **Evaluación estadística** e inicia sesión con tu cuenta SOC. Administrador y Analista pueden verificar una selección, confirmar el sello y ejecutar. Gestor puede consultar métricas agregadas. Cada operación usa los permisos y la auditoría JWT de FastAPI. Los errores y el informe detallado requieren permiso de revisión y registran la inspección.
2. El evaluador coteja las huellas del manifiesto, la selección final, el modelo, el sello y el índice VCDB. Verifica dos revisores distintos para las referencias de tipo, separa casos y fuentes expuestos al piloto, y comprueba duplicados exactos, grupos, taxonomía y soporte. Se excluyen los solapamientos probables marcados en Fase 1. Estos controles dependen de la calidad de los vínculos y de la revisión humana de origen.
3. `evaluations.sqlite3` reserva de forma transaccional la cohorte y configuración antes de inferir. Volver a solicitar una evaluación completa recupera el registro existente. Una ejecución interrumpida o fallida conserva su reserva. Cambiar el nombre de la corrida o el orden de los casos conserva la identidad de evaluación. La comparación lee predicciones archivadas. La ejecución cloud comprueba el grafo aprobado, protege el texto y exige una autorización de presupuesto propia para la nueva cohorte.
4. Los JSON en `runs/phase3/` guardan métricas, decisiones por caso con claves hash, configuración, semilla, fecha UTC, versiones, hash del conjunto y huella del resultado. Las comparaciones tienen su propio ID y referencian las evaluaciones. La inspección lee fragmentos enmascarados y limitados desde el registro local, fuera de la exportación JSON. El directorio está excluido de Git y debe permanecer bajo los permisos locales del SOC.

Para verificar con la corrida técnica existente, ejecuta desde la raíz del repositorio.

```powershell
.\.venv\Scripts\python.exe -m scripts.analytics --check
.\.venv\Scripts\python.exe -m scripts.soc_evaluate --run 20261111T022740399892Z_1c4e674e0162
New-Item -ItemType Directory -Force runs/phase3/verification | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp=runs/phase3/verification/pytest-repeticion --junitxml=runs/phase3/verification/pytest-repeticion.xml
node.exe --test tests/ui-and-workflow.test.cjs
.\.venv\Scripts\python.exe -m pip check
```

Si la corrida de Fase 2 está en otra instalación, usa el ID de una corrida sintética completa de esa instalación. El comando técnico se limita a las dos familias locales y a los modelos presentes en esa corrida. La modalidad real se inicia desde Streamlit cuando el manifiesto, la configuración y los servicios estén disponibles. El flujo integrado histórico de `Test-SocDataset.ps1` se conserva para pruebas del Caso 06.

## Lectura estadística

- **Métricas nominales.** Exactitud, exactitud balanceada, precisión, recall, especificidad, F1, MCC y kappa de Cohen se calculan con los conteos de la matriz. En métricas nominales las derivaciones ocupan una columna de salida y cuentan como desaciertos. Precisión vale cero para clases sin predicciones. La normalización de la matriz se hace por clase de referencia. Los estratos requieren una anotación humana adicional verificable. [Referencia de métricas](https://scikit-learn.org/stable/modules/model_evaluation.html).
- **Severidad.** El orden de la taxonomía del SOC determina las distancias cuadráticas. Kappa cuadrático se calcula entre pares con valores ordinales, con cobertura informada. La tasa de subclasificación usa como numerador críticos predichos en una severidad inferior. La tasa de falsos negativos críticos cuenta también las derivaciones a revisión. Ambas usan como denominador todos los críticos de referencia. [Kappa ponderado](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.cohen_kappa_score.html).
- **Intervalos.** Bootstrap percentil del 95 % con 1.000 réplicas de grupos completos, estratificado si cada grupo pertenece a una clase. Si existen grupos con varias clases, se remuestrean conjuntamente. Las diferencias de métricas y AUC usan los mismos grupos en ambos modelos. Se omite el intervalo si falta soporte, quedan menos del 80 % de réplicas válidas o la distribución es degenerada. Los intervalos son nominales y condicionados a la cohorte y a los modelos congelados. [Field y Welsh, 2007](https://doi.org/10.1111/j.1467-9868.2007.00593.x).
- **Contrastes.** McNemar exacto usa aciertos discordantes cuando cada par constituye un grupo independiente. Si un grupo tiene varios registros, se usa el contraste exacto de signos de la diferencia de aciertos de cada grupo, excluyendo empates. El efecto se expresa como diferencia pareada en exactitud o en la métrica indicada, con IC de grupos si es estimable. Para AUC ROC se usa un contraste bootstrap centrado aproximado con puntuaciones válidas en ambos modelos, soporte y variación. Holm ajusta conjuntamente los contrastes de aciertos y de AUC elegibles de la cohorte y objetivo. [Binomial exacta en SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html) · [Holm, 1979](https://www.ime.usp.br/~abe/lista/pdf4R8xPVzCnX.pdf).
- **Curvas.** ROC y Precisión–Recall requieren positivos, negativos y scores finitos, variables y completos para cada clase. La regresión logística aporta `predict_proba` y SVM lineal aporta márgenes. Se informan AUC ROC, área PR trapezoidal y precisión promedio (AP). Para LangFlow la confianza corresponde a la etiqueta elegida y se usa en la decisión de revisión. Las curvas muestran «No aplicable» en esa modalidad. [ROC multiclase](https://scikit-learn.org/stable/auto_examples/model_selection/plot_roc.html) · [Precisión promedio](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html).
- **Operación.** `soc_provider` informa el proveedor que respondió. El modelo se identifica por ese proveedor y su configuración en el grafo verificado. Una respuesta efectiva de Gemini cuenta como conmutación observada. Se muestran por separado revisión humana, errores de formato, taxonomía y fallos de la llamada a LangFlow. p50 y p95 de LangFlow incluyen la orquestación y los reintentos. La versión actual del grafo no informa el detalle de intentos internos, la latencia del proveedor ni facturación. Los campos correspondientes se conservan ausentes. `origen="fallback"` de una revisión segura carece de valor como evidencia de proveedor.

## Comparación técnica sobre los modelos de Fase 2

| Modelo final | Casos (n) | Grupos (n) | Exactitud | F1 macro | Cobertura | AUC ROC y AP por clase |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| TF-IDF con regresión logística | 24 | 12 | 1,000 | 1,000 | 1,000 | 1,000 en las cuatro clases |
| TF-IDF con SVM lineal | 24 | 12 | 1,000 | 1,000 | 1,000 | 1,000 en las cuatro clases |

**Cómo leerlo.** Los resultados usan los mismos 24 casos reservados de la prueba técnica. Las métricas van de 0 a 1. **Hallazgo clave.** Ambos modelos acertaron los 24 casos. La diferencia observada de exactitud fue 0 pp. **Limitaciones.** Las plantillas sintéticas son deliberadamente separables. Los 12 grupos y la ausencia de discordancias impidieron contrastar diferencias. Los puntajes describen únicamente la prueba técnica. [Regresión logística](../runs/phase3/20261111T025703212729Z_ed424869a272/result.json) · [SVM lineal](../runs/phase3/20261111T025703596326Z_9c1c24019cab/result.json) · [Comparación pareada](../runs/phase3/20261111T025703688216Z_fe4db31fc340/comparison.json).

Las matrices absoluta y normalizada y las curvas ROC y PR de phishing se exportaron a 600 DPI. El registro vincula los archivos, sus huellas, las unidades, «Cómo leerlo», el hallazgo y sus limitaciones. [Matriz absoluta](../runs/phase3/verification/confusion-sintetica.png) · [Matriz normalizada](../runs/phase3/verification/confusion-normalizada-sintetica.png) · [ROC](../runs/phase3/verification/roc-sintetica.png) · [Precisión–Recall](../runs/phase3/verification/precision-recall-sintetica.png) · [Evidencia de la corrida y figuras](../runs/phase3/verification/technical-evidence.json).

### Verificación controlada de severidad

| Serie fabricada | Críticos (n) | Subclasificados (n) | Derivados (n) | Tasa FN críticos | IC 95 % de la tasa | Kappa cuadrático |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 16 | 4 | 0 | 25,0 % | [6,3 %, 43,8 %] | 0,700 |
| B | 16 | 5 | 1 | 37,5 % | [12,5 %, 62,5 %] | 0,600 |

**Cómo leerlo.** Cada serie usa las mismas 64 observaciones fabricadas en 32 grupos. Los casos críticos son el denominador de la tasa FN. **Hallazgo clave.** La serie B produjo seis falsos negativos críticos, incluido un caso derivado. La diferencia de exactitud A − B fue de 12,5 pp, con IC 95 % [−1,6, 25,0] pp y p de Holm 0,152 para el contraste de signos. **Limitaciones.** Las observaciones se fabricaron con desaciertos deliberados para verificar fórmulas, cobertura e inferencia pareada. El alcance es metodológico. [Resultados controlados de severidad](../runs/phase3/verification/fixture-severidad.json).

El manifiesto real disponible registra ocho referencias de tipo y ninguna de severidad o activo. Hay 160 decisiones de preparación pendientes y falta el archivo sellado revisado. La comprobación del grafo activo fue de solo lectura. Groq sigue configurado con `openai/gpt-oss-20b` y Gemini con `gemini-3-flash-preview`. Se enviaron cero inferencias experimentales a los proveedores. [Disponibilidad de datos](../runs/phase3/verification/technical-evidence.json) · [Grafo activo](../runs/phase3/verification/langflow-readonly.json).

## Archivos de Fase 3

- `src/evaluation/` contiene contratos, verificación del sello y la selección, predicción, métricas, contrastes, registro y autorización.
- `pages/05_Evaluacion.py` y `src/reports/evaluation_presentation.py` muestran resultados, explicaciones, figuras y descargas. `pages/00_Inicio.py` ofrece el acceso.
- `config/analytics.yaml`, `src/utils/config.py` y `src/utils/streamlit_runtime.py` registran la página, la política y las tareas de fondo. Las dependencias fijadas siguen en `requirements.txt` y `requirements.lock.txt`.
- `src/inference/experimental.py` reutiliza el adaptador LangFlow y recoge procedencia y telemetría explícita. `backend/analytics_audit.py` registra las operaciones con el RBAC existente.
- `scripts/soc_evaluate.py` reproduce el recorrido local. `tests/analytics/test_evaluation_*.py`, `test_experiment_cloud.py` y `test_backend_integration.py` cubren fórmulas, sello, una sola inferencia, permisos y UI.

## Aceptación y límites de la verificación

La batería general aprobó **213 pruebas y 102 subpruebas**. La batería focalizada posterior sobre la versión final aprobó **17 pruebas** e incluyó la interfaz, el sello, los resultados pareados y FastAPI con una base aislada. Se conservaron dos advertencias, una de deprecación de Starlette/HTTPX y otra de scikit-learn provocada por la clase de salida adicional para revisión. Las dos pruebas de n8n pasaron y `pip check` confirmó dependencias coherentes. [JUnit general](../runs/phase3/verification/pytest-complete.xml) · [JUnit focalizado](../runs/phase3/verification/final-focused.xml) · [Flujo n8n](../runs/phase3/verification/workflow.txt) · [Dependencias](../runs/phase3/verification/pip-check.txt).

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Métricas y matrices de confusión | Cumple en pruebas controladas | Coinciden con scikit-learn, incluida la severidad ordinal y la matriz con derivaciones |
| Curvas según aplicabilidad | Cumple | Regresión logística y SVM produjeron ROC y PR. Casos sin scores completos o variables se omitieron. LangFlow muestra «No aplicable» |
| Contrastes con sus supuestos | Cumple en pruebas controladas | McNemar con grupos unitarios, signos con grupos repetidos, bootstrap pareado, Holm y rechazo de muestras insuficientes o desalineadas |
| Uso único de Prueba | Cumple en pruebas controladas | Dos solicitudes concurrentes produjeron una reserva. Una corrida completada recuperó los mismos resultados y la fallida conservó su reserva |
| Evidencia de desempeño real | Pendiente | Falta el conjunto revisado. Existen ocho referencias candidatas de tipo, cero de severidad/activo y cero corridas finales reales |
| Proveedor efectivo y fallos | Cumple en HTTP interceptado. Validación real pendiente | Se verificaron Groq, Gemini, revisión, errores de formato, taxonomía, fallos técnicos y respuestas sin proveedor. La lectura real verificó el grafo, la configuración y sus referencias de credenciales |
| Interfaz y permisos | Cumple en pruebas controladas. Integración operativa pendiente | Confirmación, ejecución en segundo plano, comparación, descarga a 600 DPI y acceso protegido. FastAPI validó JWT, RBAC y auditoría en base aislada |

**Cómo leerlo.** Cada fila indica el alcance de la comprobación. Los tamaños de muestra y solicitudes se expresan en conteos. **Hallazgo clave.** Se verificaron dos configuraciones finales con 24 observaciones comunes y una reserva por configuración. **Limitaciones.** El login y la auditoría sobre PostgreSQL operativo quedan pendientes. Streamlit respondió HTTP 200 tras recargar el proceso del puerto 8502. La salud de FastAPI siguió degradada por PostgreSQL. Los eventos nuevos de auditoría quedan disponibles en FastAPI al cargar esta versión con la base operativa. [Salud del entorno](../runs/phase3/verification/services.json).

**Resultado de aceptación.** Fase 3 implementada y aceptada para verificación controlada. Quedan pendientes la evaluación real con referencias humanas y el acceso integrado con el PostgreSQL operativo. El escaneo de las fuentes y los artefactos de esta fase produjo cero coincidencias con los valores de credenciales configuradas. [Verificación de integridad](../runs/phase3/verification/integrity.json).
