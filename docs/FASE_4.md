# Fase 4 · Explicabilidad textual del SOC

El módulo explica decisiones guardadas mediante evidencia observable y atribuciones del modelo local. La página **Explicabilidad textual** utiliza JWT, RBAC y la auditoría de FastAPI. La implementación toma como referencia el SPEC 2.1, el Promptuario y los artefactos verificados de las fases de [Datos](FASE_1.md), [Experimentación](FASE_2.md) y [Evaluación](FASE_3.md).

## Decisiones metodológicas

- **SUPUESTO · Justificación LLM.** La explicación complementaria es extractiva y local, con criterios versionados derivados del SPEC y del prompt. Registra citas, campos apoyados, negaciones y campos sin apoyo observable. El contrato operacional conserva su clasificación de cuatro campos. La explicación y las referencias se guardan como un artefacto asociado. La verificación literal permite comprobar las citas, mientras que el apoyo semántico requiere revisión humana.
- **SUPUESTO · SHAP lineal.** Para TF-IDF con regresión logística y SVM se implementa la solución analítica del juego interventional de Shapley. El fondo es exclusivamente Desarrollo. La unidad explicada es el contraste entre la clase seleccionada y su rival más fuerte. Los valores atribuyen características TF-IDF, incluyendo las ausentes. La independencia usada por este juego es una hipótesis explicativa, y los n-gramas reales están correlacionados. [Documentación de LinearExplainer](https://shap.readthedocs.io/en/latest/generated/shap.LinearExplainer.html).
- **SUPUESTO · Anotación humana.** La interfaz registra intervalos sobre la entrada protegida con el usuario autenticado, hash del texto, fecha y explicación asociada. Las anotaciones se identifican como retrospectivas con la explicación visible. Su coincidencia describe alineación observada y puede estar influida por la visualización. Se calcula únicamente cuando existe una anotación guardada y válida.
- **SUPUESTO · Perturbaciones.** Las comprobaciones automáticas de estabilidad y eliminación se limitan a Desarrollo y Validación de modelos locales. Cambian mayúsculas y espaciado, o eliminan un token positivo. Los artefactos registran cero inferencias de Prueba y cero solicitudes externas. La estabilidad de las decisiones de Groq/Gemini ante perturbaciones queda pendiente de un experimento cloud autorizado y presupuestado.

## Estructura e integración

```text
src/explainability/
  settings.py       política y límites
  evidence.py       citas, consistencia e intervalos humanos
  linear.py         contribuciones, SHAP y perturbaciones
  analysis.py       patrones y controles agregados
  store.py          artefactos inmutables y huellas
  workspace.py      autorización y servicios del módulo
src/reports/xai_presentation.py
pages/06_Explicabilidad.py
backend/explainability.py
scripts/soc_explain.py
tests/analytics/test_explainability*.py
```

Los ajustes de configuración están en `config/analytics.yaml`. `src/utils/config.py` valida la política y el endpoint. `src/utils/streamlit_runtime.py` integra tareas de fondo y limpia el estado privado al cerrar o caducar la sesión. La página inicial y `README.md` ofrecen el acceso al módulo. Se reutilizan las dependencias fijadas en los archivos existentes de requisitos.

La API de lectura `/api/reportes/{report_id}/explicabilidad` exige una sesión JWT y el permiso `review`. Devuelve la decisión original, la revisión humana por separado, las reglas asociadas y la entrada protegida. La opción `original=true` permite inspeccionar el original y genera su evento específico. Gestor consulta los agregados del módulo. Auditor conserva su acceso a la bitácora.

`report_ai_inputs` conserva una copia protegida para nuevas clasificaciones válidas, su huella, la asociación con la decisión y la huella del original. `backend/classifier.py` captura el contexto privado y `backend/db.py` lo guarda en la misma transacción que el reporte. El esquema usa el mecanismo existente de migración y respaldo. El restablecimiento de datos de demostración incluye esta tabla en el orden de borrado. La auditoría PostgreSQL incorpora la nueva tabla entre las entidades seguidas.

El componente LangFlow adjunta proveedor, modelo efectivo, hash del prompt y copia/hash del mensaje protegido en metadatos de respuesta. El cambio mantiene el cuerpo de clasificación y sus clientes existentes. La comprobación del grafo verificó que la actualización se limitó al código del componente y que el export coincide con el activo. Los metadatos pasan al registro complementario cuando FastAPI carga esta versión. [Comprobación del grafo](../runs/phase4/verification/langflow-metadata.json).

Los reportes históricos sin copia capturada muestran una reconstrucción con la política actual. Cuando la bitácora registró un proveedor, se recupera esa evidencia. El modelo y el prompt históricos ausentes quedan sin dato. El valor `origen="fallback"` de una revisión segura conserva su significado operacional.

## Explicaciones de los modelos académicos

Para una característica `j`, la contribución presente es `w_j × x_j`. El contraste explicado usa la diferencia de coeficientes entre clase y rival. La solución SHAP usada es `φ_j = w_j × (x_j − media_Desarrollo_j)`. La base es el intercepto más el contraste evaluado en la media de Desarrollo. La base más la suma de todos los valores SHAP reconstruye el contraste y se comprueba con la tolerancia configurada. Para regresión logística se muestran log-odds, y para SVM márgenes. [Ejemplo oficial de TF-IDF y regresión logística](https://shap.readthedocs.io/en/latest/example_notebooks/tabular_examples/linear_models/Sentiment%20Analysis%20with%20Logistic%20Regression.html).

El mapa de palabras reparte cada contribución presente entre las apariciones del término y los tokens de su n-grama. Conserva el orden y los caracteres del texto y escapa HTML. El residuo de proyección informa posibles diferencias entre tokenización y representación. La tabla de SHAP distingue características presentes y ausentes y conserva el total de las omitidas en la visualización. Los gráficos muestran signo, clase explicada, rival y unidades.

La sensibilidad a la eliminación recalcula el TF-IDF con el vectorizador congelado. La diferencia incluye cambios de normalización y de n-gramas. Una caída de score puede variar en magnitud o signo, por lo que se conserva el valor observado. Las predicciones de los casos originales y las correcciones humanas permanecen en sus fuentes de origen.

## Adaptación del Promptuario

Grad-CAM++ requiere mapas de activación convolucional y derivadas del score respecto de esas activaciones. Los modelos disponibles procesan reportes textuales mediante características TF-IDF o APIs cloud. La visualización se adapta a contribuciones sobre términos y a fragmentos citados. La biblioteca de visión artificial y las máscaras de imagen quedan fuera del módulo textual. [Artículo original de Grad-CAM++](https://arxiv.org/abs/1710.11063).

El repositorio dispone de regresión logística y SVM locales. La opción de mapas de atención o gradientes de un Transformer queda «No aplicable» hasta disponer de un modelo compatible y sus pesos. Las ponderaciones de atención requieren validación adicional antes de interpretarlas como explicaciones causales. [Jain y Wallace, 2019](https://aclanthology.org/N19-1357/).

La coincidencia de fragmentos usa conjuntos de caracteres no blancos. Informa IoU, precisión y recall, junto con el ID de anotación y su carácter retrospectivo. Antes de calcular verifica intervalos, ausencia de solapamientos y correspondencia exacta con el hash de la entrada. La ausencia de referencias humanas produce «No aplicable».

## Uso y reproducción

Abre [Streamlit](http://127.0.0.1:8502) y entra en **Explicabilidad textual**. Para un modelo académico selecciona su corrida final y Desarrollo o Validación. Para un reporte operativo consulta la lista autorizada y comprueba su evidencia. Cada informe permite ver patrones, términos, inconsistencias, estabilidad y casos individuales según el rol, además de descargar JSON y figuras a 600 DPI.

```powershell
New-Item -ItemType Directory -Force runs/phase4/verification | Out-Null
.\.venv\Scripts\python.exe -m scripts.analytics --check
.\.venv\Scripts\python.exe -m scripts.soc_explain --run 20261111T022740399892Z_1c4e674e0162
.\.venv\Scripts\python.exe -m pytest tests/analytics/test_explainability.py tests/analytics/test_explainability_workflow.py tests/analytics/test_explainability_api.py tests/analytics/test_explainability_page.py -q --basetemp=runs/phase4/verification/pytest-repeticion
```

El comando técnico utiliza los modelos sintéticos ya publicados y su Validación. Los ejemplos de la API y de anotaciones humanas se reproducen mediante las pruebas con una base temporal. Los archivos `result.json` de XAI contienen huellas, configuración, modelo, prompt disponible o referencia actual identificada, dataset, semilla, versiones y fecha. Se conservan en `runs/phase4/`, excluido de Git.

## Ejemplos y alcance verificado

La comprobación de API usa datos ficticios con un correo personal. Verifica que el proveedor reciba la copia protegida, que su entrada registrada coincida con la del cliente interceptado y que el original siga disponible al revisor autorizado. Se prueban Groq, Gemini, baja confianza, reconstrucción histórica y salida segura de revisión. La corrección humana intencional permite comprobar la comparación de un desacierto con su referencia, manteniendo la clasificación original. [Pruebas de privacidad](../tests/test_privacy.py) · [Pruebas de API XAI](../tests/analytics/test_explainability_api.py).

La batería de fórmulas usa modelos binarios y multiclase de ambas familias. Contrasta el score reconstruido con la salida de scikit-learn y los valores SHAP con una enumeración de coaliciones. También prueba citas inventadas, contradicciones de campos, negación explícita, afirmaciones fuera del contrato, escape de HTML, anotaciones inválidas, permisos y manipulación de huellas. [Pruebas de fórmulas](../tests/analytics/test_explainability.py).

### Verificación sintética de los artefactos finales

| Modelo | Casos de Validación (n) | Variantes leves (n) | Predicción conservada (n) | Residuo máximo de reconstrucción |
| --- | ---: | ---: | ---: | ---: |
| TF-IDF con regresión logística | 24 | 48 | 48 | 8,88 × 10⁻¹⁶ |
| TF-IDF con SVM lineal | 24 | 48 | 48 | 8,88 × 10⁻¹⁶ |

**Cómo leerlo.** Cada caso tiene dos variantes leves y usa el modelo final ya publicado. El residuo es la diferencia absoluta entre el contraste y la base más la suma de SHAP. **Hallazgo clave.** Se conservaron las 96 predicciones perturbadas entre ambas familias y la reconstrucción cumplió la tolerancia de 10⁻⁸. **Limitaciones.** Los textos pertenecen a plantillas sintéticas separables y las perturbaciones son limitadas. Las atribuciones describen esos modelos y su fondo de Desarrollo. El número de referencias humanas de fragmentos en estas corridas es cero. [Regresión logística](../runs/phase4/20261111T035808765948Z_15e9bdfb2bcc/result.json) · [SVM lineal](../runs/phase4/20261111T035813935491Z_48d1ad25e903/result.json).

El mapa conserva el texto protegido y la proyección de contribuciones sobre tokens. Las figuras exportadas tienen 600 DPI y sus guías de lectura, hallazgos y límites se conservan en la evidencia. Se cotejaron cuatro originales contra las huellas de Fase 3. [Mapa del caso](../runs/phase4/verification/mapa-caso-sintetico.html) · [Contribuciones](../runs/phase4/verification/contribuciones-caso-sintetico.png) · [Frecuencias](../runs/phase4/verification/terminos-validacion-sintetica.png) · [Evidencia técnica](../runs/phase4/verification/technical-evidence.json).

## Aceptación y pendientes

| Criterio | Estado | Evidencia y alcance |
| --- | --- | --- |
| Justificación verificable | Cumple en pruebas controladas | Citas y criterios extractivos vinculados a la decisión guardada. La semántica requiere revisión |
| Existencia de citas | Cumple en pruebas controladas | Offsets exactos sobre la entrada y verificación literal contra el original autorizado. Los alias protegidos pueden requerir revisión de correspondencia |
| Compatibilidad XAI | Cumple | TF-IDF lineal binario y multiclase. Enumeración de coaliciones y reconstrucción contra scikit-learn |
| Mapas y contribuciones | Cumple en pruebas controladas | Proyección de términos, signo, unidades, residuo, características ausentes y fondo documentado |
| Detección de inconsistencias | Cumple en pruebas controladas | Citas inexistentes, campos contradictorios, negación, falta de apoyo y correspondencia literal con original |
| Trazabilidad y privacidad | Cumple en base temporal y comprobación operativa de lectura. Disponibilidad intermitente | JWT, RBAC, registro protegido, original íntegro, corrección separada y huellas. La migración creó su respaldo y el trigger PostgreSQL |
| Captura de proveedor, modelo y prompt | Cumple con HTTP interceptado. Verificación cloud real pendiente | Modelo efectivo de Groq y Gemini, hash del prompt y mensaje protegido comprobados contra el cuerpo del cliente |
| Interpretación de visualizaciones | Cumple | Título, variables, unidades, leyenda, guía, hallazgo calculado y limitaciones. PNG a 600 DPI |
| Coincidencia con fragmentos humanos reales | Pendiente por datos | La interfaz registra referencias humanas identificadas. Las corridas técnicas no contienen referencias de este tipo |
| Estabilidad de explicaciones LLM | Pendiente de experimento autorizado | El módulo comprueba evidencia local. Las perturbaciones ejecutadas corresponden a los modelos académicos |

**Cómo leerlo.** Cada estado indica el entorno comprobado. Casos, variantes, pruebas y referencias se expresan en conteos. **Hallazgo clave.** Dos modelos publicados aportaron 48 explicaciones y 96 variantes leves comprobadas. **Limitaciones.** La captura de una nueva inferencia con proveedores reales conserva la validación pendiente. Los metadatos del componente activo se actualizaron con comprobación de diferencias y reversión prevista ante fallos.

Los archivos de Fase 4 incluyen los módulos y pruebas del árbol anterior, configuración y recursos Streamlit, `backend/classifier.py`, `backend/db.py`, `backend/main.py`, `backend/manage.py`, `backend/analytics_audit.py`, `db/schema.sql`, el componente y export LangFlow, `tests/test_privacy.py`, `README.md` y esta metodología. Las modificaciones del backend incorporan exclusivamente la evidencia complementaria y su lectura autorizada.

## Resultados de pruebas y operación

La batería general aprobó **223 pruebas y 102 subpruebas**, con cero fallos, errores u omisiones. La verificación focalizada de XAI, API, privacidad y proveedores aprobó **85 pruebas y 16 subpruebas**. Ocho controles posteriores de citas y procedencia histórica también pasaron. Las dos pruebas del workflow n8n y `pip check` finalizaron correctamente. Se conservan las advertencias de Starlette/HTTPX y de scikit-learn al incluir la categoría de revisión en la comparación de referencia. [JUnit general](../runs/phase4/verification/pytest-complete.xml) · [JUnit focalizado](../runs/phase4/verification/final-focused.xml) · [Controles finales](../runs/phase4/verification/final-controls.xml) · [Workflow](../runs/phase4/verification/workflow.txt) · [Dependencias](../runs/phase4/verification/pip-check.txt).

La comprobación operativa permitió eliminar un aviso de Streamlit causado por inicializar el mismo campo mediante su valor por defecto y el estado de sesión. La prueba final de la página pasó después del ajuste. [Smoke final de interfaz](../runs/phase4/verification/final-page.xml).

PostgreSQL estuvo en error en la primera comprobación y volvió a responder durante la verificación. El Analista autenticó correctamente. La migración usó el respaldo automático verificado y mantuvo las huellas de siete reportes, siete asignaciones y cero revisiones. Se verificó el trigger de auditoría de `report_ai_inputs`. El archivo de evidencia se completó después de corregir una ruta relativa de su generador. [Migración y respaldo](../runs/phase4/verification/operational-migration.json).

FastAPI y Streamlit se recargaron. Una prueba de la página conectada al backend real comprobó acceso, renderizado e interpretación con el JWT del Analista. El Gestor consultó agregados y recibió HTTP 403 al solicitar el original XAI. El informe de un reporte histórico se archivó con cero citas de apoyo identificadas y metadatos históricos ausentes, conservando su estado de reconstrucción. Se observaron los eventos de auditoría y las huellas de las tablas originales siguieron coincidiendo. Los cinco servicios respondieron correctamente durante ese smoke. Una comprobación posterior volvió a informar error de PostgreSQL. Las tres consultas siguientes, con conexiones nuevas y la API, respondieron correctamente y sin modo de recuperación. Streamlit respondió HTTP 200. [Verificación operativa](../runs/phase4/verification/operational-verification.json) · [Último estado de servicios](../runs/phase4/verification/services.json).

La prueba en la instalación operativa creó cero reportes y realizó cero inferencias externas. La actualización de metadatos tiene una nueva huella de grafo, registrada como versión. Las corridas anteriores conservan sus huellas. La comprobación de captura completa y fallback se ejecutó con HTTP interceptado, mientras que la inferencia cloud real permanece pendiente. Las anotaciones humanas reales de fragmentos y una evaluación de estabilidad del proveedor también quedan pendientes.

**Resultado de aceptación.** Fase 4 implementada y verificada en sus fórmulas, interfaz, permisos, persistencia y acceso operativo de lectura. La disponibilidad de PostgreSQL sigue siendo intermitente. Los controles dependientes de nuevas inferencias cloud y referencias humanas conservan los pendientes especificados. [Comprobaciones acotadas de disponibilidad](../runs/phase4/verification/operational-availability.json).

Las huellas del SPEC, Promptuario, fuentes implementadas y artefactos, junto con los resultados de verificación, se reúnen en un registro estructurado. El escaneo contra los valores de credenciales configuradas produjo cero coincidencias. [Registro de verificación](../runs/phase4/verification/verification.json) · [Integridad](../runs/phase4/verification/integrity.json).
