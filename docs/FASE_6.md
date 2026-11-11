# Fase 6 · Inferencia individual y robustez estadística

## Alcance y fuentes

Se incorpora una página de inferencia individual a Streamlit. La clasificación nueva utiliza `POST /api/reportes`, el webhook de FastAPI que ya procesa el formulario React. La consulta de reportes existentes utiliza `GET /api/reportes/{id}/explicabilidad` y conserva la predicción guardada. LangFlow continúa como clasificador puro, PostgreSQL conserva el reporte y n8n asigna, calcula los SLA y notifica. FastAPI valida las reglas recibidas de n8n.

Se leyeron completos el SPEC definitivo v2.1 y el Promptuario, además del código, documentación y resultados de las fases 0–5. Huellas documentales SHA-256:

- SPEC `a5868e2b7070d45f5b74cf50a8aea8d0d9a5657c45e3a85be52b3726e0f8fbfb`.
- Promptuario `438f694494a4548dbb1f6817716fb5922112155ab1fa3606185e097251c27859`.

Se conserva el contrato de respuesta del clasificador con cuatro campos, `tipo`, `severidad`, `activo_afectado` y `confianza`. La telemetría y la evidencia se registran separadamente en `session_metadata` y en el JSON de la tabla existente `report_ai_inputs`. Esta fase no requiere una migración SQL, un dataset nuevo ni una selección experimental adicional.

## Supuestos declarados

1. La inferencia académica individual requiere el permiso existente `review`, correspondiente a Analista y Administrador, y una sesión JWT. El formulario operacional público mantiene su contrato. Los indicadores agregados requieren el permiso existente `read` y JWT.
2. La justificación es evidencia extractiva verificada mediante los criterios de Fase 4. No se solicita una cadena de pensamiento ni se cambia el prompt operativo para producir explicaciones adicionales.
3. El holdout humano independiente sigue pendiente. Las revisiones operativas retrospectivas, los ocho candidatos del piloto y los resultados sintéticos de fases anteriores no acreditan exactitud real.
4. El score escalar del LLM se interpreta como puntaje operacional. Calibración, Brier multiclase, predicción conforme e intervalos individuales permanecen sin aplicación por falta de probabilidades apropiadas y conjunto independiente de calibración.
5. La cobertura léxica configurada se presenta como señal heurística de posible entrada fuera del dominio. Carece de tasas de error validadas y no cambia clasificación, revisión ni SLA.
6. Un recibo no confirmado mantiene el UUID idempotente. La interfaz permite consultar ese UUID y no repite automáticamente un POST de clasificación.

## Archivos y justificación

```text
backend/
  report_input.py          validación adicional de controles Unicode
  classifier.py            validación, revisión y captura de trazas protegidas
  inference.py             indicadores agregados bajo JWT y auditoría
  explainability.py        tiempos, eventos y contraste de SLA en la vista existente
  routing.py               función pura compartida para reglas ya vigentes
  main.py                  registro del endpoint y reutilización de esa función
  analytics_audit.py       acciones de consulta, autorización y registro
config/analytics.yaml     página, límites y objetivo p95 configurables
integrations/langflow/
  cloud_classifier_model.py  intentos acotados, versión informada y rechazo de política
  cybersecurity_classifier.json  export del mismo grafo actualizado
pages/08_Inferencia.py     controles de interfaz y trabajos asíncronos
src/inference/
  settings.py             esquema de configuración pública
  services.py             adaptador al webhook y a indicadores de FastAPI
  telemetry.py            contrato de trazas y percentiles descriptivos
  robustness.py           cobertura léxica y aplicabilidad estadística
  workspace.py            servicios autorizados y artefactos protegidos
  experimental.py         compatibilidad del consumidor experimental con las trazas
src/evaluation/predictors.py  modelo observado en lugar de inferirlo por proveedor
src/reports/inference_presentation.py  tablas, interpretaciones y figura de latencias
src/utils/config.py       integración de configuración tipada
src/utils/streamlit_runtime.py  recurso sin tokens y limpieza del estado privado
scripts/verify_inference.py   comprobación optativa con el caso autorizado
tests/analytics/test_inference_workflow.py
tests/analytics/test_inference_statistics.py
tests/analytics/test_experiment_cloud.py
tests/test_cloud_model.py
tests/test_privacy.py
docs/FASE_6.md
README.md
```

Las modificaciones previas de otras fases presentes en el directorio de trabajo se conservan. No se incorporan bibliotecas de visión, un clasificador nuevo ni cambios a los originales de datasets. `runs/` permanece excluido de Git.

## Comportamiento y privacidad

La preparación valida los límites reales de `ReportInput`, campos adicionales, caracteres de control, sustitutos Unicode y controles bidireccionales. Permite puntuación técnica, Unicode normal, saltos de línea y tabulaciones. Detecta los patrones de inyección existentes; esos reportes se guardan para revisión sin llamar a los proveedores. La detección de inyección tiene alcance heurístico y se complementa con delimitadores escapados y validación estricta del resultado.

El filtro existente minimiza datos personales y secretos antes de LangFlow y vuelve a comprobarlos antes del egreso cloud. Ambos proveedores reciben la misma copia protegida. Se conservan CVE, puertos y evidencia técnica conforme a la política existente. El texto original continúa en el almacenamiento operacional protegido. La página exporta solo evidencia protegida; la consulta explícita del original se mantiene en el módulo autorizado de explicabilidad y genera auditoría.

Un resultado correcto de Groq con confianza menor que el umbral efectivo se deriva a revisión humana y conserva a Groq como proveedor. Una taxonomía inválida o JSON de clasificación inválido produce revisión sin enviar automáticamente la misma decisión a Gemini. Los fallos técnicos de transporte o de la envoltura del proveedor conservan el failover existente. La secuencia está limitada a un intento Groq y hasta dos Gemini; el segundo intento Gemini exige fallo transitorio elegible.

Los rechazos explícitos de política terminan la conmutación. Los campos observables de rechazo y formato estructurado están documentados por [Groq](https://console.groq.com/docs/api-reference), [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs) y [Gemini generateContent](https://ai.google.dev/api/generate-content?hl=en).

Cuando ambos proveedores fallan, el componente entrega el JSON protector de cuatro campos y una traza con motivo de revisión. FastAPI conserva `origen="fallback"`, tipo `otro`, severidad `media` y confianza cero. El proveedor que respondió a la clasificación queda ausente. La traza acredita los intentos reales de Gemini aunque ninguno haya producido una clasificación válida. Los errores contienen estados, códigos HTTP y duraciones acotadas; no contienen cuerpos upstream, claves ni mensajes de excepción externos.

La versión del modelo se toma de `model` en Groq y `modelVersion` en Gemini cuando están presentes. `model_scope="response"` identifica ese dato informado; `requested` identifica solo el modelo solicitado. Un identificador devuelto puede ser un alias mutable y no acredita una revisión inmutable de pesos. Los reportes históricos sin metadatos conservan el estado desconocido.

La asignación comparte una función pura con el validador previo de FastAPI y no cambia su política. Los plazos permanecen en 15/240, 60/480, 240/1440 y 480/2880 minutos para crítica, alta, media y baja. Ambos vencimientos parten de la recepción. La vista contrasta equipo y vencimientos con la versión efectiva de reglas y muestra los actores registrados en bitácora.

Los artefactos se publican en `runs/phase6/<versión>/result.json` con hash canónico, fecha UTC, semilla, versiones de software, configuración, entrada minimizada, clasificación, corrección separada, prompt SHA-256, proveedor/modelo, trazas, citas y limitaciones. La publicación requiere identidad vigente y auditoría de finalización. Ante fallo de esa auditoría se retira el archivo publicado. Ningún token se guarda en el recurso compartido de Streamlit; la salida de sesión elimina el estado `inf_*`.

## Metodología estadística

Los p50 y p95 se calculan con cuantiles muestrales de NumPy, con denominador propio por serie. La latencia de clasificación parte de recepción; la del flujo finaliza en notificación. Cada intento de proveedor se mide por separado, incluyendo intentos fallidos. Las métricas agregadas excluyen los DEMO y están acotadas a los últimos registros configurados. Se informa truncamiento, ausencia de trazas y tamaño observado.

La comparación con p95 < 10 s es descriptiva. El mínimo configurable de observaciones no demuestra por sí solo independencia ni representatividad. El control conserva pendiente la acreditación del objetivo del SPEC hasta disponer de una campaña adecuada.

La concordancia modal de repeticiones utiliza entrada protegida, proveedor, modelo y prompt iguales, comparando tipo, severidad y activo. Las decisiones de umbral quedan fuera de esa comparación. Un identificador informado también puede ser un alias mutable. Esta observación no estima estabilidad ante paráfrasis ni constituye una validación causal.

Los errores de infravaloración crítica se calculan solo cuando existe una revisión humana crítica; las salidas protectoras se cuentan por separado. Se muestran denominador y estado pendiente si faltan referencias. Estas revisiones retrospectivas no sustituyen el holdout independiente.

El módulo puede mostrar métricas e IC de Fase 3 ya publicados si la referencia es humana independiente y coinciden proveedor, modelo, prompt y umbral. No ajusta umbrales ni lee nuevamente el conjunto de Prueba. Los resultados sintéticos quedan excluidos como evidencia real. La falta actual de ese holdout mantiene las métricas reales y los IC agregados pertinentes pendientes.

Toda tabla y figura usa título, variables/unidades, guía de lectura, hallazgo calculado y limitaciones. La figura de latencias conserva la paleta accesible del sistema y se descarga a 600 DPI verificables.

## Ejecución y comprobación

Desde la raíz del repositorio, en PowerShell:

```powershell
.venv/Scripts/python.exe -m scripts.analytics --check
.venv/Scripts/python.exe -m scripts.analytics
# Abrir http://127.0.0.1:8502 y seleccionar Inferencia individual.

.venv/Scripts/python.exe -m pytest tests/analytics/test_inference_workflow.py tests/analytics/test_inference_statistics.py -q
.venv/Scripts/python.exe -m pytest -q
node --test tests/ui-and-workflow.test.cjs
.venv/Scripts/python.exe -m pip check
```

Para la regresión completa que genera PDF en este Windows se usan las dependencias locales existentes:

```powershell
$env:WEASYPRINT_DLL_DIRECTORIES='C:/Program Files/Tesseract-OCR'
$env:FONTCONFIG_FILE=(Join-Path (Get-Location) '.venv/soc-runtime/fonts.conf').Replace([char]92,[char]47)
```

El siguiente comando comprueba grafo y export sin consumir API cloud:

```powershell
.venv/Scripts/python.exe -m scripts.verify_inference
```

`--sync-component` actualiza exclusivamente el código del componente existente, verifica cada otro campo del grafo y conserva las referencias a credenciales. Una discrepancia posterior provoca reversión del grafo. No modifica modelos ni prompt. La comparación del export y el grafo se guarda con huella en `runs/phase6/verification/`.

Las verificaciones cloud son optativas y requieren la huella exacta autorizada. Usan solo el caso público revisado del piloto existente, nunca el holdout. La prueba de Gemini altera el modelo Groq con un tweak limitado a esa petición. No cambia el modelo persistido.

```powershell
.venv/Scripts/python.exe -m scripts.verify_inference --live --approved-input-sha256 <SHA256_DEL_CASO_AUTORIZADO>
```

El script utiliza PostgreSQL y n8n aislados, usuarios temporales y tokens propios del entorno. Detiene sus servicios al terminar y conserva evidencia y volúmenes de esa ejecución para auditoría. Sus archivos de configuración locales contienen secretos temporales y permanecen en `runs/`, excluido de Git. Las opciones `--resume-stack`, `--resume-project` y `--resume-report` permiten consultar un reporte aislado ya guardado, validando primero que su contenido coincida con la huella autorizada; evitan reclasificarlo al completar una comprobación interrumpida.

## Resultados y matriz de aceptación

Verificación del 11 de noviembre de 2026, con horas conservadas en UTC en los artefactos:

- Regresión completa de Python: **261 pruebas y 102 subpruebas aprobadas**, cero fallos y cero omitidas, en 1120,91 s. [JUnit completo](../runs/phase6/verification/full.xml) registra 363 casos al incluir las subpruebas.
- Comprobación final del tamaño configurable de la figura y navegación de Streamlit: **2 pruebas aprobadas**. [JUnit](../runs/phase6/verification/final-ui.xml).
- Regresión inicial de privacidad/clasificador: 85 pruebas y 62 subpruebas aprobadas. Nuevas comprobaciones funcionales/estadísticas iniciales: 25 aprobadas; después se añadieron navegación y dos controles de sincronización, incluidos en la regresión completa.
- Workflow n8n: **2 pruebas aprobadas** con Node; cubren los equipos, los cuatro plazos, revisión y rechazo de contextos sin regla.
- Compilación React/TypeScript aprobada. Permanece la advertencia informativa previa del chunk de gráficos mayor que 500 kB.
- `pip check` sin requisitos rotos; `git diff --check` sin errores. Escaneo de 230 archivos de código/configuración/documentación contra secretos configurados: **cero coincidencias**. No se encontraron archivos de Git mayores que 5 MB y `runs/` continúa ignorado. [Escaneo](../runs/phase6/verification/security-scan.json).
- **Siete archivos de datasets conservan exactamente los SHA-256 de Fase 1**, incluidos ZIP VCDB, piloto, índice, cola, preparación, EuRepoC y simulación existente. [Comparación](../runs/phase6/verification/originals.json).
- FastAPI, PostgreSQL, Redis, LangFlow y n8n respondieron disponibles en la comprobación operacional autenticada; React y Streamlit devolvieron HTTP 200. Un Analista consultó siete reportes, indicadores y una observación protegida sin clasificar casos adicionales. [Comprobación operacional](../runs/phase6/verification/operational.json).

Las advertencias de Python corresponden a la deprecación de HTTPX en TestClient y a un caso controlado de evaluación con una clase predicha ausente de su referencia. No produjeron fallos. No se añadieron dependencias para ocultarlas.

### Evidencia real y límites de desempeño

El mismo caso público previamente autorizado fue clasificado por Groq en dos ejecuciones aisladas. La segunda clasificación se reutilizó para terminar los controles de PostgreSQL/n8n y auditoría; la llamada de Gemini se realizó con el modelo Groq inexistente aplicado solo a esa petición. Se conservaron ambos modelos configurados, prompt, referencias de credenciales y originales. [Verificación integrada final](../runs/phase6/verification/20261111T070149Z_live_2871d7c5/verification.json).

| Observación | Intento del proveedor que respondió (s) | Recepción hasta clasificación (s) | Recepción hasta notificación (s) |
|---|---:|---:|---:|
| Groq, primera ejecución aislada | 0,9584 | 8,2804 | 12,7990 |
| Groq, segunda ejecución aislada, reutilizada al completar la verificación | 0,7117 | 2,1005 | 7,1335 |
| Gemini, llamada del grafo ante error Groq HTTP 404 | 4,3107 | No aplicable: prueba directa del grafo | No aplicable: prueba directa del grafo |

**Cómo leerlo.** Cada fila es una observación del mismo texto, sin referencia humana de severidad. Las columnas describen tramos distintos y usan segundos. La prueba directa de Gemini no crea un reporte operacional; su integración con persistencia, revisión y SLA está cubierta por los transportes controlados de las pruebas automatizadas. **Hallazgo clave.** Una de las dos observaciones completas superó 10 s. El mismo tipo `phishing` obtuvo severidad `media` con Groq y `alta` con Gemini en las respuestas comparadas. **Limitaciones.** Estos resultados no acreditan p95 poblacional, exactitud ni superioridad de un proveedor; no permiten atribuir causalmente la diferencia de tiempos a calentamiento. La severidad y el activo requieren referencias humanas independientes para medir errores.

La verificación final confirmó PostgreSQL 16.15 y n8n 1.109.2, un reporte, una asignación y una notificación en la base aislada, los cuatro eventos en orden y sus actores. Los triggers rechazaron UPDATE, DELETE y TRUNCATE de auditoría. La reanudación usó otro actor JWT y comprobó HTTP 409 al reutilizar el UUID ajeno; el reintento idempotente por el mismo actor está cubierto por las pruebas automatizadas. La predicción y el texto original permanecieron íntegros.

Las dos primeras verificaciones quedaron **incompletas** por un error del script al pasar una fecha nativa de PostgreSQL a una función que esperaba el JSON de la API. La primera reanudación quedó **incompleta** por exigir erróneamente el recibo idempotente del dueño original desde una sesión de otro actor. Se corrigió el script y se verificó el conflicto autorizado de propiedad. Sus archivos anteriores conservan estado incompleto y no se reescribieron como aprobados. Las pruebas iniciales de interfaz detectaron errores de preparación de AppTest, corregidos al restablecer el botón y usar la navegación real; la ejecución final y la regresión completa aprobaron la interfaz.

En la instalación operacional existe además un reporte histórico no DEMO, con 56,6879 s hasta notificación y sin traza de intentos de proveedor. Los seis DEMO se excluyen. Estos registros conservan su falta de proveedor/modelo cuando no hay evidencia histórica; no se mezclan con las observaciones aisladas ni permiten acreditar el objetivo de latencia.

PostgreSQL operativo presentó recuperación recurrente antes y durante la validación. Se reinició su contenedor y se utilizó el reinicio de Docker Desktop previamente autorizado; se recargaron FastAPI y Streamlit. La última comprobación autenticada fue satisfactoria. La causa de las recaídas y la disponibilidad sostenida siguen sin acreditarse. No se restauraron tablas, borraron volúmenes ni alteraron originales para ocultar esa condición.

### Matriz de aceptación y trazabilidad

| Requisito de Fase 6 / SPEC | Estado | Evidencia y alcance |
|---|---|---|
| Inferencia individual mediante servicios existentes; Streamlit complementa React | Cumple | Webhook existente, Groq/LangFlow reales, PostgreSQL/n8n aislados y comprobación operacional autenticada; navegación AppTest |
| Taxonomía y contrato estrictos | Cumple | Respuestas reales de cuatro campos; pruebas de JSON inválido, campos adicionales, severidad/tipo inválidos y caracteres no admitidos |
| Groq principal, Gemini ante fallo técnico elegible | Cumple | Traza real Groq→Gemini por HTTP 404 temporal de prueba; transporte controlado para fallos, rechazo de política, máximo tres intentos y ausencia de conmutación por confianza baja |
| Revisión humana ante confianza insuficiente, inyección o resultado inválido | Cumple | Pruebas del backend y UI; política efectiva de revisión y corrección separada de la predicción original |
| Asignación y SLA determinísticos desde recepción | Cumple | Cuatro pares de plazos verificados, validación de reglas falsas, dos pruebas del workflow n8n y correspondencia real del caso aislado |
| Trazabilidad de extremo a extremo, modelo/proveedor efectivos y auditoría | Cumple | JSON protegido versionado, hash, citas, eventos, fuente de versión del modelo, intentos y rechazo real de tres operaciones de alteración de auditoría |
| RBAC, JWT y protección de originales y egreso | Cumple dentro de la cobertura de la política | Pruebas de permisos, privacidad en ambos proveedores/reintentos, falta de política bloqueante, integridad de archivos y publicación retirada ante fallo de auditoría |
| Estadística válida o identificada como no aplicable | Cumple | Cuantiles comparados con NumPy; guardas de evidencia humana/configuración; IC individuales/calibración/conforme declarados no aplicables; Prueba no se reabre |
| Métricas reales e IC sobre holdout humano independiente | Pendiente | No existe aún el holdout revisado requerido; no se usaron etiquetas provisionales, sintéticas o del LLM como verdad real |
| Acreditar p95 < 10 s del SPEC | Pendiente | Muestra insuficiente y no representativa; una observación completa supera la meta y el histórico tiene otro tiempo mayor |
| Disponibilidad sostenida del entorno operacional | Parcial | Lecturas y servicios disponibles al cierre de la comprobación; recuperación recurrente de PostgreSQL pendiente de diagnóstico del entorno |

**Cómo leerlo.** La unidad es el requisito verificado; el estado se limita a la evidencia indicada. **Hallazgo clave.** Los ocho criterios funcionales y de seguridad/validez de implementación tienen evidencia aprobada; la calidad predictiva real, el objetivo de p95 y la estabilidad sostenida del entorno conservan sus límites explícitos. **Limitaciones.** La protección determinística no constituye anonimización universal. Un ensayo de integración y los casos controlados no sustituyen una campaña representativa, revisión humana independiente ni pruebas prolongadas de disponibilidad.

**Aceptación técnica de Fase 6:** cumplida para el módulo implementado y las guardas de seguridad/estadística verificadas. Las validaciones empíricas pendientes y la intermitencia operacional quedan identificadas; no se declaran satisfechas. No se avanzó a Fase 7. [Resumen verificable](../runs/phase6/verification/acceptance.json).
