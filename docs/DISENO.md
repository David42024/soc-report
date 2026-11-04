# Diseño de SOC Report Router

Las capturas, galerías y registros de verificación mencionados son evidencia local generada y se excluyen de Git. Sus rutas se conservan como referencia para consultarlas en el equipo donde se ejecutaron las pruebas.

La configuración actual se describe en [Ronda 2](#ronda-2). Las secciones anteriores conservan el diagnóstico y la evidencia de la primera entrega.

## Diagnóstico visual

| Vista | Hallazgo | Origen | Referencia previa |
| --- | --- | --- | --- |
| Acceso | Idioma y tema quedan pegados a sus selectores. La cabecera domina el formulario y los campos dependen del estilo de autocompletado del navegador. | `frontend/src/main.tsx`, `styles.css` | Acceso (`diseno/antes/1440-light/acceso.jpg`) |
| Tablero | Las cabeceras de estado comparten tratamiento y el SLA queda en un acordeón. Al cargar aparecen columnas vacías antes de conocer los datos. | `frontend/src/main.tsx` | Tablero (`diseno/antes/1440-light/tablero.jpg`) |
| Navegación | Las opciones tienen un peso similar y Operaciones se diferencia con un rótulo pequeño. | `frontend/src/main.tsx`, `styles.css` | Navegación (`diseno/antes/1440-light/tablero.jpg`) |
| Dashboard | Los KPI se confunden con texto corrido. Las barras comparten el verde y el chat cubre parte de Carga por equipo. Los filtros se envuelven sin una cuadrícula definida. | `frontend/src/DashboardPanel.tsx`, `styles.css` | Dashboard (`diseno/antes/1440-light/dashboard.jpg`) |
| Operaciones, usuarios y auditoría | Las tablas y formularios necesitan más contraste entre datos, estado y acción. | `frontend/src/OperationsPanels.tsx`, `main.tsx`, `styles.css` | Salud (`diseno/antes/1440-light/salud.jpg`) · Auditoría (`diseno/antes/1440-light/auditoria.jpg`) |
| Evolución | Los avisos DEMO son explícitos. Comparten el color de marca con controles e indicadores operativos. | `frontend/src/ImpactPanel.tsx`, `OperationalImpactPanel.tsx` | Evolución (`diseno/antes/1440-light/evolucion.jpg`) |

## Decisiones de presentación

El verde identifica la marca y las acciones principales. Los fondos y las tablas usan neutros. La severidad aparece en una insignia y en el borde de cada caso. El estado tiene un icono, una etiqueta y una cabecera de columna. El SLA tiene su propia insignia con el plazo absoluto y una estimación relativa de tiempo.

La pantalla de acceso reúne identidad, formulario y acceso al reporte público. El control de visibilidad de contraseña permite revisar el texto antes de enviarlo. Idioma y tema tienen etiquetas separadas de sus selectores.

El menú lateral agrupa Principal, Operaciones, Administración y Cuenta. Los grupos dependen de los permisos existentes. El modo compacto mantiene nombres accesibles y ayudas de texto en los iconos. En móvil se abre un cajón desde Menú. Escape lo cierra y devuelve el foco al botón. Al cambiar de módulo, el contenido vuelve al inicio y recibe el foco.

Los KPI usan tarjetas con cifras tabulares e iconos. El dashboard mantiene los numeradores, denominadores y resúmenes textuales de los gráficos. El color de advertencia en un KPI indica que hay casos evaluables fuera de plazo. No se introduce una meta de cumplimiento. Los informes filtrados tienen tarjetas separadas con sus tres formatos. En el tablero y Auditoría, los formatos se agrupan en un desplegable.

El botón del chat cerrado ocupa un carril reservado en escritorio y una franja inferior en móvil. El panel abierto permite consultar y cerrar la conversación. Los indicadores de salud distinguen el estado informado, la fecha de consulta y las verificaciones anteriores de proveedores.

Los avisos DEMO emplean violeta, texto explícito y un fondo diferente de las alertas operativas. La clasificación original, la revisión humana, los filtros y los datos de las exportaciones siguen siendo los que entrega la API.

## Tokens

La fuente de los valores está en [tokens.css](../frontend/src/tokens.css). [tailwind.config.js](../frontend/tailwind.config.js) referencia las variables de color, fuente y radio. Los componentes usan variables CSS y evitan valores hexadecimales locales.

| Familia | Variables principales | Aplicación |
| --- | --- | --- |
| Superficies | `--page`, `--panel`, `--subtle`, `--raised` | Fondo, panel, agrupación y elevación |
| Texto y controles | `--text`, `--muted`, `--border`, `--field-border`, `--focus` | Jerarquía y navegación por teclado |
| Marca | `--accent`, `--on-accent`, `--brand-surface` | Acción principal e identidad |
| Severidad | `--critical`, `--danger`, `--warning`, `--info` y sus fondos | Crítica, alta, media y baja |
| Estado | `--warning`, `--info`, `--success` | Por atender, en atención y resuelto |
| SLA | `--success`, `--warning`, `--danger` | En plazo, por vencer y vencido |
| DEMO | `--demo`, `--demo-bg` | Datos simulados e insignias |
| Gráficos | `--chart-1` a `--chart-8` | Paleta categórica, acompañada de etiquetas y valores |
| Tipografía | `--font-sans`, `--text-xs` a `--text-display` | Pila del sistema y escala de tamaños |
| Ritmo | `--space-1` a `--space-8`, `--radius`, `--shadow` | Base de 4/8 px y elevación sutil |

Cada token de color define su versión clara y oscura mediante `light-dark()`. Las superficies oscuras tienen valores propios. Los pesos se distribuyen entre cuerpo, etiquetas y encabezados. Las transiciones de controles duran 160 ms y se desactivan con `prefers-reduced-motion`. Los gráficos de datos evitan animaciones de entrada.

## Componentes y controles

[ui.tsx](../frontend/src/ui.tsx) contiene Button, Card, KpiCard, Badge, DataTable, Avatar, Icon, ExportMenu, LoadingBlock y EmptyState. Los iconos son SVG locales, con trazo consistente y ocultos al lector cuando acompañan un nombre accesible.

Los campos, selectores, detalles desplegables y mensajes mantienen semántica HTML nativa. Los mensajes de error usan `role=alert` y los de carga o confirmación usan `role=status`. Las tablas extensas tienen una región con scroll accesible por teclado y cabeceras fijas. La paginación existente de Auditoría conserva Cargar anteriores. Los módulos se seleccionan desde la navegación lateral mediante `aria-current`.

El detalle de un caso conserva su acordeón. El único cajón nuevo es el menú móvil. Este criterio evita introducir modales en las acciones de atención y formularios que ya funcionan.

## Capturas comparativas

Las capturas se realizaron en Edge mediante Playwright contra FastAPI local. Se consultaron las catorce vistas solicitadas, con los cuatro roles existentes. Las contraseñas se leyeron desde el archivo privado de acceso y se introdujeron en campos enmascarados. Las capturas de Acceso se tomaron con el formulario vacío.

El diagnóstico conserva 84 capturas, correspondientes a 1440, 1024 y 390 px en claro y oscuro. La matriz final incorpora 768 px y añade vistas del área inferior del dashboard. Algunas capturas iniciales muestran el estado de carga. Las finales esperan a que terminen los indicadores y los servicios.

| Vista | Antes, 1440 claro | Después, 1440 claro |
| --- | --- | --- |
| Acceso | Ver (`diseno/antes/1440-light/acceso.jpg`) | Ver (`diseno/despues/1440-light/acceso.jpg`) |
| Nuevo reporte | Ver (`diseno/antes/1440-light/nuevo-reporte.jpg`) | Ver (`diseno/despues/1440-light/nuevo-reporte.jpg`) |
| Tablero | Ver (`diseno/antes/1440-light/tablero.jpg`) | Ver (`diseno/despues/1440-light/tablero.jpg`) |
| Dashboard | Ver (`diseno/antes/1440-light/dashboard.jpg`) | Ver (`diseno/despues/1440-light/dashboard.jpg`) |
| Evolución | Ver (`diseno/antes/1440-light/evolucion.jpg`) | Ver (`diseno/despues/1440-light/evolucion.jpg`) |
| Auditoría | Ver (`diseno/antes/1440-light/auditoria.jpg`) | Ver (`diseno/despues/1440-light/auditoria.jpg`) |
| Usuarios | Ver (`diseno/antes/1440-light/usuarios.jpg`) | Ver (`diseno/despues/1440-light/usuarios.jpg`) |
| Mi perfil | Ver (`diseno/antes/1440-light/perfil.jpg`) | Ver (`diseno/despues/1440-light/perfil.jpg`) |
| Notificaciones | Ver (`diseno/antes/1440-light/notificaciones.jpg`) | Ver (`diseno/despues/1440-light/notificaciones.jpg`) |
| Activos | Ver (`diseno/antes/1440-light/activos.jpg`) | Ver (`diseno/despues/1440-light/activos.jpg`) |
| Equipos | Ver (`diseno/antes/1440-light/equipos.jpg`) | Ver (`diseno/despues/1440-light/equipos.jpg`) |
| Salud | Ver (`diseno/antes/1440-light/salud.jpg`) | Ver (`diseno/despues/1440-light/salud.jpg`) |
| Revisión humana | Ver (`diseno/antes/1440-light/revision.jpg`) | Ver (`diseno/despues/1440-light/revision.jpg`) |
| Reglas y SLA | Ver (`diseno/antes/1440-light/reglas.jpg`) | Ver (`diseno/despues/1440-light/reglas.jpg`) |

La galería completa (`diseno/index.html`) permite elegir cada vista, ancho y tema. Las capturas adicionales de gráficos e informes muestran el contenido inferior del dashboard.

## Verificación

La comprobación inicial de Test-Soc.ps1 quedó interrumpida por las restricciones de sockets del entorno de ejecución. La compilación y las catorce pruebas React iniciales sí se completaron. Al repetir la suite con acceso local, aprobaron 55 pruebas Python, 2 de reglas y 14 React. La prueba nueva comprueba que mostrar u ocultar la contraseña conserva el valor sin enviar una solicitud.

La evidencia de contraste y teclado está en verificacion.json (`diseno/verificacion.json`). Se comprobaron los pares de texto principal, texto secundario, colores semánticos y marca con una relación mínima de 4,5 a 1. Se comprobó un mínimo de 3 a 1 para controles y gráficos. Esto cubre los tokens utilizados, y complementa la revisión de pantallas. No representa una auditoría exhaustiva de conformidad.

La ejecución final de Test-Soc.ps1 aprobó los cuatro grupos. El registro conserva 55 pruebas Python, 2 de reglas, 15 pruebas React y la compilación TypeScript. Resultado final (`diseno/pruebas-locales.log`). El ajuste final de ancho mínimo en las tablas móviles se recompiló y se revisó en las capturas. La compilación y las 15 pruebas React se repitieron con éxito al terminar los ajustes de foco.

La navegación comprobada incluye acceso mediante Tab y Enter, menú compacto, desplegable de exportación, aplicación de filtros por teclado y cierre del menú móvil con Escape. El filtro seleccionado aparece en un chip. Las cuatro cuentas mantienen las vistas correspondientes a su rol. La lectura del dashboard real encontró 42 reportes.

La prueba de 10.000 reportes usa una respuesta agregada simulada en Playwright. Se comprueba el render del frontend y el rotulado de 10.000 DEMO. El ensayo no crea reportes en PostgreSQL ni mide consultas SQL sobre 10.000 filas. Su captura está en dashboard-10000-demo.jpg (`diseno/dashboard-10000-demo.jpg`).

En esa ejecución, mostrar el agregado simulado demoró 313 ms desde el clic hasta la aparición de la tarjeta DEMO. Es una observación local de render, dependiente del equipo y del entorno. Las capturas incluyen 1440, 1024, 768 y 390 px en ambos temas. Las tablas extensas mantienen un ancho legible y scroll dentro de su región. No se observaron desbordes horizontales del documento.

## Dependencias, alcance y límites de la primera entrega

Se utiliza la pila tipográfica del sistema y un conjunto pequeño de SVG propios. No se añadieron dependencias al frontend. Playwright se instaló en un directorio temporal exclusivamente para las verificaciones locales.

Los cambios están en frontend/src, la configuración de tokens de Tailwind y esta documentación. Los informes exportables conservan el estilo existente. El bundle mantiene la advertencia de Vite sobre el módulo de gráficos superior a 500 kB. El tamaño comprimido de gráficos pasó de 153,99 a 156,33 kB. El JavaScript principal pasó de 25,44 a aproximadamente 29,3 kB comprimidos. El CSS pasó de 4,49 a aproximadamente 6,5 kB comprimidos.

## Ronda 2

### Diagnóstico de tipografía

La revisión se realizó en Edge sobre FastAPI local, mediante document.fonts, las solicitudes de recursos, los estilos calculados y CSS.getPlatformFontsForNode del protocolo de depuración de Chromium.

Antes del cambio, document.fonts no contenía fuentes web y no había solicitudes WOFF, WOFF2 o TTF. El navegador dibujaba el cuerpo con Segoe UI y los títulos y botones con Segoe UI Semibold del sistema. La pila declarada era system-ui, Segoe UI, sans-serif. No se observó un error de descarga de fuentes. Los pesos 400 y 600 correspondían a archivos del sistema. El aspecto dependía de Windows y de su fuente de interfaz.

El cuerpo y los controles medían 16 px con interlineado de 24 px. El título de acceso medía 24 px con letter-spacing de −0,48 px. Otros títulos y cifras aplicaban valores entre −0,025em y −0,035em. Las reglas de etiquetas y revisión también incluían un peso 650. Estos valores dificultaban una apariencia uniforme.

Después del cambio, la inspección de los glifos confirma Inter como fuente personalizada en cuerpo, título y botón. document.fonts informa Inter Variable cargada con rango 100–900. FastAPI sirve el archivo inter-latin-wght-normal con extensión WOFF2 desde los assets compilados. El recurso pesa 48,26 kB. El cuerpo mide 15 px con interlineado de 22,5 px. Las reglas de interfaz usan pesos 400, 500 y 600, títulos con espaciado neutro o −0,01em, y cifras tabulares. Los identificadores y marcas de tiempo usan la pila monoespaciada del sistema.

La pila de respaldo es Inter Fallback, system-ui, Segoe UI, sans-serif. Inter Fallback referencia Segoe UI local, con size-adjust de 109,18 %, ascent-override de 88,73 %, descent-override de 22,09 % y line-gap-override de 0 %. Los valores se calcularon a partir de las métricas de los archivos Inter y Segoe UI disponibles en este equipo. font-synthesis está desactivado. No se añadieron ajustes de suavizado dependientes de otro sistema operativo.

La medición de acceso con observación de layout-shift registró CLS de 0 en esta ejecución local. Ese resultado corresponde al equipo y al escenario comprobados.

Mediciones antes (`diseno/ronda-2/fuentes-antes.json`) · Mediciones después (`diseno/ronda-2/fuentes-despues.json`) · Verificación de navegador (`diseno/ronda-2/verificacion.json`).

### Cabecera y preferencias

La cabecera del área autenticada mide 64 px y permanece visible mientras el contenido se desplaza. Contiene un H1 con el nombre del módulo. Se eliminaron los títulos repetidos del contenido y la tarjeta envolvente. Las secciones, KPI, tablas y gráficos se presentan directamente sobre el fondo neutro.

La campana abre Notificaciones y cuenta los avisos sin leer recibidos de la API existente, con límite de 500 avisos recientes. El contador se actualiza al cambiar de módulo, al marcar una notificación como leída y cada minuto. Una lectura fallida oculta la cifra. El rol Auditor conserva su acceso a Auditoría y no consulta esta API de lectura operativa.

El avatar abre un popover con nombre, rol, Mi perfil, tema, idioma y Cerrar sesión. Los controles segmentados usan radios nativos dentro de grupos etiquetados. Las flechas cambian la opción y Tab recorre los grupos. Escape cierra el popover y devuelve el foco al avatar. El clic exterior también lo cierra. La salida usa un icono propio y adopta el color de peligro al recibir foco o hover.

El menú lateral conserva la navegación de módulos y una tarjeta compacta de usuario. Los selectores y Preferencias se retiraron de esa ubicación. La pantalla de acceso comparte los controles en versión compacta. El logotipo se alinea con el ancho del formulario y su panel de identidad.

### Conversación

El lanzador mide 54 px. El chat abierto ocupa 400 px en escritorio, con una altura máxima de 640 px limitada por el viewport. El contenido reserva espacio a su derecha mientras está abierto. En 390 px se convierte en una hoja de pantalla completa. En ese formato, Tab permanece dentro del diálogo.

La conversación distingue burbujas del usuario y del asistente, incorpora un avatar, conserva el proveedor debajo de cada respuesta y presenta tres puntos mientras espera. Los errores mantienen Reintentar. Las sugerencias aparecen dentro del saludo y se ocultan después del primer envío.

El textarea crece hasta su límite visual. Enter envía y Shift+Enter inserta una línea. La etiqueta accesible sigue disponible y el aviso del proveedor permanece visible. Al abrir recibe foco el campo. Al cerrar o minimizar, el foco vuelve al lanzador. La conversación se conserva al volver a abrir el panel. El render de Markdown continúa con react-markdown y descarte de HTML activo.

La captura de conversación y los escenarios de error, escritura y respaldo emplean respuestas DEMO interceptadas en Playwright. Los KPI y las tablas se consultaron en los servicios locales. Estas capturas no acreditan llamadas nuevas a Groq o Gemini.

### Comparaciones y pruebas

La galería de esta ronda (`diseno/ronda-2/index.html`) contiene acceso, cabecera con KPI, menú de usuario, chat con saludo, conversación y tabla en claro y oscuro a 1440, 1024 y 390 px. Se añade la captura del indicador de escritura en el diseño final.

| Comprobación | Resultado |
| --- | --- |
| Test-Soc.ps1 antes de los cambios | 55 Python, 2 de reglas y 15 React aprobadas, junto con TypeScript |
| Test-Soc.ps1 al finalizar | 55 Python, 2 de reglas y 17 React aprobadas, junto con TypeScript |
| Tema e idioma con flechas | Verificado en Edge con radios nativos |
| Escape y clic exterior en el menú | Verificados, con retorno del foco al avatar mediante Escape |
| Minimizar y reabrir el chat | Conserva la conversación y devuelve el foco al lanzador |
| Shift+Enter, Enter y reintento | Conservan el contrato language/messages y el mismo cuerpo al reintentar |
| Cabecera y títulos | 64 px, fija durante el scroll del contenido y un H1 por módulo |
| Gráficos con chat abierto | Sin solapamiento de tarjetas a 1440 y 1024 px |
| Chat móvil | Hoja de 390 × 900 px, foco contenido en el diálogo |
| Consola del navegador | Cero errores durante la verificación final |
| DEMO y estimaciones | Conservan su rotulado en datos, insignias y vistas |

Suite anterior (`diseno/ronda-2/pruebas-antes.log`) · Suite final (`diseno/ronda-2/pruebas-despues.log`).

Los colores siguen usando los tokens semánticos ya comprobados para contraste. La comprobación de colores cubre las superficies, el texto, los controles y las burbujas de acento con sus fondos correspondientes. La evidencia mide aspectos concretos de accesibilidad y no constituye una auditoría exhaustiva de todas las combinaciones posibles.

### Dependencia y alcance

Se añadió @fontsource-variable/inter 5.3.0 para disponer de una familia y pesos uniformes sin fuentes remotas. Se empaqueta un único WOFF2 latino para español e inglés. Los componentes Preferences y WorkspaceHeader reutilizan tokens, iconos, avatar y popover de ui.tsx.

El JavaScript principal pasó de 29,28 a aproximadamente 30,88 kB comprimidos y el CSS de 6,54 a 7,56 kB. El módulo de gráficos mantiene la advertencia de Vite por superar 500 kB sin comprimir.

La entrega abarca presentación, controles de interfaz, empaquetado de la fuente y documentación. El estilo de los informes exportables queda fuera de esta ronda.
