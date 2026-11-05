# SOC Report Router

Plataforma local de clasificación y enrutamiento de reportes. El formulario React envía los datos a FastAPI. Langflow clasifica con Groq y respaldo de Gemini. FastAPI valida y guarda en PostgreSQL antes de invocar n8n. El workflow asigna el equipo y los plazos, y registra el aviso interno.

## Arranque en Windows PowerShell

El entorno preparado utiliza las instalaciones existentes de Python y Langflow. Docker Desktop ejecuta PostgreSQL 16, Redis y n8n. Las dependencias Python permanecen en .venv.

Desde la carpeta del proyecto:

    powershell -ExecutionPolicy Bypass -File .\Start-Soc.ps1

Para aplicar cambios del backend:

    powershell -ExecutionPolicy Bypass -File .\Start-Soc.ps1 -Restart

El comando muestra el progreso, compila React y comprueba la salud de los servicios. Las imágenes de Docker se descargan durante el primer arranque. Si falta node_modules, instala las dependencias con npm ci --prefix frontend. Para instalar las dependencias Python usa .\.venv\Scripts\python.exe -m pip install -r requirements.txt.

| Servicio | Dirección |
| --- | --- |
| Aplicación | http://127.0.0.1:8000/ |
| Documentación de API | http://127.0.0.1:8000/docs |
| Salud del flujo | http://127.0.0.1:8000/health |
| Langflow del proyecto | http://127.0.0.1:7861/ |
| n8n del proyecto en Docker | http://127.0.0.1:5680/ |
| PostgreSQL 16 | 127.0.0.1:5434 |
| Redis autenticado | 127.0.0.1:6380 |

Para detener los procesos y contenedores administrados por el proyecto:

    powershell -ExecutionPolicy Bypass -File .\Stop-Soc.ps1

El frontend lo sirve FastAPI desde frontend/dist. Las fuentes están en frontend/src. Se utilizan React 18, TypeScript, TailwindCSS y Recharts. El backend usa FastAPI, Pydantic y SQLAlchemy con psycopg.

La identidad visual se configura en frontend/src/tokens.css, con colores, tipografía Inter variable autoalojada, espaciado, radios y variantes de tema. Tailwind referencia estos tokens desde frontend/tailwind.config.js. Los iconos SVG locales y los componentes compartidos están en frontend/src/ui.tsx. La fuente se incluye mediante @fontsource-variable/inter y FastAPI sirve su archivo WOFF2 con el frontend compilado. El diseño funciona sin descargar recursos externos durante su uso. Para ajustar un color semántico, modifica su par claro/oscuro y verifica el contraste con su fondo correspondiente. Compila con npm run build --prefix frontend. El diagnóstico, las capturas comparativas y la evidencia de validación están en [docs/DISENO.md](docs/DISENO.md).

## Usuarios y permisos

Las credenciales iniciales generadas aleatoriamente están en .venv/soc-runtime/access.json. El comando de arranque muestra su ruta. Las contraseñas se guardan con PBKDF2 en la base de datos. El archivo local permite al propietario de este entorno consultar las credenciales iniciales.

| Rol | Permisos |
| --- | --- |
| Administrador | Reportes, cambios de estado, exportación, línea base, usuarios y auditoría |
| Analista | Consulta, reintentos, primera respuesta, resolución y tiempo de revisión |
| Gestor | Consulta de reportes, indicadores, exportación y registro de líneas base |
| Auditor | Lectura de la bitácora de auditoría |
| Solicitante | Enviar reportes y consultar su progreso en **Mis solicitudes** |

El administrador crea usuarios, cambia roles, restablece contraseñas y desactiva cuentas en Usuarios. Debe permanecer al menos un administrador activo. Cambiar un rol, contraseña o estado invalida los tokens previos de ese usuario.

Inicia sesión antes de enviar un reporte para vincularlo a tu cuenta. **Mis solicitudes** muestra la recepción, la asignación, la primera respuesta y la resolución de los reportes que enviaste con esa cuenta. Los envíos públicos conservan su comprobante y quedan sin propietario.

El acceso web usa JWT con vencimiento y sesiones revocables. Cerrar sesión invalida el token. Redis mantiene sesiones y límites de solicitudes. La interfaz mantiene el token de acceso en memoria y solicita un nuevo inicio de sesión después de recargar la página.

El encabezado histórico X-Operator-Token se conserva para compatibilidad con clientes anteriores si LEGACY_OPERATOR_ENABLED=true. En este entorno integrado está deshabilitado. Los endpoints internos mantienen X-Internal-Token y el webhook de n8n utiliza X-Webhook-Token. Sus secretos son independientes.

## Operación

En **Tablero del operador** se muestran hasta cuatro tarjetas por página en cada columna. Pulsa el encabezado de una columna para plegarla o desplegarla. Filtra los 100 reportes recientes por título o ID, estado, severidad, tipo, equipo, fecha o vencimiento. **Muestra del seeder** muestra los casos SOC-01 a SOC-06. **Ver detalle** abre la ficha con descripción, hitos y bitácora.

1. Desde la pantalla de acceso, elige Reportar sin iniciar sesión. Si ya ingresaste, elige Nuevo reporte en el menú lateral. Introduce un título y una descripción con el activo afectado.
2. Espera la confirmación con el ID. La clasificación externa puede tardar.
3. Inicia sesión y usa el menú lateral para abrir Tablero del operador, Dashboard e informes o los demás módulos de tu rol.
4. Las columnas Por atender, En atención y Resueltos muestran el avance.
5. El analista registra la primera respuesta cuando ocurre y después la resolución.
6. Ver detalle muestra las fechas, el origen, el motivo de revisión y la bitácora del caso.
7. El gestor puede descargar PDF, Word y Excel desde el tablero. Las exportaciones abarcan todos los reportes, con un máximo de 10000.

El idioma y el tema se seleccionan en la cabecera de acceso o al pie del menú lateral. En pantallas pequeñas, el botón Menú abre la navegación. El botón Asistente SOC abre un chat flotante en la esquina inferior derecha. FastAPI recibe los mensajes en POST /api/chat, consulta Groq y usa Gemini como respaldo ante errores del proveedor principal. Cada respuesta identifica al proveedor. El historial de la conversación permite preguntas de seguimiento y permanece en memoria mientras la página esté abierta.

Las claves GROQ_API_KEY y GEMINI_API_KEY están en .env y se usan desde el backend. CHAT_GROQ_MODEL y CHAT_GEMINI_MODEL seleccionan los modelos. CHAT_TIMEOUT_SECONDS limita la espera por proveedor y CHAT_LIMIT limita las solicitudes por IP y minuto. El navegador recibe el texto de la respuesta y el nombre del proveedor.

El chat envía al proveedor los mensajes que escribes y el contexto de uso de la aplicación. Sus instrucciones explican los equipos y SLA configurados. Los registros privados de reportes y los secretos del servidor quedan fuera del contexto del chat. La auditoría registra el acceso al endpoint sin guardar el cuerpo de la conversación.

## Clasificación y enrutamiento

El componente cloud del flujo activo de Langflow está en `integrations/langflow/cloud_classifier_model.py`. La clasificación devuelve tipo, severidad, activo afectado y confianza. Gemini cubre fallos de transporte, respuestas inválidas y errores del proveedor Groq. Una negativa explícita de política y una posible inyección se derivan a revisión. Una salida inválida o una confianza inferior al umbral vigente también deriva al equipo de revisión. El umbral inicial es 0,75. Para actualizar solo el componente del flujo local configurado, ejecuta `.\.venv\Scripts\python.exe .\scripts\update_langflow_component.py`.

El workflow de n8n está en integrations/n8n/assign_report.json. Los nodos HTTP usan host.docker.internal para llamar a FastAPI desde el contenedor. Asignaciones y plazos iniciales proceden de integrations/reglas.json. Un administrador puede publicar nuevas versiones en Operaciones → Reglas. Cada caso nuevo conserva la versión vigente en el momento de la clasificación y los reintentos reutilizan esa versión. La notificación es interna y queda en la bandeja.

El Idempotency-Key identifica el envío. El mismo ID con el mismo contenido devuelve el reporte existente. Cambiar el contenido con ese ID produce HTTP 409. Las restricciones de base de datos impiden duplicar la asignación y la notificación inicial.

Cuando n8n falla, el reporte se conserva. El operador puede usar Reintentar enrutamiento. Redis mantiene una cola de reintentos automáticos, y un proceso periódico recupera trabajo pendiente desde PostgreSQL. PostgreSQL sigue siendo la fuente de los pendientes aunque Redis se reinicie.

Los modos SQLite, clasificador demo y enrutador local siguen disponibles mediante DATABASE_URL vacío, REDIS_URL vacío, CLASSIFIER_MODE=demo y ROUTER_MODE=local. Los modos integrados se configuran en .env. La demo usa tablas equivalentes y almacenamiento SQL para sesiones y limitación de solicitudes cuando Redis no está configurado.

## Auditoría

La bitácora de cada reporte conserva sus eventos de negocio. audit_log registra entradas, salidas y accesos rechazados de la API, con identidad, rol, acción, módulo, IP, fecha y resultado HTTP. El cuerpo de las solicitudes y los secretos de autenticación quedan fuera de estos registros.

PostgreSQL tiene triggers para registrar cambios críticos en reportes, asignaciones, usuarios, eventos y mediciones. Otros triggers rechazan UPDATE, DELETE y TRUNCATE sobre audit_log. La protección cubre las operaciones de datos. Un administrador de la base de datos con privilegios para modificar el esquema conserva su autoridad de mantenimiento.

La vista Auditoría está restringida al administrador y al auditor. Permite filtrar por usuario, rol, módulo, acción, fechas, código HTTP y desenlace, con descarga en PDF, Word y Excel. Cada nueva solicitud auditada tiene un X-Request-ID. Las fases entry y exit comparten ese identificador y los rechazos 401 y 403 conservan también rejected. El resultado se guarda por separado del código HTTP. Las transiciones públicas y autenticadas generan module_enter y module_exit. Si el navegador pierde conexión o se cierra sin enviar la salida, el servidor infiere el cierre tras tres minutos sin renovación y lo marca `expirado`. Los registros históricos conservan su contenido.

## Dashboard, operaciones y permisos

Dashboard e informes agrega todos los casos del filtro por fechas de recepción en Lima, tipo, severidad y equipo. Los siete informes son cola operativa, SLA próximos o vencidos, asignaciones pendientes, cumplimiento mensual, tendencia, desempeño del clasificador y carga por equipo. Un SLA pendiente se considera próximo durante las cuatro horas previas a su vencimiento. La precisión compara tipo, severidad y activo con la última revisión humana. Muestra cuántos casos se revisaron, separa los casos DEMO y queda vacía sin validaciones. El histórico sintético de Evolución usa una tabla independiente.

| Acceso | Permisos |
| --- | --- |
| Administrador | Todos los módulos, cuentas y restablecimiento, directorio de equipos y publicación de reglas. |
| Analista | Tablero y atención, revisión de clasificación, activos, comentarios, adjuntos y registro de observaciones operativas. |
| Gestor | Consulta, informes, lectura de colaboración y líneas base. |
| Auditor | Auditoría filtrada y descargas de auditoría. |
| Cada cuenta | Perfil propio, cambio de contraseña y cierre de sesión. |

El bloqueo temporal por cuenta se activa después de cinco fallos durante quince minutos. El restablecimiento de administrador limpia el bloqueo. Cambiar o restablecer contraseña invalida las sesiones existentes. El JWT sigue en memoria y se requiere iniciar sesión después de recargar.

En **Mi perfil → Segundo factor** puedes activar TOTP con la contraseña actual y un código de la aplicación de autenticación. Guarda los códigos de recuperación al activar. Cada uno es de un solo uso y se muestra una sola vez. Activar o desactivar revoca las sesiones. El bootstrap genera una clave independiente en `.env` si falta. Conserva esa clave junto con el material privado de recuperación del servicio, por separado de los volcados de la base. Restaurar una base con cuentas TOTP requiere la clave que cifró sus semillas.

| API adicional | Uso |
| --- | --- |
| `GET /api/dashboard` y `GET /api/informes/{tipo}/{formato}` | Filtros `desde`, `hasta`, `tipo`, `severidad`, `equipo`. Formatos `pdf`, `docx`, `xlsx`. |
| `GET /api/audit/exportar/{formato}` y `POST /api/audit/navegacion` | Descarga filtrada y transiciones autenticadas. |
| `POST /api/auth/password` | Cambiar la contraseña propia con confirmación de la contraseña actual. |
| `GET /api/activos`, `GET /api/equipos`, `GET /api/reglas` | Catálogos y configuración versionada. Los contactos y disponibilidad son informativos. |
| `GET /api/revision` y `PUT /api/reportes/{id}/revision` | Confirmar o corregir sin modificar la predicción ni los SLA originales. |
| `GET /api/reportes/{id}/colaboracion` | Ver comentarios, adjuntos y revisión. Se admiten 10 archivos de hasta 2 MiB por caso. |
| `GET /api/notificaciones` y `PUT /api/notificaciones/{id}/leida` | Avisos internos con marca de lectura por usuario. |
| `GET /health?detalle=true` | Disponibilidad local y último resultado de Groq y Gemini con fecha, vigencia y un motivo resumido si falla. |
| `POST /api/salud/proveedores` | Administrador. Prueba los proveedores por separado con un mensaje sintético fijo y reutiliza el resultado durante cinco minutos. |
| `GET/POST /api/estudios-impacto` | Consulta y registro de estudios operativos. La creación requiere Gestor o Administrador. |

Para arrancar y verificar el entorno integrado desde PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\Start-Soc.ps1
Invoke-RestMethod 'http://127.0.0.1:8000/health?detalle=true'
```

El arranque espera hasta 600 segundos por los servicios locales y reconoce los procesos del proyecto que siguen iniciándose. `-TimeoutSeconds` permite cambiar el plazo. Para comprobar los proveedores cloud, usa **Operaciones → Salud** con una cuenta Administrador.

## Medición del triaje y SLA

Cada caso notificado registra el tiempo transcurrido desde la recepción hasta el aviso. Un gestor o administrador introduce al menos tres tiempos manuales en segundos para crear una línea base. Se conservan las muestras, el promedio, el autor y la fecha.

La estimación por caso comparable calcula:

    tiempo manual medio - tiempo del ciclo automático - tiempo de revisión humana

Los casos con revisión quedan fuera de la comparación hasta registrar el tiempo humano. Una cifra negativa muestra un incremento del tiempo. El indicador es una estimación basada en tiempos comparables de ciclo, y requiere muestras representativas para evaluar productividad real.

Las muestras creadas para demostración se marcan expresamente y la interfaz las identifica. El script de población genera una línea base sintética.

Los indicadores de SLA incluyen casos con el hito registrado o el plazo vencido. Los pendientes dentro del plazo todavía quedan fuera del cálculo. El tablero muestra los últimos 100 reportes y los indicadores usan todos los registros.

## Histórico de evolución DEMO

La vista Evolución muestra una serie mensual simulada de SLA y tiempo de triaje. Se identifica como DEMO en pantalla y en la respuesta de GET /api/impacto. La meta de SLA del 90 % es ilustrativa. La tabla incluye numeradores, denominadores y tiempos por caso para comprobar el cálculo.

Para preparar los seis meses completos anteriores al mes actual:

    .\.venv\Scripts\python.exe -m backend.manage seed-history

El comando es idempotente por periodo. Los agregados están en demo_impact_history, separados de reports, assignments y las líneas base reales. La fecha de creación refleja la carga actual y el campo period representa el mes simulado. Los eventos de auditoría conservan sus fechas reales de inserción.

En la serie inicial hay 40 casos por mes, una media manual de 15 minutos por caso y una reducción ilustrativa del ciclo automático más revisión desde 13,5 hasta 2,5 minutos. La respuesta a tiempo pasa del 55 % al 95 %, la resolución del 50 % al 92,5 % y el ahorro estimado de 1 a 8,33 horas mensuales. Estas cifras demuestran la visualización y las fórmulas. Acreditar impacto operacional requiere datos medidos comparables y un periodo representativo.

**DEMO · SLA manual frente a asistido** es un escenario independiente del histórico mensual. Compara 40 casos simulados de phishing de severidad media en septiembre de 2026 con 40 en octubre, con plazos de 4 horas para responder y 24 para resolver. La respuesta a tiempo pasa de 26/40 a 38/40 y la resolución pasa de 24/40 a 36/40. Ambos mejoran 30 puntos porcentuales frente a una meta ilustrativa de 15. El escenario se calcula en memoria y permanece separado de los estudios operativos.

## Medición operacional real

En **Evolución → Estudios de impacto operacional**, Gestor o Administrador define el tipo y severidad de los casos, periodos independientes en Lima, regla de muestreo, mínimo por grupo, plazos compartidos y meta de mejora para ambos SLA. Si los criterios se guardan cuando el periodo asistido ya comenzó, el estudio se identifica como retrospectivo.

Registra el tiempo humano activo en segundos. El grupo manual requiere una referencia externa y se registra cuando los hitos están documentados o sus plazos han vencido. El grupo asistido recupera los hitos del reporte operativo. Cada observación exige confirmar que el caso es real y cumple el criterio de muestreo. Se rechazan reportes DEMO, duplicados y casos fuera del periodo.

El informe presenta el tamaño de ambos grupos, hitos evaluables, cumplimiento y tiempos humanos. Solo muestra la comparación final al completar el periodo y alcanzar la muestra declarada. La diferencia de horas estima el ahorro observado en el conjunto asistido a partir de las medias de trabajo activo. Para demostrar impacto en la operación se necesitan registros reales de ambos grupos y una muestra representativa.

## Pruebas y datos de demostración

Pruebas locales, compilación y pruebas React:

    powershell -ExecutionPolicy Bypass -File .\Test-Soc.ps1

Pruebas adicionales con PostgreSQL, Redis, Langflow, Groq, Gemini y n8n reales. El script evalúa todos los grupos, conserva stdout y stderr en el registro y devuelve un código de salida distinto de cero si falla cualquier grupo:

    powershell -ExecutionPolicy Bypass -File .\Test-Soc.ps1 -Live

Preparar seis incidentes de práctica, dos por estado en la primera ejecución. Cada caso tiene un activo, contexto, alcance, evidencia y una nota de seguimiento. Dos casos incluyen un adjunto de laboratorio. La cuenta local `solicitante` envía los seis casos DEMO y puede seguir sus hitos en **Mis solicitudes**. Su campana abre **Avisos de mis solicitudes**, con las actualizaciones de asignación, primera respuesta y resolución. La interfaz y la evidencia del seeder muestran las fechas en hora de Perú.

    .\.venv\Scripts\python.exe -m backend.manage seed

Puedes usar `--count` para cargar una parte del catálogo, que tiene seis casos distintos. Repetir el comando reutiliza los mismos ID, completa los pasos pendientes y conserva los hitos ya registrados. Los resultados quedan en `.venv/soc-runtime/seed-evidence.json` para PostgreSQL o `seed-evidence-demo.json` para SQLite. Las pruebas integradas crean reportes temporales propios y conservan los eventos de auditoría que producen.

Para empezar de cero con los datos operativos de reportes, ejecuta `seed --reset`. Antes de borrar, crea una copia verificable en `.venv/soc-runtime/migration-backups`. Elimina reportes, asignaciones, bitácoras, adjuntos, comentarios, mediciones y muestras DEMO, y luego vuelve a cargar los seis casos y el histórico DEMO. Conserva las cuentas y su acceso, la configuración, los activos y equipos, y `audit_log`, que es inmutable. **No uses `--reset` si necesitas conservar reportes actuales.**

    .\.venv\Scripts\python.exe -m backend.manage seed --reset

## Evaluación con incidentes históricos de VERIS VCDB

El comando de evaluación reproduce incidentes públicos por la API del formulario. Cada corrida conserva sus resultados en una base dedicada. La corrida integrada crea PostgreSQL y n8n en un proyecto Docker independiente, con su propia copia del workflow y sus propios tokens. Usa el clasificador Langflow del SOC configurado en .env. Los textos revisados pasan a los proveedores cloud de ese flujo. Los indicadores operativos de la instalación principal quedan separados de esta evaluación.

En PowerShell, desde la raíz del proyecto, descarga la revisión fijada y revisa los candidatos:

    New-Item -ItemType Directory -Force .\tmp\datasets-real | Out-Null
    curl.exe -fL https://codeload.github.com/vz-risk/VCDB/zip/f6f98c00f66ab35f5b49977a5852ce94a5bb31d1 -o .\tmp\datasets-real\vcdb-f6f98c0.zip
    powershell -ExecutionPolicy Bypass -File .\Test-SocDataset.ps1 -DryRun -Archive .\tmp\datasets-real\vcdb-f6f98c0.zip

El modo de inspección funciona sin servicios y verifica SHA-256. El archivo `.venv/soc-runtime/dataset/preview.json` conserva las exclusiones, los identificadores, las fuentes y los tipos sugeridos. Las etiquetas se infieren de las acciones VERIS y requieren revisión. La muestra piloto de ocho incidentes contiene paráfrasis en español de resúmenes retrospectivos. Su finalidad es verificar el flujo. Los datos derivados del piloto se distribuyen con atribución bajo [CC BY-SA 4.0, licencia de VCDB](https://github.com/vz-risk/VCDB/blob/f6f98c00f66ab35f5b49977a5852ce94a5bb31d1/LICENSE.txt).

Para ejecutar el piloto integrado, inicia el Langflow del proyecto y compila el frontend si falta `frontend/dist`. Ejecuta:

    powershell -ExecutionPolicy Bypass -File .\Test-SocDataset.ps1 -Run -VerifyRecovery -RunId vcdb-pilot-docker -Archive .\tmp\datasets-real\vcdb-f6f98c0.zip -ReviewedCases .\integrations\dataset\vcdb-pilot.json

`-VerifyRecovery` comprueba guardado durante un corte del n8n aislado, reintento, repetición, conflicto por cambio de contenido y registro de ambos hitos. Para probar sin Docker con PostgreSQL y n8n ya instalados en Windows, agrega `-Native` y usa otro ID. Este modo requiere `pg_ctl`, `node` y la instalación npm de `n8n` en PATH. Para usar SQLite, clasificador demo y enrutamiento local, agrega `-Local` y omite `-VerifyRecovery`.

Cada ejecución escribe `.venv/soc-runtime/dataset/<RunId>/results.json` con los casos, ID de reporte, predicciones, origen, proveedor cuando Langflow lo informa, eventos, comprobaciones SQL, plazos, latencias y métricas. Repite el mismo comando para reanudar con la misma muestra y configuración. Usa otro ID al cambiar modo, muestra o implementación. Los servicios propios de la corrida se detienen al finalizar. Las bases separadas se conservan para reanudación y auditoría.

Para una muestra del artículo, prepara un JSON con la estructura del piloto y `stage: "holdout"`. Documenta el tamaño y el método de muestreo en `sampling`, separa las campañas del piloto en `group`, y registra dos revisores distintos por caso. Ante una discrepancia, documenta la decisión en `adjudication`. Usa `initial_public_report` cuando el texto proceda de la primera fuente disponible y `retrospective_summary` cuando proceda de un resumen posterior. Revisa cada descripción y título para retirar datos sensibles antes de aprobar el envío. El programa admite severidad y activo de referencia cuando los revisores disponen de evidencia para etiquetarlos.

El módulo `scripts.vcdb_review` permite preparar el manifiesto por etapas sin iniciar servicios. La preselección usa una semilla fija, excluye casos piloto y evita fuentes compartidas. Para generar una cola nueva, usa `select` con `--per-type`. Si ya tienes la cola local, empieza en `init`:

    $py = '.\.venv\Scripts\python.exe'
    $dir = '.\.venv\soc-runtime\dataset'
    $zip = '.\tmp\datasets-real\vcdb-f6f98c0.zip'
    & $py -m scripts.vcdb_review select --archive $zip --per-type 40 --output "$dir\holdout-review-queue.json"
    & $py -m scripts.vcdb_review init --queue "$dir\holdout-review-queue.json" --output "$dir\holdout-preparation.json"

En la plantilla de preparación, cada fila debe quedar como `include` o `exclude` en `disposition`. Para excluir, escribe el motivo en `exclusion_reason`. Para incluir, registra la fuente, el grupo, el tipo de fuente, el título y la descripción redactados y confirma `redaction_reviewed`. Luego genera el paquete:

    & $py -m scripts.vcdb_review packet --archive $zip --queue "$dir\holdout-review-queue.json" --preparation "$dir\holdout-preparation.json" --output "$dir\holdout-packet"

Comparte `blinded-cases.json` y una planilla distinta con cada revisor. Cada persona rellena su `reviewer` y el `tipo` de todos los casos. Conserva `packet.json` con el coordinador. Si hay discrepancias, registra cada decisión en un JSON con el ID del caso como clave y un objeto con `tipo` y `reason` como valor. La huella del paquete vincula las dos planillas con los textos evaluados.

    & $py -m scripts.vcdb_review freeze --archive $zip --packet "$dir\holdout-packet\packet.json" --review-a "$dir\holdout-packet\review-a.json" --review-b "$dir\holdout-packet\review-b.json" --output "$dir\holdout-reviewed.json"

Si hay discrepancias, añade `--adjudication` con la ruta de ese JSON. Una vez congelado, pasa `holdout-reviewed.json` a `Test-SocDataset.ps1 -Run` mediante `-ReviewedCases` y usa un `RunId` nuevo. Mantén los formularios separados y archívalos junto con el registro de exclusiones para conservar la trazabilidad del estudio.

La evaluación compara tipos con las reglas demo sobre los mismos textos y calcula cobertura, error entre los casos aceptados automáticamente y F1 macro entre las clasificaciones evaluables. Registra por separado fallos de servicio y motivos de revisión. Los plazos se verifican contra la política del sistema. El piloto y las corridas retrospectivas carecen de hitos operativos comparables para estimar horas de trabajo humano ahorradas o mejoras reales de SLA.

## Datos y configuración

El entorno usa PostgreSQL 16 en Docker. La instalación PostgreSQL 18 original y sus archivos permanecen disponibles como origen de la migración. La copia de datos previa está en .venv/soc-runtime/postgres-before-platform.json. La configuración previa está en .venv/soc-runtime/env-before-platform.backup. Contienen información local del proyecto y deben tratarse como privadas.

scripts/migrate_pg16.py copia las tablas originales, verifica sus filas y solo después cambia DATABASE_URL. scripts/prepare_containers.py prepara las credenciales locales y una copia de la base de n8n para el contenedor. El workflow de esa copia utiliza los callbacks hacia FastAPI desde Docker.

Antes de cambiar el esquema de una base existente, el arranque genera un respaldo verificado. PostgreSQL usa un archivo custom y valida su catálogo. El contenedor del proyecto utiliza las herramientas PostgreSQL de su propia versión. SQLite usa la API de copia y `integrity_check`. Si el respaldo falla, el cambio se cancela. Las copias quedan en `.venv/soc-runtime/migration-backups` para PostgreSQL o en `migration-backups` junto al archivo SQLite. La prueba integrada restaura una copia en una base temporal y comprueba la inmutabilidad de la auditoría restaurada.

.env conserva la configuración del modelo y los secretos de los servicios. compose.env y access.json están dentro de .venv. Los directorios de datos se montan de forma persistente. Stop-Soc.ps1 detiene los servicios sin eliminar esos directorios.

WeasyPrint genera PDF reutilizando las bibliotecas GTK/Pango de Tesseract instaladas en este PC. WEASYPRINT_DLL_DIRECTORIES y FONTCONFIG_FILE se configuran durante el bootstrap.
