# MEJORAS.md — Auditoría del algoritmo de reconocimiento

> Auditoría de `backend/detector.py`, `backend/tracker.py`, `backend/recognizer.py` y su integración en `backend/stream.py`.
> Fecha: 2026-07-09 · supervision instalado: 0.27.0 · repo fuente clonado en `third_party/supervision/` (0.30.0.dev)

## Resumen

El pipeline funciona, pero tiene un bug real de conteo, varias fugas de memoria lentas y un cuello de botella de latencia: el reconocimiento facial (dlib) corre dentro del hilo de captura RTSP y congela el vídeo cada vez que se intenta identificar a alguien. La precisión del reconocimiento también sufre porque se registra una persona nueva con una sola muestra de cara, sin ningún filtro de calidad.

---

## Críticas (bugs de corrección)

### 1. ✅ RESUELTO (2026-07-09) — El conteo in/out está roto para trayectorias de ida y vuelta
`tracker.py:56-63` — el set `_crossed_ids` impide que un mismo `tracker_id` cuente dos veces. Consecuencia: una persona que entra (cruce "in") y luego sale (cruce "out") solo registra el "in"; el "out" se descarta porque su id ya está en el set. El `elif` agrava el caso límite de cruce doble en el mismo frame.

**Arreglo:** `LineZone` ya deduplica cruces por track internamente (mantiene estado por `tracker_id`). Eliminar `_crossed_ids` y usar directamente `line_zone.in_count` / `line_zone.out_count`, o al menos llevar sets separados por dirección. El "total de personas distintas" puede seguir calculándose con un set aparte que no bloquee el conteo direccional.

### 2. ✅ RESUELTO (2026-07-09) — Cruces falsos por jitter de detección
La línea usa un solo anchor (`CENTER`) y umbral por defecto. Cuando la caja de YOLO tiembla cerca de la línea se generan cruces espurios.

**Arreglo:** `LineZone(..., minimum_crossing_threshold=2)` (disponible en 0.27) exige que el objeto esté N frames al otro lado antes de confirmar el cruce. Coste cero, elimina la mayor parte del jitter.

### 3. ✅ RESUELTO (2026-07-09) — `visit_count` no mide visitas
`recognizer.py:299-305` — `_touch` incrementa `visit_count` cada vez que un `tracker_id` nuevo matchea. Si ByteTrack pierde y recupera a la misma persona tres veces en una estancia, cuenta 3 visitas.

**Arreglo:** incrementar solo si `last_seen` es anterior a un margen (p. ej. 5 min): `UPDATE persons SET visit_count = visit_count + (last_seen < datetime('now','-5 minutes')), last_seen = datetime('now')`.

---

## Altas (precisión del reconocimiento facial)

### 4. ✅ RESUELTO (2026-07-09) — Registro de persona nueva con una sola muestra sin filtro de calidad
`recognizer.py:127` — cualquier cara no reconocida en un solo frame crea una persona nueva en la BD. Una cara borrosa, de perfil o mal iluminada de una persona ya conocida genera un duplicado "fantasma" permanente que además envenena futuros matches.

**Arreglo (por capas, en orden de impacto):**
- **Tamaño mínimo de cara**: descartar caras < 60×60 px antes de codificar — los embeddings de caras pequeñas no son fiables.
- **Filtro de desenfoque**: `cv2.Laplacian(gray, cv2.CV_64F).var() < umbral` → descartar frame.
- **Confirmación por consenso**: exigir K muestras consistentes (p. ej. 3 embeddings a distancia < 0.4 entre sí en frames distintos del mismo track) antes de crear persona nueva. Buffer por `tracker_id`.

### 5. ✅ RESUELTO (2026-07-09) — Sin test de margen en el matching
`recognizer.py:118-125` — se acepta el vecino más cercano si `dist <= 0.55`. Con la BD creciendo, dos personas parecidas caen dentro del umbral y se confunden.

**Arreglo:** ratio test: aceptar solo si además `second_best - best > 0.10` (margen entre el mejor match y el mejor match de *otra* persona). Barato: `face_distance` ya devuelve todas las distancias.

### 6. ✅ RESUELTO (2026-07-09) — Match contra embeddings individuales en vez de por persona
Las listas planas hacen que una persona con 20 muestras tenga 20 "boletos" en el vecino más cercano. Mejor: agrupar distancias por `person_id` y comparar contra la mínima (o la media de las 3 mínimas) por persona. Mismo dato, decisión más robusta, y el ratio test del punto 5 pasa a ser entre personas, que es lo que importa.

### 7. ✅ RESUELTO (2026-07-09) — Se codifica la primera cara del crop, no la correcta
`recognizer.py:114` — `encodings[0]`. Si el bbox de la persona incluye una segunda cara al fondo (solapamiento de personas), puede asignarse la cara equivocada al track.

**Arreglo:** elegir la cara de mayor área, o la más cercana al centro-superior del bbox (donde está la cabeza del track).

### 8. ✅ RESUELTO (2026-07-09) — Identidad cacheada de por vida sin re-verificación
`recognizer.py:93-94` — el primer match gana para siempre para ese `tracker_id`. Un falso positivo se queda pegado al track (y su nombre sale en eventos, notificaciones y grabaciones).

**Arreglo:** re-verificar cada N segundos mientras el track siga vivo; mantener votación por mayoría de los últimos M intentos y corregir la cache si cambia el ganador.

### 9. ⚠️ PARCIAL (2026-07-09) — Detector HOG limita el sistema en escenario CCTV
HOG solo detecta caras frontales y relativamente grandes. En cámara de techo/esquina con ángulos picados falla la mayoría de las veces, y todo lo demás (re-ID, nombres, capturas) depende de ese primer paso.

**Opciones (de menor a mayor esfuerzo):**
1. ✅ RESUELTO (2026-07-09) — `fr.face_locations(rgb, model="hog", number_of_times_to_upsample=2)` cuando el crop sea pequeño (< 240 px de lado) — más detecciones a cambio de CPU, que ahora absorbe el worker de reconocimiento.
2. PENDIENTE (solo si tras los filtros de calidad siguen los fallos de reconocimiento) — Sustituir la pila `face_recognition`/dlib por **InsightFace** (`buffalo_s`: detector SCRFD + embeddings ArcFace 512-d, ONNX Runtime CPU). Salto grande de precisión en ángulos/iluminación difíciles y ~igual de rápido en CPU. Requiere migración de embeddings (128-d float64 → 512-d float32) — la tabla `face_encodings` ya lo soporta con una columna de versión de modelo.

---

## Medias (rendimiento y robustez)

### 10. ✅ RESUELTO (2026-07-09) — dlib bloquea el hilo de captura RTSP
`stream.py:238` — `identify_or_register` (detección HOG + encoding dlib, 100–500 ms en CPU) corre en el hilo de captura. Cada intento congela la captura: se pierden frames, el MJPEG da tirones y ByteTrack pierde tracks (lo que a su vez dispara más intentos de reconocimiento — círculo vicioso).

**Arreglo:** cola de trabajos + hilo worker dedicado. El hilo de captura encola `(crop.copy(), tid, frame_num)` y sigue; el worker publica resultados en `_person_cache`. Es el cambio con mejor ratio impacto/esfuerzo de toda la lista.

### 11. ✅ RESUELTO (2026-07-09) — YOLO en cada frame
`stream.py:213` — inferencia en todos los frames. En CPU, detectar cada 2-3 frames y dejar que ByteTrack interpole mantiene los tracks estables y duplica el FPS efectivo. Alternativa complementaria: fijar `imgsz=640` (o 480) explícito en la llamada al modelo.

### 12. ✅ RESUELTO (2026-07-09) — Fugas de memoria lentas (proceso 24/7)
Crecen sin límite con los `tracker_id` (monótonos crecientes):
- `recognizer._cache` y `recognizer._last_attempt` (`recognizer.py:48-50`)
- `stream._person_cache`
- `tracker._crossed_ids` (desaparece con el arreglo del punto 1)

**Arreglo:** poda periódica — eliminar entradas cuyo `tracker_id` ya no esté en los tracks activos de ByteTrack (con margen de `lost_track_buffer`), o simple límite LRU.

### 13. ✅ RESUELTO (2026-07-09) — Commits SQLite en el hilo de captura
`_touch` y `_register` hacen `commit()` síncrono dentro del flujo por frame. Con WAL es rápido, pero sigue siendo I/O en el hilo caliente. Se resuelve gratis al mover el reconocimiento al worker (punto 10).

### 14. ✅ RESUELTO (2026-07-09) — `frame_rate` de ByteTrack no coincide con el real
`tracker.py:21` — `ByteTrack(lost_track_buffer=60)` asume `frame_rate=30`. El stream real (substream Tapo + detección) va a bastante menos; el buffer efectivo en segundos es el doble del esperado. Pasar el FPS medido (ya existe `_fps_times` en stream.py) al construir el tracker.

### 15. ✅ RESUELTO (2026-07-09) — Personas "fantasma" sin limpieza
Cada transeúnte registra una fila + embedding para siempre. En una cámara a la calle, la BD crece indefinidamente y todo matching se degrada (más candidatos → más falsos positivos).

**Arreglo:** tarea de retención — borrar personas sin nombre con `visit_count == 1` y `last_seen` > 30 días. Las personas nombradas nunca se tocan.

---

## Bajas (oportunidades con supervision — repo en `third_party/supervision/`) — ✅ RESUELTAS (2026-07-09)

| Mejora | API | Qué aporta | Estado |
|---|---|---|---|
| Zonas activas de verdad | `sv.PolygonZone` | Con `PolygonZone.trigger(tracked)` las zonas cuentan presencia y entradas, no solo se dibujan | ✅ `_update_zones_and_heat` + `GET /api/zones/stats`; el overlay muestra la ocupación en vivo |
| Cajas estables | `sv.DetectionsSmoother` | Suaviza bboxes entre frames; menos jitter visual y menos cruces falsos (complementa el punto 2) | ✅ en `PersonTracker.update` |
| Estelas de trayectoria | `sv.TraceAnnotator` | Dibuja el recorrido de cada track — depuración visual de la línea de conteo casi gratis | ✅ en `PersonTracker.annotate` |
| Mapa de calor | `sv.HeatMapAnnotator` | Vista de actividad acumulada | ✅ acumulación propia por frame (mismo algoritmo, sin blur/colormap por frame) + `GET /api/heatmap` |
| FPS del pipeline | `sv.FPSMonitor` | Sustituye el cálculo manual con `_fps_times` | ✅ en `stream.py` |
| Anchor de cruce | `Position.BOTTOM_CENTER` | Los pies cruzan la línea de forma más fiable que el centro de la caja (el centro oscila con los brazos/postura) | ✅ LineZone y heatmap usan BOTTOM_CENTER |

Fuente para consulta: `third_party/supervision/src/supervision/detection/line_zone.py`, `.../detection/tools/polygon_zone.py`, `.../detection/tools/smoother.py`, `.../tracker/byte_tracker/core.py`.

---

## Orden de ataque sugerido

1. **Punto 1** (bug de conteo) + **punto 2** (`minimum_crossing_threshold`) — corrección, poco código.
2. **Punto 10** (worker de reconocimiento) — desbloquea el hilo de captura; mejora FPS y estabilidad de tracks de inmediato.
3. **Puntos 4, 5, 7** (filtros de calidad + ratio test + selección de cara) — precisión facial sin cambiar de librería.
4. **Punto 12** (poda de caches) + **punto 15** (retención de fantasmas) — salud a largo plazo.
5. **Punto 9.2** (InsightFace) — solo si tras 3 sigue habiendo fallos de reconocimiento; es la mejora de mayor calado.
