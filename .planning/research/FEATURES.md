# Feature Landscape

**Dominio:** Dashboard local de detección de personas con cámara RTSP
**Investigado:** 2026-04-16

## Table Stakes

Funcionalidades que el usuario da por sentadas. Sin ellas, el producto se siente incompleto o roto.

| Funcionalidad | Por qué se espera | Complejidad | Notas |
|---|---|---|---|
| Vídeo en directo en el navegador | Es la razón de abrir el dashboard. Sin feed, no hay dashboard. | Media | MJPEG sobre HTTP es suficiente en LAN. Frigate, LightNVR, camera.ui: todos muestran stream en vivo como elemento central. |
| Bounding boxes sobre personas detectadas | Feedback visual inmediato de que la IA funciona. Todos los NVR con detección lo muestran. | Baja | Dibujar rectángulo + etiqueta "persona" con OpenCV antes de emitir frame. Sin esto el usuario no sabe si la detección está activa. |
| Contador de personas del día | Métrica principal del proyecto. Responde "¿cuánta gente ha pasado hoy?". | Baja | Número grande y visible. Depende del sistema de conteo por línea virtual. |
| Histograma de actividad por hora (últimas 24 h) | Patrón temporal: "¿a qué horas hay más actividad?". Es la estadística más intuitiva. | Baja | Bar chart vertical con Chart.js. 24 barras, una por hora. Los usuarios de Grafana y Home Assistant usan este formato como estándar para datos de actividad. |
| Indicador de estado de conexión | El usuario necesita saber si la cámara está conectada o caída. Sin esto, un frame congelado parece un bug. | Baja | Punto verde/rojo o texto "Conectado"/"Desconectado". WebSocket puede emitir estado. |
| Modo oscuro por defecto | Dashboards de monitorización se usan en modo oscuro casi universalmente. Frigate, LightNVR, Blue Iris: todos usan fondo oscuro. Reduce fatiga visual en uso prolongado. | Baja | Fondo gris oscuro (#1a1a2e o similar), no negro puro. Contraste mínimo 4.5:1 para texto. |
| Diseño responsive | El dashboard se consulta desde móvil, tablet y PC. Todos los NVR modernos (Frigate, camera.ui, LightNVR) son responsive. | Media | CSS Grid o Flexbox. El vídeo ocupa ancho completo en móvil, mitad en escritorio. |
| Eventos recientes visibles | Lista mínima de las últimas detecciones con timestamp. Da contexto al contador numérico. | Baja | 5-10 últimos eventos con hora. No requiere paginación en v1. |

## Differentiators

Funcionalidades que añaden valor real sin ser esperadas. Separan "funcional" de "bien hecho".

| Funcionalidad | Propuesta de valor | Complejidad | Notas |
|---|---|---|---|
| Thumbnail de última detección | Ver qué se detectó sin rebobinar vídeo. Captura el frame del momento de la detección. | Baja | Guardar JPEG del frame con bounding box al detectar persona. Mostrar el más reciente en el dashboard. Frigate hace esto y los usuarios lo valoran mucho. |
| Heatmap día/hora (7 días) | Visualización de patrones semanales: matriz 7x24 coloreada por intensidad. Más rico que el histograma. | Media | Grid HTML con colores de frío a cálido (azul a rojo). Consulta SQLite agrupando por día de semana y hora. Grafana ofrece un plugin específico para esto. |
| Log de detecciones con tabla paginada | Tabla con timestamp, confianza, y thumbnail. Permite revisar el historial de forma estructurada. | Media | Paginación con API REST (offset/limit). Tabla HTML con scroll. |
| Exportar datos a CSV | Compartir datos o analizarlos en Excel. Funcionalidad habitual en dashboards de seguridad profesionales (Verkada, etc.). | Baja | Endpoint API que genera CSV desde SQLite. Botón en la UI. |
| Score de confianza visible en overlay | Mostrar porcentaje de confianza junto al bounding box (ej: "Persona 87%"). | Baja | Ya disponible en la salida de YOLOv8. Solo hay que renderizarlo. Útil para calibrar el umbral. No saturar: solo mostrar cuando supera umbral configurado. |
| Estadísticas comparativas (hoy vs ayer, vs semana pasada) | Contexto temporal: "¿hoy hay más actividad de lo normal?". | Baja | Consulta SQLite comparando periodos. Mostrar como texto: "Hoy: 34 (+12% vs ayer)". |
| Zona de detección configurable | Delimitar un área del frame donde se cuentan personas, ignorando el resto. Evita falsos positivos en zonas irrelevantes. | Alta | Editor visual de polígono sobre el frame (como LightNVR). Requiere lógica de punto-en-polígono en el backend. Diferir a v2. |
| Configuración desde la UI | Ajustar umbral de confianza, URL de cámara, intervalo de captura sin tocar archivos. | Media | Formulario web que escribe a la config. Requiere endpoint PUT en la API y validación. |

## Anti-Features

Funcionalidades que deliberadamente no se construyen. Incluirlas añadiría complejidad sin valor proporcional.

| Anti-Feature | Por qué evitarla | Qué hacer en su lugar |
|---|---|---|
| Grabación continua de vídeo | Fuera de alcance (PROJECT.md explícito). El objetivo es estadísticas, no almacenamiento. Consume disco masivamente y convierte el proyecto en un NVR completo. | Guardar solo thumbnails de detecciones. |
| Notificaciones push/email | Complejidad de infraestructura (SMTP, service workers, tokens) desproporcionada para v1 de uso local. | El usuario consulta el dashboard cuando quiere. Log de eventos cumple la función. |
| Autenticación de usuarios | Red privada LAN. Añadir auth complica el setup sin beneficio real. Los usuarios de Frigate se quejan de complejidad innecesaria. | Confiar en el aislamiento de red. Documentar que no debe exponerse a internet. |
| Múltiples cámaras | Una cámara en v1 (PROJECT.md). Multi-cámara multiplica la complejidad de UI, recursos CPU y arquitectura. | Diseñar la arquitectura para que sea extensible, pero no implementarlo. |
| Reconocimiento facial / de matrículas | Scope creep. Requiere modelos adicionales, almacenamiento de datos biométricos, implicaciones de privacidad. | Mantener detección genérica de "persona". |
| Integración Home Assistant | Añade dependencia externa y complejidad de configuración. Para un dashboard standalone no aporta valor en v1. | API REST abierta que otros podrían consumir si quieren. |
| WebRTC | Complejidad de señalización (STUN/TURN) sin beneficio real en LAN donde MJPEG funciona bien. Los usuarios reportan problemas de estabilidad con WebRTC en NVRs. | MJPEG sobre HTTP. Latencia aceptable en red local. |
| Modo claro / toggle de tema | Overhead de CSS y preferencias para un dashboard que se usa casi exclusivamente en oscuro. Los dashboards de monitorización profesionales son oscuros por defecto. | Solo modo oscuro. Diseñar bien un solo tema. |

## UX Patterns

Patrones de diseño validados por el ecosistema de dashboards de cámaras locales.

### Layout: Vídeo dominante + sidebar de estadísticas

El patrón universal en dashboards de cámara única es el vídeo como elemento principal (60-70% del viewport) con un panel lateral o inferior para métricas. En móvil, se apilan verticalmente: vídeo arriba, stats debajo.

- **Desktop**: Grid de dos columnas. Izquierda: vídeo en directo. Derecha: contador, histograma, últimos eventos.
- **Móvil**: Stack vertical. Vídeo full-width arriba, cards de métricas debajo con scroll.

### Colores y tipografía

- **Fondo**: Gris oscuro (#1b1b2f o #0f0f23), no negro puro (#000). El negro puro crea contraste agresivo que cansa la vista.
- **Acentos**: Un color primario para datos activos (azul eléctrico #4fc3f7 o verde esmeralda #00e676). Rojo solo para alertas/errores.
- **Texto principal**: Blanco con opacidad (~rgba(255,255,255,0.87)). Texto secundario al 60%.
- **Números destacados**: Tamaño grande (2-3rem) con fuente monoespaciada para el contador principal.
- **Bounding boxes**: Color sólido brillante (verde lima #76ff03 o cian #00e5ff) con borde de 2-3px. Etiqueta con fondo semitransparente.

### Feedback en tiempo real

- WebSocket para actualizar contador y eventos sin recargar página.
- Animación sutil al incrementar contador (transición numérica).
- Los bounding boxes deben aparecer y desaparecer suavemente, no parpadear.

### Gráficos: qué funciona

- **Histograma horario**: Bar chart vertical, 24 barras. Es el estándar para datos de actividad por hora. Chart.js lo resuelve con configuración mínima. Color uniforme con la barra de la hora actual resaltada.
- **Heatmap semanal** (diferenciador): Matriz 7x24 con gradiente de color. Más denso en información pero requiere familiaridad del usuario. Implementar como mejora posterior al histograma.
- **Evitar**: Gráficos de línea para datos horarios discretos (sugieren continuidad falsa), gráficos circulares/pie (no aportan nada en este dominio), gráficos 3D (ruido visual).

### Información en overlay de vídeo

Mostrar sobre el feed de vídeo, por orden de utilidad:

1. **Bounding box** (imprescindible): Rectángulo alrededor de persona detectada.
2. **Etiqueta de clase** (imprescindible): "Persona" junto al bounding box.
3. **Score de confianza** (útil): Porcentaje junto a la etiqueta, solo cuando supera el umbral. No mostrarlo para cada frame para evitar ruido.
4. **Línea virtual de conteo** (útil): Línea semitransparente que el usuario puede ver para entender dónde se cuenta.
5. **Track ID** (no recomendado en v1): Añade ruido visual sin valor claro para el usuario final. Solo útil para debugging.
6. **Timestamp en overlay** (no recomendado): El navegador ya muestra la hora. Duplicar información en el vídeo reduce área útil.

## Feature Dependencies

```
Stream RTSP capturado
  └─► Vídeo en directo en navegador (MJPEG)
       └─► Bounding boxes en overlay
            └─► Score de confianza en overlay
            └─► Thumbnail de última detección

Detección YOLOv8
  └─► Conteo por línea virtual
       └─► Contador diario
       └─► Eventos en SQLite
            └─► Histograma horario
            └─► Log de detecciones
            └─► Heatmap semanal
            └─► Exportar CSV
            └─► Comparativa hoy vs ayer

WebSocket
  └─► Actualización en tiempo real del contador
  └─► Eventos recientes sin recargar
  └─► Indicador de estado de conexión
```

## Recomendación MVP

Construir primero (table stakes que desbloquean valor):

1. Vídeo en directo con bounding boxes
2. Contador de personas del día
3. Histograma horario (24 h)
4. Indicador de estado de conexión
5. Lista de últimos 5-10 eventos

Añadir después (diferenciadores de bajo esfuerzo):

6. Thumbnail de última detección
7. Score de confianza en overlay
8. Estadísticas comparativas (hoy vs ayer)
9. Exportar CSV

Diferir a v2:

- Heatmap semanal
- Zona de detección configurable
- Configuración desde la UI
- Log paginado completo

## Fuentes

- [Frigate NVR](https://frigate.video/) - Referencia principal de NVR con detección IA
- [LightNVR](https://github.com/opensensor/lightNVR) - NVR ligero con overlays de detección y temas
- [camera.ui](https://github.com/seydx/camera.ui) - Interfaz web para cámaras RTSP con widgets de dashboard
- [Frigate Roadmap Discussion](https://github.com/blakeblackshear/frigate/discussions/4573) - Expectativas de usuarios
- [Frigate user complaints](https://www.xda-developers.com/things-i-wish-i-knew-before-setting-up-frigate-for-home-security/) - Problemas comunes de usabilidad
- [Grafana Hourly Heatmap](https://grafana.com/grafana/plugins/marcusolsson-hourly-heatmap-panel/) - Referencia de visualización temporal
- [Verkada Heatmaps & Bounding Boxes](https://www.verkada.com/blog/introducing-heatmaps-bounding-boxes/) - Overlays en dashboards profesionales
- [Dark Mode UX Best Practices](https://www.graphiceagle.com/dark-mode-ui/) - Guías de diseño modo oscuro
- [Chart.js Bar Chart](https://www.chartjs.org/docs/latest/charts/bar.html) - Documentación oficial
- [Frigate vs Blue Iris](https://www.wundertech.net/frigate-vs-blue-iris/) - Comparativa de funcionalidades NVR
