# Fase 1 · Módulo de datos del SOC

El módulo **Datos del SOC** incorpora el inventario, la exploración, las revisiones y la preparación de evidencia del Caso 06. Aplica el SPEC definitivo 2.1 y adapta las actividades de datos del Promptuario a reportes de seguridad. La entrega abarca la Fase 1.

## Supuestos y decisiones de implementación

- **SUPUESTO.** Una corrección en Streamlit es una anotación analítica versionada. La revisión operativa mantiene su recorrido por React y FastAPI. Cada corrección local queda ligada al original consultado y a la política de privacidad que se aplicó.
- **SUPUESTO.** La identidad del revisor y la fecha de una nueva versión provienen del JWT y del reloj UTC del servidor. El identificador de grupo es editable. El identificador original del incidente se usa para vincular, buscar y auditar la representación.
- **SUPUESTO.** EuRepoC y la simulación conservan sus propios campos y escalas. La etiqueta provisional VERIS/VCDB, la predicción operativa, la etiqueta DEMO y la anotación humana se muestran con su procedencia por variable.
- **SUPUESTO.** Los vínculos exactos y los candidatos por similitud sirven para revisar fugas y duplicados. La evidencia estadística de esta fase es descriptiva, dada la selección de cada fuente y la dependencia entre representaciones del mismo incidente.

## Ejecución

Desde PowerShell, en la raíz del repositorio. Ejecuta los dos primeros comandos si necesitas arrancar el SOC y comprobar la configuración. Mantén Streamlit abierto en otra terminal para usar la interfaz.

~~~powershell
powershell -ExecutionPolicy Bypass -File .\Start-Soc.ps1
.\.venv\Scripts\python.exe -m scripts.analytics --check
.\.venv\Scripts\python.exe -m scripts.analytics
~~~

Abre [Streamlit local](http://127.0.0.1:8502), inicia sesión con tu cuenta SOC y elige **Datos del SOC → Cargar inventario**. **Explorar** admite búsqueda por texto protegido, ID, clave y grupo, filtros combinables y paginación. **Catálogo** muestra el esquema, la huella y la cobertura. **Calidad** muestra los criterios y sus evidencias. **Estadística** permite elegir variables, revisar faltantes y exportar figuras. **Manifiestos** muestra la situación de la reserva, genera versiones y permite descargarlas.

Administrador, Analista y Gestor pueden consultar. Administrador y Analista pueden guardar revisiones y manifiestos. En **Explorar**, elige un registro y abre **Editar metadatos**. Para confirmar una referencia, selecciona **Revisado**, indica los campos que validaste y marca la confirmación de guardado. El historial muestra los cambios protegidos, el revisor, la fecha UTC, la huella y el identificador de la operación auditada.

## Inventario observado

| Fuente | Ubicación y formato | Registros | Etiquetas o campos disponibles |
| --- | --- | ---: | --- |
| VERIS VCDB original | `tmp/datasets-real/vcdb-f6f98c0.zip`, ZIP de JSON validados | 10.047 | Acciones y activos VERIS, resumen cuando existe, revisión del repositorio `f6f98c0` |
| Índice VCDB | `.venv/soc-runtime/dataset/preview.json`, JSON | 1.732 | Sugerencias de tipo, referencias y partición provisional. Se reprodujo y se cotejó con el ZIP |
| Piloto VCDB | `integrations/dataset/vcdb-pilot.json`, JSON | 8 | Referencia humana de tipo para los ocho. El piloto carece de referencia de severidad y activo |
| Cola reservada | `.venv/soc-runtime/dataset/holdout-review-queue.json`, JSON | 160 | Selección de candidatos |
| Preparación reservada | `.venv/soc-runtime/dataset/holdout-preparation.json`, JSON | 160 | Decisión de inclusión, grupo y redacción |
| EuRepoC | `tmp/datasets-real/eurepoc_global_dataset_1_3.csv`, CSV 1.3.2 | 3.414 | Tipos originales, intensidad y recuentos. Se conservan los 85 encabezados, incluidos los nombres repetidos |
| PostgreSQL 16.15 operacional | `GET /api/reportes` y `GET /api/reportes/{report_id}/colaboracion` mediante FastAPI | 7 en la consulta verificada | 1 real, 6 DEMO y 0 revisiones operativas. El hash corresponde al corte de la API |
| Simulación académica | `output/articulo-soc/supplementary/synthetic-cases.csv`, CSV existente, semilla 20261103 | 2.400 | Clase y severidad indexadas, confianza y tiempos asumidos |

**Cómo leerlo.** La unidad es la fila de cada fuente. Consulta Catálogo para las columnas, revisiones y huellas SHA-256 observadas. **Hallazgo de la verificación.** El piloto aporta 8 referencias de tipo y tiene 0 para severidad y activo. **Limitaciones.** El archivo, el índice, el piloto y la reserva pueden representar el mismo incidente. Las dos vistas de la reserva documentan los mismos 160 candidatos en momentos distintos. El endpoint operacional ofrece un corte reciente.

## Calidad, estadística y versionado

- Se revisan estructura, faltantes, taxonomía, duplicados por ID o descripción, desbalance, mezcla de naturalezas, referencias humanas y solapamiento de grupos. Las agrupaciones enlazan ID del incidente, campañas nativas de VCDB, grupos declarados, referencias de artículo y descripciones normalizadas exactas. EuRepoC aporta varias referencias por registro cuando su celda las contiene. La evidencia histórica reutiliza las exclusiones, el índice y las ejecuciones previas del piloto. Un vínculo por artículo es evidencia para revisar, porque un artículo puede describir varios incidentes.
- Los candidatos por similitud usan coseno sobre unigramas y bigramas de texto protegido. El umbral inicial es 0,86, con un mínimo de ocho palabras y equivalencias técnicas configurables. El informe cuenta un representante por descripción exacta y omite pares ya vinculados en el mismo grupo. El criterio puede omitir paráfrasis o coincidencias entre idiomas y requiere confirmar cada candidato.
- Las frecuencias categóricas usan registros válidos por naturaleza y procedencia como denominador. Una etiqueta múltiple aporta una vez a cada categoría. El resumen numérico incluye n, faltantes, media, mediana, desviación muestral, cuartiles lineales y rango. Se cuentan términos de un vocabulario técnico sobre descripciones protegidas. Los gráficos incorporan unidades, leyenda cuando corresponde, guía, hallazgo derivado de datos y límites. El PNG exportado usa 600 DPI.
- FastAPI autoriza y audita cada consulta y publicación con el JWT vigente. La base local `runs/phase1/revisiones.sqlite3` guarda el historial de solo inserción. Los guardados validan la versión y la huella del original. Un fallo de autorización impide publicar la corrección. Un cambio del texto devuelve a propuesta las referencias que requieren nueva confirmación. El enmascaramiento tiene la cobertura de la política local compartida.
- Cada versión del manifiesto vive en `runs/phase1/manifiestos/<versión>/manifest.json`. El contenido canónico registra configuración, semilla, versiones, huellas de archivos y de la respuesta operativa, esquema, calidad, revisión aplicada y agrupaciones. Incluye los identificadores candidatos por objetivo y sus advertencias. La fecha y el identificador de publicación quedan fuera de la huella de contenido. La descarga recalcula la huella.
- El acceso a prueba requiere las decisiones de preparación, un manifiesto reservado validado, dos revisores distintos para cada tipo y separación de pilotos y referencias históricas. Las revisiones individuales del editor complementan el inventario. La verificación independiente de la reserva se realiza con el procedimiento existente en `scripts/vcdb_review.py`.

## Archivos de la Fase 1

| Componente | Archivos | Propósito |
| --- | --- | --- |
| Fuentes, análisis y persistencia | `src/data/models.py`, `sources.py`, `quality.py`, `statistics.py`, `revisions.py`, `manifest.py`, `workspace.py`, `catalog.py` | Esquemas, inventario protegido, calidad, revisiones, grupos y manifiestos |
| Interfaz y reportes | `pages/03_Datos.py`, `pages/00_Inicio.py`, `src/reports/data_presentation.py`, `src/utils/streamlit_runtime.py` | Navegación, vistas, exportación y sesión privada |
| Integración y configuración | `src/inference/services.py`, `backend/analytics_audit.py`, `src/utils/config.py`, `src/utils/privacy.py`, `config/analytics.yaml`, `config/datasets.yaml`, `scripts/vcdb_review.py` | Contrato de colaboración, JWT y bitácora, configuración, privacidad y evidencia histórica |
| Pruebas y documentación | `tests/analytics/conftest.py`, `tests/analytics/test_data_module.py`, `tests/analytics/test_data_page.py`, `README.md`, `docs/FASE_1.md` | Pruebas aisladas, smoke tests, guía y aceptación |

**Cómo leerlo.** Cada fila agrupa archivos por responsabilidad. **Hallazgo de la revisión.** El acceso a PostgreSQL desde Streamlit usa los dos endpoints ya disponibles y la bitácora usa su endpoint existente. **Limitación.** Los artefactos de ejecución se guardan fuera de Git. Los reportes que cambien de huella requieren actualizar el inventario antes de confirmar una edición.

## Verificación reproducible

~~~powershell
New-Item -ItemType Directory -Force runs/phase1/verification | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --junitxml=runs/phase1/verification/pytest-repeticion.xml
node --test tests/ui-and-workflow.test.cjs
npm.cmd run build --prefix frontend
.\.venv\Scripts\python.exe -m pip check
~~~

Para verificar la reproducibilidad con datos reales, carga el inventario y guarda un manifiesto. Actualiza el inventario y guarda una segunda versión mientras se mantengan los mismos archivos, las mismas revisiones y el mismo corte de FastAPI. Compara `content_sha256` y usa **Preparar descarga** para validar la lectura de la versión guardada.

## Resultados del 10 de noviembre de 2026

- Dos lecturas independientes con JWT de Analista accedieron a las ocho fuentes en 74,92 y 32,31 segundos. Se verificaron seis SHA-256 de archivos originales contra la evidencia de la Fase 0 y se reprodujo el índice VCDB a partir del ZIP. Se comprobó también la huella del SPEC. [Evidencia de ejecución](../runs/phase1/verification/live-final.json).
- El inventario identificó 23 grupos de identificadores repetidos dentro de una fuente, 81 grupos de descripciones exactas repetidas, 679 representaciones con texto incompleto y 78 pares candidatos por similitud. Hubo 1 par por revisar entre reserva y otro grupo y 0 grupos exactos que conectaran piloto y reserva. Se incorporaron 13 campañas VCDB. De 11.774 grupos calculados, 1.820 vinculan más de una representación. El mayor reúne 1.909 representaciones por conectividad transitiva. Conviene revisar sus vínculos antes de usarlo en una partición supervisada. [Detalle de calidad](../runs/phase1/verification/live-final.json).
- Las versiones `20261110T231302116879Z_947a4da3ad3b` y `20261110T231339973135Z_10b8cc582884` se leyeron y validaron a través del flujo autenticado. Ambas tienen la huella canónica `d382847b8953599a088e2ae5098c40a0fead359f0164f822e3debc6c5342f14a`. [Primer manifiesto](../runs/phase1/manifiestos/20261110T231302116879Z_947a4da3ad3b/manifest.json), [segundo manifiesto](../runs/phase1/manifiestos/20261110T231339973135Z_10b8cc582884/manifest.json).
- Pytest aprobó **182 pruebas y 102 subpruebas** en 201,34 segundos, con cero fallos, errores u omisiones. Incluye tres smoke tests de Datos y una regresión de campañas nativas. Se registró una advertencia de deprecación de Starlette para TestClient. [JUnit](../runs/phase1/verification/pytest-final.xml).
- Las dos pruebas Node del workflow y la compilación de React pasaron. Vite informó el aviso de tamaño del paquete de gráficos. `pip check` confirmó que las dependencias instaladas son coherentes. [Workflow](../runs/phase1/verification/workflow.txt), [compilación](../runs/phase1/verification/react-build.txt).
- React y Streamlit devolvieron HTTP 200. FastAPI informó estado OK para sus cinco servicios al cierre. Durante una pasada inicial, PostgreSQL entró en recuperación y se observó HTTP 503. Las dos lecturas de aceptación se completaron después de la recuperación. [Salud tras recarga](../runs/phase1/verification/services.json), [salud al cierre](../runs/phase1/verification/live-final.json).

## Matriz de aceptación

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Fuentes accesibles y verificables | Cumple | Ocho lecturas autenticadas por ejecución, huellas verificadas y esquema observado |
| Edición versionada con originales íntegros | Cumple | Pruebas de persistencia protegida, autoría, historial, confirmación, concurrencia y rollback ante fallo de auditoría. Comparación SHA-256 de originales |
| Validación de registros defectuosos y grupos | Cumple | Casos de prueba de estructura, etiquetas, grupos, duplicados y preparación reservada. Hallazgos observados en el inventario |
| Interpretabilidad de tablas y gráficos | Cumple | Smoke tests de todas las vistas y verificación de la densidad del [PNG de cobertura](../runs/phase1/verification/cobertura-tipo.png) |
| Distinción de procedencia y calidad de etiquetas | Cumple | Referencias por objetivo, sugerencias, valores de taxonomía externa, predicciones, DEMO y simulación con evidencias separadas |
| Manifiesto reproducible | Cumple | Dos versiones con la misma huella. Prueba automatizada de rechazo de un contenido alterado |
| Pruebas automatizadas y smoke tests | Cumple | 182 pruebas Python, 102 subpruebas y 2 pruebas del workflow |
| Integración con servicios operativos | Cumple | Lectura y auditoría con JWT real, regresión de FastAPI y privacidad, build de React y salud de FastAPI, PostgreSQL, Redis, LangFlow y n8n |

**Cómo leerlo.** Cumple significa que se ejecutó la verificación descrita. Los números de pruebas, grupos y registros se expresan como conteos. **Hallazgo de la verificación.** Los ocho criterios de implementación se cumplen y la reserva conserva 160 decisiones pendientes. **Limitaciones.** El estado de los servicios corresponde a las comprobaciones observadas. La reproducibilidad usa el mismo corte de datos y configuración.

El manifiesto registra **8 candidatos por tipo y 0 por severidad o activo**. La prueba reservada sigue pendiente para los tres objetivos. Se requiere cerrar las 160 decisiones, comprobar las relaciones candidatas con la reserva y completar la revisión independiente del tipo. Severidad y activo requieren evidencia humana por campo.
