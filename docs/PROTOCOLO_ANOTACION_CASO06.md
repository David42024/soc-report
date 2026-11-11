# Protocolo de anotación y custodia del Caso 06

Versión propuesta 1.0. Aplica a la reserva VCDB y a las referencias de Desarrollo y Validación. La rúbrica toma los diez tipos y cuatro severidades del SPEC §8, el criterio de evidencia del prompt vigente y los contratos del repositorio. El responsable SOC confirma su aplicación antes de repartir el material. [SPEC v2.1](<C:/Users/USERJSSV/Downloads/ARCHIVO_SPEC_SOC_Caso06_Concordante_Groq_Gemini.docx>) · [Prompt vigente](../integrations/langflow/prompt.txt) · [Orientación sobre priorización y triaje de NIST](https://csrc.nist.gov/pubs/sp/800/61/r3/final)

## Preparación y acceso

1. Designar a una persona responsable de custodia, dos revisores independientes con conocimiento SOC y una persona adjudicadora para las discrepancias. Registrar sus identidades autorizadas, rol, fecha UTC y versión de la rúbrica. La identidad de cada archivo se comprueba con el registro del responsable. El campo `reviewer` del CLI es texto y por sí solo no acredita la identidad.
2. Ensayar la rúbrica con ejemplos de entrenamiento ya expuestos y autorizados. Los ocho casos del piloto se pueden usar para discutir criterios de tipo. Mantenerlos en Desarrollo/Validación. La persona que selecciona configuraciones recibe únicamente datos de Desarrollo/Validación y conteos de elegibilidad de Prueba.
3. Decidir **inclusión o exclusión en los 160 candidatos** de la copia de coordinación. Para cada inclusión registrar fuente ya asociada en el índice, grupo real, etapa del texto, título y descripción protegidos y revisión de redacción. Para cada exclusión registrar motivo comprobable. Revisar los vínculos por incidente, fuente, campaña y similitud. La ficha privada marca un candidato con posible solapamiento. Si hay incidentes de la misma campaña, conservar un representante documentado en esta reserva, ya que el sellador actual exige un caso por grupo. La ausencia de coincidencias exactas no permite confirmar por sí sola la independencia. [Copia de preparación](../runs/validacion-caso06/20261111T182925Z/coordinacion/preparacion-trabajo.json) · [Controles privados de independencia](../runs/validacion-caso06/20261111T182925Z/coordinacion/controles-de-independencia.json)
4. Distinguir `initial_public_report` de `retrospective_summary`. Para una evaluación de triaje en recepción, presentar solo hechos conocidos al recibir el aviso. Guardar el desenlace, la fecha posterior y la fuente completa en la evidencia restringida para cotejar la referencia cuando proceda. Analizar los resúmenes retrospectivos como cohorte explícita. Una paráfrasis debe mantener señales, alcance e incertidumbre. Excluir o registrar como insuficiente el objetivo que dependa de detalles retirados o desconocidos. En este trabajo se verificaron las fuentes locales. La disponibilidad del texto contemporáneo de cada caso queda a cargo de la revisión humana.
5. Validar el texto con el `ReportInput` existente (título de 5–120 caracteres y descripción de 15–4.000). Conservar la fuente íntegra en su ubicación. Revisar y proteger nombres, contactos, secretos y otros identificadores antes de circular el texto de trabajo. Mantener fragmentos técnicos útiles y sus límites. Repartir `blinded-cases.json` a los revisores por acceso restringido. El archivo de coordinación, las sugerencias del índice, las predicciones y los resultados del otro revisor se mantienen fuera del material de anotación. [Contrato de entrada](../backend/report_input.py) · [Política de privacidad](SEGURIDAD_PRIVACIDAD.md)

## Rúbrica de decisión

Cada decisión por campo registra estado (`etiquetado`, `insuficiente`, `ambiguo` o `ausente`), valor cuando corresponda, fragmento literal o referencia interna verificable y una nota breve de criterio. `ausente` se reserva al activo cuando el texto claramente carece de una mención. Conservar el caso y su falta de evidencia en los conteos de elegibilidad. Ninguno de esos estados es un tipo de incidente, un valor de severidad ni un nombre de activo.

### Tipo

Elegir la categoría principal sustentada por los hechos disponibles y registrar señales secundarias en notas. Priorizar el incidente que motiva el reporte. Cuando se narren cadena y consecuencias, identificar qué hecho se está reportando de forma principal. Si dos tipos igualmente plausibles no se resuelven con la evidencia, marcar `ambiguo` y enviar a adjudicación.

- `phishing` cuando el hecho principal es un mensaje, enlace o suplantación que intenta inducir una acción.
- `malware` cuando el reporte se centra en código malicioso o infección, incluido ransomware. Un correo previo queda como vector cuando la infección es el evento principal.
- `acceso_no_autorizado` cuando hay acceso o intento de acceso sin permiso, incluido el uso de credenciales ajenas. El uso abusivo de un acceso legítimo se considera `uso_indebido`.
- `ddos` cuando se describe un ataque distribuido contra la disponibilidad. Una caída sin evidencia de distribución no basta.
- `fuga_datos` cuando la divulgación, exposición o extracción no autorizada es el hecho principal. Pedir información o sospechar acceso puede ser evidencia de otro tipo sin que se haya demostrado una fuga.
- `vulnerabilidad` cuando se reporta una debilidad técnica o configuración insegura como hallazgo. Una explotación confirmada se clasifica por el incidente reportado.
- `uso_indebido` cuando hay uso contrario a políticas de un recurso o privilegio concedido. Registrar la evidencia de autorización inicial cuando sea relevante.
- `incidente_fisico` cuando una pérdida, intrusión, daño o evento físico afecta a un activo de seguridad.
- `fraude` cuando la acción principal es un engaño para conseguir un beneficio indebido, por ejemplo una transferencia irregular. Si el reporte trata ante todo del mensaje de captación o suplantación, considerar `phishing`.
- `otro` cuando hay un evento interpretable fuera de las otras categorías. Una descripción incompleta conserva su estado de insuficiencia.

El selector VCDB partió de cuatro estratos provisionales de 40 casos. Las sugerencias describen el mecanismo de muestreo y se ocultan durante la revisión. La cobertura final se mide por grupos y tipos adjudicados. [Diagnóstico de la reserva](../runs/validacion-caso06/20261111T182925Z/diagnostico-datos.json)

### Severidad

Asignar severidad a partir del impacto disponible al momento del texto de entrada. Registrar el alcance, la criticidad del servicio si está respaldada, qué impacto está confirmado, cuál es probable y qué fragmento lo sustenta. Los plazos operativos sirven como referencia contextual de la configuración. La anotación se decide por el impacto y deja intactos los SLA.

- `critica` ante afectación activa grave, exfiltración confirmada o caída de un servicio esencial con evidencia de impacto.
- `alta` ante compromiso probable o impacto material respaldado, como exposición relevante, sin evidencia suficiente para la categoría crítica.
- `media` ante sospecha sustentada o impacto limitado o pendiente de confirmar, con una base que permita valorar ese alcance.
- `baja` ante un hallazgo menor, consulta o incidencia con impacto acotado y poca urgencia respaldados.

La falta total de contexto se registra como `insuficiente`. Los revisores aplican los mismos criterios a todas las clases. El valor se guarda exactamente como lo define la taxonomía, con el orden `baja < media < alta < critica`. [Criterios del clasificador](../integrations/langflow/prompt.txt) · [Reglas operativas](../integrations/reglas.json)

### Activo afectado

Tomar el activo principal explícitamente mencionado y ligado al impacto. Registrar cita y nombre funcional a la misma granularidad en todos los casos, por ejemplo `correo corporativo` o `servidor de archivos` cuando esa descripción figure en la evidencia. Si hay varios, registrar los secundarios como notas. Cuando no sea posible escoger un principal, usar `ambiguo`. Proteger identificadores particulares y no incorporar inventarios externos al texto de entrada.

Para el cotejo se propone la comparación textual exacta tras NFKC, minúsculas mediante `casefold` y compactación de espacios, como en Fase 3. Cualquier diccionario de equivalencias semánticas se acuerda y versiona en Desarrollo/Validación antes del sello. Informar aparte cobertura, ausencia explícita y concordancia en activos evaluables. Las tasas por clase requieren soporte por grupo. El valor nulo expresa ausencia o insuficiencia según el estado registrado. [Normalización implementada](../src/evaluation/contracts.py)

## Dos revisiones, adjudicación y control de calidad

- El responsable fija la huella SHA-256 del paquete y de la rúbrica. Cada revisor entrega una decisión por caso incluido y por variable sin acceso al archivo del otro. Registrar identificador, huellas, fecha, estados, evidencia y notas en el formulario de trabajo. Con todos los candidatos incluidos habría 320 registros de revisión, 160 por revisor, y hasta 960 decisiones iniciales de campo entre ambos. Las exclusiones de preparación reducen esos máximos.
- Antes de adjudicar, cotejar correspondencia con el paquete, duplicados, etiquetas válidas, literalidad de fragmentos y estados faltantes. Informar proporción de acuerdo y denominadores sobre pares comparables. Por campo, conservar la matriz de discrepancias y los faltantes. El kappa nominal de tipo y el ponderado cuadrático de severidad sirven como diagnósticos si el soporte y la variación lo permiten. Para activo usar acuerdo textual con la normalización declarada.
- La persona adjudicadora revisa todas las discrepancias y los casos ambiguos. Registrar identidad, UTC, valores originales, decisión final, fragmento y motivo. Si persiste la insuficiencia, conservarla por objetivo y reportar su efecto sobre la cobertura. Si el formato de tipo exige excluir ese caso, conservar la versión de trabajo, registrar el motivo y emitir el paquete definitivo con huella nueva antes de cualquier evaluación. Un responsable distinto valida la resolución de los casos marcados, la privacidad y los campos obligatorios antes de publicar.
- Los formularios ampliados de severidad y activo son **evidencia de trabajo**. El CLI `vcdb_review` recibe y adjudica hoy solo `tipo`. Las propiedades opcionales en `ReviewedCase` no comprueban revisores independientes para otros campos. `holdout_status` y `_sealed_real` tampoco los habilitan. Se necesita una ampliación versionada del contrato analítico y pruebas de procedencia por campo antes de publicar un sello de severidad o activo. [Revisión existente](../scripts/vcdb_review.py) · [Sello de Fase 1](../src/data/manifest.py) · [Lector de Fase 3](../src/evaluation/dataset.py)

El [formulario por campo](../runs/validacion-caso06/20261111T182925Z/coordinacion/formulario-de-trabajo.json) indica qué registrar antes de consolidar las referencias. La información sensible y las decisiones por caso permanecen en el área de trabajo privada.

## Preparar y sellar el tipo mediante el CLI existente

Usar los comandos después de completar inclusión, privacidad y agrupación. Ejecutarlos desde la raíz del repositorio. Entregar cada planilla de revisión por separado.

```powershell
$validacion = 'runs/validacion-caso06/20261111T182925Z'
$archivo = 'tmp/datasets-real/vcdb-f6f98c0.zip'
$cola = '.venv/soc-runtime/dataset/holdout-review-queue.json'
$preparacion = Join-Path $validacion 'coordinacion/preparacion-trabajo.json'
$paquete = Join-Path $validacion 'coordinacion/paquete-tipo'

.venv/Scripts/python.exe -m scripts.vcdb_review packet --archive $archivo --queue $cola --preparation $preparacion --output $paquete
```

Una vez archivadas las dos planillas de tipo completadas y la adjudicación, generar el sello en el espacio de trabajo. Pasar un objeto JSON vacío como adjudicación si hubo acuerdo total. El CLI exige que las claves de adjudicación coincidan con todas las discrepancias.

```powershell
.venv/Scripts/python.exe -m scripts.vcdb_review freeze --archive $archivo --packet (Join-Path $paquete 'packet.json') --review-a (Join-Path $paquete 'review-a.json') --review-b (Join-Path $paquete 'review-b.json') --adjudication (Join-Path $paquete 'adjudicacion-tipo.json') --output (Join-Path $paquete 'holdout-reviewed.json')
```

Custodia valida la coincidencia entre archivos de preparación y sello. Una configuración analítica de trabajo puede referenciar esas copias mediante `registry_file` y `data.sealed_holdout_file` en una variante indicada por `SOC_ANALYTICS_CONFIG`. Mantener la lista histórica de exposiciones al cambiar la ubicación del sello, pues el lector busca ejecuciones previas junto al archivo configurado. Verificarlo con las fuentes históricas y publicar un nuevo manifiesto desde **Datos del SOC** con el rol autorizado. No sobrescribir la plantilla original ni las evidencias de fases previas. [Carga de configuración](../src/utils/config.py) · [Validación de historial](../src/data/sources.py)

## Autorización de la evaluación

1. Conseguir referencias independientes de la reserva para Desarrollo y Validación. La comprobación actual pide al menos cinco grupos de Desarrollo y uno distinto de Validación por clase. Eso es un mínimo técnico. Hoy existen dos por clase en cuatro clases de tipo, por lo que faltan al menos 16 grupos externos a la reserva para ese alcance. Las seis clases restantes carecen de referencias en el piloto.
2. Definir si el primer estudio cubre esas cuatro clases o todo el catálogo. Para un estudio de cuatro, informar como fuera del alcance las clases restantes y conservar las predicciones inesperadas en el análisis. Para las diez, diseñar una ampliación de selección y verificación dentro de las fuentes locales antes de sellar. El índice VCDB actual se basa en cuatro correspondencias VERIS y los tipos EuRepoC requieren mapeo y revisión independientes.
3. Comprobar al menos cinco grupos de Prueba por clase para el evaluador real actual. Para los intervalos, el umbral técnico es 20 grupos y cinco por clase. Justificar soporte y precisión para cada objetivo, con atención al recall crítico y a los casos derivados a revisión. Si la muestra no sostiene un intervalo o un contraste, registrar su motivo y el denominador. [Política y mínimos](../config/analytics.yaml)
4. Seleccionar y congelar la configuración en Fase 2 usando Desarrollo/Validación. Registrar fuente, grupos, prompt/hash, proveedor/modelo, umbral, semilla, fecha y huellas. El responsable de custodia valida que Prueba no intervino en ajustes, coincidencias cercanas ni selección. Ejecutar Fase 3 una vez por configuración, objetivo y versión sellada. Si ocurre un fallo parcial, seguir la bitácora de uso y preservar el intento.
5. Publicar macro-F1 y matriz por tipo, kappa ponderado y degradaciones para severidad, y las métricas de activo definidas antes del sello. Informar cobertura sobre todos los casos elegibles, incluidas las abstenciones o derivaciones. Para los críticos, informar los casos clasificados por debajo y los enviados a revisión por separado, con sus denominadores e intervalos por grupos cuando procedan. Las metas de macro-F1 ≥ 0,85 y kappa ≥ 0,70 se cotejan con estimaciones reales y su incertidumbre. El puntaje del LLM mantiene su uso operacional. [Fase 2](FASE_2.md) · [Fase 3](FASE_3.md)
