# Análisis técnico

Inventario de la versión previa a la ampliación del 3 de noviembre de 2026. El proyecto se ejecuta en Windows con PowerShell y en este directorio carece de repositorio Git. Se conserva una copia del código antes de la ampliación en `tmp/soc-source-before-extension-20261103-125252.zip`.

| Capa | Versiones verificadas y fuentes |
| --- | --- |
| Entorno | Python 3.12.9 y Node.js 22.17.1. Start-Soc.ps1, Stop-Soc.ps1 y Test-Soc.ps1 administran arranque, parada y verificación. |
| Frontend | React 18.3.1, TypeScript 5.9.3, Tailwind 3.4.19, Recharts 3.10.1, Vite 6.4.5, React Markdown 10.1.0, Vitest 5.1.0 y Testing Library 16.3.3. Declaraciones en frontend/package.json y resolución en frontend/package-lock.json. |
| Backend | FastAPI 0.162.0, Uvicorn 0.54.0, Pydantic 2.14.2, SQLAlchemy 2.1.6, psycopg 3.3.7, httpx 0.28.1, Redis Python 6.4.0 y PyJWT 2.15.1. Rangos declarados en requirements.txt. |
| Datos y automatización | Imágenes PostgreSQL 16, Redis 7 Alpine y n8n 1.109.2 en compose.yaml, líneas 4, 18 y 31. |
| IA | Langflow como servicio separado. integrations/langflow contiene el flujo, el prompt y el componente Groq/Gemini. El asistente tiene su propia ruta en backend/chat.py, línea 114. |
| Exportación | WeasyPrint 68.1, python-docx 1.2.0 y openpyxl 3.1.5. Generador en backend/exports.py, línea 33. |

## Convenciones existentes

- El esquema se crea con db/schema.sql y Database.initialize en backend/db.py, línea 66. Las actualizaciones comprueban columnas y agregan migraciones compatibles. backend.manage prepara usuarios y datos DEMO. scripts/prepare_containers.py y scripts/migrate_pg16.py son utilidades de infraestructura.
- backend/main.py instala las rutas públicas, privadas y el middleware. backend/platform.py contiene módulos de plataforma. Pydantic valida parámetros y cuerpos. Las consultas de SQLAlchemy se parametrizan y funcionan con PostgreSQL y SQLite.
- backend/security.py aplica una matriz de permisos a los cuatro roles y usa JWT firmado, expiración, versión de token y sesiones revocables. Redis mantiene sesiones y límites. La web mantiene el token en memoria.
- frontend/src/main.tsx selecciona vistas y monta componentes. La interfaz usa traducciones español/inglés y variables CSS para los temas. Las pruebas combinan unittest, pruebas de reglas de n8n, Vitest y grupos integrados.

## Mapa funcional previo

| Área | Rutas, interfaz y almacenamiento |
| --- | --- |
| Recepción | Formulario público y POST /api/reportes, backend/main.py, línea 219. Langflow clasifica y el backend persiste en reports antes de despachar. Idempotency-Key identifica el reporte. |
| Enrutamiento | n8n consume el webhook, consulta contexto y guarda asignación y notificación mediante /internal/reportes/{id}. assignments conserva SLA y estados. Redis recupera enrutamientos pendientes. |
| Atención | GET /api/reportes y GET /api/metricas. Tablero por estado, bitácora por reporte, reintento y registro de primera respuesta o resolución. La lista está limitada a 100, las métricas globales SQL usan todo el conjunto. |
| Triaje | /api/triage, líneas base, registro de tiempos y Evolución DEMO. triage_baselines, triage_measurements y demo_impact_history. |
| Acceso | /api/auth/login, /me y /logout. /api/users permite listar, crear, editar y desactivar. users, auth_sessions y rate_limits. |
| Auditoría | /api/audit con cursor y middleware de entrada y salida correlacionadas. bitacora registra el proceso por reporte. audit_log tiene triggers de protección y triggers de cambios de negocio. |
| Archivos | /api/exportar/{formato} genera PDF, Word y Excel. El formato base exporta todos los reportes, hasta 10 000. |
| Chat y salud | /api/chat y /health. El asistente flotante trata la conversación por separado del flujo de clasificación. |

## Riesgos de compatibilidad

| Cambio | Riesgo y tratamiento |
| --- | --- |
| Agregados y filtros | Las fechas, los casos sin asignación y las muestras pequeñas pueden distorsionar las métricas. Se define la fecha de recepción en Lima y se conservan numeradores y denominadores. |
| Exportaciones | Riesgo de exponer datos, fórmulas de Excel o HTML. Se conserva el generador y se aplican los mismos filtros y permisos en el servidor. |
| Navegación y auditoría | El cierre abrupto de pestaña puede interrumpir el envío. Se registran transiciones autenticadas y eventos de API, conservando la inmutabilidad. |
| Cuentas | Cambiar credenciales debe invalidar sesiones y preservar al último administrador. Se mantiene el modelo JWT y la compatibilidad del token histórico. |
| Configuración y módulos operativos | Las reglas nuevas no deben alterar plazos ya asignados ni romper los callbacks de n8n. Cambios aditivos y revisión humana separada de la predicción original. |

## Línea base y respaldo

- `Test-Soc.ps1` completó 39 pruebas Python, 2 de reglas de n8n y 9 de React. La compilación TypeScript y Vite terminó correctamente. Registro local `soc-tests-20261103-125211.log`.
- El directorio de trabajo carecía de repositorio Git. Se creó `tmp/soc-source-before-extension-20261103-125252.zip` con los archivos del proyecto y se excluyeron credenciales, configuración privada y directorios de dependencias.
- El respaldo previo de datos está en `tmp/soc-data-before-extension-20261103-125300`. Se validó el catálogo del volcado de PostgreSQL 16 con `pg_restore --list` y la integridad de la copia SQLite con `PRAGMA integrity_check`.
