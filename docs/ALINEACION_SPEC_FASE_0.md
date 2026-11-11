# Alineación de la Fase 0 con el SPEC definitivo 2.1

Actualización posterior al cierre de F0: el control NF-02 se implementó y probó por orden expresa del usuario antes de F1. La corrección, sus límites y el estado operacional de esta revisión se documentan en [SEGURIDAD_PRIVACIDAD.md](SEGURIDAD_PRIVACIDAD.md). Las pruebas de la entrega original de F0 se conservan como antecedente; no sustituyen los resultados de seguridad posteriores.

## Fuente y alcance de la revisión

Fuente principal: `ARCHIVO_SPEC_SOC_Caso06_Concordante_Groq_Gemini.docx`, versión 2.1 del 10/11/2026, leído completo, incluidos requisitos, modelo lógico, fases, criterios, riesgos y concordancia documental con la Cartera. SHA-256 del original: `a5868e2b7070d45f5b74cf50a8aea8d0d9a5657c45e3a85be52b3726e0f8fbfb`. El documento original permanece intacto.

La revisión contrasta requisitos con código y ejecución, distingue los estados históricos reportados en el SPEC y limita las correcciones a preparación e integración. Los campos lógicos orientativos de la sección 6 no se convierten en migraciones de esquema. No se implementó la Fase 1 ni se reconstruyeron los servicios operativos.

SUPUESTO de acceso aplicado conforme a los roles de la sección 4: las verificaciones que escriben un registro local requieren Administrador o Analista; el Gestor mantiene lectura de informes y metadatos. Se reutilizan los permisos existentes `write` y `read`; no se crea un segundo RBAC.

## Correcciones realizadas y contradicciones contrastadas

1. **Export y ejecución de LangFlow diferentes.** El archivo versionado conservaba Ollama/Qwen; el flujo activo contenía `SocCloudModel` Groq/Gemini. Se regeneró el export desde ese mismo grafo y se añadió un comprobador de código, prompt, modelos, conexiones y huella. El nuevo export contiene nombres de variables, nunca valores de claves.
2. **Credenciales globales existentes sin enlace.** `GROQ_API_KEY` y `GEMINI_API_KEY` existían como Credential en LangFlow, pero ambos campos del componente estaban vacíos con `load_from_db=false`. Se enlazaron a esos nombres con `load_from_db=true`. No se crearon claves ni se cambiaron sus valores, modelos, prompt o política del componente.
3. **Auditoría analítica inespecífica.** La Fase 0 anterior validaba identidad con `/api/auth/me`, pero las lecturas locales y los registros no tenían eventos funcionales propios. Se añadió `POST /api/analitica/eventos`, que reutiliza identidad, permisos, auditoría y triggers existentes. Las vistas previas no se devuelven si su auditoría falla.
4. **Gestor podía escribir verificaciones.** El alta usaba el permiso de lectura. Ahora requiere `write` en cliente y servidor; Gestor/Auditor/Solicitante no pueden registrar verificaciones. Los registros distinguen `local`, `pendiente` y `confirmada`; no se certifican retroactivamente los anteriores.
5. **Descripción de fases derivada del promptuario de imágenes.** Se actualizaron los textos de módulos futuros hacia experimentación de prompts/parámetros cloud y explicabilidad textual verificable. `src/training/` conserva su nombre arquitectónico; no representa entrenamiento de pesos de Groq/Gemini.
6. **Confianza operacional.** El catálogo advierte explícitamente que el valor no es una probabilidad calibrada y que predicciones/DEMO no son etiquetas humanas verdaderas.
7. **Conteo EuRepoC del estado reportado.** El SPEC recoge 3.663 filas; la lectura CSV estándar con comillas dobles escapadas produce **3.414 registros, todos de 85 columnas**. La inferencia automática que originó 3.663 fragmentaba campos multilínea y generaba anchos inconsistentes. Se preservó el archivo y se documentó la discrepancia, sin modificar el SPEC ni inventar registros.
8. **Estados históricos frente a ejecución actual.** Las afirmaciones de que Streamlit estaba pendiente y los servicios eran inaccesibles pertenecen a la inspección previa consignada en el SPEC. La revisión actual verifica el estado nuevo mediante pruebas; no elimina componentes para reproducir un estado histórico ni modifica el documento.

Al cierre original de F0, la huella canónica del grafo cambió de `36fe9610b2b9aece850e32c027c32dadc5b2961b92e4a6d8db16826b7925337c` a `5b0726be6e46a32929f7a9d04cf1c19b6e362f5c62914319eb9f2c2a131db8eb`. La comparación excluyendo solo los dos enlaces de credenciales confirmó que el resto del grafo se conservó. El componente de entonces tenía SHA-256 `7c50749d9322e99efeef1732617460cb246c3f3845cd0b10c7cba7421a0c8657`. El cierre de NF-02 actualiza exclusivamente el código del componente y su export; su nueva huella canónica es `e630d3772c96ae482229af595479566ba79026b230d84e84823aaae898f7006b`. El prompt conserva SHA-256 `94d860eed0cdf2e6137d5fea2561a67b9773e5f4606f71ee37ba7ab9841ddefe`, y los modelos, referencias de claves y resto del grafo se conservan.

## Matriz de trazabilidad

Los identificadores RF son los del SPEC. Los prefijos AR, NF, MD, DS, F y CA son referencias locales a sus secciones, no requisitos inventados. `Cumple` significa que hay implementación y evidencia identificada; `Parcial` indica cobertura incompleta o una discrepancia documentada; `No cumple` identifica una capacidad exigida todavía ausente; `No aplica` delimita un estado histórico, alcance excluido o fase no implementable en Fase 0. La columna de pendiente evita interpretar los objetivos globales como criterios ya logrados.

Resumen calculado de las 76 filas tras el cierre del control NF-02: **50 Cumple, 14 Parcial, 0 No cumple y 12 No aplica**. La versión estructurada está en [ALINEACION_SPEC_FASE_0.json](ALINEACION_SPEC_FASE_0.json). Estos conteos no son un porcentaje de conformidad de F0: incluyen requisitos globales y fases posteriores.

### Arquitectura y requisitos funcionales

| Referencia del SPEC | Requisito | Componente implementado | Estado | Evidencia y pendiente |
| --- | --- | --- | --- | --- |
| AR-01 §§1–3 | Identidad Caso 06, SOC, clasificación y gestión | React, FastAPI, LangFlow y n8n | Cumple | `README.md`, `backend/main.py`, `integrations/n8n/assign_report.json`; E2E aislado |
| AR-02 §§3.1–3.3 | React operacional y Streamlit complementario | `frontend/`, `app.py`, `pages/` | Cumple | Tres páginas académicas; compilación React y smoke tests; no se reemplaza el formulario |
| AR-03 §§3.1–3.2 | FastAPI único backend operacional | `backend/main.py`, `src/inference/services.py` | Cumple | JWT, consultas y auditoría por API; ninguna conexión SQL nueva desde Streamlit |
| AR-04 §§3.1–3.4 | LangFlow como clasificador puro | `SocCloudModel`, export sincronizado | Cumple | Solo ChatInput, Prompt, SocCloudModel y ChatOutput; pruebas de grafo y ejecución |
| AR-05 §§3.1,10 | Groq principal y modelo configurado | `cloud_classifier_model.py` | Cumple | Prueba real: Groq / `openai/gpt-oss-20b` |
| AR-06 §§3.1,7.3 | Gemini ante fallo técnico elegible | Mismo componente y clientes existentes | Cumple | Gemini / `gemini-3-flash-preview` ante modelo Groq inexistente por petición; sin cambio persistido |
| AR-07 §§3.4,9 F0,13 | Export equivalente y secretos enlazados | `src/utils/langflow.py`, `scripts/align_langflow.py` | Cumple | Referencias existentes válidas y huella de export igual al runtime; sin Ollama/Qwen |
| AR-08 §§3.1–3.2 | PostgreSQL y Redis existentes | SQLAlchemy/psycopg y `RuntimeServices` | Cumple | Salud real, lectura operativa y base PostgreSQL aislada en E2E |
| AR-09 §§3.4,13 | Servicios antes inaccesibles | Estado histórico del documento | No aplica | No es un objetivo de indisponibilidad; se verifica el estado actual por separado |
| RF-01 §5.1 | Formulario con reportante, canal, asunto, descripción, fecha y adjuntos | Formulario React y `ReportInput` | Parcial | Actualmente el envío exige `titulo`/`descripcion`; identidad se relaciona con cuenta y adjuntos existen aparte. Faltan campos completos del RF; evolución operacional fuera de F0 |
| RF-02 §§5.1,7 | Recepción, ID y persistencia después de clasificar | `submit`, `save_report`, `dispatch` | Cumple | E2E real aislado e idempotencia; clasificación precede a persistencia funcional y despacho n8n |
| RF-03 §§5.1,7.2 | Tipo, severidad, activo, confianza y ampliación de justificación | `Classification`, `SocCloudModel` | Parcial | Contrato actual de cuatro campos válido; justificación estructurada pendiente de F4/F6, sin romper consumidores |
| RF-04 §§5.1,8 | n8n asigna responsable y SLA; API valida | Workflow, `route_for`, endpoint interno de asignación | Cumple | Dos pruebas de workflow y E2E validan equipo y ambos vencimientos |
| RF-05 §§5.1,7.3 | Revisión bajo umbral, inválidos y corrección separada | `classify`, `report_reviews`, `operations.py` | Cumple | Frontera 0,75, errores y conservación de predicción cubiertos por regresiones |
| RF-06 §5.1 | Notificación por n8n y reintentos | Workflow, `dispatch`, cola Redis | Cumple | E2E registra una notificación interna con actor n8n; pruebas de recuperación simulada preservadas; no se certifica email externo |
| RF-07 §5.1 | Indicadores operativos y ampliación académica | Dashboard React, insights, Streamlit F0 | Parcial | Operación disponible; comparativas y evaluación académica pertenecen a F2/F3 |
| RF-08 §§4,5.1 | Eventos y bitácora inmutable | Middleware, triggers, auditoría analítica nueva | Cumple | Autoría por JWT, auditoría funcional y bloqueos PostgreSQL comprobados en base aislada |
| RF-09 §§4,5.1 | JWT/RBAC/TOTP también para Streamlit | Seguridad existente y adaptadores | Cumple | Login/TOTP delegados; pruebas por cinco roles; consultas y escrituras locales auditadas por backend |
| RF-10 §5.1 | Reusar PDF/Word/Excel y PNG científico | `backend/exports.py`, `src/reports/figures.py` | Parcial | Exportadores operativos preservados y PNG de 600 DPI probado; informes científicos integrados corresponden a F5 |
| RF-11 §§5.1,9 | Módulo académico por fases 0–7 | Estructura src/pages y F0 | Parcial | Preparación implementada; F1–F7 esperan orden explícita |
| RF-12 §§5.1,6.5 | Originales, procedencia y reproducibilidad de datasets | Catálogo, hashes y herramientas VCDB existentes | Parcial | Acceso e integridad cubiertos; revisión humana y particiones definitivas pertenecen a F1/F2 |
| RF-13 §§5.1,7.3,13 | Proveedor/modelo y causa técnica separados del origen protector | Metadata `soc_provider`, bitácora y evidencias de prueba | Parcial | Proveedor se conserva; modelo y causa de fallback no se persisten íntegramente por cada reporte productivo. Instrumentación F2/F6 pendiente |

Leyenda: estados categóricos sin unidad física; las rutas señalan evidencia versionada y los registros de ejecución se detallan más abajo. Cómo leerlo: RF-03, RF-10 y RF-11 separan el contrato actual de sus ampliaciones futuras. Hallazgo clave: la corrección de F0 conserva la secuencia del Caso 06 y la responsabilidad de n8n; la tabla mantiene visibles las ampliaciones no implementadas. Limitación: un E2E con un caso acredita integración observada, no cobertura estadística de todos los incidentes.

### Seguridad, datos y requisitos no funcionales

| Referencia del SPEC | Requisito | Componente implementado | Estado | Evidencia y pendiente |
| --- | --- | --- | --- | --- |
| NF-01 §5.2 | Texto no confiable, delimitación y validación | `SUSPICIOUS`, escape, Pydantic y taxonomía | Cumple | Regresiones de inyección, JSON inválido y salida fuera de contrato; la cobertura no equivale a seguridad absoluta ante toda entrada |
| NF-02 §§5.2,12 | Minimización/enmascaramiento automático de PII antes de cloud | `src/utils/privacy.py`, `config/privacy.yaml`, clasificador, `SocCloudModel` y chat | Cumple | Filtro local en ambos límites; copia protegida para Groq/Gemini/reintentos; fallo cerrado; originales restringidos y evidencia mínima. `tests/test_privacy.py`, `runs/privacy-fix-20261110/full-tests-final.xml` y E2E real aislado prueban el alcance descrito en `docs/SEGURIDAD_PRIVACIDAD.md`. No se certifica detección universal de PII ni cifrado/retención |
| NF-03 §§3.4,5.2 | Claves fuera de código/export/logs | `.env`, variables Credential y referencias | Cumple | Export con nombres globales, mensajes saneados y escaneo de valores reales; no se crearon claves |
| NF-04 §§5.2,11 | Medir p50/p95 y no afirmar p95 menor a 10 s sin evidencia | Marcas de tiempo y comprobaciones individuales | Parcial | Solo observaciones de integración; percentiles representativos y objetivo de rendimiento pendientes de campaña de F2/F3 |
| NF-05 §§5.2,7.3 | Política técnica de fallback y salida protectora | Componente cloud y `backend/classifier.py` | Cumple | Prueba real de conmutación, simulaciones de errores y rechazo de política sin conmutación; baja confianza deriva a revisión |
| NF-06 §§5.2,12 | Coherencia de prompt, modelos, workflow y reglas | Export, comprobador y hashes | Cumple | Mismo código y prompt; grafo equivalente y prueba repetible; fuentes operativas protegidas por hashes |
| NF-07 §§5.2,10 | Reproducibilidad numérica y registro | Config, lock, semillas y runs | Cumple | Registros técnicos con huellas, versiones y fecha; no se atribuye determinismo a las APIs |
| NF-08 §5.2 | Prompt/modelo/proveedor/particiones por experimento | Registro F0 y evidencias cloud | Parcial | F0 registra sus fuentes y comprobaciones; manifiestos completos de experimentación y Prueba sellada pendientes de F1/F2 |
| NF-09 §5.2 | Español e identificadores operativos | Streamlit en español y taxonomía original | Cumple | Identificadores de diez clases preservados; React conserva su soporte existente |
| SG-01 §4 | Administrador y Analista realizan operaciones | Permisos `manage`, `write`, `review` | Cumple | Cinco roles probados en auditoría; creación de verificaciones limitada a los dos roles |
| SG-02 §4 | Gestor de lectura; Auditor de bitácora | `read` para informes y `audit` para bitácora | Cumple | Gestor no registra verificaciones; Auditor/Solicitante no acceden al catálogo analítico |
| SG-03 §§4,5.1 | Operaciones Streamlit auditadas en backend | `backend/analytics_audit.py` | Cumple | Catálogo, fuente, alta y lectura de verificaciones; actor no aceptado desde el payload |
| SG-04 §§4,6.3 | audit_log sin UPDATE/DELETE/TRUNCATE | Triggers PostgreSQL existentes | Cumple | Tres operaciones rechazadas por el trigger en PostgreSQL real aislado |
| MD-01 §6 | Mapear entidades lógicas sin forzar nombres físicos | `db/schema.sql`, `Database`, tablas existentes | Cumple | `reports`, `assignments`, `audit_log`, `report_reviews`; no se hicieron migraciones para imitar el esquema orientativo |
| MD-02 §§6.1–6.2,8 | Referencia temporal de recepción y minutos transcurridos | `deadline`, asignaciones y reglas | Cumple | Regresión de cuatro severidades y ambos SLA en E2E; no se usan días hábiles |
| DS-01 §6.5 | VCDB original y revisión/hash | ZIP existente y `scripts/vcdb.py` | Cumple | 10.047 JSON; huella original verificada; candidatos provisionales no son gold labels |
| DS-02 §6.5 | Piloto de ocho casos y cuatro tipos | `vcdb-pilot.json` | Cumple | Procedencia y revisor preservados; ausencia de severidad/activo declarada |
| DS-03 §§6.5,13 | Holdout de 160 candidatos sin prueba final | Cola y preparación existentes | Cumple | Se conserva la condición de pendiente; no se crea `holdout-reviewed.json` ni se usa para ajuste |
| DS-04 §6.5 | EuRepoC accesible sin reemplazo | CSV original y lector estricto | Parcial | Fuente funcional; el conteo real 3.414 × 85 difiere del estado reportado 3.663 × 85 en el SPEC |
| DS-05 §6.5 | Operación real separada de DEMO | API de reportes y catálogo explícito | Cumple | Acceso limitado documentado; predicciones y DEMO no se presentan como referencia humana |
| DS-06 §6.5 | Simulación marcada como sintética | CSV del artículo preexistente | Cumple | 2.400 filas, identificación explícita; no se sustituye corpus por simulación |
| DS-07 §§6.5,10 | Conservar originales y fuentes existentes | Lectura y huellas antes/después | Cumple | Ningún dataset alternativo descargado; integridad contrastada contra baseline |
| DS-08 §§6.5,9,13 | Gold labels suficientes para evaluar | Piloto y preparación parcial | Parcial | Faltan revisión independiente, severidad/activo y Prueba final; preparación F1 pendiente |

Leyenda: filas y columnas son conteos; SLA se mide en minutos, tiempos de prueba en segundos o milisegundos según su campo. Cómo leerlo: NF-02 identifica ahora un filtro implementado y probado dentro de la cobertura declarada; DS-04 conserva la discrepancia documental sin alterar originales. Hallazgo clave: el único control que estaba en No cumple tiene evidencia de implementación; las etiquetas humanas y las garantías de privacidad que exceden las pruebas mantienen sus límites. Limitación: los datos personales ficticios se verifican con HTTP simulado y el caso público autorizado se usa en cloud; esto no certifica cobertura universal sobre PII real.

### Fases y reglas transversales

| Referencia | Requisito | Componente implementado | Estado | Evidencia o pendiente |
| --- | --- | --- | --- | --- |
| F-00 §9 | Preparación, validación de servicios, export y credenciales | F0 y correcciones de alineación | Cumple | Unitarias, smoke, cloud autorizado y E2E aislado |
| F-01 §9 | Datos, revisión, sesgos y estadística textual | Catálogo preparatorio; herramientas previas VCDB | No aplica | Implementación de F1 pendiente; no se añadió editor ni análisis exploratorio |
| F-02 §9 | Experimentación de prompts/parámetros y Prueba sellada | Infraestructura de registros | No aplica | No se entrenan pesos de APIs; experimentación y línea base local condicionada a justificación |
| F-03 §9 | Evaluación con etiquetas humanas y scores adecuados | Reservado | No aplica | Macro-F1, recall crítico, kappa y curvas solo con datos/score válidos |
| F-04 §9 | Explicación textual y fragmentos verificables | Reservado | No aplica | Justificación estructurada y citas pendientes; SHAP/LIME no son obligación para APIs cloud |
| F-05 §9 | Reportes científicos interpretados | Exportadores previos y utilidad PNG | No aplica | Integración de informes académicos en F5 |
| F-06 §9 | Inferencia por pipeline existente y trazabilidad | Pipeline operacional conservado | No aplica | Interfaz de inferencia académica y ampliaciones de contrato pendientes |
| F-07 §9 | Optuna, límites de costo/tasa y no despliegue automático | Dependencia preparada, sin estudios ejecutados | No aplica | UI/búsquedas futuras; no se crearon trials |
| R1 | Lógica modular, páginas y tipos | `src/`, `pages/`, extensión mínima de backend | Cumple | Lógica analítica separada; backend no se replica |
| R2 | Configuración externa y credenciales | YAML/TOML, `.env` y referencias globales | Cumple | Nuevos endpoints/rutas y referencias de conformance externos |
| R3 | Semilla, versiones y registros | Lock, semillas y runs | Cumple | Fechas, hashes y versiones; variabilidad cloud declarada |
| R4 | Grupos y preprocesamiento sin fuga | Lectura sin ajuste ni partición | Cumple | En F0 no se ajustan modelos ni se consume el holdout; partición efectiva futura |
| R5 | Títulos, unidades, lectura, hallazgo y límites | `presentation.py` y páginas | Cumple | Guías calculadas de resultados reales; confianza no calibrada advertida |
| R6 | Estilo accesible y 600 DPI | Tema y `figures.py` | Cumple | Test PNG comprueba 600 DPI |
| R7 | Validación, errores, caché, sesión y tareas | Config/servicios/runtime | Cumple | Sin tokens en caché; auditoría falla de forma segura; trabajos de red en segundo plano |
| R8 | Conservar suites y añadir pytest/smoke | Tests existentes y `tests/analytics/` | Cumple | Batería completa y pruebas optativas reales separadas |
| R9 | Supuestos, árbol, implementación y evidencias | Mensajes de trabajo y este informe | Cumple | Matriz, archivos, comandos y criterios documentados |
| R10 | Solo fase solicitada | Preparación y validación | Cumple | No se implementan funcionalidades de F1–F7 |
| EX-01 §2.3 | SOAR, análisis profundo de correo y tickets externos | Excluidos | No aplica | No son correcciones de F0 ni se construyeron |
| EX-02 §§9,10 | No imponer visión artificial | Dependencias textuales/científicas | Cumple | Sin Grad-CAM, ResNet, torchvision u Ollama nuevos |
| EX-03 §§3.4,13 | Declaraciones históricas de Streamlit pendiente | Estado reportado previo | No aplica | Se conserva el SPEC; la implementación actual se verifica aquí |
| CA-01 §11 | Flujo completo o revisión segura y auditoría | Pipeline original e integración aislada | Cumple | Un caso real autorizado completó clasificación, persistencia, asignación, notificación y bitácora; ramas de error cubiertas por regresión |
| CA-02 §11 | Diez tipos y contrato compatible con ampliación | `Classification`, prompt y esquema cloud | Parcial | Diez clases y cuatro campos comprobados; quinto campo pendiente de F4/F6 |
| CA-03 §11 | Meta macro-F1 de tipo mayor o igual a 0,85 | Evaluación final pendiente | No aplica | Meta, no resultado de F0; no hay holdout revisado suficiente |
| CA-04 §11 | Meta kappa ordinal mayor o igual a 0,70 | Etiquetas de severidad pendientes | No aplica | No evaluable válidamente con el piloto actual; no se fabrican etiquetas |
| CA-05 §11 | Umbral 0,75 y correcciones separadas | Clasificador y `report_reviews` | Cumple | Regresión del límite y conservación de predicciones originales |
| CA-06 §11 | Fallback técnico y proveedor real auditable | Componente original, metadata y bitácora | Cumple | Probes reales separados de pruebas simuladas de baja confianza/rechazo de política |
| CA-07 §11 | Rechazo de mutaciones de audit_log | Triggers PostgreSQL | Cumple | Tres rechazos en base real aislada; sin operaciones destructivas sobre producción |
| CA-08 §11 | Plazos 15/240, 60/480, 240/1.440, 480/2.880 | Reglas y vencimientos existentes | Cumple | Workflow recorre las cuatro severidades y E2E contrasta ambos vencimientos desde recepción |
| CA-09 §11 | Privacidad, inyección, rol y secretos | Controles existentes, filtro local y auditoría | Parcial | Roles, secretos, inyección y protección de los formatos de NF-02 probados; cobertura de PII real arbitraria, cifrado y retención no se certifican. No se elevan controles no probados a Cumple |
| CA-10 §11 | Cada fase demuestra función y pruebas | F0 completada; módulos posteriores reservados | Parcial | F0 cumple; el conjunto de fases 0–7 no se presenta como terminado |

Leyenda: No aplica en F-01 a F-07 delimita esta entrega, no elimina el requisito de las siguientes fases. Cómo leerlo: la carpeta `training` conserva la arquitectura exigida y no autoriza entrenar pesos de proveedores cloud. Hallazgo clave: las correcciones se concentran en F0 y dejan visibles las fases pendientes. Limitación: se validó preparación, no la calidad académica de módulos todavía no implementados.

## Resultados verificables de pruebas

Las evidencias locales se guardan en `runs/spec-alignment-20261110/` y otros subdirectorios de `runs/`, excluidos de Git. Son registros técnicos, no un nuevo dataset. Los tiempos UTC están identificados como tales; la fecha de esta revisión corresponde a Lima, 10/11/2026.

| Comprobación | Resultado | Evidencia |
| --- | --- | --- |
| Analítica inicial tras correcciones | Superada: 38 pruebas | `runs/spec-alignment-20261110/analytics-tests.xml` |
| Regresión Python completa final | Superada: 101 pruebas y 102 subpruebas | `runs/spec-alignment-20261110/full-tests.xml`; 80,48 s; una advertencia de deprecación de TestClient/HTTPX |
| Groq real por LangFlow | Superada | `runs/spec-alignment-20261110/cloud-probes.json`; modelo principal, contrato de cuatro campos, grafo sin cambios |
| Gemini real tras fallo técnico controlado | Superada | Mismo JSON; modelo Groq inexistente solo por tweak de la petición; modelo Gemini configurado intacto |
| Caso 06 real en entorno aislado | Superada: una prueba | `runs/20261110T185148Z_e2e_74232ac4/e2e-result.json`; unittest, 39,756 s |
| Persistencia, n8n y aviso | Superada | Un reporte, una asignación y una notificación; orden recibido, clasificado, asignado, notificación; SLA e idempotencia válidos |
| Inmutabilidad PostgreSQL real | Superada | UPDATE, DELETE y TRUNCATE rechazados por el trigger en la base aislada `soc_evaluation` |
| Auditoría analítica en API activa y Streamlit real | Superada | `runs/spec-alignment-20261110/runtime-audit.json`: cinco eventos funcionales con actor válido, alta confirmada, Gestor rechazado con 403 y HTTP 200 de Streamlit |
| Integridad de SPEC, originales y configuración protegida | Superada | `runs/spec-alignment-20261110/integrity.json`: seis archivos originales y siete fuentes operativas protegidas intactos; 7 reportes, 7 asignaciones y 0 revisiones antes/después |
| Reglas n8n y dependencias | Superadas | Dos pruebas de workflow; `pip check` sin requisitos rotos; compilación React aprobada al activar el backend |
| Secretos y consistencia de cambios | Superadas | Cero coincidencias con credenciales reales en 51 fuentes revisadas; `git diff --check` sin errores de whitespace |

Cómo leerlo: las pruebas locales/simuladas, cloud y E2E están separadas para no atribuir a una suite la evidencia de otra. Hallazgo clave: Groq, Gemini y el flujo funcional se ejecutaron con el único caso público expresamente autorizado; los reportes de producción se excluyeron de esa prueba. Limitación: 19,203 s en la primera comprobación directa de Groq y 7,203 s en el diagnóstico Gemini son observaciones individuales de LangFlow y su verificación, no percentiles ni tiempos exclusivos del proveedor. En el E2E aislado se observaron 983,491 ms de clasificación y 1.780,197 ms hasta notificación, también para un solo caso.

Las comprobaciones iniciales de enlaces/export fallaron de forma esperada antes de corregirlos y después pasaron. No se oculta ese diagnóstico inicial. La revisión automática de aprobación bloqueó inicialmente el envío cloud; tras presentar el título, descripción y destinos exactos, el usuario autorizó ese único caso y ambos proveedores. Las pruebas cloud y E2E se ejecutaron después de esa autorización.

El registro de interfaz `20261110T190946149260Z_57d4b137f290` quedó con `audit_state=confirmada`. PostgreSQL contiene los eventos consultar catálogo, consultar fuente, iniciar y completar el registro, y consultar informes; todos corresponden al usuario autenticado. La consulta de conteos utiliza alias explícitos para cada tabla y solo lectura. Los eventos y sesiones de prueba añaden auditoría legítima; no añaden reportes operativos ni alteran sus etiquetas.

No ejecutables válidamente en F0: Macro-F1 objetivo, kappa de severidad, evaluación de activo y métricas finales del holdout, porque faltan referencias revisadas suficientes y el manifiesto sellado. No se calcularon ROC/AUC/Brier sin scores apropiados. Un p95 representativo tampoco se deduce de una observación. En el cierre posterior de NF-02 se implementó el filtro y se añadieron pruebas con PII ficticia mediante HTTP simulado; no se transmitió PII real ni se inventó una validación exhaustiva. La inspección visual de navegador no forma parte de la evidencia funcional automatizada; las páginas se comprobaron con AppTest y HTTP.

## Archivos modificados y justificación

| Archivos | Cambio y motivo |
| --- | --- |
| `integrations/langflow/cybersecurity_classifier.json` | Export del grafo activo Groq/Gemini, con referencias a credenciales y sin Ollama/Qwen |
| `src/utils/langflow.py`, `scripts/align_langflow.py` | Comprobar/sincronizar código, prompt, modelos, enlaces y export; probes optativas con caso existente autorizado |
| `backend/analytics_audit.py`, `backend/main.py` | Endpoint mínimo de auditoría que reutiliza seguridad y `Database.access_event`; sin tablas nuevas |
| `src/inference/services.py`, `src/data/catalog.py` | Reutilizar el endpoint y exigir auditoría antes de entregar vistas previas |
| `src/training/experiments.py` | Permiso de escritura, auditoría del alta, confirmación o estado pendiente y lectura auditada |
| `src/utils/streamlit_runtime.py`, `pages/01_Fuentes.py`, `pages/02_Registros.py` | Tareas y estado privado para accesos auditados; invalidación de informes tras altas |
| `pages/00_Inicio.py`, `src/training/__init__.py` | Alinear nombres futuros con experimentación cloud y explicabilidad textual |
| `src/reports/presentation.py`, `config/datasets.yaml` | Hallazgos de auditoría y advertencia de confianza operacional |
| `src/utils/config.py`, `config/analytics.yaml` | Parámetros públicos del endpoint y comprobaciones, sin claves |
| `tests/analytics/conftest.py`, `test_pages.py`, `test_spec_alignment.py` | Regresión del export, cinco roles, auditoría fallida, gestor de lectura y smoke asíncrono |
| `tests/live_phase0_alignment.py` | Prueba optativa reproducible con caso aprobado y base aislada; sin puntuar calidad del modelo |
| `docs/FASE_0.md`, `README.md`, este informe | Referenciar el SPEC definitivo y conservar la entrega inicial como antecedente |

Cómo leerlo: se agrupan cambios con una misma responsabilidad en la entrega original de F0. Hallazgo clave: esa entrega añadió auditoría; el cierre posterior de NF-02 añade protección al clasificador/chat y evidencia en la bitácora, con el detalle completo en `docs/SEGURIDAD_PRIVACIDAD.md`. Las reglas, el esquema y el workflow no se reconstruyen. Limitación: la recarga del filtro requiere reiniciar los intérpretes correctos de FastAPI/LangFlow y comprobar disponibilidad del entorno.

## Comandos de reproducción

Desde la raíz del proyecto en PowerShell:

```powershell
.\.venv\Scripts\python.exe -m scripts.analytics --check
.\.venv\Scripts\python.exe -m scripts.align_langflow
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/ui-and-workflow.test.cjs
.\.venv\Scripts\python.exe -m pip check
```

Corrección explícita de referencias/export, sin llamadas LLM:

```powershell
.\.venv\Scripts\python.exe -m scripts.align_langflow --sync
```

Los comandos siguientes consumen APIs externas y deben ejecutarse únicamente con autorización del contenido y destinos. El caso aprobado en esta revisión tiene huella `882af8b669b92ad9695a4004311ee477464da3d84db50bfa91d3083f63a82b84`:

```powershell
.\.venv\Scripts\python.exe -m scripts.align_langflow --probe
$env:SOC_PHASE0_APPROVED_INPUT_SHA256='882af8b669b92ad9695a4004311ee477464da3d84db50bfa91d3083f63a82b84'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p live_phase0_alignment.py -v
```

No se debe ejecutar `--probe` con un caso distinto basándose en la autorización anterior. La prueba E2E se omite sin la huella autorizada. Las imágenes Docker usadas son las existentes del proyecto; los contenedores de prueba usan un proyecto distinto y se detienen al terminar.

## Pendientes y puertas de las siguientes fases

1. NF-02 implementado y probado antes de F1. Mantener la política de minimización y revisar su cobertura frente a formatos reales autorizados; no interpretar las pruebas como garantía universal de anonimización, cifrado o retención. Ver `docs/SEGURIDAD_PRIVACIDAD.md` y su evidencia.
2. Evolución operacional pendiente: completar los campos RF-01 y su persistencia sin duplicar el webhook o reconstruir React. Requiere alcance específico; no forma parte del inventario F1.
3. F1: completar revisión independiente, procedencia, grupos/campañas, sesgos, duplicados y etiquetas humanas de tipo, severidad y activo. Preservar originales y distinguir datos sintéticos, DEMO y predicciones.
4. F2: comparar prompts/versiones/parámetros en Desarrollo/Validación; sellar Prueba por grupos. Modelos locales entrenables solo si se justifican; nunca entrenar pesos de las APIs.
5. F2/F6: persistir por reporte proveedor/modelo, versión/hash del prompt y causa técnica real de conmutación, separados de `origen=fallback` y del motivo de revisión.
6. F3: métricas de calidad y percentiles con muestra adecuada y referencias humanas; no presentar las metas 0,85/0,70 como resultados.
7. F4/F6: ampliar la justificación con fragmentos verificables y compatibilidad del contrato; no atribuir causalidad o calibración no demostrada.
8. F5 y F7: reportes académicos y Optuna con límites de costo/tasa, sin despliegue automático.

## Dictamen de Fase 0

| Criterio de aceptación de F0 | Estado | Evidencia final |
| --- | --- | --- |
| Streamlit inicia correctamente | Cumple | Aplicación activa en 127.0.0.1:8502, HTTP 200 y tres páginas probadas con AppTest |
| Datasets existentes identificables y accesibles | Cumple | Siete fuentes registradas; originales con hash conservado y acceso protegido/auditado |
| Integración con servicios actuales | Cumple | Cinco servicios en ok, ciclo real aislado y auditoría de la interfaz sobre el backend activo |
| Groq/Gemini conservan configuración y fallback | Cumple | Proveedores/modelos/prompt/código conservados; referencias reparadas; dos probes reales y export equivalente |
| Credenciales protegidas | Cumple | Nombres de variables en export, JWT privado, manejo seguro de errores y escaneo sin valores reales |
| Pruebas aplicables aprobadas | Cumple | 101 pruebas, 102 subpruebas, un E2E real aislado, dos pruebas de workflow y comprobaciones reales adicionales |

Leyenda: cumplimiento de preparación e integración al cierre original de F0, no porcentaje de conformidad del sistema entero. Cómo leerlo: cada criterio se vincula a los resultados de esa entrega; el estado posterior del entorno se informa en el cierre de seguridad. Hallazgo clave calculado de la tabla: los seis criterios originales de F0 quedaron cubiertos. Limitación: la ampliación de contrato, la cobertura de privacidad que excede los casos probados y la evaluación académica conservan sus estados propios en la matriz.

**La Fase 0 concluyó cumpliendo sus criterios de aceptación.** Su cierre posterior de seguridad incorpora NF-02 dentro del alcance probado. El sistema completo conserva conformidad parcial por los objetivos posteriores y las garantías que todavía no se han verificado. La decisión de continuar requiere la orden del usuario y considerar el estado operacional registrado en `docs/SEGURIDAD_PRIVACIDAD.md`; esta corrección no inicia la Fase 1.
