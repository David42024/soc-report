# Prueba JDBC con Apache JMeter 5.6.3

El plan adapta el ejercicio del manual del SENA a los reportes de SOC. El primer muestreador consulta hasta 1 000 reportes por ID y el segundo lee todos sus títulos. Las aserciones verifican que ambas consultas devuelvan un conteo de filas y que la primera respete el límite.

El grupo usa 8 usuarios y 3 vueltas. En **Usuarios de JDBC**, establece el período de subida en 0 segundos para reproducir la captura de la página 18 del manual o en 5 segundos para escalonar el arranque. El plan incorpora una pausa de 1 segundo antes de cada petición. Las dos consultas por vuelta producen 48 muestras en total, 24 por consulta.

## Abrir JMeter y revisar la ejecución guardada

Busca **Apache JMeter 5.6.3** en el menú Inicio. La instalación de este equipo está en `%LOCALAPPDATA%\Programs\Apache JMeter\5.6.3` e incluye el controlador de PostgreSQL en `lib`.

Abre `soc-jdbc.jmx` con **Archivo → Abrir**. Despliega **Usuarios de JDBC**, selecciona **Gráfico de resultados** y pulsa **Navegar** para cargar el archivo `resultados.jtl` de tu ejecución. El lanzador crea una carpeta en `tmp/jmeter/` por cada ejecución. Puedes conservar una copia en `output/jmeter/` para consultarla después.

## Ejecutar contra la base de SOC

Con el motor de Docker en ejecución, inicia PostgreSQL desde la raíz del proyecto. El archivo `.venv/soc-runtime/compose.env` se genera durante la preparación normal de SOC.

```powershell
docker compose --env-file .\.venv\soc-runtime\compose.env up -d --no-deps --wait postgres
```

Ejecuta el plan con el Python del proyecto, Java, JMeter 5.6.3 y un JAR de pgJDBC. Ajusta las rutas a las de tu equipo.

```powershell
$jmeterHome = Join-Path $env:LOCALAPPDATA 'Programs\Apache JMeter\5.6.3'
.\.venv\Scripts\python.exe .\tests\jmeter\run.py --soc `
  --java 'C:\Program Files\Java\latest\jdk-21\bin\java.exe' `
  --jmeter-home $jmeterHome `
  --driver (Join-Path $jmeterHome 'lib\postgresql-42.7.13.jar')
```

La opción `--soc` lee `DATABASE_URL` de `.env` o del entorno. En la configuración actual consulta `public.reports` en `soc_reports`, accesible por `127.0.0.1:5434`. Las conexiones abren transacciones de solo lectura y el archivo de muestras guarda métricas sin cuerpos de respuesta. El script imprime la cantidad de reportes al iniciar y la ruta de `resultados.jtl`, `jmeter.log` e `informe/index.html`. Abre el informe para consultar los tiempos, percentiles y errores.

## Ejecutar desde la interfaz gráfica

Agrega `--gui` al comando con `--soc`. Se abrirá JMeter con el plan y la conexión a SOC preparados. Despliega **Usuarios de JDBC**, selecciona **Gráfico de resultados** y pulsa el botón verde de inicio o `Ctrl+R`. El gráfico se actualiza en la ventana y el receptor escribe `resultados.jtl` en la carpeta indicada al abrir JMeter.

## Ejecutar con datos de ejemplo

Omite `--soc` para usar la base `prueba` temporal con 1 200 reportes sintéticos. Este modo requiere PostgreSQL nativo con `pg_ctl` en `PATH`. Comprueba los conteos exactos de 1 000 reportes y 1 200 títulos y detiene la instancia temporal al finalizar.

Durante una ejecución en la interfaz, **Lanzar → Detener** corta los hilos y **Lanzar → Apagar** deja terminar las muestras en curso.
