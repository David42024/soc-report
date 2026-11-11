# Protección de datos antes de los proveedores SOC

Esta corrección incorpora minimización local del texto antes de Groq y Gemini, incluyendo fallback y reintentos. Conserva los originales y los permisos del sistema existente. Su alcance es exclusivamente el requisito NF-02 del SPEC definitivo 2.1; no implementa la Fase 1.

## Recorrido comprobado y cambio aplicado

Antes, `POST /api/reportes` normalizaba la entrada con `ReportInput`, enviaba título y descripción a LangFlow y después persistía el reporte original y su clasificación. `SocCloudModel` construía la petición a Groq y reutilizaba el texto completo al pasar a Gemini. Escapar HTML no protegía la información personal. El chat tenía una segunda salida HTTP directa a ambos proveedores.

Ahora, FastAPI conserva el objeto `ReportInput` y protege una copia antes de entregar texto a LangFlow. Así, las trazas del flujo llamadas desde la API reciben texto protegido. El componente aplica el mismo filtro antes del bloque de proveedores: una única copia protegida alimenta Groq, Gemini y sus reintentos. Las ejecuciones directas del componente también pasan por ese control. El chat protege la conversación completa, incluidos turnos del asistente, y sus dos funciones de salida vuelven a comprobar el filtro porque también las usan los diagnósticos de disponibilidad.

Tras validar la clasificación se guarda el título y la descripción originales en PostgreSQL, mediante `save_report`, como antes. n8n recibe únicamente el identificador del reporte y obtiene el contexto técnico sin título ni descripción. Las reglas determinísticas, ambos SLA, la notificación y la bitácora conservan su recorrido. No se reconstruye ningún servicio.

## Política y conservación de contexto técnico

`config/privacy.yaml` contiene la versión, límites y detectores locales. `src/utils/privacy.py` es su única implementación compartida. Se reutiliza PyYAML ya instalado; no se descarga un modelo ni otro dataset y no se añade un servicio externo de detección.

Los casos verificados cubren correos, nombres con los formatos reconocidos, teléfonos, documentos, cuentas y tarjetas, direcciones postales, fechas personales etiquetadas, datos sensibles etiquetados, usuarios y directorios personales, credenciales, tokens, cookies, claves privadas, credenciales y parámetros de URL, bloques base64 de URI de datos, IP y MAC. Se normalizan Unicode, caracteres invisibles y formas comunes de escape HTML/URL únicamente en la copia de salida.

Los marcadores incluyen el tipo, por ejemplo `[SOC_EMAIL_1]`. Una misma identidad detectada conserva su marcador dentro de la solicitud; solicitudes diferentes no comparten diccionario ni hashes de personas. Los intervalos solapados se unen para evitar redacciones parciales. Un segundo filtrado conserva los marcadores existentes.

Se mantienen palabras del incidente, tipos y severidades, CVE, puertos, hashes de archivos, versiones de software, fecha general del evento, dominios y rutas de URL sin datos personales reconocidos y nombres técnicos de activos como `FS-01`. Las frases técnicas configuradas se conservan incluso cuando aparecen junto a un nombre personal; esta excepción solo se aplica al detector heurístico de nombres, nunca a correos, secretos o campos explícitamente personales. Las IP se sustituyen indicando familia y alcance público/no global; las direcciones originales quedan disponibles para investigación autorizada en el reporte original. Los valores de parámetros URL se minimizan aunque parezcan inocuos.

La clasificación sigue teniendo exactamente `tipo`, `severidad`, `activo_afectado` y `confianza`. No se reinsertan identidades originales en el texto enviado ni en la salida del modelo. La confianza baja mantiene la revisión humana y no provoca por sí misma un cambio de proveedor. El rechazo explícito de seguridad de Groq mantiene el comportamiento del componente existente.

## Originales, accesos y auditoría

Se conservan los roles existentes: Administrador, Analista y Gestor pueden consultar detalles; el Solicitante consulta únicamente sus propios reportes. El Auditor accede a la bitácora conforme al permiso actual, sin adquirir lectura general de reportes. Los accesos anónimos o con token inválido se rechazan. Las pruebas ejercitan estas rutas con JWT reales emitidos por el backend aislado, sin saltarse la autenticación.

La respuesta pública de recepción y el contexto interno de n8n continúan omitiendo título y descripción. No se crea una exportación ni un archivo con un diccionario reversible. El chat sigue sin guardar conversaciones en la base. Los originales y sus copias de auditoría siguen dentro de los almacenes protegidos preexistentes; no se cambia su política de retención ni se afirma haber añadido cifrado en reposo.

La evidencia del control se añade al evento existente `clasificado`: estado, versión y SHA-256 de la política y conteos por categoría. No contiene valores detectados ni texto del reporte. El campo `proveedor` conserva su posición compatible con el lector de evaluaciones existente. Los cuatro eventos del recorrido normal mantienen sus nombres y orden.

Una política ausente, incompleta o inválida, una codificación no procesable o los límites excedidos bloquean el envío. El reporte sigue guardándose con su original y se deriva a Triaje SOC mediante la política ya existente, con motivo `privacidad_no_disponible`. Ese fallo sucede antes del bloque de fallback: Gemini no se usa para eludir la protección. El chat devuelve un error seguro sin llamar a ninguno de los proveedores.

## Archivos de esta corrección

- `src/utils/privacy.py`, `config/privacy.yaml`: detección, minimización, marcadores, límites, recarga y evidencia sin texto original.
- `backend/classifier.py`: copia protegida antes de LangFlow, evidencia privada fuera del contrato y revisión ante fallo de protección.
- `backend/config.py`: entrega al filtro las credenciales de servicio ya configuradas para proteger también valores conocidos pegados sin etiqueta, incluidos passwords de DSN; no los registra ni los transmite como metadatos.
- `integrations/langflow/cloud_classifier_model.py` y su export JSON: protección compartida antes de Groq/Gemini, con los mismos modelos, prompt y enlaces a Credential.
- `backend/chat.py`, `backend/provider_health.py`: protección de todos los turnos y de las salidas directas; manejo seguro de errores del control.
- `backend/db.py`: evidencia mínima de privacidad en la bitácora; persistencia del original sin sustituirlo.
- `.env.example`: ruta opcional de la política por `SOC_PRIVACY_POLICY`; el valor predeterminado obligatorio es el YAML del proyecto.
- `frontend/src/i18n.ts`: explicación del bloqueo de privacidad para el operador, en ambos idiomas existentes.
- `Start-Soc.ps1`: importación del módulo compartido por ambos intérpretes, reinicio optativo de LangFlow y cierre del árbol del servicio verificado. En Windows, terminar solo el lanzador venv puede dejar el intérprete anterior atendiendo solicitudes.
- `scripts/update_langflow_component.py`: actualización con la credencial LangFlow existente, sin depender del autologin; conserva el resto del grafo.
- `tests/test_privacy.py`: casos sintéticos de detección, preservación técnica, cuerpos HTTP, fallback/reintentos, acceso a originales, fallo cerrado, auditoría, SLA y compatibilidad del evaluador.
- `tests/test_cloud_model.py`: conserva los controles previos y comprueba la nueva evidencia de privacidad fuera del contrato.
- `tests/live_phase0_alignment.py`: añade evidencia de política y conservación del original al E2E real aislado existente.
- `README.md`, este informe y la matriz Markdown/JSON: instrucciones, resultados y alcance verificable.

## Ejecución y comprobación

Desde la raíz del proyecto, en PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=runs/privacy-fix-20261110/full-tests-final.xml
node --test tests/ui-and-workflow.test.cjs
.\.venv\Scripts\python.exe -m pip check
```

Al actualizar la instalación local:

```powershell
.\.venv\Scripts\python.exe -m scripts.update_langflow_component
.\.venv\Scripts\python.exe -m scripts.align_langflow --sync
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-Soc.ps1 -Restart -RestartLangflow
.\.venv\Scripts\python.exe -m scripts.align_langflow
```

`--sync` exporta el mismo grafo comprobado. No copia claves ni cambia modelos. La instalación completa del proyecto y su módulo `src` son necesarios para importar el export; un import fallido no habilita una salida sin filtro.

Las pruebas con datos personales ficticios usan `httpx.MockTransport` y bases temporales; no requieren permiso de transmisión porque no contactan proveedores. Las comprobaciones cloud reales se limitan al caso público expresamente autorizado previamente, con huella `882af8b669b92ad9695a4004311ee477464da3d84db50bfa91d3083f63a82b84`. Nunca se mandan las fixtures de privacidad a una API real.

```powershell
.\.venv\Scripts\python.exe -m scripts.align_langflow --probe
$env:SOC_PHASE0_APPROVED_INPUT_SHA256='882af8b669b92ad9695a4004311ee477464da3d84db50bfa91d3083f63a82b84'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p live_phase0_alignment.py -v
```

## Resultados verificables

Las evidencias de esta corrección están en `runs/privacy-fix-20261110/`, excluido de Git. El resumen estructurado es `verification.json`; conserva referencias a las ejecuciones y no cuerpos de reportes.

| Comprobación | Estado final | Resultado y evidencia |
| --- | --- | --- |
| Regresión Python completa | Superada | 170 pruebas y 102 subpruebas; cero fallos, errores u omisiones; `full-tests-final.xml` (242.289 segundos) |
| Casos de privacidad | Superada | 69 casos incluidos en las 170 pruebas; `tests/test_privacy.py` intercepta los cuerpos HTTP de ambos proveedores |
| Clasificación y fallback | Superada | Éxito principal, 429/500, timeout, respuesta malformada, reintento Gemini y fallo de ambos; las copias protegidas se conservan; seguridad y baja confianza mantienen su política |
| Originales, RBAC y auditoría | Superada | JWT real de cinco roles en backend aislado, anónimo/token inválido, propietario/otro solicitante, original intacto, evidencia sin texto y evaluador compatible |
| Caso 06 real aislado | Superada | `runs/20261110T212107Z_e2e_2d306b56/e2e-result.json`: PostgreSQL 16.15, Groq real, n8n, ambos SLA, notificación, idempotencia y rechazo de UPDATE/DELETE/TRUNCATE de auditoría |
| Gemini real después del cambio | Superada | `fallback-final.json`: fallo técnico por modelo Groq inexistente solo en esa petición; respuesta de Gemini y versión/hash real del filtro confirmados |
| React y workflow | Superada | TypeScript/Vite compilados; dos pruebas Node del workflow aprobadas |
| Dependencias | Superada | `pip check`: No broken requirements found; ninguna dependencia nueva |
| Integridad | Superada | `file-integrity.json`: SPEC, seis originales, reglas, workflow, prompt y configuración operacional conservados |
| Sistema operativo después de recuperación | Superada en la comprobación final | `production-runtime.json`: cinco servicios ok; PostgreSQL fuera de recuperación; 7 reportes, 7 asignaciones y 0 revisiones; Streamlit HTTP 200 |
| Acceso real al backend operativo | Superada | Lectura pública 401; login/me/lectura del Analista 200 y logout 204; cero reportes de prueba creados en producción |
| Garantías fuera de cobertura | No ejecutadas / no certificadas | PII real arbitraria, anonimato formal, cifrado de disco/backups, retención del proveedor e inspección de adjuntos |

Leyenda: Superada significa ejecución observada con esa evidencia. Los resultados de PII usan datos ficticios y HTTP simulado; cloud recibe únicamente el caso público autorizado. Unidades: pruebas, subpruebas y casos son conteos; el tiempo de suite está en segundos. Cómo leerlo: los 69 casos de privacidad forman parte de las 170 pruebas y no deben sumarse otra vez. Hallazgo clave generado de los resultados: 0 fallos finales en 170 pruebas, evidencia de la misma política en el E2E y en Gemini, y original conservado. Limitación: una observación cloud no mide precisión, cobertura poblacional ni percentiles de rendimiento.

Las primeras ejecuciones detectaron y permitieron corregir el tipo de marcador de teléfono, la idempotencia y el manejo de regex inválida. Una ampliación del test del evaluador necesitó aportar el JWT del analista; se corrigió el test sin debilitar RBAC. Los fallos de esas ejecuciones previas no se mezclan con `full-tests-final.xml`, que tiene cero fallos. Se conserva una advertencia preexistente de Starlette/httpx y la advertencia informativa del bundle de gráficos de Vite.

Durante el despliegue PostgreSQL entró repetidamente en recuperación. Se verificaron lecturas, se reinició su contenedor y, con autorización expresa por afectar otras aplicaciones, Docker Desktop. El cierre normal de su interfaz agotó el tiempo; se volvió a iniciar Docker. Para recargar FastAPI se precargaron los módulos y se esperó de forma acotada a su inicialización existente, sin saltarla ni cambiar esquema o datos. La comprobación final confirmó los cinco servicios y autenticación real. Esta evidencia describe ese instante; la causa de las recuperaciones no se atribuye al filtro ni se considera diagnosticada.

Tras restaurar los contenedores previos, uno ajeno al SOC no pudo volver a publicar su endpoint en la IP LAN configurada. `docker-recovery.json` identifica el contenedor y el error. Se conservó su configuración, pues pertenece a otro proyecto. Esta incidencia de restauración se distingue de la aceptación del control de privacidad y de los cinco servicios SOC verificados.

**Resultado de aceptación: corrección NF-02 aprobada dentro de la cobertura probada.** El filtro está integrado antes de los proveedores, conserva los originales y el flujo Caso 06 y dispone de evidencia automática y real. La matriz conserva Parcial para garantías más amplias no demostradas. La Fase 1 permanece sin iniciar.

## Límites del control

El detector es determinístico y su cobertura se define por los formatos y casos de prueba descritos. No constituye una garantía de anonimización universal: nombres libres no reconocidos, idiomas, direcciones o codificaciones no contemplados pueden requerir ampliar la política y validar casos representativos. Las pruebas de conservación técnica comprueban información de entrada y contratos; no equivalen a una medición de precisión del modelo ni a una evaluación de pérdida de utilidad sobre toda la población.

No se certifican mediante esta corrección cifrado de disco/backups, políticas de retención de los proveedores, anonimato formal, inspección de adjuntos ni ausencia universal de PII. No se envió PII real para probarlos ni se crean datos reales ficticios. Las ejecuciones manuales que introduzcan originales directamente en la GUI de LangFlow pueden generar trazas locales antes del componente; el filtro de salida protege los proveedores, mientras que el recorrido soportado de reportes desde FastAPI entrega texto ya protegido a LangFlow.

La evaluación de cobertura sobre muestras reales autorizadas y las métricas académicas conservan su alcance propio. Esta entrega implementa la protección operacional solicitada y no inicia el inventario ni la experimentación de la Fase 1.
