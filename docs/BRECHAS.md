# Matriz de brechas

Estado previo a los cambios. Las líneas remiten a la copia inicial del código.

| Requisito | Estado inicial | Evidencia inicial |
| --- | --- | --- |
| A. Estado, tipo, severidad, SLA, tiempos, precisión, carga y tendencia | Parcial | frontend/src/main.tsx:169 grafica el tipo de los últimos 100. backend/db.py:180 calcula SLA global. ImpactPanel usa una serie DEMO. |
| A. Filtros por fechas, tipo, severidad y equipo | Faltante | frontend/src/api.ts:24 filtra la lista local por estado. |
| A. Todos los registros | Parcial | backend/db.py:83 limita la lista. backend/db.py:180 agrega globalmente. |
| B. Cola, SLA próximo o vencido y asignación pendiente | Parcial | Tablero y plazos en frontend/src/main.tsx:164 y :193. Exportación única en backend/platform.py:129. |
| B. Cumplimiento mensual, tendencias, clasificador y carga | Faltante | No hay exportaciones de gestión por tema. |
| B. PDF, Word, Excel con filtros y auditoría | Parcial | backend/exports.py:33 genera los tres formatos. backend/main.py:83 audita las solicitudes. Faltan filtros y tipos de informe. |
| C. CRUD y restablecimiento de administrador | Implementado | backend/platform.py:63–94 permite alta, lectura, edición, reset y baja lógica. |
| C. Perfil propio y cambio de contraseña | Parcial | backend/platform.py:55 expone el perfil de sesión. Falta vista y cambio propio. |
| C. Permisos por módulo y acción | Parcial | backend/security.py:21 tiene lectura, escritura, auditoría y administración. |
| C. Bloqueo por intentos fallidos | Parcial | backend/security.py:93 limita por IP. Falta bloqueo temporal por cuenta. |
| C. TOTP opcional y evaluación de refresh | Parcial | JWT revocable en backend/security.py:93–173. La sesión web exige login al recargar. |
| D. Login, logout, entrada y salida de API | Implementado | backend/platform.py:51–61 y backend/main.py:83–137. |
| D. Entrada y salida por navegación | Faltante | frontend/src/main.tsx:142 cambia de vista sin evento. |
| D. Filtros y exportación de auditoría | Parcial | backend/db.py:249 y frontend/src/main.tsx:269 tienen cursor y tabla. |
| D. Triggers e inmutabilidad | Implementado | backend/db.py:200–238. Hash opcional ausente. |
| E. Catálogo de activos | Faltante | db/schema.sql:10 guarda texto libre del activo. |
| E. Equipos, carga y disponibilidad | Parcial | integrations/reglas.json:2 contiene equipos. assignments guarda el nombre. |
| E. Reglas de asignación y SLA versionadas y auditadas en UI | Faltante | backend/main.py usa integrations/reglas.json. |
| E. Cola de triaje humano y precisión | Parcial | backend/platform.py:119 registra tiempo humano. Falta confirmar o corregir predicción. |
| E. Umbral del clasificador configurable | Faltante | backend/classifier.py contiene el umbral fijo 0,75. |
| E. Comentarios y adjuntos | Faltante | db/schema.sql y rutas de reportes carecen de registros de colaboración. |
| E. Centro de notificaciones | Parcial | backend/db.py:151 registra avisos, visibles en la tarjeta. |
| E. Salud de servicios | Parcial | backend/main.py:210 comprueba la base y devuelve modos. |

## Estado tras la extensión

| Requisito | Estado final | Evidencia y alcance |
| --- | --- | --- |
| A. Estados, tipos, severidades, SLA, promedios, precisión, carga y tendencia | Implementado | `backend/insights.py` y `frontend/src/DashboardPanel.tsx`. El SLA muestra numerador y denominador. Precisión significa coincidencia completa sobre revisiones humanas, con muestras DEMO separadas. |
| A. Filtros y universo completo | Implementado | `ReportFilters` aplica fechas en Lima y filtros SQL de tipo, severidad y equipo. La prueba con 102 registros contrasta el dashboard con el tablero de 100. |
| B. Siete informes y tres formatos | Implementado | `report_table` y `/api/informes/{tipo}/{formato}` reutilizan `backend/exports.py`. Dashboard y exportaciones aplican los mismos filtros. El middleware audita todas las solicitudes de descarga. |
| C. CRUD, perfil, cambio, bloqueo y restablecimiento | Implementado | `backend/platform.py`, `backend/security.py` y `ProfilePanel`. Los cuatro roles mantienen el contrato y las acciones nuevas exigen permisos específicos. |
| C. TOTP opcional | Pendiente justificado | Requiere guardar semillas cifradas con una clave separada, proteger contra reuso y definir recuperación para cuentas bloqueadas. Se conserva el acceso existente mientras se define ese proceso. |
| C. Evaluar refresh | Evaluado | El JWT revocable sigue en memoria. Implementar refresh persistente requeriría cookies HttpOnly/Secure bajo HTTPS, rotación con detección de reuso y protección CSRF. El entorno actual usa HTTP local. |
| D. Login, logout y eventos por módulo | Implementado | `POST /api/audit/navegacion` registra las dos fases de cada transición autenticada en una transacción. El envío por el navegador depende de una sesión vigente y conexión. El cierre abrupto de la pestaña puede interrumpirlo. |
| D. Filtros, exportación e inmutabilidad | Implementado | `AuditFilters`, `AuditPanel` y triggers conservados. La descarga limita a 10 000 filas e indica si la consulta supera ese límite. El encadenamiento por hash era opcional y queda fuera del alcance. |
| E. Activos | Implementado | `GET/PUT /api/activos`, con baja lógica. El nombre libre de los reportes históricos se conserva. |
| E. Equipos, carga y disponibilidad | Implementado | `GET/PUT /api/equipos` combina equipos configurados, directorio y carga real. El responsable de un caso es el equipo. Contacto y disponibilidad se muestran como información operativa. |
| E. Reglas y umbral | Implementado | `backend/routing.py` y `Operaciones → Reglas`. Cada publicación guarda versión, autor y fecha. Los reportes nuevos quedan asociados a la versión publicada vigente. Los anteriores a la primera publicación siguen con el respaldo inicial en JSON. |
| E. Triaje humano | Implementado | `GET /api/revision` y `PUT /api/reportes/{id}/revision`. Las confirmaciones y correcciones alimentan precisión y conservan clasificación inicial y SLA. |
| E. Comentarios, adjuntos y avisos | Implementado | `backend/operations.py`. Descarga forzada de adjuntos, límite de tamaño y cantidad, y notificaciones con marca de lectura por usuario. |
| E. Salud de servicios | Implementado | `/health?detalle=true` comprueba PostgreSQL o SQLite, Redis, Langflow y n8n. `/health` conserva su respuesta histórica. |

Los reportes con marca DEMO se contabilizan explícitamente en el dashboard. El histórico sintético de impacto conserva su tabla independiente. Evaluar el ahorro operacional requiere muestras manuales y tiempos de revisión reales de un periodo representativo.

## Verificación ejecutada

| Verificación | Resultado |
| --- | --- |
| Suite local después de los cambios | 46 pruebas Python con SQLite y simulaciones, 2 de reglas n8n, 10 de React y compilación TypeScript aprobadas. |
| Servicios reales | PostgreSQL 16, Redis, Langflow y n8n disponibles. Las 7 pruebas de plataforma, las 2 del chat y la prueba de recuperación controlada de n8n aprobaron. |
| Formulario real | El caso DEMO `4e07fb29-af74-4bdc-9e97-89e90b36531f` quedó como phishing, severidad media y equipo Seguridad de correo. La bitácora registra los actores formulario, Langflow, n8n y operador. Se verificaron los dos SLA y se abrieron los tres formatos filtrados con sus lectores. |
| Proveedores en el clasificador | La suite `-Live` terminó con código 1 por el subcaso aislado de Groq, que devolvió HTTP 500 en Langflow. El diagnóstico observó HTTP 400 de Groq y otra ejecución HTTP 200. En la repetición de `live_soc.py` Groq pasó y falló el subcaso de Gemini. Otra repetición diagnosticó que Gemini agotó el tiempo de respuesta. El fallback del chat aprobó su prueba independiente. |

La corrida principal está en `.venv/soc-runtime/test-results/soc-tests-20261103-130144.log`. La evidencia del formulario y de los reintentos está en `tmp/soc-verificacion-formulario-20261103.log`, `tmp/soc-reprueba-proveedores-20261103.log` y `tmp/soc-reprueba-integracion-clasificador-20261103.log`.
