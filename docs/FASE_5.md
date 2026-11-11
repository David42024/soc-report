# Fase 5 · Reportes científicos y operacionales

El módulo consolida evidencia versionada del SOC en PDF, Word editable y Excel. Usa el SPEC definitivo 2.1, RF-10, el Promptuario adaptado a texto y los resultados publicados de las Fases 1 a 4.

## Supuestos y decisiones

- La exportación científica usa el permiso operativo report_export, reservado a administrador y gestor. FastAPI valida el JWT al consultar evidencias, preparar figuras y publicar el informe. Cada generación tiene autorización inicial, resultado y auditoría del actor.
- Las exportaciones nuevas contienen agregados. Las vistas de Explicabilidad y Evaluación conservan el acceso autorizado a fragmentos individuales. Los nombres de personas, equipos, activos, textos originales y citas individuales quedan fuera de la proyección científica.
- El intervalo selecciona fechas de recepción operativa, inclusivas y en hora de Lima, mediante /api/dashboard. Cada resultado experimental conserva su cohorte completa y fecha originales.
- El informe hereda el origen y las limitaciones de cada referencia. Las pruebas sintéticas aparecen identificadas en metodología, resultados y conclusiones.
- Las secciones carentes de evidencia conservan su estado pendiente. Un guion largo representa un valor ausente y los controles estadísticos conservan su motivo técnico.

## Estructura y justificación de cambios

| Archivo | Cambio y motivo |
| --- | --- |
| src/reports/scientific.py | Contratos de selección, plantillas, tablas, figuras e instantánea inmutable común a todos los formatos. |
| src/reports/composition.py | Proyecciones agregadas de manifiestos, folds, configuraciones finales, evaluación, XAI y tablero SOC. Reutiliza interpretaciones de las fases previas. |
| src/reports/exporters.py | Composición científica de PDF, DOCX, XLSX y archivo de figuras PNG/SVG. |
| src/reports/workspace.py | Orquestación autenticada, comprobación de huellas, almacenes existentes y publicación atómica en runs/phase5/. |
| pages/07_Informes.py | Selección, previsualización, trabajos en segundo plano y descargas privadas a la sesión. |
| backend/exports.py | Serialización compartida de WeasyPrint, python-docx y openpyxl, reutilizada por los exportadores operativos. |
| backend/analytics_audit.py | Acciones de informes con JWT, permiso report_export y módulo analitica/informes. |
| src/evaluation/store.py | Lectura de comparaciones archivadas y verificación de integridad. |
| src/inference/services.py | Adaptador autenticado del endpoint agregado y parámetros de fecha. |
| src/utils/config.py, config/analytics.yaml | Registro de página, endpoint, directorio, límites y dimensiones del lienzo de figuras. |
| src/utils/streamlit_runtime.py | Recurso compartido sin tokens y limpieza del estado privado de informes. |
| scripts/soc_report.py | Generación reproducible desde CLI con contraseña privada y segundo factor existente. |
| tests/analytics/test_scientific_reports.py | Regresión de seguridad, consistencia, formatos, DPI, auditoría, pendientes e interfaz. |
| README.md | Acceso al módulo y documentación de ejecución. |

Las dependencias utilizadas ya están fijadas en requirements.txt y requirements.lock.txt.

## Tablas e interpretación

Las tres plantillas permiten seleccionar secciones. La académica incluye datos, entrenamiento, evaluación, explicabilidad y operación. La técnica prioriza operación, evaluación y XAI. La ejecutiva reduce el inventario y prioriza los indicadores de atención y disponibilidad de referencias.

Cada tabla conserva su título, variables, unidades, instrucciones de lectura, hallazgo derivado de sus valores y limitaciones. La estructura común conserva estimaciones numéricas, conteos, referencias y valores ausentes. Las cifras impresas usan cuatro decimales para medidas continuas y dos para porcentajes. Excel conserva el valor numérico completo y aplica el mismo formato visible.

Los IC provienen de la Fase 3. Cuando faltan grupos o variación, se publica el motivo. Las comparaciones se incluyen únicamente si ambos resultados elegidos participan en un contraste archivado. La generación de informes conserva la reserva de Prueba y las predicciones publicadas.

Las matrices se exportan en tablas y mapas de color con referencia en filas y predicción en columnas. Los identificadores textuales de activos usan categorías ordinales dentro de cada evaluación. Las áreas ROC/PR requieren scores continuos registrados.

Los indicadores operativos reutilizan la definición de SLA de FastAPI. Se informa la población DEMO junto al total. La concordancia conjunta usa la muestra revisada por humanos y conserva su denominador. Un origen fallback requiere metadatos adicionales para atribuir una respuesta a Gemini.

## Exportaciones y seguridad

PDF usa WeasyPrint con cabeceras repetidas, títulos, numeración y figuras vectoriales. Word usa tablas editables, encabezados repetidos, leyendas, figuras PNG y numeración de página. Excel contiene hojas por sección, metadatos y una hoja imprimible por figura, formatos numéricos y comprobaciones de proporciones mediante fórmulas. Las fórmulas se recalculan al abrir el archivo. Sus entradas y las proporciones observadas se conservan como números.

Las cadenas externas se escriben como texto en Excel y los HTML se escapan. Las credenciales permanecen en el mecanismo de autenticación existente. Los tokens y las descargas pertenecen al estado privado de cada sesión. La generación revalida el rol antes de publicar y retira la publicación si falla la auditoría de finalización.

Cada versión contiene manifest.json, los tres formatos y un ZIP de figuras. El manifiesto incluye la instantánea agregada y las huellas SHA-256 de cada salida. Los PNG conservan 600 DPI y los SVG son vectoriales. Las dimensiones nominales del lienzo se configuran en pulgadas y el recorte ajusta los márgenes alrededor del contenido.

## Ejecución

~~~powershell
.\.venv\Scripts\python.exe -m scripts.analytics --check
.\.venv\Scripts\python.exe -m scripts.analytics
~~~

Abre http://127.0.0.1:8502, accede con una cuenta autorizada y selecciona **Reportes científicos y operacionales**. Elige plantilla, secciones, fechas y versiones. Pulsa **Previsualizar informe** y luego **Generar PDF, Word y Excel**.

La CLI solicita contraseña y segundo factor sin guardarlos en argumentos.

~~~powershell
.\.venv\Scripts\python.exe -m scripts.soc_report --username USUARIO_SOC --template academico --manifest VERSION_FASE_1 --experiment VERSION_FASE_2 --evaluation VERSION_FASE_3 --explanation VERSION_FASE_4
~~~

Para verificar las pruebas en Windows se utilizan los componentes gráficos ya configurados para la exportación operativa.

~~~powershell
New-Item -ItemType Directory -Force runs/phase5/verification | Out-Null
$env:WEASYPRINT_DLL_DIRECTORIES='C:/Program Files/Tesseract-OCR'
$env:FONTCONFIG_FILE=(Join-Path (Get-Location) '.venv/soc-runtime/fonts.conf').Replace([char]92,[char]47)
.\.venv\Scripts\python.exe -m pytest tests/analytics/test_scientific_reports.py -q
~~~

## Evidencias y aceptación

Los resultados de ejecución y comprobación visual se registran en runs/phase5/verification/. Las versiones de ejemplo remiten a los artefactos existentes de las Fases 1 a 4 y al tablero consultado con JWT. El holdout real conserva el estado identificado por el manifiesto elegido.

### Pruebas automatizadas

| Comprobación | Resultado | Evidencia |
| --- | --- | --- |
| Regresión del sistema y Fases 0 a 4 | 232 pruebas y 102 subpruebas superadas | regression.xml |
| Pruebas específicas finales de reportes | Diez casos, incluida la cobertura del manifiesto y la integridad de originales | reports-final-verified.xml |
| Apertura nativa de documentos | Las tres plantillas se abren en Word y Excel | office-verification.json |
| Cifras y huellas | Todas las celdas de las tablas Word y Excel se comparan con la instantánea y están presentes en PDF | export-validation.json |
| Fórmulas y credenciales | 38 resultados recalculados coinciden con sus conteos y cero coincidencias con credenciales configuradas | formula-and-credential-check.json |
| DPI y vectorización | Todas las figuras rasterizadas conservan 599,9988 DPI en ambos ejes, dentro de la precisión del formato PNG. SVG válido asociado | export-validation.json |
| Interfaz con servicios reales | JWT del gestor, previsualización, imagen, cuatro descargas y eventos de auditoría completados | live-verification.json |
| Preservación operativa | Siete reportes, siete asignaciones y cero revisiones conservan sus huellas antes y después del smoke | live-verification.json |
| Datasets originales | VCDB, EuRepoC y simulación del artículo conservan su SHA-256 de Fase 1 | original-datasets.json |
| Dependencias | pip check finaliza correctamente | Comando documentado y ejecución de verificación |

La regresión completa precede a los ajustes visuales finales y al caso adicional de cobertura. Las diez pruebas específicas se ejecutaron de nuevo sobre la versión final. La ejecución completa conserva una advertencia de Starlette/httpx y otra de scikit-learn sobre clases presentes únicamente en las predicciones de una prueba controlada.

Las primeras pruebas detectaron dos aserciones de verificación inadecuadas, una cota arbitraria de píxeles y el nombre del elemento de imagen de AppTest. Se corrigieron. La revisión visual también detectó figuras divididas entre páginas de Excel y un borde heredado en el estilo Title de Word. Se corrigieron la distribución de hojas y el estilo, con pruebas de regresión.

El renderizador empaquetado de DOCX carece de LibreOffice en este equipo. La comprobación final usa Word y Excel nativos en instancias ocultas, con cierre sin modificar los originales. Los PDF resultantes de verificación y los PDF del exportador se rasterizaron con Poppler. Las salidas finales conservan sus huellas.

### Integración operativa y recuperación

PostgreSQL volvió a entrar en recuperación durante los primeros intentos autenticados y produjo HTTP 503. Se reinició su contenedor y posteriormente Docker Desktop, utilizando la autorización previa. FastAPI y Streamlit se reconectaron. La generación posterior de las tres plantillas y el smoke de la página concluyeron con auditoría confirmada y los cinco servicios del SOC en estado correcto.

Los ejemplos anteriores generados desde archivos, identificados con operación pendiente, se conservan como evidencia de esa condición. Los ejemplos finales de examples.json contienen los indicadores consultados en el tablero operativo. La disponibilidad observada corresponde al instante de comprobación.

La prueba operativa generó informes y eventos de auditoría. Realizó cero clasificaciones nuevas y cero solicitudes a proveedores LLM. Conservó las tablas originales comprobadas.

### Criterios de aceptación

| Criterio | Estado | Evidencia y alcance |
| --- | --- | --- |
| PDF, Word y Excel generados | Cumple | Tres plantillas completas y generación autenticada confirmada |
| Cifras concordantes | Cumple | Comparación contra una instantánea común y comprobación independiente de celdas, PDF y fórmulas |
| PNG de 600 DPI verificables | Cumple | Cabecera PNG comprobada en todas las figuras y SVG asociado |
| Interpretaciones dinámicas | Cumple | Título, variables, unidades, cómo leerlo, hallazgo calculado y limitaciones en tablas y figuras |
| Métricas sustentadas | Cumple | Resultados archivados, referencias identificadas y valores ausentes conservados |
| Archivos abiertos correctamente | Cumple | Parsers independientes y apertura/renderización en Word y Excel |
| Pruebas y evidencias | Cumple | Regresión completa, diez casos finales y comprobación con backend real |
| Privacidad y trazabilidad | Cumple en el alcance probado | RBAC, JWT, auditoría, datos agregados, revisión de credenciales configuradas y huellas |

La evaluación predictiva real continúa pendiente del holdout humano revisado. Las métricas predictivas incluidas en los ejemplos corresponden a las pruebas sintéticas archivadas. Los indicadores operativos contienen siete reportes, seis marcados DEMO. Estas poblaciones y limitaciones se muestran en cada informe.

La Fase 5 cumple sus criterios de aceptación en las verificaciones descritas.

## Ejemplos finales

Las siguientes versiones se generaron mediante la sesión real del gestor y su auditoría confirmada. Las descargas y el manifiesto permanecen en runs/phase5/.

| Plantilla | Versión | Descargas |
| --- | --- | --- |
| academico | 20261111T053224050188Z_6e0f7d4b6809 | [PDF](../runs/phase5/20261111T053224050188Z_6e0f7d4b6809/soc-academico-20261111T053224050188Z_6e0f7d4b6809.pdf) · [DOCX](../runs/phase5/20261111T053224050188Z_6e0f7d4b6809/soc-academico-20261111T053224050188Z_6e0f7d4b6809.docx) · [XLSX](../runs/phase5/20261111T053224050188Z_6e0f7d4b6809/soc-academico-20261111T053224050188Z_6e0f7d4b6809.xlsx) |
| tecnico | 20261111T053432304421Z_962e628fab12 | [PDF](../runs/phase5/20261111T053432304421Z_962e628fab12/soc-tecnico-20261111T053432304421Z_962e628fab12.pdf) · [DOCX](../runs/phase5/20261111T053432304421Z_962e628fab12/soc-tecnico-20261111T053432304421Z_962e628fab12.docx) · [XLSX](../runs/phase5/20261111T053432304421Z_962e628fab12/soc-tecnico-20261111T053432304421Z_962e628fab12.xlsx) |
| ejecutivo | 20261111T053459626431Z_eae25399287c | [PDF](../runs/phase5/20261111T053459626431Z_eae25399287c/soc-ejecutivo-20261111T053459626431Z_eae25399287c.pdf) · [DOCX](../runs/phase5/20261111T053459626431Z_eae25399287c/soc-ejecutivo-20261111T053459626431Z_eae25399287c.docx) · [XLSX](../runs/phase5/20261111T053459626431Z_eae25399287c/soc-ejecutivo-20261111T053459626431Z_eae25399287c.xlsx) |

La recuperación intermitente de PostgreSQL reapareció en una comprobación posterior al smoke. Las exportaciones y los eventos confirmados corresponden a los instantes registrados. Esta intermitencia continúa como limitación del entorno operativo.

Las evidencias finales están en [validación de exportaciones](../runs/phase5/verification/export-validation.json), [apertura en Office](../runs/phase5/verification/office-verification.json), [regresión completa](../runs/phase5/verification/regression.xml), [pruebas finales](../runs/phase5/verification/reports-final-verified.xml), [página con servicios reales](../runs/phase5/verification/live-verification.json) y [auditoría de versiones finales](../runs/phase5/verification/final-audit.json).

La revisión final compara 58 tablas Word y 1.109 celdas numéricas o textuales de Excel con sus instantáneas, comprueba su presencia en PDF y valida 38 fórmulas recalculadas. El resumen verificable está en [aceptación](../runs/phase5/verification/acceptance.json). La última comprobación de FastAPI y Streamlit devolvió HTTP 200 y una conexión PostgreSQL nueva completó su lectura.
