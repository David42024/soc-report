# Cambios de SOC Report Router

## Cierre de brechas operativas · 2026-11-03

- Exportación de informes de casos restringida a Gestor y Administrador. Los permisos de descarga de auditoría se mantienen separados.
- Respaldo previo a cambios de esquema, verificación del volcado y prueba de restauración en PostgreSQL temporal. Las migraciones se aplican dentro de una transacción.
- Auditoría de navegación pública y autenticada. Resultado separado del código HTTP y salida inferida cuando expira la visita.
- Respaldo Gemini ampliado para fallos propios del proveedor Groq. Diagnóstico cloud bajo demanda y mejoras en el arranque en frío.
- TOTP opcional, semillas cifradas, verificación contra reutilización, códigos de recuperación de un solo uso y revocación de sesiones.
- Estudios de impacto operacional con criterios, observaciones comparables y evidencia separada del histórico DEMO.

## 2026-11-03

- Dashboard filtrado por fecha, tipo, severidad y equipo sobre todo el conjunto. Siete informes operativos y de gestión con exportación en PDF, Word y Excel.
- Auditoría de navegación autenticada, filtros y exportaciones. Se conservan las fases de acceso a la API y la protección por triggers.
- Perfil y cambio de contraseña, bloqueo temporal por intentos fallidos y permisos por acción con los cuatro roles existentes.
- Catálogos de activos y equipos, carga operativa, versionado de reglas y umbral, triaje humano, colaboración, notificaciones y salud detallada.
- Pruebas de los módulos en SQLite y de permisos, auditoría y exportaciones con PostgreSQL. Datos de capacitación identificados como DEMO.

| Área | Archivos fuente |
| --- | --- |
| API y persistencia | `backend/main.py`, `backend/platform.py`, `backend/security.py`, `backend/db.py`, `backend/classifier.py`, `backend/exports.py`, `backend/manage.py`, `backend/insights.py`, `backend/routing.py`, `backend/operations.py`, `db/schema.sql` |
| Interfaz | `frontend/src/main.tsx`, `frontend/src/api.ts`, `frontend/src/styles.css`, `frontend/src/ChatWidget.tsx`, `frontend/src/DashboardPanel.tsx`, `frontend/src/OperationsPanels.tsx` |
| Pruebas | `tests/test_extension.py`, `tests/live_platform.py`, `frontend/src/App.test.tsx` |
| Documentación | `README.md`, `docs/ANALISIS_TECNICO.md`, `docs/BRECHAS.md`, `CHANGELOG.md` |

El arranque y la suite compilaron los recursos servidos desde `frontend/dist`.
