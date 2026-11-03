# Revalidación de SOC Report Router

**Actualizado** 3 de noviembre de 2026, hora de Lima. **Entorno** Windows y PowerShell.

## Checklist vigente del Proyecto 06

| Estado | Requisito | Evidencia actual |
| --- | --- | --- |
| Cumple | React 18, TypeScript, TailwindCSS y Recharts | Compilación aprobada y dashboard disponible. |
| Cumple | FastAPI, SQLAlchemy y Pydantic | API, persistencia y validación. |
| Cumple | PostgreSQL 16, Redis y n8n en Docker, con Langflow independiente | Los cinco servicios, incluido FastAPI, respondieron `ok` después de rotar la clave. |
| Cumple | Redis para caché, colas, sesiones y límites | Pruebas reales de plataforma y recuperación tras reiniciar Redis. |
| Cumple | Flujo de reporte, clasificación, asignación y aviso | Groq clasificó en Langflow. PostgreSQL guardó el reporte y n8n asignó y notificó. |
| Cumple | Contingencia de clasificación y triaje | Baja confianza, respuesta inválida, error de proveedor e inyección se derivan a revisión. Los escenarios se cubrieron con pruebas locales y el desvío de contenido sospechoso se verificó en la pila real. |
| Cumple | Respaldo Gemini en el clasificador y el chat | La última rotación en FastAPI y Langflow pasó tres pruebas reales. Gemini clasificó en Langflow tras un timeout y un HTTP 400 simulados de Groq, y respondió como respaldo en el chat. |
| Cumple | Idempotencia, SLA y recuperación | Diez reenvíos devolvieron el mismo reporte, el cambio de contenido devolvió 409 y la recuperación tras reiniciar n8n y Redis conservó una asignación y un aviso. |
| Cumple | JWT, gestión de usuarios y cuatro roles | Permisos en servidor, baja lógica, bloqueo temporal, revocación y protección del último administrador. |
| Cumple | Perfil y TOTP opcional | Cambio de contraseña y TOTP con semilla cifrada y recuperación de un solo uso. Alta y revocación verificadas en PostgreSQL real. |
| Cumple | Auditoría de API y rechazos | `entry`, `rejected` y `exit` correlacionados. Los eventos nuevos distinguen resultado y código HTTP. |
| Cumple | Auditoría de navegación | Entradas públicas y autenticadas, salidas observadas y salidas inferidas por expiración identificadas como tales. |
| Cumple | Triggers, inmutabilidad y consulta de auditoría | PostgreSQL rechazó `UPDATE`, `DELETE` y `TRUNCATE` directos. Auditoría filtrada y descargable por Administrador y Auditor. |
| Cumple | Dashboard, filtros y revisión humana | Indicadores sobre todo el conjunto, comparación con SQL, precisión con revisión humana y separación DEMO. |
| Cumple | Siete informes en PDF, Word y Excel | Se abrieron 42 archivos filtrados y se confirmó su auditoría. La generación se realiza con bibliotecas de Python. |
| Cumple | Permisos de exportación | Gestor y Administrador exportan informes de casos. Auditor y Administrador exportan auditoría. Validado por API y pruebas de interfaz. |
| Cumple | Activos, equipos, reglas y umbral | Catálogos, carga por equipo, versiones de asignación y SLA, y umbral configurable. |
| Cumple | Colaboración y avisos | Comentarios, adjuntos y notificaciones con marca de lectura por usuario. |
| Cumple | Diagnóstico de salud | Estado de la pila local y diagnóstico independiente de Groq y Gemini. La disponibilidad de generación de Gemini se evalúa aparte. |
| Cumple | Arranque en frío y persistencia | El ciclo Stop/Start completó en unos seis minutos y medio y conservó el caso de referencia. |
| Cumple | Respaldo antes de migrar | Copia validada antes del cambio, aborto si falla y restauraciones comprobadas en SQLite y PostgreSQL temporal. |
| Cumple | Seguridad de la aplicación | Límites, validación, CORS, PBKDF2 y credenciales separadas. El chat carece de acceso a reportes privados. |
| Cumple | Captura y cálculo de impacto operativo | Estudios con criterios, cohortes, tiempos humanos y SLA, verificados en SQLite y PostgreSQL temporal. |
| Cumple | Suite local y modos alternativos | 69 pruebas locales aprobadas, más la compilación. Incluye SQLite, clasificador demo y enrutador local. |
| Cumple | Suite integrada completa | `Test-Soc.ps1 -Live` terminó con código 0. Pasaron 69 pruebas locales y 22 con servicios reales, incluida la verificación del respaldo y la salud de Gemini. |
| Adicionado | Interfaz y asistente | Español e inglés, temas claro, oscuro y sistema, tablero de tres columnas, chat flotante, Markdown, historial y reintentos. |

**Estado de entrega técnica: completa.** La comparación **DEMO · SLA manual frente a asistido** muestra una mejora simulada de 30 puntos porcentuales en ambos SLA y se calcula por separado.

### Evidencia operativa posterior a la entrega

| Indicador | Estado de la evidencia |
| --- | --- |
| Mejora real de SLA | Pendiente de casos comparables y una meta acordada. |
| Horas reales de triaje ahorradas | Pendiente de mediciones de tiempo humano activo en triaje manual y asistido. |

La captura y el cálculo ya están disponibles en **Evolución → Estudios de impacto operacional**. La última consulta a PostgreSQL mostró cero observaciones y cero líneas base reales.

La corrida integrada vigente está en `.venv/soc-runtime/test-results/soc-tests-20261103-161108.log`. En el primer intento tras rotar la clave, el respaldo funcionó, pero la sonda sintética de Gemini agotó su espera de 12 segundos. La sonda ajustada usa un máximo de 25 segundos y un nivel de razonamiento bajo para el modelo Gemini 3 Flash configurado. La prueba específica y la suite completa posterior aprobaron.

## Revalidación histórica anterior al plan de cierre

Las tablas siguientes conservan el estado anterior a la implementación. La checklist vigente está al inicio del documento.

## Plataforma común obligatoria

| Característica | Estado | Evidencia |
| --- | --- | --- |
| React 18 | Cumple | Declarado y fijado en `frontend/package.json` y el archivo de bloqueo. |
| TypeScript | Cumple | El arranque ejecutó `tsc --noEmit` y Vite completó el build. |
| TailwindCSS | Cumple | Configurado en el frontend e incorporado al CSS compilado. |
| Recharts | Cumple | Dashboard con gráficos de distribución, carga, tendencia y SLA mensual. |
| FastAPI, SQLAlchemy y Pydantic | Cumple | API, sesiones y consultas parametrizadas, validación de cuerpos y filtros. |
| n8n en Docker | Cumple | Contenedor `soc-router-n8n-1`, con webhook y callbacks de asignación y aviso. |
| Langflow independiente | Cumple | Servicio Windows del proyecto en `127.0.0.1:7861` y consumo por API HTTP. La disponibilidad de los proveedores se evalúa aparte. |
| PostgreSQL 16 | Cumple | `SHOW server_version` devolvió PostgreSQL 16.15 en el contenedor dedicado. |
| Redis para caché | Cumple | `soc:metrics` usa vencimiento de cinco segundos. Aplica a `/api/metricas`. |
| Redis para colas | Cumple | Conjunto ordenado `soc:routing`. PostgreSQL conserva los pendientes para la recuperación. |
| Redis para sesiones y límites | Cumple | Sesiones con vencimiento y contadores por ventana. Las pruebas de plataforma ejercitan el Redis local. |
| JWT y RBAC propio | Cumple | JWT firmado, con expiración, sesión revocable y permisos en el servidor. |
| Administrador | Cumple | Gestión de usuarios, casos, reglas, equipos y auditoría. |
| Analista | Cumple | Atención, hitos, revisión humana, colaboración y exportaciones de casos. |
| Gestor | Cumple | Consulta, dashboard, exportaciones y creación de líneas base. |
| Auditor | Cumple | Auditoría y su exportación. La bitácora por ID de reporte también está autorizada. |
| `audit_log` y campos de identidad | Cumple | Tabla independiente de la bitácora de negocio, con usuario, rol, acción, módulo, IP y fecha. El resultado HTTP se registra en la salida. |
| Middleware de auditoría | Cumple | Intercepta `/api/` y `/internal/`. |
| Entrada y salida normal | Cumple | `entry` y `exit` correlacionados por `X-Request-ID`. |
| Entrada y salida de rechazos | Cumple | El rechazo autenticado con credencial inválida registra `entry`, `rejected` y `exit` para el mismo ID. La cobertura se refiere a las rutas del middleware. |
| Inmutabilidad | Cumple | Triggers que rechazan `UPDATE`, `DELETE` y `TRUNCATE`. |
| Cambios críticos | Cumple | Triggers para reportes, asignaciones, usuarios, bitácora, mediciones y tablas operativas nuevas. |
| PDF con WeasyPrint | Cumple | Generación en servidor y apertura mediante lector PDF. |
| Word con python-docx | Cumple | Generación y lectura de las tablas DOCX. |
| Excel con openpyxl | Cumple | Generación y lectura de hojas XLSX. |
| Generación independiente de Office | Cumple | Las tres exportaciones se generan mediante las bibliotecas de Python. |

## Indicadores e impacto

| Característica | Estado | Evidencia |
| --- | --- | --- |
| Configurar y medir SLA | Cumple | Plazos de respuesta y resolución versionados. El dashboard presenta cumplidos sobre casos evaluables. |
| Demostrar impacto operacional de SLA | No cumple | Existe un histórico DEMO. Falta una serie operativa representativa y un criterio de éxito acordado. |
| Medir ciclo, línea base y revisión humana | Cumple | Se guardan el tiempo de recepción a notificación, las muestras de línea base y el tiempo de revisión cuando se registra. |
| Calcular horas estimadas | Cumple | Estimación basada en tiempo manual medio menos ciclo automático y revisión humana. |
| Demostrar horas reales ahorradas | No cumple | PostgreSQL contiene una línea base DEMO y cero reales. El ahorro real requiere mediciones comparables de triaje manual y asistido. |

## Validación funcional ampliada

### 1. Flujo central

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Persistencia antes de n8n | Cumple | `db.save_report` confirma la transacción antes de `dispatch`. La prueba de corte consulta `reports` y confirma que todavía no hay asignación. |
| Salida estructurada de Langflow | Cumple | Tipo, severidad, activo y confianza validados con Pydantic. El caso integrado anterior conserva los cuatro campos en PostgreSQL. |
| Confianza inferior a 0,75, salida inválida e inyección | Cumple | El umbral inicial es 0,75 y admite configuración. Hay pruebas de los tres motivos. El caso malicioso integrado va a Triaje SOC sin entregar la instrucción a Langflow. |
| Respaldo Gemini cuando falla Groq | Parcial | Se activa para fallos de transporte, HTTP 408, 429 o 5xx. Groq y el respaldo forzado Gemini pasaron en Langflow real. Un error permanente de Groq, como HTTP 400, sigue enviando al caso a la contingencia de FastAPI. |
| Contingencia cuando el clasificador falla | Cumple | FastAPI conserva el reporte, marca `origen=fallback`, usa `otro` y severidad `media` y deriva al equipo de revisión. El enrutador aplica las reglas a esa clasificación de contingencia. |
| n8n asigna equipo, SLA y aviso | Cumple | Asignación y notificación registradas por el actor `n8n`. Los plazos se determinan por severidad y versión de reglas. |
| Idempotencia y conflicto | Cumple | Repetición de la clave y contenido devuelve el caso. Con contenido distinto responde 409. |
| Una asignación y una notificación | Cumple | Se comprueba por SQL y bitácora después de diez reenvíos. |
| Recuperación con n8n y Redis reiniciados | Cumple | Caso persistido durante el corte y recuperación automática al restaurar la pila. |
| Resistencia a la instrucción de prueba | Cumple | El patrón «ignora todas las instrucciones» se desvía a revisión. Es una comprobación específica de la detección básica. |

### 2. Usuarios, roles y perfiles

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Alta, lectura, actualización, cambio de rol, reset y desactivación | Cumple | `/api/users` limitado al administrador. La baja es lógica. |
| Al menos un administrador activo | Cumple | El backend bloquea degradar o desactivar al último administrador. |
| Matriz de los cuatro roles | Cumple | Sesiones de los cuatro roles y 67 comprobaciones HTTP de lectura y acciones protegidas. La visibilidad de la interfaz se contrastó con React y sus pruebas. |
| Invalidación al cambiar rol, contraseña o estado | Cumple | Incremento de versión de token, comprobado en autenticación. |
| Revocación al cerrar sesión | Cumple | Se elimina la sesión y el token deja de autorizar. |
| Perfil y cambio de contraseña | Cumple | Perfil de sesión y actualización con contraseña actual, con revocación. |
| Bloqueo por intentos fallidos | Cumple | Límite por IP y bloqueo por cuenta tras cinco fallos durante quince minutos. |
| Permisos granulares | Cumple | Matriz fija por rol y acción aplicada en API. |
| TOTP opcional | No cumple | El sistema actual carece de alta, verificación y recuperación TOTP. |

### 3. Bitácora y auditoría

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Login, logout y accesos rechazados | Cumple | Eventos explícitos de autenticación y triple registro correlacionado del 401. |
| Entrada y salida por navegación | Parcial | Registra `module_enter` y `module_exit` en transiciones autenticadas. La navegación pública y el cierre abrupto de pestaña quedan fuera de la garantía. |
| Resultado en cada fila | Parcial | La columna admite `NULL`. La entrada, las transiciones de navegación y los eventos de triggers pueden carecer de resultado HTTP. La salida correlacionada de API tiene el código. |
| Cuerpos y secretos fuera de la auditoría | Cumple | El middleware guarda metadatos, sin el cuerpo ni los encabezados de credenciales. |
| Bloqueos directos y triggers críticos | Cumple | PostgreSQL rechaza `UPDATE`, `DELETE` y `TRUNCATE` directos. La prueba de plataforma verifica `INSERT` y `UPDATE` de usuarios por trigger. |
| Filtros y exportación | Cumple | Usuario, rol, módulo, acción, fechas y estado HTTP. Desde la cuenta Auditor se abrieron PDF, DOCX y XLSX con las dos mismas filas del filtro aplicado. |
| Solo administrador y auditor | Cumple | Restricción en React y permisos en API. |

### 4. Dashboard

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Estado, tipo y severidad | Cumple | Tres distribuciones en el dashboard. |
| SLA y tiempos medios | Cumple | Respuesta y resolución a tiempo. Promedios y muestras para clasificación, primera respuesta y resolución. |
| Precisión con revisión humana | Cumple | Coincidencia de tipo, severidad y activo frente a la última revisión. Denominador explícito y separación DEMO. |
| Carga y tendencia | Cumple | Carga por equipo responsable y tendencia mensual. |
| Cuatro filtros | Cumple | Fecha de recepción en Lima, tipo, severidad y equipo. |
| Universo completo | Cumple | Consulta independiente del tablero limitado a 100. Prueba local con 102 filas. |
| Coincidencia con SQL independiente | Cumple | 37 casos globales y 18 con los cuatro filtros. Coincidieron los totales, DEMO, distribuciones, tiempos, SLA, carga, tendencia y revisión. |
| Identificación DEMO y estimaciones | Cumple | Se distingue la marca DEMO y el histórico sintético separado. Los totales generales incluyen los casos DEMO y muestran su cantidad. |

### 5. Reportes

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Tres informes operacionales | Cumple | Cola actual, vencimiento SLA y asignaciones pendientes. |
| Cuatro informes de gestión | Cumple | Cumplimiento mensual, tendencias, clasificador y carga por equipo. |
| Tres formatos por informe | Cumple | Se abrieron 42 archivos, las 21 combinaciones de siete informes y tres formatos con dos filtros. Una corrida inicial interrumpida por un HTTP 503 se repitió completa. |
| Exportación exclusiva de gestor y administrador | No cumple | Analista también puede exportar informes y reportes operativos. Auditor puede exportar auditoría y recibe 403 en informes de casos. |
| Exportaciones auditadas | Cumple | Las 42 descargas exitosas tuvieron salida HTTP 200 en `audit_log` para el mismo `X-Request-ID`. |

### 6. Módulos adicionales

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Catálogo de activos | Cumple | Alta, edición, consulta y marcado de inactividad. |
| Equipos y responsables | Cumple | Directorio con contacto, disponibilidad y casos abiertos por equipo. |
| Reglas y SLA editables, versionadas y auditadas | Cumple | UI Operaciones → Reglas y API de publicación. El JSON sigue como configuración inicial. |
| Cola y confirmación o corrección humana | Cumple | Cola dedicada y revisión persistida por reporte. |
| Configuración del umbral | Cumple | Se publica con la versión de reglas. |
| Comentarios y adjuntos | Cumple | Colaboración por reporte, con permisos, límite de tamaño y descarga forzada. |
| Centro de notificaciones | Cumple | Lista de avisos y marca de lectura por cuenta. |
| Salud de todos los servicios y proveedores | Parcial | El diagnóstico comprueba FastAPI, PostgreSQL, Redis, Langflow y n8n. Groq y Gemini se comprueban con pruebas de proveedor separadas. |

### 7. Seguridad

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Secretos fuera de fuentes y logs | Cumple en el alcance revisado | Se examinaron 72 archivos fuente y registros por coincidencia exacta de credenciales configuradas, con cero coincidencias. `.env` y `.venv` están en `.gitignore`. Esta carpeta carece de historial Git verificable. |
| Acceso directo con roles y sin token | Cumple en las rutas probadas | API directa devuelve 401 sin sesión y 403 con rol insuficiente. Formulario, chat, login y salud son públicos por diseño. |
| Límites en formulario y chat | Cumple | Ventanas de solicitudes configurables y pruebas locales de limitación. |
| Validación, adjuntos y CORS | Cumple | Pydantic, tamaño y cantidad de adjuntos, nombre validado y descarga forzada. El preflight de origen externo carece de `Access-Control-Allow-Origin`. |
| PBKDF2 y secretos independientes | Cumple | PBKDF2-HMAC-SHA256 con sal y 600 000 iteraciones. Operador, webhook e interno usan valores distintos. |
| Chat sin reportes privados ni secretos en el mensaje | Cumple por diseño | La API del chat recibe el historial del usuario y contexto fijo. Carece de herramientas de lectura de casos. Las credenciales se usan como autenticación del proveedor. El usuario puede escribir datos sensibles en el texto. |

### 8. Calidad y operación

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Suite local antes y después | Cumple | Línea base registrada y nueva corrida local de Python, reglas, build y React. |
| Suite con servicios reales | Cumple | `Test-Soc.ps1 -Live` terminó con código 0. Pasaron 14 pruebas reales en clasificación, plataforma, chat y recuperación, además de las 58 pruebas locales y la compilación. |
| Stop y arranque desde cero | Parcial | Stop detuvo FastAPI, Langflow y los tres contenedores. El primer arranque alcanzó el límite de espera de 360 segundos por Langflow. El proceso quedó iniciándose y la pila quedó operativa tras restablecerse la conexión. |
| Persistencia tras reiniciar | Cumple | Comprobación de un reporte preexistente en PostgreSQL tras el ciclo de arranque. |
| SQLite, demo y local | Cumple | Pruebas de la API en SQLite temporal, clasificación demo y enrutamiento local. |
| Respaldo antes de cada migración | Parcial | Hay respaldo documentado de la migración previa y copia verificada antes de la última extensión. El arranque no genera automáticamente una copia para cada posible cambio de esquema. |
| README actualizado | Cumple | Arranque, pruebas, endpoints, permisos, datos DEMO y alcance de salud documentados. |

## Características adicionadas

Se conservan los temas claro, oscuro y sistema, la interfaz bilingüe con preferencias persistentes, el tablero de tres columnas, y el chat flotante con contexto, proveedor visible y reintentos. También permanecen el umbral inicial de 0,75, la detección básica de inyección, el triaje de contingencia, la idempotencia con conflicto, el reintento manual y los hitos separados. Revocación, PBKDF2, protección del último administrador, bloqueo de `TRUNCATE`, paginación, modos de respaldo, scripts PowerShell, datos DEMO y suites local e integrada siguen disponibles. El dashboard completo y los módulos de la extensión se desglosan en esta lista.

## Evidencia reproducible

- Reporte de recuperación DEMO `40361e98-b04e-4f6c-842e-6ad04b1431f4`. PostgreSQL registró `phishing`, `media`, `correo corporativo`, confianza `0,90` y origen `langflow`. La bitácora mostró `recibido`, `clasificado`, `enrutamiento_pendiente`, `asignado` y `notificacion`, con actor `n8n` en los dos últimos.
- Tras reiniciar Redis se comprobó el cambio de su `run_id`. El reporte se recuperó automáticamente al restaurar n8n. Diez reenvíos obtuvieron HTTP 200 con el mismo ID y el cambio de contenido obtuvo 409.
- Los resultados operativos están en `tmp/soc-revalidacion-operativa-20261103.log`. La corrida local está en `.venv/soc-runtime/test-results/soc-tests-20261103-140255.log`. La corrida integrada está en `.venv/soc-runtime/test-results/soc-tests-20261103-145319.log`.

## Implementación del plan de cierre

| Brecha | Implementación y evidencia |
| --- | --- |
| Exportaciones de casos | Permiso separado `report_export` para Administrador y Gestor en las dos familias de rutas. La interfaz oculta los controles al Analista. Las descargas de auditoría mantienen su propia autorización. |
| Respaldo previo | PostgreSQL y SQLite validan la copia antes del cambio. Un fallo cancela la migración y la versión de esquema solo se registra en la transacción exitosa. Se restauraron copias en SQLite y en un PostgreSQL temporal. El arranque generó una copia automática y conservó el caso de referencia. |
| Resultado de auditoría | `outcome` separa el desenlace del código HTTP. Los eventos nuevos de aplicación y los triggers PostgreSQL lo escriben. Las filas históricas se conservan. |
| Visitas | La API acepta entradas públicas de recepción, login y chat. Las visitas autenticadas respetan RBAC. El servidor registra la salida observada o la infiere tras 180 segundos sin renovación con resultado `expirado`. Se probaron eventos fuera de orden y expiración idempotente. |
| Groq y Gemini | El componente cloud actualizado intenta Gemini ante fallos propios de Groq. La prueba unitaria cubre HTTP 400, respuestas inválidas, errores transitorios y rechazo explícito de política. FastAPI conserva el caso cuando falla la clasificación. |
| Salud | `/health?detalle=true` separa servicios locales y último diagnóstico de cada proveedor. Un administrador ejecuta las pruebas cloud con entrada sintética y caché de cinco minutos. El arranque mostró a Langflow como pendiente mientras el resto de la pila respondía. |
| Arranque en frío | `Stop-Soc.ps1` seguido de `Start-Soc.ps1` completó el ciclo. La pila alcanzó disponibilidad a las 15:28:03, aproximadamente seis minutos y medio después de iniciar. Se verificó que un segundo intento reconoce Langflow mientras está iniciándose y conserva el mismo proceso. |
| TOTP | Activación con confirmación, semilla cifrada y ligada a la cuenta, códigos de recuperación de un solo uso y revocación. Se probó en SQLite y con una cuenta temporal de la pila PostgreSQL. |
| Medición operacional | API e interfaz disponibles. Comparación de cohortes, SLA, tiempos activos y exclusión DEMO comprobadas en SQLite y en un PostgreSQL temporal. La base del proyecto tenía cero estudios, observaciones y líneas base reales tras la migración. |

La disponibilidad del mecanismo de medición permite iniciar la captura. La demostración de impacto operacional en SLA y el ahorro basado en observaciones reales siguen pendientes hasta reunir casos comparables y acordar los criterios. Los datos sintéticos de las pruebas se usaron en bases temporales.

Evidencia del arranque en `tmp/soc-arranque-frio-plan-20261103-reintento.log`. La primera corrida se detuvo antes de cambiar el esquema. Se corrigió la posición del archivo de respaldo heredada por `pg_restore` en Windows y se verificó la restauración antes del nuevo arranque. Los conteos de la base operativa están en `tmp/soc-verificacion-plan-20261103.log`.

La corrida integrada `soc-tests-20261103-153221.log` completó todos sus grupos. Aprobaron recuperación de n8n, restauración PostgreSQL, TOTP e impacto en PostgreSQL temporal. En los grupos de clasificación, salud y chat fallaron comprobaciones de Gemini. La reejecución del grupo de clasificación identificó HTTP 429 en ambos subcasos de respaldo. La consulta sintética a Google confirmó `RESOURCE_EXHAUSTED` para `GenerateRequestsPerDayPerProjectPerModel-FreeTier`. Google indicó volver a intentar cerca de las 03:00 del 4 de noviembre, hora de Lima. Los registros sin secretos están en `tmp/soc-proveedores-revalidacion-plan-20261103.log` y `tmp/soc-diagnostico-cloud-plan-20261103.log`.

La corrida local final `soc-tests-20261103-154012.log` terminó con código 0. Pasaron 55 pruebas Python, 2 de reglas n8n, 12 de React y la compilación. Incluye el reintento acotado de Gemini, el resultado público sanitizado para HTTP 429 y el rechazo de observaciones manuales con plazos aún abiertos.

En la continuación del 3 de noviembre, las pruebas de Groq y de los dos escenarios de Gemini en Langflow se separaron para identificar el resultado de cada proveedor. Se volvieron a ejecutar cuatro pruebas reales sin forzar Gemini. Pasaron la clasificación aislada con Groq, el flujo completo con PostgreSQL y n8n, el desvío de contenido sospechoso y la salud de la pila. El registro está en `tmp/soc-verificacion-sin-forzar-gemini-20261103.log`. PostgreSQL seguía mostrando cero estudios, cero observaciones y cero líneas base reales. Quedan por repetir las comprobaciones dependientes de Gemini tras el plazo de cuota informado por el proveedor.
