# Reproducción del estudio sintético del SOC

Estos archivos acompañan el manuscrito. Todos los casos y tiempos son **SIMULADOS**. No son registros operativos ni mediciones de Groq, Gemini o analistas. Los programas no consultan proveedores ni modifican PostgreSQL, Redis, Langflow o n8n.

Entorno de generación: Python 3.12.14, NumPy 2.3.5 y Matplotlib 3.10.8. La aplicación inspeccionada utiliza su propio entorno, con Python 3.12.9; ambos entornos se distinguen en el manuscrito.

Desde la raíz del proyecto, en PowerShell:

```powershell
py -3.12 -m venv .venv-articulo
.\.venv-articulo\Scripts\python.exe -m pip install -r .\output\articulo-soc\supplementary\requirements.txt
.\.venv-articulo\Scripts\python.exe .\output\articulo-soc\supplementary\simulate.py
.\.venv-articulo\Scripts\python.exe .\output\articulo-soc\supplementary\verify_numbers.py
.\.venv-articulo\Scripts\python.exe .\output\articulo-soc\supplementary\figures.py
```

Semilla principal: 20261103. Bootstrap: 20261104. Control de confianza permutada: 20261107. Se generan 2.400 registros, 2.000 remuestreos y seis figuras. El script sobrescribe solamente sus CSV, JSON y figuras en esta carpeta. Si encuentra el proyecto padre, actualiza un manifiesto de hashes de módulos y registros de prueba; no lee `.env` ni `access.json`.

Resultados de referencia:

- Aceptados: 1.703; remitidos a revisión: 697.
- Errores de tipo entre aceptados: 93; riesgo selectivo: 5,46095 %.
- SLA de respuesta: manual 1.447/2.400; asistido con revisión 2.137/2.400.
- SLA de resolución: manual 2.099/2.400; asistido 2.182/2.400.
- Trabajo activo medio supuesto: manual 13,38427 min; asistido 4,90013 min.
- Diferencia hipotética acumulada: 339,36568 horas para esta cohorte; no es ahorro real.

`verify_numbers.py` recalcula los conteos y tiempos directamente desde el CSV usando la biblioteca estándar. `source-manifest.json` identifica la instantánea inspeccionada; no constituye un archivo público del código ni una firma de integridad externa.

La evidencia funcional del manuscrito proviene de los registros existentes `docs/diseno/ronda-2/pruebas-despues.log` y `.venv/soc-runtime/test-results/soc-tests-20261103-161108.log`. Se revisaron sus fuentes y resultados archivados. No se repitió esa suite integrada durante la generación del manuscrito. Las cifras sintéticas no provienen de esas pruebas.

Antes de enviar el artículo, los autores deben confirmar contenido, autoría, financiación, conflictos de interés y la declaración de asistencia de IA. No se ha enviado el manuscrito a la revista.
