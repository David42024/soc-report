# Validación científica y operacional del Caso 06

Corte del 11 de noviembre de 2026. La evaluación predictiva real sigue pendiente. La reserva contiene **160 candidatos sin preparación humana cerrada**, y la configuración no tiene un sello de Prueba ni una corrida final real. La ventana operacional encontró **13 observaciones degradadas de 61** en FastAPI por PostgreSQL, con recuperación entre bloques. Se completaron las comprobaciones de procedencia, el protocolo de anotación y las pruebas aisladas de latencia y fallback. [Diagnóstico de datos](../runs/validacion-caso06/20261111T182925Z/diagnostico-datos.json) · [Observación operacional](../runs/validacion-caso06/20261111T182925Z/servicios-resumen.json)

Se leyeron completos el SPEC v2.1 y el Promptuario docente, la matriz general, Fase 7 y su aceptación. La huella canónica de aceptación histórica coincidió con sus 26 archivos fuente y seis evidencias al inicio. Los 284 tests y 102 subtests de la entrega anterior se conservan como evidencia técnica. El nuevo informe registra su propia muestra y sus pruebas. [SPEC](<C:/Users/USERJSSV/Downloads/ARCHIVO_SPEC_SOC_Caso06_Concordante_Groq_Gemini.docx>) · [Promptuario](<C:/Users/USERJSSV/Downloads/38833FF26BA1D.UnigramPreview_g9c9v27vpyspw!App/Promptuario.docx>) · [Aceptación Fase 7](../runs/phase7/verification/acceptance.json) · [Matriz anterior](../runs/validacion-caso06/20261111T182925Z/matriz-previa.md)

## Diagnóstico y orden de ejecución

1. **Preparar la anotación y resolver independencia.** Se reprodujo el índice desde el ZIP fijado y se cotejaron las huellas, los grupos y la elegibilidad. La copia de preparación y el protocolo están disponibles. El responsable SOC debe designar revisores, decidir los 160 casos y resolver los vínculos señalados.
2. **Caracterizar la indisponibilidad con bajo impacto.** Se midieron salud y latencia locales y se revisaron eventos del contenedor. El equipo operador puede reproducir la observación y preparar una comparación de almacenamiento con una base aislada.
3. **Confirmar el contrato experimental.** Se comprobó el bloqueo vigente y se probaron el uso único y las métricas en condiciones controladas. Hay que acordar el alcance de clases, las etiquetas por campo y la separación de grupos antes del sello. La selección de configuraciones sigue en Fase 2.
4. **Cerrar evidencia científica y operacional.** Con referencias suficientes, ejecutar la evaluación de Fase 3. Para una campaña activa en cloud se necesita presupuesto, alcance de datos y destinos autorizados. RF-01 y RF-03 tienen opciones de ampliación acotadas que necesitan aprobación propia antes de tocar la operación. [Protocolo de anotación](PROTOCOLO_ANOTACION_CASO06.md) · [Matriz actualizada](CUMPLIMIENTO_FASES_0_A_7.md)

## Inventario y suficiencia de referencias

| Fuente observada | Registros | Referencia y uso |
|---|---:|---|
| VCDB fijado `f6f98c0` | 10.047 JSON validados | Procedencia histórica. Las variables VERIS son evidencia de fuente |
| Índice VCDB | 1.732 | Sugerencias provisionales reproducidas desde el ZIP |
| Piloto VCDB | 8 | Tipo humano de un revisor por caso. Dos de cada tipo en phishing, malware, acceso no autorizado y uso indebido. Ocho grupos, todos retrospectivos |
| Cola y preparación de la reserva | 160 | Los mismos 160 candidatos en las dos vistas. Cero decisiones cerradas, grupos declarados o revisiones de redacción registradas |
| EuRepoC 1.3.2 local | 3.414 | 85 columnas, dos encabezados repetidos. Taxonomía original pendiente de correspondencia humana con SOC |
| Simulación del artículo | 2.400 | 17 columnas y referencias sintéticas, útiles para comprobación técnica |
| PostgreSQL mediante FastAPI | 7 | Un reporte no DEMO, seis DEMO, cero revisiones humanas observadas. Consulta de indicadores completa para el corte |

**Cómo leerlo.** La unidad es el registro en la fuente indicada. Los conteos entre fuentes pueden compartir incidentes. **Hallazgo calculado.** Solo ocho referencias humanas de tipo son elegibles en el último manifiesto y hay cero de severidad o activo. La lectura CSV de EuRepoC devuelve 3.414 filas de 85 columnas, frente a las 3.663 consignadas en el inventario histórico del SPEC. **Limitaciones.** La revisión del piloto tiene un revisor por caso y el origen retrospectivo limita extrapolar al triaje en recepción. Los conteos operativos corresponden al corte de la API. [Diagnóstico reproducible](../runs/validacion-caso06/20261111T182925Z/diagnostico-datos.json) · [Indicadores operacionales](../runs/validacion-caso06/20261111T182925Z/telemetria-operacional-reintento.json)

Los 160 IDs coinciden con la plantilla y el índice de la revisión fijada. No se detectaron IDs ni referencias normalizadas compartidas con las exposiciones históricas registradas. Hay 287 referencias normalizadas distintas en la cola y ningún grupo exacto compartido con el piloto en el último manifiesto. Queda **un candidato marcado por similitud textual** que el responsable debe cotejar. Los cuatro estratos de 40 obedecen a sugerencias VERIS y dejan seis tipos fuera del diseño de selección. La frecuencia real de tipos y severidades solo se conoce tras la adjudicación. [Copia privada de coordinación](../runs/validacion-caso06/20261111T182925Z/coordinacion/preparacion-trabajo.json) · [Controles de independencia](../runs/validacion-caso06/20261111T182925Z/coordinacion/controles-de-independencia.json)

La validación de Fase 2 necesita al menos cinco grupos de Desarrollo y uno distinto de Validación por clase. Con dos grupos por clase de tipo se requieren al menos **16 grupos adicionales fuera de la reserva** para un estudio de cuatro clases. Es una cota técnica, sujeta a distribución y calidad. Para las diez clases, la cota sería 52 grupos adicionales bajo el supuesto de que se conservan los ocho elegibles. La reserva debe conservarse fuera del entrenamiento. El evaluador exige al menos cinco grupos de Prueba por clase. Su intervalo por grupos tiene mínimos adicionales y requiere examinar soporte por objetivo. [Configuración experimental](../config/analytics.yaml) · [Elegibilidad Fase 2](../src/training/dataset.py)

## Evaluación predictiva

Se inspeccionaron metadatos verificados, sin abrir contenidos de Prueba. Hay seis corridas completas verificables de Fase 2 y todas son sintéticas. Dos registros históricos se omitieron por metadatos no verificables con el lector actual. Ningún objetivo tiene sello disponible ni una configuración final real. El contrato de revisión y el lector real existentes habilitan solo tipo. Agregar valores opcionales a un JSON no suministra la procedencia independiente que se requiere para severidad y activo. [Resultado de elegibilidad](../runs/validacion-caso06/20261111T182925Z/diagnostico-datos.json) · [Lector de Prueba](../src/evaluation/dataset.py)

Macro-F1 real ≥ 0,85 y kappa ponderado real ≥ 0,70 permanecen **pendientes**. Las pruebas nuevas contrastaron métricas nominales y ordinales con scikit-learn y verificaron el registro de uso único, la integridad, los revisores y el soporte en datos controlados. Cuando haya referencias y configuraciones finales, Fase 3 emitirá matrices, macro-F1, tasas de severidad crítica, kappa y cobertura, con intervalos por grupos cuando procedan. Los modelos LLM se mantienen evaluables por clases duras y abstenciones. Curvas o calibración requieren scores por clase con procedencia y significado adecuados. [Pruebas de validación](../runs/validacion-caso06/20261111T182925Z/pruebas-validacion.xml) · [Metodología Fase 3](FASE_3.md)

## Rendimiento y disponibilidad

### Mediciones reales de infraestructura local

61 rondas entre 18:31:48 y 18:46:45 UTC, con cadencia objetivo de 15 s. Se consultaron las rutas de salud por loopback y PostgreSQL con una consulta de solo lectura. Las latencias de cada sonda resumen las observaciones correctas. Para la sesión reutilizada se excluyen las tres aperturas exitosas del cálculo de tiempos de reutilización. La consulta desde el contenedor incluye la sobrecarga de `docker exec`. [Serie completa](../runs/validacion-caso06/20261111T182925Z/servicios.jsonl) · [Resumen de sondas](../runs/validacion-caso06/20261111T182925Z/servicios-resumen.json) · [Funciones de recuperación de PostgreSQL](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-RECOVERY-INFO) · [Hora de inicio del servidor](https://www.postgresql.org/docs/16/functions-info.html)

| Sonda | Correctas / total | n de latencias | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|
| FastAPI con dependencias listas | 48/61 | 48 | 1.045,420 | 2.763,400 |
| FastAPI `/health` básico | 48/61 | 48 | 61,678 | 320,368 |
| PostgreSQL Windows, conexión nueva | 47/61 | 47 | 465,904 | 2.612,457 |
| PostgreSQL Windows, sesión reutilizada | 48/61 | 45 | 12,775 | 62,458 |
| PostgreSQL, consulta dentro del contenedor | 48/61 | 48 | 822,938 | 2.992,622 |
| LangFlow | 61/61 | 61 | 25,107 | 114,538 |
| n8n | 61/61 | 61 | 35,787 | 168,057 |
| Streamlit | 61/61 | 61 | 13,007 | 69,989 |

**Cómo leerlo.** Las dos primeras columnas cuentan observaciones. Los percentiles descriptivos usan interpolación lineal y milisegundos. Redis obtuvo 61 respuestas correctas al ping incluido en la salud detallada, sin tiempo individual en esa ruta. **Hallazgo calculado.** FastAPI respondió HTTP 200 en las 61 comprobaciones detalladas, pero 13 marcaron error de PostgreSQL. El endpoint básico devolvió HTTP 503 en esas 13 rondas. Las consultas nuevas desde Windows tuvieron 13 rechazos por recuperación y un timeout adicional. **Limitaciones.** Son sondas sucesivas en el mismo equipo y las fallas entre rondas pueden pasar inadvertidas. Sus tiempos incluyen componentes distintos y la conexión reutilizada no se compara como experimento causal. La sonda de salud no mide clasificación ni notificación. [Conteos HTTP y bloques](../runs/validacion-caso06/20261111T182925Z/resumen-comprobaciones.json)

![Disponibilidad observada por sonda](../runs/validacion-caso06/20261111T182925Z/disponibilidad.png)

**Cómo leerlo.** Cada punto es una ronda. El eje horizontal expresa minutos desde el inicio. Círculo azul indica éxito y cruz naranja indica fallo o degradación. **Hallazgo calculado.** Las 13 rondas degradadas de FastAPI se agruparon en tres bloques observados de 5, 6 y 2 rondas. **Limitaciones.** El gráfico muestra estados muestreados, por lo que no estima duración exacta de cada caída. Se verificó la resolución de 600 DPI.

Docker marcó el contenedor PostgreSQL como saludable al inicio y al final, con contador de reinicios 0 y la misma hora de inicio del servidor en las conexiones exitosas. En las rondas degradadas la conexión se rechazó antes de poder consultar `pg_is_in_recovery()`, incluso desde dentro del contenedor. Esto ubica la degradación dentro del servicio de base en esas rondas. En un corte acotado a las últimas 5.000 líneas retenidas de hasta 24 h hubo 153 mensajes de recuperación automática, 151 de reinicialización y 118 mensajes de E/S. El análisis adicional asoció 89 de esos errores con el directorio `base`. Los datos usan un montaje `bind` del proyecto Windows. La causa de las recaídas sigue sin confirmarse. [Historial agregado](../runs/validacion-caso06/20261111T182925Z/postgres-historial.json) · [Observación de almacenamiento](../runs/validacion-caso06/20261111T182925Z/postgres-almacenamiento.json) · [Montajes en Docker Desktop](https://docs.docker.com/engine/storage/bind-mounts/)

### Latencia aislada con proveedores simulados

El laboratorio de Fase 6 ejecutó FastAPI, autenticación, el código del componente cloud y persistencia SQLite aislada. Se simularon las fronteras HTTP de LangFlow, n8n, Groq y Gemini, y se comprobaron los callbacks de asignación y notificación. El mismo texto de prueba se repitió secuencialmente. Se descartaron dos calentamientos por escenario.

| Escenario simulado | n | Proveedor efectivo y destino | Clasificación p50 / p95 (ms) | Recepción a notificación p50 / p95 (ms) |
|---|---:|---|---:|---:|
| Principal disponible | 20 | Groq, asignación | 5,6 / 10,3 | 64,8 / 95,7 |
| Fallo técnico del principal | 20 | Gemini, asignación | 8,2 / 16,3 | 74,7 / 122,4 |
| Confianza baja | 10 | Groq, revisión humana | 10,4 / 12,9 | 72,4 / 99,8 |
| Rechazo de política del principal | 10 | Salida protectora, revisión humana | 8,1 / 14,5 | 84,1 / 111,0 |
| Ambos proveedores fallan | 10 | Salida protectora, revisión humana | 13,0 / 19,5 | 98,6 / 142,0 |

**Cómo leerlo.** Cada fila describe una condición controlada y n cuenta reportes medidos. Las columnas de latencia son tramos diferentes en milisegundos. **Hallazgo calculado.** Los 70 reportes medidos siguieron la ruta esperada. La secuencia incluyó Gemini cuando hubo fallo técnico elegible y la salida protectora tras el fallo de ambos. **Limitaciones.** El entorno tiene SQLite y transportes simulados. No mide latencia cloud, concurrencia real ni desempeño predictivo. [Groq simulado](../runs/validacion-caso06/20261111T182925Z/simulado-success.json) · [Gemini simulado](../runs/validacion-caso06/20261111T182925Z/simulado-gemini.json) · [Confianza baja](../runs/validacion-caso06/20261111T182925Z/simulado-low-confidence.json) · [Rechazo](../runs/validacion-caso06/20261111T182925Z/simulado-policy.json) · [Ambos fallan](../runs/validacion-caso06/20261111T182925Z/simulado-both-fail.json)

La ejecución final tuvo **41 pruebas y 16 subpruebas aprobadas**, sin fallos ni omisiones. También pasaron las dos pruebas Node de asignación y SLA de n8n. Dos intentos iniciales quedaron interrumpidos al usar el entorno restringido de Windows. La ejecución válida habilitó el loopback requerido por las pruebas asíncronas y conservó las simulaciones de HTTP. Se registraron dos advertencias conocidas de Starlette/TestClient y de una clase predicha ausente en una referencia controlada. [JUnit final](../runs/validacion-caso06/20261111T182925Z/pruebas-validacion.xml) · [Pruebas de n8n](../runs/validacion-caso06/20261111T182925Z/workflow-node.tap)

### Mediciones de inferencia con sistemas reales

La primera consulta autenticada devolvió HTTP 503. Tras verificar la salud se realizó una nueva consulta agregada con rol Analista y se cerró la sesión. El corte contiene un caso no DEMO, con **54,865 s hasta clasificación y 56,688 s hasta notificación**, sin traza de proveedor y con origen protector de revisión. Con una sola observación, el p95 poblacional permanece pendiente. La ausencia de intentos registrados deja desconocido el proveedor de ese caso. [Primera consulta y grafo](../runs/validacion-caso06/20261111T182925Z/telemetria-operacional.json) · [Consulta agregada posterior](../runs/validacion-caso06/20261111T182925Z/telemetria-operacional-reintento.json)

La Fase 6 conserva evidencia histórica del único caso autorizado, con dos observaciones completas aisladas de 12,799 s y 7,134 s y una respuesta directa de Gemini de 4,311 s en un fallo técnico inducido. Son escenarios diferentes y su denominador no se suma a las sondas ni al ensayo simulado. La nueva comprobación del grafo activo coincidió con el export, el prompt, el componente y las referencias de credenciales. Groq `openai/gpt-oss-20b` y Gemini `gemini-3-flash-preview` conservan sus roles. Esta validación efectuó **cero solicitudes externas de clasificación**. [Evidencia histórica de Fase 6](FASE_6.md) · [Huella del grafo activo](../runs/validacion-caso06/20261111T182925Z/telemetria-operacional.json)

### Siguiente medición representativa

- Repetir la observación pasiva en una ventana sugerida de 24 h que incluya actividad habitual. Registrar inicio del servidor, recuperación, espacio y eventos de Docker/Windows. Comparar en una instancia aislada PostgreSQL con volumen administrado por Docker y datos de control. Si el diagnóstico justifica cambiar el almacenamiento productivo, preparar copia lógica verificable, restauración aislada y ventana de cambio aprobada. No hay causa atribuida al montaje sin esa comparación. [Almacenamiento recomendado por Docker](https://docs.docker.com/desktop/settings-and-maintenance/settings/#file-sharing)
- Recoger tiempos del flujo completo y de cada intento efectivo con trazas del sistema. Incluir horario, familia de incidente, carga, conexiones nuevas y reutilizadas, reintentos, resultados protectores y errores. Definir el inicio en recepción y el fin en notificación o derivación registrada. Preservar casos sin fin observado y contabilizar los timeouts y fallos al informar el indicador de servicio. Separar los intentos por proveedor y el contexto de fallback. Una campaña activa requiere presupuesto y autorización para el corpus y los destinos.
- Antes de la campaña, fijar tamaño por precisión, estratos y dependencia temporal. Reportar p50, p95, tasa de flujos que alcanzan 10 s o que fallan, y sus intervalos. Si se tienen observaciones independientes y cero eventos adversos, 59 flujos sitúan el límite unilateral binomial del 95 % por debajo del 5 %. Esa cifra ilustra el método, y la repetición de un mismo caso u horario no satisface su supuesto. Para tráfico agrupado, diseñar inferencia por bloques o campañas. La meta de p95 < 10 s sigue pendiente de evidencia representativa. [Intervalos de confianza binomiales, NIST](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)
- Medir impacto operativo con un comparador de triaje manual y ventanas o casos de complejidad comparables. Registrar tiempos, cobertura, plazo y severidad. Los datos DEMO quedan fuera de ese análisis. [Objetivos y limitaciones de Fase 6](FASE_6.md)

## Ampliaciones del SPEC y preservación

**RF-01 es parcial.** React y `ReportInput` validan título y descripción. FastAPI asocia el usuario autenticado y hay adjuntos mediante un endpoint posterior. Canal, fecha del evento, datos del reportante y activo informado como campos explícitos, y metadatos de adjuntos al ingreso no están en el contrato actual. Se pueden añadir como metadatos opcionales versionados en el mismo webhook y formulario. La propuesta conserva `recibido_at` para los SLA, protege datos del reportante y mantiene adjuntos fuera del prompt. Requiere acordar campos, permisos, persistencia y compatibilidad con los clientes existentes. [React](../frontend/src/main.tsx) · [Contrato del webhook](../backend/report_input.py) · [Adjuntos](../backend/operations.py)

**RF-03 es parcial.** Se verificó el esquema estricto de cuatro campos y la explicación extractiva de Fases 4 y 6. Falta la justificación estructurada generada en el contrato de LangFlow. Una ampliación compatible puede ensayar un esquema explícito para la nueva versión, con citas validadas sobre el texto minimizado y evidencia separada del resultado. Antes de activarla hay que probar consumidores de cuatro campos, JSON inválido, privacidad, roles y política de revisión/fallback. [Esquema actual](../backend/classifier.py) · [Explicación extractiva](../src/explainability/evidence.py)

RF-06 cuenta con evidencia de notificación interna y reintento en el caso aislado. La entrega sostenida requiere observación de operaciones reales. RF-12 queda parcial por el sello humano y los contratos por campo. RF-13 registra proveedor y conmutación donde hay traza, con un caso histórico sin información recuperable por la telemetría actual. El cumplimiento de las metas de calidad, latencia e impacto mantiene su estado pendiente. [Detalle por requisito](CUMPLIMIENTO_FASES_0_A_7.md)

El trabajo se limitó a documentación, copias de coordinación y evidencias en `runs/`, que Git ignora. Se cotejaron los siete originales con las huellas previas. El ensayo usó fixtures aislados y el monitoreo leyó servicios existentes. Los únicos eventos de autenticación y auditoría operativa corresponden a consultas autorizadas de indicadores y su sesión. El clasificador, las reglas, la auditoría y los servicios conservan su configuración. [Evidencia consolidada](../runs/validacion-caso06/20261111T182925Z/cierre-validacion.json)

## Reproducción

Desde la raíz, usar una carpeta de ejecución nueva bajo `runs/validacion-caso06`. Los archivos de coordinación conservan acceso local. La lectura de originales y sondas prescinde de datos de Prueba.

```powershell
$origen = 'runs/validacion-caso06/20261111T182925Z'
$destino = Join-Path 'runs/validacion-caso06' ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $destino
$env:PYTHONPATH = (Get-Location).Path

.venv/Scripts/python.exe (Join-Path $origen 'inspeccionar_datos.py') --output $destino
.venv/Scripts/python.exe (Join-Path $origen 'observar_servicios.py') --samples 61 --interval 15 --output $destino
Copy-Item (Join-Path $origen 'medir_caso06_aislado.py') $destino
.venv/Scripts/python.exe -m pytest -q (Join-Path $destino 'medir_caso06_aislado.py') --junitxml (Join-Path $destino 'latencia-aislada.xml')
```

La comprobación de integridad de una repetición señalará esta actualización en la matriz de Fase 7. Se archivó una copia de los bytes anteriores que coincide con la aceptación histórica. [Matriz anterior](../runs/validacion-caso06/20261111T182925Z/matriz-previa.md)
