**Checklist de evaluación del Proyecto 06**

Evaluación del 3 de noviembre de 2026, zona America/Lima.

El proyecto implementa el flujo de clasificación y enrutamiento. La auditoría de rechazos ya registra entrada y salida. La vista Evolución presenta seis meses simulados y los dos impactos operativos siguen pendientes de evidencia real.

Fuente normativa. [Cartera de proyectos n8n LangChain LangFlow](<C:/Users/USERJSSV/Downloads/38833FF26BA1D.UnigramPreview_g9c9v27vpyspw!App/Cartera de proyectos-n8n-LangChain-LangFlow.docx>), ficha 6 y la segunda sección Plataforma común, aplicable a todos los casos.

Los estados tienen este significado.

- **Cumple** indica que la característica exigida está implementada y cuenta con evidencia de código o pruebas. Las incidencias de integración se registran expresamente en filas separadas.
- **No cumple** indica que el criterio evaluado falló, presenta una diferencia literal o carece de evidencia suficiente. La observación identifica cuál de esas situaciones aplica.
- **Adicionado** identifica una característica implementada que la ficha 06 y la plataforma común no piden expresamente.

El flujo de referencia se materializa como formulario web → entrada HTTP de FastAPI → Langflow → PostgreSQL → n8n → aviso interno → bitácora.

Las filas I02 e I05 evalúan los impactos declarados por la ficha. Los indicadores y el cálculo están implementados, mientras que la demostración de beneficios reales requiere datos operativos. S14 utiliza una lectura estricta de cada entrada y salida, incluidos rechazos de autenticación.

**Características mínimas de la ficha 06**

| ID | Característica evaluada | Estado | Evidencia y observación |
| --- | --- | --- | --- |
| F01 | Formulario web para recibir reportes | **Cumple** | Formulario React con título y descripción y envío HTTP. [frontend/src/main.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/main.tsx:145) |
| F02 | Recepción mediante webhook o endpoint HTTP | **Cumple** | POST /api/reportes en FastAPI recibe el formulario. Equivale a la entrada HTTP de la ficha. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:190) |
| F03 | Langflow como clasificador LLM | **Cumple** | Flujo importado y ejecución API v1. Su prueba directa con proveedores reales pasó. Ver F15 para la incidencia integrada. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:71) |
| F04 | Clasificar el tipo de incidente | **Cumple** | Campo tipo validado contra las diez categorías admitidas. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:12) |
| F05 | Clasificar la severidad | **Cumple** | Campo severidad validado con valores crítica, alta, media y baja. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:17) |
| F06 | Identificar el activo afectado | **Cumple** | Campo activo_afectado validado y mostrado en el detalle. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:25) |
| F07 | Persistir en PostgreSQL antes del enrutamiento | **Cumple** | save_report se ejecuta antes de dispatch y la llamada a n8n. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:191) |
| F08 | Tabla principal reports | **Cumple** | Guarda reporte, clasificación, confianza y fechas. [db/schema.sql](C:/Users/USERJSSV/Downloads/soc-report-router/db/schema.sql:1) |
| F09 | Tabla principal assignments | **Cumple** | Guarda responsable, asignación, dos plazos y dos hitos. [db/schema.sql](C:/Users/USERJSSV/Downloads/soc-report-router/db/schema.sql:18) |
| F10 | Asignación por reglas | **Cumple** | Reglas por categoría, severidad y revisión. La prueba JavaScript recorre la matriz de equipos y SLA. [integrations/reglas.json](C:/Users/USERJSSV/Downloads/soc-report-router/integrations/reglas.json:1) |
| F11 | n8n asigna el responsable | **Cumple** | Workflow consulta contexto, aplica reglas y llama al endpoint de asignación. Verificado también durante recuperación. [integrations/n8n/assign_report.json](C:/Users/USERJSSV/Downloads/soc-report-router/integrations/n8n/assign_report.json:1) |
| F12 | n8n fija los SLA | **Cumple** | Calcula plazos con las reglas y se guardan en assignments. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:136) |
| F13 | Notificación tras la asignación | **Cumple** | Aviso interno en la bandeja, con actor n8n. La ficha deja abierto el canal de notificación. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:151) |
| F14 | Bitácora del flujo de negocio | **Cumple** | Eventos de recepción, clasificación, asignación, notificación, incidencias y hitos. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:91) |
| F15 | Aceptación integrada actual del flujo completo con un reporte válido | **No cumple** | La reevaluación produjo otro / fallback / langflow_no_disponible en lugar de phishing / langflow. El reporte se conservó, pero esta prueba real falló. [tests/live_soc.py](C:/Users/USERJSSV/Downloads/soc-report-router/tests/live_soc.py:74) |

**Tecnologías de la plataforma común**

| ID | Característica evaluada | Estado | Evidencia y observación |
| --- | --- | --- | --- |
| T01 | React 18 | **Cumple** | Dependencia React 18.3.x y componentes TSX compilados. [frontend/package.json](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/package.json:11) |
| T02 | TypeScript | **Cumple** | Compilación tsc --noEmit aprobada. [frontend/tsconfig.json](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/tsconfig.json:1) |
| T03 | TailwindCSS | **Cumple** | Configuración y directivas Tailwind incorporadas al CSS compilado. [frontend/tailwind.config.js](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/tailwind.config.js:1) |
| T04 | Recharts y gráficos del dashboard | **Cumple** | Gráfico de reportes por tipo y contenedor adaptable. [frontend/src/main.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/main.tsx:169) |
| T05 | FastAPI | **Cumple** | Punto de entrada de la web y API del sistema. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:77) |
| T06 | SQLAlchemy | **Cumple** | Engine, pooling y consultas parametrizadas con SQLAlchemy Core. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:34) |
| T07 | Pydantic | **Cumple** | Valida entradas, clasificación, usuarios, línea base y mensajes. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:28) |
| T08 | n8n en Docker | **Cumple** | Servicio n8n definido y ejecutado en Compose. [compose.yaml](C:/Users/USERJSSV/Downloads/soc-report-router/compose.yaml:33) |
| T09 | Langflow como servicio separado | **Cumple** | Servicio local independiente en el puerto 7861, consumido por HTTP. [Start-Soc.ps1](C:/Users/USERJSSV/Downloads/soc-report-router/Start-Soc.ps1:82) |
| T10 | PostgreSQL 16 | **Cumple** | Versión 16.15 comprobada en esta revisión. [compose.yaml](C:/Users/USERJSSV/Downloads/soc-report-router/compose.yaml:4) |
| T11 | Redis para caché | **Cumple** | Cachea indicadores y utiliza invalidación y TTL. [backend/runtime.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/runtime.py:18) |
| T12 | Redis para colas | **Cumple** | Cola ordenada de pendientes con bloqueo y recuperación desde PostgreSQL. [backend/runtime.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/runtime.py:39) |
| T13 | Redis para limitación de solicitudes | **Cumple** | Contador atómico por IP y ventana de tiempo para login, reportes y chat. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:71) |
| T14 | Redis para sesiones | **Cumple** | Mantiene sesiones JWT con expiración y comprueba su vigencia. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:93) |
| T15 | Autenticación JWT | **Cumple** | Firma HS256, expiración, emisor, audiencia y verificación de sesión. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:121) |
| T16 | Módulo RBAC propio | **Cumple** | Matriz de permisos propia aplicada en el servidor. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:19) |
| T17 | PDF mediante WeasyPrint | **Cumple** | Exportación real aprobada. El PDF también se renderizó y revisó en el trabajo anterior. [backend/exports.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/exports.py:33) |
| T18 | Word mediante python-docx | **Cumple** | DOCX descargado y abierto con python-docx en la prueba real. [backend/exports.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/exports.py:33) |
| T19 | Excel mediante openpyxl | **Cumple** | XLSX descargado y abierto con openpyxl en la prueba real. [backend/exports.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/exports.py:33) |
| T20 | Exportaciones mediante librerías open source y ejecución independiente de Office | **Cumple** | Generación desde Python y bibliotecas declaradas en requirements. [requirements.txt](C:/Users/USERJSSV/Downloads/soc-report-router/requirements.txt:1) |

**Roles y auditoría transversal**

| ID | Característica evaluada | Estado | Evidencia y observación |
| --- | --- | --- | --- |
| S01 | Rol Administrador | **Cumple** | Gestiona usuarios, roles, reportes, líneas base, exportaciones y auditoría. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:19) |
| S02 | Rol Analista | **Cumple** | Consulta y atiende casos, registra hitos y reintenta enrutamiento. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:19) |
| S03 | Rol Gestor limitado a dashboards y reportes | **Cumple** | Consulta, exporta y registra líneas base del ámbito de indicadores. Carece de permisos para atender casos o administrar usuarios. [backend/platform.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/platform.py:100) |
| S04 | Rol Auditor con lectura de bitácora | **Cumple** | Acceso a auditoría y bitácora. La API rechaza consulta general de reportes y gestión de usuarios para este rol. [tests/live_platform.py](C:/Users/USERJSSV/Downloads/soc-report-router/tests/live_platform.py:42) |
| S05 | Permisos comprobados en backend | **Cumple** | Respuestas 403 por rol verificadas mediante API real. [tests/live_platform.py](C:/Users/USERJSSV/Downloads/soc-report-router/tests/live_platform.py:42) |
| S06 | Tabla audit_log | **Cumple** | Existe separada de la bitácora de eventos del reporte. [db/schema.sql](C:/Users/USERJSSV/Downloads/soc-report-router/db/schema.sql:58) |
| S07 | Middleware de auditoría FastAPI | **Cumple** | Intercepta rutas /api/ e /internal/. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:83) |
| S08 | Identidad del usuario en auditoría | **Cumple** | user_id identifica al usuario, al servicio o al acceso público. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:235) |
| S09 | Rol en auditoría | **Cumple** | Se registra junto a la identidad. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:235) |
| S10 | Acción y módulo en auditoría | **Cumple** | Registra método HTTP y ruta, además de acciones SQL de los triggers. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:235) |
| S11 | IP en auditoría | **Cumple** | Registra la IP de la conexión recibida. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:87) |
| S12 | Fecha y hora en auditoría | **Cumple** | occurred_at con marca de tiempo. [db/schema.sql](C:/Users/USERJSSV/Downloads/soc-report-router/db/schema.sql:65) |
| S13 | Registro de entrada y salida en operaciones normales de la API | **Cumple** | Fases entry y exit con resultado HTTP. Prueba específica aprobada. [tests/test_platform.py](C:/Users/USERJSSV/Downloads/soc-report-router/tests/test_platform.py:76) |
| S14 | Cobertura de entrada y salida de la API, incluidos accesos rechazados | **Cumple** | Una solicitud real con token inválido generó entry, rejected 401 y exit 401 con el mismo ID `455f9dc6-c4b3-405c-b468-ec0cf36906ec` en PostgreSQL. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:84) |
| S15 | Bloqueo de UPDATE en audit_log | **Cumple** | Trigger lo rechaza. Probado contra PostgreSQL real. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:221) |
| S16 | Bloqueo de DELETE en audit_log | **Cumple** | Trigger lo rechaza. Probado contra PostgreSQL real. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:221) |
| S17 | Triggers PostgreSQL para cambios críticos | **Cumple** | Cubren reports, assignments, users, bitacora, triage_baselines y triage_measurements, con INSERT, UPDATE y DELETE. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:226) |

**Indicadores e impactos mencionados en la ficha**

| ID | Característica evaluada | Estado | Evidencia y observación |
| --- | --- | --- | --- |
| I01 | Configurar y medir cumplimiento de SLA | **Cumple** | Indicadores separados de respuesta y resolución, con reglas de casos evaluables. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:175) |
| I02 | Demostrar el impacto operacional de SLA cumplido | **No cumple** | Evolución muestra una mejora simulada de mayo a octubre de 2026, con meta ilustrativa del 90 %. La acreditación real requiere un periodo operativo representativo y una meta acordada. [ImpactPanel.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/ImpactPanel.tsx) |
| I03 | Medir ciclo automático, línea base y revisión humana | **Cumple** | Conserva muestras manuales, promedio, autor y tiempos por caso. [db/schema.sql](C:/Users/USERJSSV/Downloads/soc-report-router/db/schema.sql:80) |
| I04 | Calcular horas estimadas de triaje ahorradas | **Cumple** | Compara línea base, tiempo de ciclo y revisión humana. Excluye revisiones sin medir. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:276) |
| I05 | Demostrar horas reales de triaje manual ahorradas | **No cumple** | El histórico simula un ahorro estimado de 1 a 8,33 horas mensuales. PostgreSQL registra cero líneas base reales. Falta comparar tiempos manuales medidos con casos automatizados equivalentes. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:297) |

**Características adicionadas**

| ID | Característica evaluada | Estado | Evidencia y observación |
| --- | --- | --- | --- |
| A01 | Modo claro y oscuro | **Adicionado** | Seleccionable en la cabecera. [frontend/src/main.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/main.tsx:10) |
| A02 | Tema del sistema y preferencias persistentes | **Adicionado** | Guarda idioma y tema en el navegador. [frontend/src/main.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/main.tsx:33) |
| A03 | Interfaz español e inglés | **Adicionado** | Textos traducidos y selector de idioma. [frontend/src/i18n.ts](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/i18n.ts:1) |
| A04 | Tablero de tres columnas | **Adicionado** | Por atender, En atención y Resueltos. [frontend/src/main.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/main.tsx:174) |
| A05 | Filtros de reportes | **Adicionado** | Todos, pendientes, revisión y resueltos. [frontend/src/api.ts](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/api.ts:24) |
| A06 | Chat flotante inferior derecho | **Adicionado** | Ventana con apertura, cierre y controles accesibles. Respaldo por pruebas React y CSS. [frontend/src/ChatWidget.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/ChatWidget.tsx:14) |
| A07 | Chat con Groq y respaldo Gemini | **Adicionado** | Prueba real de Groq y de Gemini con fallo de transporte de Groq provocado. [backend/chat.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/chat.py:91) |
| A08 | Contexto conversacional y proveedor visible | **Adicionado** | Envía contexto acotado y muestra Groq o Gemini en la respuesta. [frontend/src/ChatWidget.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/ChatWidget.tsx:35) |
| A09 | Chat bilingüe y reintentos | **Adicionado** | Instrucciones por idioma y reintento de la misma pregunta sin duplicarla. [frontend/src/ChatWidget.tsx](C:/Users/USERJSSV/Downloads/soc-report-router/frontend/src/ChatWidget.tsx:26) |
| A10 | Respaldo Gemini en la clasificación | **Adicionado** | El flujo de Langflow utiliza Groq y respaldo Gemini. La ficha 06 deja abierto el proveedor del LLM. [integrations/langflow/cloud_classifier_model.py](C:/Users/USERJSSV/Downloads/soc-report-router/integrations/langflow/cloud_classifier_model.py:26) |
| A11 | Confianza de la clasificación | **Adicionado** | Campo numérico validado entre cero y uno. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:31) |
| A12 | Triaje por confianza inferior a 0.75 | **Adicionado** | Deriva a Triaje SOC y conserva el motivo de revisión. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:102) |
| A13 | Triaje por salida inválida o proveedor no disponible | **Adicionado** | Conserva el caso y aplica revisión manual. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:92) |
| A14 | Detección básica de instrucciones sospechosas | **Adicionado** | Identifica patrones de posible inyección y deriva a revisión. [backend/classifier.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/classifier.py:19) |
| A15 | Idempotencia del envío | **Adicionado** | La misma clave y contenido recuperan el mismo reporte. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:191) |
| A16 | Conflicto al reutilizar clave con otro contenido | **Adicionado** | Respuesta HTTP 409. [backend/main.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/main.py:204) |
| A17 | Asignación y notificación inicial únicas | **Adicionado** | Claves y restricciones impiden duplicarlas al repetir webhook o envío. [db/schema.sql](C:/Users/USERJSSV/Downloads/soc-report-router/db/schema.sql:18) |
| A18 | Enrutamiento pendiente y reintento manual | **Adicionado** | Caso conservado durante la caída controlada de n8n y recuperado al restaurarlo. [tests/live_recovery.py](C:/Users/USERJSSV/Downloads/soc-report-router/tests/live_recovery.py:15) |
| A19 | Dos hitos operativos | **Adicionado** | Primera respuesta y resolución registradas desde la bandeja. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:158) |
| A20 | Sesiones revocables | **Adicionado** | Logout y cambios de usuario invalidan accesos previos. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:162) |
| A21 | Contraseñas con PBKDF2 y sal aleatoria | **Adicionado** | Hash con 600000 iteraciones. [backend/security.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/security.py:30) |
| A22 | Protección del último administrador activo | **Adicionado** | Impide desactivar o degradar al último administrador. [backend/platform.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/platform.py:80) |
| A23 | Bloqueo de TRUNCATE en audit_log | **Adicionado** | Extiende la protección de UPDATE y DELETE indicada expresamente en el documento. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:221) |
| A24 | Paginación de auditoría | **Adicionado** | Consulta de registros anteriores con cursor. [backend/db.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/db.py:244) |
| A25 | Modos SQLite, clasificador demo y enrutador local | **Adicionado** | Permiten pruebas aisladas y operación de demostración. [backend/config.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/config.py:14) |
| A26 | Arranque y parada desde PowerShell | **Adicionado** | Scripts que muestran progreso y administran los servicios del proyecto. [Start-Soc.ps1](C:/Users/USERJSSV/Downloads/soc-report-router/Start-Soc.ps1:1) |
| A27 | Población DEMO y ejecuciones repetidas | **Adicionado** | Semilla de doce casos, reenvíos idempotentes y varios estados. [backend/manage.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/manage.py:51) |
| A28 | Migración con verificación de datos | **Adicionado** | Copia y cotejo de tablas originales antes del cambio a PostgreSQL 16. [scripts/migrate_pg16.py](C:/Users/USERJSSV/Downloads/soc-report-router/scripts/migrate_pg16.py:1) |
| A29 | Credenciales del lado servidor | **Adicionado** | Secretos en configuración local y campos SecretStr para el chat. [backend/config.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/config.py:32) |
| A30 | Batería automatizada local y real | **Adicionado** | Ejecuta todos los grupos, conserva su salida y devuelve un código de error si falla alguno. [Test-Soc.ps1](C:/Users/USERJSSV/Downloads/soc-report-router/Test-Soc.ps1:1) |
| A31 | Evolución mensual de SLA y ahorro de triaje | **Adicionado** | Seis meses DEMO, 240 casos simulados y tabla con los recuentos y tiempos del cálculo. El histórico se almacena aparte de los reportes operativos. [backend/manage.py](C:/Users/USERJSSV/Downloads/soc-report-router/backend/manage.py) |

**Resumen de la checklist**

La checklist contiene 88 filas. 54 se marcan Cumple, 3 No cumple y 31 Adicionado. La ficha no establece pesos para convertir estas filas en un porcentaje de cumplimiento.

**Verificación tras la corrección**

La ejecución del 3 de noviembre de 2026 evaluó los 63 tests. Pasaron 62, incluidas las seis pruebas de plataforma real y la recuperación de n8n. La prueba F15 volvió a devolver `langflow_no_disponible` para un reporte válido. Los demás grupos terminaron con código 0. [Registro completo](C:/Users/USERJSSV/Downloads/soc-report-router/.venv/soc-runtime/test-results/soc-tests-20261103-124757.log)

**Resultados de la evaluación anterior**

| Grupo | Entorno y alcance | Aprobadas | Fallidas |
| --- | --- | --- | --- |
| Python | SQLite y proveedores simulados | 35 | 0 |
| Reglas n8n | Código JavaScript de reglas | 2 | 0 |
| React | Componentes con API simulada, más compilación TypeScript | 6 | 0 |
| Flujo SOC | PostgreSQL, Langflow, Groq, Gemini y n8n reales | 3 | 1 |
| Plataforma | Roles, Redis, PostgreSQL 16, exportaciones y triggers reales | 4 | 0 |
| Chat | Groq real y Gemini real con fallo de Groq provocado | 2 | 0 |
| Recuperación | Parada del n8n del proyecto, persistencia y restauración reales | 1 | 0 |
| Total | Todos los grupos evaluados | **53** | **1** |

El script principal se detuvo tras el fallo de live_soc. Los tres grupos restantes se ejecutaron por separado y finalizaron correctamente. La prueba fallida esperaba phishing / langflow / sin motivo de revisión y recibió otro / fallback / langflow_no_disponible. La clasificación directa del flujo y el caso de revisión de seguridad sí pasaron. La causa de la indisponibilidad del flujo activo requiere diagnóstico.

[Salida completa del primer tramo](C:/Users/USERJSSV/Downloads/soc-report-router/.venv/soc-runtime/checklist-tests-20261103.log).

[Salida completa de los grupos restantes](C:/Users/USERJSSV/Downloads/soc-report-router/.venv/soc-runtime/checklist-tests-restantes-20261103.log).

[Comprobaciones anteriores a la corrección de auditoría](C:/Users/USERJSSV/Downloads/soc-report-router/.venv/soc-runtime/checklist-runtime-evidence.json).

El transcript de la ejecución anterior conservaba encabezados sin la salida nativa completa. Para esta checklist se generaron los dos archivos de salida anteriores mediante redirección explícita.

**Pendientes para cerrar la evaluación integral**

1. F15. Diagnosticar el fallo del flujo activo de Langflow observado desde FastAPI, corregir su causa y comprobar el caso válido de forma reproducible.
2. I02. Reunir un periodo operativo representativo y definir el criterio con el que se acreditará el impacto sobre cumplimiento de SLA.
3. I05. Registrar muestras reales de triaje manual y compararlas con casos automatizados equivalentes, incluyendo la revisión humana.

**Alcance y condiciones**

- La notificación implementada es interna y visible en la bandeja. La ficha 06 permite evaluar ese canal.
- La ficha 06 elige Langflow. La mención de pgvector en la plataforma común está condicionada a RAG. El chat incorporado se evalúa como una función adicional.
- La cobertura de inmutabilidad corresponde a las operaciones de datos protegidas por los triggers. El administrador de PostgreSQL conserva sus capacidades de mantenimiento del esquema.
- El tablero muestra los últimos 100 reportes. Los indicadores consideran todos los registros y las exportaciones admiten hasta 10000.
- La interfaz se respalda en pruebas React y revisión del código. La inspección visual del navegador sigue pendiente.
- Las comprobaciones de salud devolvieron HTTP 200 para FastAPI, Langflow y n8n, y Redis respondió PING. La versión PostgreSQL observada fue 16.15. Esas comprobaciones de salud coexisten con el fallo de clasificación integrada consignado en F15.
- La captura de datos encontró cero líneas base reales y una línea base DEMO. Los datos de demostración permiten evaluar funciones y no acreditan ahorro operacional real.
