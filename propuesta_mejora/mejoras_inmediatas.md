Mi diagnóstico general sería:

El pipeline funcional está bien resuelto, pero el siguiente salto de calidad debería centrarse en arquitectura de procesamiento, precisión de visión artificial, observabilidad y una interfaz mucho más orientada a la operación.

La arquitectura actual ya tiene una cadena bastante completa:

Cámara RTSP → captura → YOLO → ByteTrack → LineZone → reconocimiento facial → eventos → SQLite → grabación → Google Drive → API/WebSocket → Dashboard

Además, el repositorio ya incorpora elementos interesantes como zonas, heatmap, trazas, PTZ, alertas, grabación, métricas y seguridad. Eso es una buena base.

1. Mi valoración global
Área	Estado actual	Mi valoración
Captura RTSP	Reconexión + control de buffer	🟢 Bien
Detección YOLO	Modelo ligero + CPU	🟢 Bien
Tracking	ByteTrack	🟢 Bien
Conteo	Línea virtual	🟡 Mejorable
Reconocimiento facial	dlib / face-recognition	🟡 Principal área de mejora
Procesamiento	Hilos separados parcialmente	🟡 Hay que desacoplar más
Persistencia	SQLite + WAL	🟢 Correcto para una cámara
Grabación	Clips automáticos	🟢 Bien
Cloud	Google Drive	🟢 Correcto, pero mejorable
Seguridad	Bastante avanzada para una LAN	🟡 Hay deuda técnica
Frontend	Funcional y visualmente cuidado	🟡 Puede evolucionar mucho
Escalabilidad	Monocámara	🔴 Limitada
Observabilidad	CPU/RAM/FPS	🟡 Insuficiente para producción
IA avanzada	Detección + reconocimiento	🟡 Falta una capa semántica
Testing	Buena cobertura backend	🟢 Buena base
Arquitectura	Monolito modular	🟡 Próximo cuello de botella
2. La mejora técnica más importante: separar el pipeline de vídeo

Esta sería mi prioridad número 1.

Por lo que veo, aunque ya habéis corregido varias cuestiones importantes documentadas en MEJORAS.md, el sistema sigue estando conceptualmente muy acoplado.

Yo evolucionaría hacia algo parecido a:

                 ┌────────────────────┐
                 │      Cámara RTSP    │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │   Capture Worker   │
                 │  latest-frame only │
                 └─────────┬──────────┘
                           │
                 ┌─────────▼─────────┐
                 │   Frame Broker     │
                 │  ring buffer /     │
                 │  latest frame     │
                 └──────┬─────┬──────┘
                        │     │
             ┌──────────┘     └───────────┐
             ▼                            ▼
      ┌───────────────┐           ┌───────────────┐
      │   Detector    │           │  Recorder     │
      │    YOLO       │           │   MP4/codec   │
      └───────┬───────┘           └───────────────┘
              │
              ▼
      ┌───────────────┐
      │    Tracker    │
      │   ByteTrack   │
      └───────┬───────┘
              │
        ┌─────┴─────┐
        ▼           ▼
 ┌────────────┐ ┌───────────────┐
 │  Behavior  │ │ Face Worker   │
 │  Analysis  │ │ InsightFace   │
 └─────┬──────┘ └───────┬───────┘
       │                │
       └───────┬────────┘
               ▼
        ┌──────────────┐
        │ Event Engine │
        └──────┬───────┘
               │
      ┌────────┼─────────┐
      ▼        ▼         ▼
    SQLite   WebSocket  Alerts
      │
      ▼
  Dashboard

La idea fundamental es:

La captura nunca debe esperar a la IA.

Y tampoco:

El reconocimiento facial nunca debe bloquear al detector.

La cámara debe producir continuamente el último frame disponible.

Si YOLO tarda 100 ms, procesa el último frame.

Si reconocimiento facial tarda 500 ms, no debería afectar al vídeo.

Si Google Drive tarda 5 segundos, no debería afectar absolutamente nada del pipeline.

Esto se puede conseguir con:

asyncio.Queue para eventos.
queue.Queue(maxsize=1) para frames.
workers dedicados.
descarte explícito de frames antiguos.
un bus de eventos interno.

Por ejemplo:

RTSP
  │
  ▼
[Latest Frame]
  │
  ├──► Detection Worker
  │
  ├──► Recording Worker
  │
  └──► Streaming Worker

No utilizaría una cola infinita de frames.

Para CCTV en tiempo real es mejor:

Perder frames que acumular latencia.

3. Mejoraría radicalmente el reconocimiento facial

Este es, para mí, el mayor salto de calidad de IA que puede dar el proyecto.

Actualmente tenéis una arquitectura basada en:

face-recognition
    ↓
dlib HOG
    ↓
128D embedding
    ↓
distancia euclidiana

Para una primera versión está bien.

Para un sistema de videovigilancia continuo, yo migraría progresivamente a:

Detector facial
      ↓
Quality Assessment
      ↓
Face Alignment
      ↓
ArcFace embedding
      ↓
Vector database
      ↓
Identity matching
      ↓
Temporal voting

Mi candidato sería InsightFace / ArcFace.

La diferencia conceptual es importante:

Actualmente:

"Veo una cara"
      ↓
"Intento reconocerla"

Yo haría:

"Veo una cara"
      ↓
"¿La imagen tiene suficiente calidad?"
      ↓
"¿Es frontal / visible?"
      ↓
"¿Es suficientemente grande?"
      ↓
"Genero embedding"
      ↓
"Comparo con identidades"
      ↓
"¿Tengo suficiente confianza?"
      ↓
"Confirmo identidad después de N frames"

Por ejemplo:

Frame 1 → Juan 82%
Frame 2 → Juan 87%
Frame 3 → Juan 91%
Frame 4 → Juan 89%

IDENTIDAD CONFIRMADA: JUAN

Esto es muchísimo más robusto que:

Frame 1 → Juan

Y además evita el problema de:

Juan
  ↓
Track perdido
  ↓
Nuevo track
  ↓
Juan_2
  ↓
Juan_3
  ↓
Juan_4

Yo implementaría una máquina de estados:

UNKNOWN
   │
   ▼
CANDIDATE
   │
   │  N matches consistentes
   ▼
CONFIRMED
   │
   │  pérdida temporal
   ▼
TEMPORARILY_LOST
   │
   ├── vuelve → CONFIRMED
   │
   └── timeout → UNKNOWN

Eso convertiría el reconocimiento facial en un sistema mucho más profesional.

4. Añadiría Re-Identification (ReID)

Esta sería probablemente mi segunda gran mejora de IA.

Actualmente el sistema depende mucho de:

detección facial

Pero en una cámara de vigilancia hay situaciones donde la cara no se ve:

persona de espaldas.
gorra.
baja iluminación.
persona lejos.
ángulo lateral.
rostro parcialmente oculto.

Aquí añadiría:

Person Detection
       ↓
ByteTrack
       ↓
Person ReID embedding
       ↓
Face Recognition

El sistema tendría dos tipos de identidad:

Face Identity
    Juan

Person Identity
    Track #152

Y podría inferir:

Track #152
    ↓
Face match
    ↓
Juan
    ↓
Juan sigue siendo Track #152
    ↓
Cara deja de ser visible
    ↓
ReID mantiene continuidad

Esto es mucho más adecuado para CCTV.

5. Convertiría el sistema de "detección" en un "motor de eventos"

Ahora mismo gran parte de la lógica está alrededor de:

persona detectada

Yo introduciría una capa explícita:

EventEngine

Por ejemplo:

PERSON_ENTERED
PERSON_EXITED
PERSON_RECOGNIZED
UNKNOWN_PERSON
INTRUSION
LOITERING
CROWD_DETECTED
LINE_CROSSED
OBJECT_LEFT
OBJECT_REMOVED
CAMERA_OFFLINE
CAMERA_RECOVERED

Esto permitiría construir reglas:

rules:
  - name: intrusión nocturna
    when:
      event: PERSON_ENTERED
      zone: jardin
      time: "23:00-06:00"
    actions:
      - record
      - telegram
      - webhook

Y otra:

- name: persona desconocida
  when:
    event: UNKNOWN_PERSON
  actions:
    - snapshot
    - record
    - notify

Y:

- name: permanencia excesiva
  when:
    event: LOITERING
    duration: 120
  actions:
    - notify

Esto separaría:

Visión artificial
        ↓
Eventos
        ↓
Reglas
        ↓
Acciones

Es una arquitectura mucho más escalable.

6. Incorporaría un "Scene Understanding Layer"

Ahora mismo tenéis principalmente:

¿Hay una persona?

El siguiente nivel sería:

¿Qué está ocurriendo?

Por ejemplo:

Personas
Entrada.
Salida.
Permanencia.
Dirección.
Velocidad.
Tiempo en zona.
Recuento.
Comportamiento
Persona inmóvil.
Persona corriendo.
Persona cayendo.
Persona entrando en zona restringida.
Grupo de personas.
Objetos
Objeto abandonado.
Objeto retirado.
Vehículo.
Bicicleta.
Mochila.
Contexto
08:00
Zona principal
5 personas
2 conocidas
3 desconocidas
Actividad alta

Esto ya convierte el proyecto en una plataforma de Video Analytics.

7. Mejoraría la detección de personas con inferencia adaptativa

Actualmente YOLO se utiliza como detector general.

Yo implementaría una política adaptativa:

FPS cámara = 25
FPS detección = 8-12
FPS tracking = 25
FPS reconocimiento facial = 2-5

Es decir:

Captura        25 FPS
        ↓
Tracking       25 FPS
        ↓
YOLO            8 FPS
        ↓
Face            2 FPS
        ↓
Eventos        según cambios

Esto puede reducir muchísimo CPU.

Además, usaría:

detección cada N frames.
tracking entre detecciones.
reconocimiento facial solo cuando:
aparece un nuevo track.
cambia la identidad.
baja la confianza.
ha pasado un tiempo de revalidación.

Así evitarías:

YOLO → Face → Face → Face → Face

para la misma persona.

8. Cambiaría el modelo de persistencia

Para una cámara:

SQLite

está perfectamente bien.

Pero separaría las entidades:

cameras
persons
face_embeddings
tracks
detections
events
recordings
alerts
zones
rules
system_metrics

Especialmente:

detections

y

events

deben ser cosas diferentes.

Ejemplo:

Detection
2026-07-29 12:00:01
person
confidence 0.92
bbox (...)

Detection
2026-07-29 12:00:02
person
confidence 0.94
bbox (...)

Pero:

Event
PERSON_ENTERED
2026-07-29 12:00:04
person_id=Juan
zone=entrada

No guardaría cada detección en SQLite si el objetivo es operar 24/7.

Guardaría:

detecciones → memoria / métricas agregadas
eventos → persistencia

Esto reduce mucho el volumen.

9. Haría el almacenamiento de vídeo mucho más robusto

Actualmente:

Detecta actividad
      ↓
Graba
      ↓
5s sin detección
      ↓
Finaliza
      ↓
Sube Drive

Yo implementaría:

Pre-buffer: 5-10 segundos
      ↓
Evento
      ↓
Graba evento
      ↓
Post-buffer: 5-10 segundos

Esto es importantísimo.

Ahora mismo puedes perder los primeros segundos de una intrusión.

Con un buffer circular:

00:00  frame
00:01  frame
00:02  frame
00:03  frame ← comienza evento

El vídeo guardado sería:

00:00 ───────────── 00:03 ───────────── 00:10
       PREBUFFER       EVENTO           POST

Así el vídeo tiene contexto.

También añadiría:

miniatura.
hash del archivo.
duración.
tamaño.
evento asociado.
persona asociada.
zona.
motivo de grabación.
checksum.
estado de upload.

Y consideraría almacenamiento local + cloud:

SSD local
   ↓
retención 7 días

Google Drive
   ↓
eventos importantes

No necesariamente subiría todos los clips.

10. El Dashboard necesita evolucionar visualmente

Aquí veo muchísimo potencial.

La interfaz actual tiene una estética moderna y oscura, pero yo cambiaría la jerarquía visual.

Ahora parece más un:

Dashboard técnico de monitorización

Yo lo convertiría en:

Centro de operaciones de videovigilancia inteligente

La pantalla principal debería responder en 3 segundos:

¿Está todo bien?
¿Qué está ocurriendo ahora?
¿Ha ocurrido algo importante?


Mi propuesta de layout
┌───────────────────────────────────────────────────────────┐
│ ● SISTEMA ONLINE       Cámara 1       12:43:32            │
├───────────────────────────────┬───────────────────────────┤
│                               │                           │
│                               │  ALERTAS                  │
│        VIDEO EN DIRECTO       │  🔴 Persona desconocida   │
│                               │  🟡 Intrusión             │
│       [ detecciones ]         │  🟢 Sistema OK            │
│                               │                           │
│                               ├───────────────────────────┤
│                               │  PERSONAS AHORA           │
│                               │       3                   │
│                               │  Juan · Ana · Unknown     │
│                               │                           │
├───────────────────────────────┴───────────────────────────┤
│                                                           │
│ ACTIVIDAD HOY                                             │
│ ████▆▆█████████▆▆                                         │
│                                                           │
├─────────────────────┬─────────────────┬───────────────────┤
│ ENTRADAS            │ SALIDAS         │ EVENTOS           │
│ 124                 │ 119             │ 7                 │
└─────────────────────┴─────────────────┴───────────────────┘

11. Añadiría un "Event Timeline"

Esto sería una mejora visual y funcional enorme.

En lugar de tener únicamente una tabla:

Hora | Dirección | Persona

Tendría:

12:42:31
🔴 Persona desconocida detectada
📍 Zona entrada
🎥 Clip disponible

12:41:08
🟢 Juan identificado
➡ Entrada

12:38:22
🟡 Intrusión detectada
📍 Zona restringida

Y cada evento:

[Thumbnail]
Persona desconocida
12:42:31
Entrada
Confianza 92%

[Ver vídeo]
[Ver captura]
[Marcar como persona]

Eso haría el dashboard mucho más útil.

12. Haría una pantalla específica de "Analítica"

Otra sección:

ANALÍTICA

Con:

Actividad
Personas por hora
Ocupación
Zona A
████████ 8

Zona B
███ 3
Heatmap
      🔥🔥
   🔥🔥🔥🔥🔥
    🔥🔥🔥
Personas
Juan             128 visitas
Ana               73 visitas
Desconocidos      51 visitas
Tendencias
Hoy       342 personas
Ayer      281 personas
+21.7%

Y:

Hora más activa
18:00 - 19:00

Esto transforma el producto de:

"Cámara con IA"

a:

"Sistema de inteligencia operacional basado en vídeo".

13. Añadiría una vista "Cámara"

Una sección específica:

CÁMARA

Con:

┌──────────────────────────────┐
│                              │
│        LIVE VIEW             │
│                              │
└──────────────────────────────┘

FPS        24.3
Latencia   180 ms
CPU        42%
RAM        2.1 GB
Detector   8.2 FPS
Tracking   OK
RTSP       Connected

Y debajo:

Configuración

Detection confidence  ─────●──
Detection FPS         ─────●──
Face recognition      ON
Recording             ON

[Editar zona]
[Editar línea]
[Calibrar cámara]
14. Haría que la configuración fuera visual

Ahora mismo mucha configuración está orientada al .env.

Para un producto final, la interfaz debería permitir:

Configuración
│
├── Cámara
│   ├── RTSP
│   ├── Resolución
│   └── FPS
│
├── Detección
│   ├── Confianza
│   ├── Clases
│   └── FPS inferencia
│
├── Tracking
│   ├── ByteTrack
│   └── Persistencia
│
├── Reconocimiento
│   ├── Personas
│   ├── Umbral
│   └── Revalidación
│
├── Zonas
│
├── Reglas
│
├── Alertas
│
└── Almacenamiento

Y permitir:

Dibujar zona
Dibujar línea
Dibujar área restringida

directamente sobre el vídeo.

Esta es una mejora que considero muy importante.

15. Seguridad: corregiría inmediatamente los puntos del propio vulnerabilidades.md


16. La arquitectura debería prepararse para multi-cámara

Aunque ahora no lo necesites, el código debería poder evolucionar de:

Camera

a:

CameraManager
    │
    ├── Camera 1
    │     ├── Capture
    │     ├── Detector
    │     ├── Tracker
    │     └── Recorder
    │
    ├── Camera 2
    │     ├── Capture
    │     ├── Detector
    │     ├── Tracker
    │     └── Recorder
    │
    └── Camera N

La base de datos:

camera_id

debería estar presente en:

detections
events
recordings
zones
rules

Así no tendrías que reescribir todo cuando llegue la segunda cámara.

17. Mejoraría la observabilidad

Ahora tenéis:

CPU
RAM
FPS
Uptime

Yo añadiría:

RTSP reconnect count
RTSP latency
Capture FPS
Detection FPS
Tracking FPS
Recognition FPS
Inference latency
Face recognition latency
Queue size
Dropped frames
Dropped detections
Active tracks
Unknown persons
Events/min
Recording queue
Upload queue
Upload failures
Database size
Disk free

Especialmente:

Frames dropped: 234

es una métrica muy importante.

Un sistema puede mostrar:

FPS = 25

y tener una latencia de 15 segundos.

Por eso también mediría:

Camera timestamp
    ↓
Processing timestamp
    ↓
Display timestamp

para calcular:

End-to-end latency
18. Mejoraría los tests

La cobertura backend parece bastante buena, pero veo un área clara:

Frontend

No tiene una estrategia equivalente.

Yo incorporaría:

Playwright

o similar para probar:

vídeo disponible.
cámara offline.
WebSocket reconecta.
nuevo evento aparece.
filtro funciona.
clip reproduce.
modal funciona.
PTZ responde.
alertas aparecen.

Y tests de integración:

RTSP fake
   ↓
Detector mock
   ↓
Tracker
   ↓
Event Engine
   ↓
DB
   ↓
WebSocket
   ↓
Frontend

Esto sería mucho más valioso que añadir más tests unitarios aislados.

19. El frontend debería dejar de tener toda la lógica en index.html

Veo que frontend/app.js prácticamente no contiene lógica y el comentario indica:

"Lógica del dashboard incluida en index.html"

Yo cambiaría eso.

Pasaría a:

frontend/
├── index.html
├── css/
│   ├── base.css
│   ├── dashboard.css
│   └── components.css
│
└── js/
    ├── app.js
    ├── api.js
    ├── websocket.js
    ├── camera.js
    ├── events.js
    ├── analytics.js
    ├── recordings.js
    ├── ptz.js
    └── notifications.js

Incluso sin framework.

Puedes mantener JavaScript vanilla y seguir sin build step.

Pero dividir responsabilidades haría que el proyecto fuera mucho más mantenible.

20. Mi propuesta de evolución del proyecto

Yo plantearía una v2.0 en este orden:

Fase A — Robustez
1. Event Engine
2. Frame Broker
3. Workers independientes
4. Pre-buffer de vídeo
5. Métricas avanzadas
6. Limpieza de memoria
7. Seguridad pendiente
Fase B — IA
8. InsightFace / ArcFace
9. Quality filtering
10. Re-identification
11. Identidad temporal
12. Revalidación facial
13. Análisis de comportamiento
Fase C — Producto
14. Event Timeline
15. Centro de alertas
16. Vista analítica
17. Configuración visual
18. Editor de zonas
19. Editor de reglas
Fase D — Escalabilidad
20. CameraManager
21. Multi-camera
22. Event bus
23. PostgreSQL opcional
24. Redis opcional
25. GPU worker opcional
Mi ranking de mejoras

Si yo tuviera que trabajar directamente sobre este repositorio, mi orden sería:

🔴 Prioridad crítica
Separar totalmente captura / detección / reconocimiento / grabación.
Eliminar cualquier uso inseguro de pickle.
Implementar pre-buffer de vídeo.
Convertir el pipeline en un sistema orientado a eventos.
Corregir y endurecer todos los puntos pendientes de seguridad.
🟠 Prioridad alta
Migrar face-recognition/dlib → InsightFace/ArcFace.
Añadir re-identificación de personas.
Implementar identidad con votación temporal.
Detección YOLO adaptativa.
Crear un Event Timeline.
Editor visual de zonas y líneas.
🟡 Prioridad media
Multi-cámara.
Reglas configurables.
Analítica avanzada.
Métricas de latencia end-to-end.
Tests E2E frontend.
La transformación que yo haría

La evolución conceptual sería:

                    V1 ACTUAL

       Cámara
          ↓
      Detectar
          ↓
       Trackear
          ↓
     Reconocer
          ↓
       Contar
          ↓
      Grabar
          ↓
      Dashboard

hacia:

                    V2 PROPUESTA

                       CÁMARA
                          │
                          ▼
                  ┌───────────────┐
                  │ VIDEO PIPELINE│
                  └───────┬───────┘
                          │
                 ┌────────▼────────┐
                 │ PERCEPTION LAYER│
                 │                 │
                 │ Detection       │
                 │ Tracking        │
                 │ Face            │
                 │ ReID            │
                 │ Pose            │
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │  EVENT ENGINE   │
                 │                 │
                 │ Entry           │
                 │ Exit            │
                 │ Intrusion       │
                 │ Unknown         │
                 │ Loitering       │
                 │ Object          │
                 └────────┬────────┘
                          │
                 ┌────────▼────────┐
                 │  RULE ENGINE    │
                 └────────┬────────┘
                          │
             ┌────────────┼─────────────┐
             ▼            ▼             ▼
         Alertas       Grabación      Analytics
             │            │             │
             └────────────┼─────────────┘
                          ▼
                    OPERATIONS UI

Ese sería mi objetivo final para este repositorio.

---

# Plan de mejoras tras la v2.0 (revisión del 2026-10-31)

Revisión hecha sobre el commit `437398e`, leyendo el código actual. El texto de arriba se conserva como propuesta original: casi todo lo que pedía ya existe, de modo que este plan no repite la arquitectura objetivo, sino lo que falta para que el sistema funcione sin vigilancia durante semanas.

La conclusión es que la v2.0 está construida, pero no se ha ejercitado de verdad. Con las reglas por defecto no se graba ningún clip, y por eso los fallos de esa ruta siguen ocultos; la retención apenas borra nada; y CI no ejecuta los tests que protegen los invariantes del pipeline. Conviene arreglar eso antes de añadir funciones nuevas.

## Estado de la propuesta original

De las 20 secciones, 11 están hechas, 8 parciales y la primera era solo un diagnóstico. Estas son las parciales:

| § | Propuesta | Qué falta |
|---|---|---|
| 4 | ReID | Herencia de identidad desactivada por defecto y sin validar con personas reales |
| 5 | Event Engine | Solo se cablean 5 de las 8 acciones; `INTRUSION` nunca se emite |
| 6 | Capa de escena | Sin caídas ni pose |
| 7 | Detección adaptativa | ByteTrack corre solo en los frames procesados, no entre detecciones |
| 9 | Almacenamiento de vídeo | El mecanismo existe, pero nada graba por defecto y `upload_drive` no hace nada |
| 13 | Vista Cámara | No existe la calibración |
| 16 | Multi-cámara | `cam1` fijo en parte de la interfaz y PTZ global |
| 17 | Observabilidad | La latencia mide hasta el envío por WebSocket, no hasta la pantalla |

De `vulnerabilidades.md` siguen abiertos los permisos de `key.pem`, y a medias los puntos 2, 4, 7, 9, 10 y 14, que el plan recoge abajo.

## Fases, por orden de ejecución

El orden sigue una lógica sencilla: primero que CI vigile de verdad, después cerrar la seguridad barata, luego asegurar los datos y la calidad del conteo, y solo entonces activar la grabación. Cada identificador corresponde a un hallazgo del registro final. El esfuerzo es S (horas), M (un día) o L (varios días).

### Fase 1. Que CI compruebe lo que dice comprobar (S)

Es lo primero porque el resto del plan se apoya en ello. `pytest.ini` declara `python_functions = TEST_*`, y en Windows esa comparación ignora mayúsculas, pero en Linux no: 79 funciones `def test_*`, entre ellas las seis de `tests/test_architecture.py`, pasan aquí y nunca corren en CI. Además, los E2E solo se lanzan en pull requests, y desde agosto casi todo entra directamente en `main`.

| Id | Cambio | Esfuerzo |
|---|---|---|
| TEST-01 | Recoger también `test_*` y añadir un test que falle si alguno queda fuera | S |
| TEST-02 | Ejecutar Playwright en los push a `main` | S |
| DX-02 | Añadir `ruff` con reglas `E9,F`, pasar pytest una sola vez con cobertura y activar `-rs` | S |

Al activar TEST-01 pueden aparecer fallos reales en Linux. Hay que corregirlos, no silenciarlos.

### Fase 2. Seguridad de esfuerzo pequeño (S)

Importa si `DASHBOARD_USER` está activo, porque hoy esa protección es menor de lo que parece. El grave es SEC-01: `/clips`, `/gallery` y `/snapshots` son mounts de `StaticFiles`, y la dependencia global de autenticación no los cubre, aunque el comentario de `backend/main.py:810` afirme lo contrario. Cualquiera en la LAN puede descargar vídeos y recortes de rostros.

| Id | Cambio | Esfuerzo |
|---|---|---|
| SEC-01 | Exigir autenticación en `/clips`, `/gallery`, `/snapshots` y `/docs`, con test de 401 por prefijo | S |
| SEC-03 | Sustituir `innerHTML` con `p.name` en `personGallery.js` por `textContent` (XSS almacenado) | S |
| SEC-06 | Abortar el arranque si hay usuario sin contraseña y avisar si no hay autenticación | S |
| SEC-02 | Reescribir `mask_rtsp_url`, que devuelve la URL intacta si la contraseña contiene `/`, `?` o `#`; codificar en `build_rtsp_url`; no registrar la URL de Telegram | S |
| SEC-07 | Validar `time_range` y plantillas de reglas, y aislar fallos por regla en `match()` | S |
| SEC-11 | Corregir las ACL de `certs/key.pem` en instalaciones existentes, no solo al generarla | S |

Si alguna credencial llegó a un log, hay que rotarla. El barrido no encontró ninguna en el repositorio ni en el historial.

### Fase 3. Datos y procesos en marcha 24/7 (M)

Estos fallos solo se ven con el proceso muchos días encendido, que es justo el uso previsto.

| Id | Problema | Cambio | Esfuerzo |
|---|---|---|---|
| BUG-01 | `_detection_stats_flush_loop` vacía el `EventEngine` global, pero las detecciones van al de cada pipeline: fuga de memoria y `detection_stats` sin datos desde agosto | Recorrer los engines de cada pipeline y probar el cableado | S |
| BUG-02 | `purge_old_events` solo borra `LINE_CROSSED`; el primer purge llega a las 24 h de uptime; `recordings_retention_days` filtra por un `created_at` que el repositorio nunca escribe; galería y `captures` no se purgan | Retención completa, al arrancar y por hora del día, con un `try` por paso | M |
| BUG-09 | Cada 30 s se relanzan subidas de clips que siguen `pending`, y `UPLOADING` no se asigna nunca, así que un clip puede subirse varias veces | Reclamar el clip de forma atómica y recuperar huérfanos al arrancar | S |
| BUG-04 | El broadcast itera `set` vivos con `await` dentro; `_tracks_broadcast_loop` no tiene `try` y puede morir para siempre; las acciones de reglas esperan a los clientes WebSocket | Iterar sobre una copia, timeout por cliente y acciones independientes del broadcast | M |
| BUG-05, BUG-06 | Un worker FAILED no se reintenta ni avisa; el supervisor no para la instancia anterior; `get()` de un slot cerrado puede provocar un bucle activo | Emitir `DEGRADED_MODE`, reintentar con enfriamiento largo y parar antes de reemplazar | M |
| BUG-07 | `_is_in_schedule` no admite horarios que cruzan la medianoche: 22:00 a 06:00 marcaría todo cruce como intrusión | Reutilizar `_time_in_range` y usar reloj monotónico en plazos y debounce | S |

### Fase 3 bis. Algoritmo de detección y tracking (M)

La velocidad no es el problema: YOLO26n tarda unos 37 ms por frame en el i7-9700K, de sobra para los 8 FPS objetivo. El punto débil está después de la red, en cómo se convierten las cajas en tracks y eventos. Los datos de `data/events.db` (8 días con actividad entre agosto y septiembre) lo muestran: de 561 tracks hubo un solo `LINE_CROSSED`; la vida mediana de un track es de 2,3 s, el 86 % dura menos de 3 s y el 19 % menos de 1 s; y en 110 entradas (20 %) el mismo `track_id` «vuelve a entrar» menos de un minuto después de haber salido. Con este volumen no se puede separar qué parte son falsos positivos y qué parte personas de paso, pero son cifras incompatibles con un conteo fiable.

El orden importa. DET-01 y DET-02 son correcciones directas. El resto cambia el comportamiento del conteo y solo debe adoptarse si mejora las métricas del banco de pruebas DET-03, porque hoy no hay forma objetiva de saber si un ajuste ayuda o perjudica.

| Id | Problema | Cambio | Esfuerzo |
|---|---|---|---|
| DET-01 | Nadie fija los hilos. `ultralytics/__init__.py` pone `OMP_NUM_THREADS=1` al importarse y `select_device` lo sube a 7 en la primera inferencia, de modo que el pipeline usa 1,9 núcleos a 8 FPS sin que nadie lo haya decidido | Añadir `inference_threads` con 3 por defecto, aplicado tras la primera inferencia: 42 ms en lugar de 37 ms, y la mitad de CPU | S |
| DET-02 | `process_tracks` emite `PERSON_EXITED` en cuanto un id falta en el frame, pero ByteTrack solo devuelve los tracks emparejados en ese frame. Un fallo breve de detección genera una salida y una entrada falsas, sin esperar a la ventana de pérdida | Declarar la salida al expirar el track, no al faltar. Comprobar si `ZONE_ENTERED`/`ZONE_EXITED` sufren el mismo parpadeo | S–M |
| DET-03 | No hay banco de evaluación: ningún ajuste de detección se puede validar | `scripts/eval_detection.py`, que reproduce clips anotados a mano (10–15, con día, noche e infrarrojos) y mide error de conteo, cambios de id y tracks falsos por hora | M |
| DET-04 | ByteTrack pierde su razón de ser: su segunda fase asocia cajas de confianza entre 0,1 y el umbral de activación, pero `conf=0.45` las descarta dentro de YOLO. Una persona parcialmente tapada pierde el track en vez de conservarlo | Inferir con `conf` en torno a 0,15, pasar `track_activation_threshold=yolo_confidence` a `sv.ByteTrack` y filtrar los objetos por confianza antes de `ObjectTracker`. Coste medido: ninguno (36,4 ms frente a 36,8 ms) | S |
| DET-05 | `minimum_consecutive_frames` queda en 1: una sola caja falsa crea un track y un `PERSON_ENTERED` | Exigir 2 o 3 frames seguidos. Retrasa el evento ese tiempo, pero el id no cambia | S |
| DET-06 | `DetectionsSmoother(length=5)` se mide en frames: son 0,6 s a 8 FPS y 1,7 s a 3 FPS. Además, sigue devolviendo una caja promediada varios frames después de que el track desaparezca, lo que podría explicar parte de los tracks de 2 a 3 s | Limitarlo por tiempo (unos 0,4 s) o usarlo solo en el overlay si el banco confirma que `LineZone` no lo necesita | S |
| DET-07 | La ventana de pérdida es siempre de 2 s (`LOST_TRACK_BUFFER = 60`, fijo). Quien pase 3 s detrás de una columna recibe un id nuevo. `tracker_frame_rate` se muestra en Ajustes, pero `_sync_tracker_frame_rate` lo pisa en el primer frame | Hacerla configurable en segundos y probar 3 a 5 s. Retirar `tracker_frame_rate` | S |
| DET-08 | `AdaptiveRate` no distingue el FPS pedido del real: con una fuente a 15 FPS, 12 FPS exigen 83 ms entre frames y solo se cumple uno de cada dos, es decir 7,5 FPS, mientras ByteTrack cree trabajar a 12 | Sincronizar el tracker con el FPS medido y dar tolerancia en `should_process` | S |
| DET-09 | Se ejecuta YOLO igual con la escena vacía. La mayor parte de un sistema 24/7 es tiempo sin nadie | Puerta de movimiento: si no hay tracks ni cambios en una miniatura de 160×90, bajar a 2 FPS. Nunca a cero, para no perder a alguien quieto. Cuesta 1,4 ms por frame frente a 125 ms de CPU por inferencia | M |
| DET-10 | `.env` usa `stream2` sin `PROCESS_*`, así que cada frame se redimensiona a 1280×720. Si el stream nativo es menor, se amplía para nada y `FaceEngine` recibe imagen interpolada | Consultar `native_resolution` en `/api/v2/cameras/cam1/health` y fijar el tamaño de proceso al nativo. Valorar `stream1` solo para reconocimiento y grabación | S |
| DET-11 | Un cruce en 39 días, con la línea en `y=0.5` | Revisar con imagen real si la línea corta la trayectoria habitual. Las variables `LINE_*` de `.env` ya no se leen: borrarlas | S |
| DET-12 | La RTX 2070 SUPER no se usa porque `torch` es `2.11.0+cpu`; `inference_device=auto` cae a CPU sin avisar | Ver la decisión de GPU más abajo | M |

Medido en este PC con `bus.jpg` a 1280×720 e `imgsz=640`, con la máquina en reposo y sin el resto del pipeline, de modo que sirve para comparar opciones, no como dato de producción:

| Configuración | Latencia p50 | CPU por inferencia | Núcleos a 8 FPS |
|---|---|---|---|
| 7 hilos (lo que ocurre hoy) | 36,7 ms | 238 ms | 1,90 |
| 6 hilos | 37,0 ms | 211 ms | 1,69 |
| 4 hilos | 38,6 ms | 153 ms | 1,22 |
| **3 hilos** | **42,1 ms** | **125 ms** | **1,00** |
| 2 hilos | 50,4 ms | 103 ms | 0,82 |
| ONNX Runtime CPU | 46,1 ms | sin medir | sin medir |

No propongo migrar a ONNX Runtime, que es más lento que PyTorch aquí, ni a OpenVINO, que añade una dependencia para resolver un problema que no existe. Tampoco BoT-SORT o DeepSORT: el proyecto ya tiene ReID, y antes hay que aprovechar ByteTrack, que hoy trabaja a medias. Bajar `imgsz` a 480 ahorra un 30 % (26,6 ms), pero reduce el alcance sobre personas lejanas, y solo se justificaría con datos del banco. El preprocesado nocturno queda como línea de investigación en cuanto haya clips de infrarrojos.

### Fase 4. Activar la grabación con garantías (M)

Aquí va la primera decisión de producto. `request_clip` solo se invoca desde la acción `record`, y `config/rules.yaml` usa únicamente `notify`, de modo que una instalación limpia nunca graba. `STATE.md` y `backend/config.py` dan por hecho que `OBJECT_LEFT` sube clips a Drive, y eso no ocurre.

Hay que corregir primero esta ruta y activarla después, porque nunca ha corrido con datos reales. Por ejemplo, `/api/recordings` daría error 500 con el primer clip, al hacer `isoformat()` sobre un `created_at` nulo (`backend/database.py:322`).

| Id | Cambio | Esfuerzo |
|---|---|---|
| BUG-08 | Escribir a un nombre temporal, renombrar al terminar, registrar errores de persistencia y reconciliar disco y BD al arrancar | M |
| BUG-10 | Conservar la severidad máxima al extender un clip, cerrar el hueco tras el pre-buffer y medir el FPS real con `ffprobe` | M |
| BUG-11 | Duración máxima por clip, umbral de disco que pare la grabación y retención por tamaño | M |
| DIR-02 | Cablear `upload_drive` y `snapshot`, y retirar o implementar las opciones que no hacen nada: `recording_tail_secs`, `alert_on_*`, `pre_secs`, `post_secs`, `url_ref`, zonas `restricted` | M |
| DIR-03 | Tratar el error `auth` de Drive como pausa visible y no lanzar nunca `run_local_server` dentro del worker | M |
| DIR-01 | Sembrar las reglas de grabación acordadas y corregir los textos | S |

### Fase 5. Frontend autónomo y límite de peticiones (M)

Esta fase resuelve la decisión pendiente en `STATE.md`. Sin internet, `new Chart(...)` lanza al evaluar `dashboard-events.js`, que `app.js` importa de forma estática, y con eso muere toda la interfaz, incluido el vídeo. Una aplicación de LAN no debería depender de tres CDN.

| Id | Cambio | Esfuerzo |
|---|---|---|
| DEBT-01, SEC-09 | Copiar Tailwind, Chart.js y las fuentes a `frontend/vendor/`, sin build; crear el gráfico al iniciar; E2E con hosts externos bloqueados; ajustar la CSP | M |
| DIR-04 | Pedir `/api/v2/config` una sola vez, sondear solo la pestaña activa y tratar el 429 con backoff | S |
| SEC-04 | Contar intentos fallidos de autenticación por IP y aplicar el límite por plantilla de ruta, no por URL concreta | M |
| SEC-05, SEC-08 | Validar `Origin` en métodos que cambian estado y limitar el tamaño del cuerpo antes de procesarlo | S |

Migrar métricas y salud al WebSocket v2 queda como paso posterior, solo si el sondeo sigue siendo un problema tras estos cambios.

### Fase 6. Cambios de configuración en caliente (M)

`set_process_size` para la captura y crea otra sin avisar al supervisor. Este ve la instancia parada, la cuenta como caída y llama a `start()` sobre la nueva, que ya está corriendo y no tiene guarda: durante unos segundos dos hilos leen el mismo `VideoCapture`. Tres cambios en 60 s marcan como FAILED una captura que está viva.

| Id | Cambio | Esfuerzo |
|---|---|---|
| BUG-03 | Reinicio explícito desde el supervisor, `start()` idempotente y fachada resuelta desde `CameraManager` | M |
| PERF-01 | Mover a `asyncio.to_thread` `/persons`, la creación y parada de pipelines y la codificación JPEG; paginar `/persons` | S |

### Fase 7. Deuda y documentación (por tandas)

Nada de esto bloquea, y conviene hacerlo aprovechando otros cambios en la misma zona.

| Id | Cambio | Esfuerzo |
|---|---|---|
| DEPS-01 | Declarar `cryptography`, quitar `aiofiles`, `websockets` y `google-auth-httplib2`, separar `requirements-dev.txt` y retirar los restos de dlib | S |
| DOCS-01 | Actualizar el README, que sigue hablando de dlib y de rutas que ya no existen, y añadir `.env.example` | S |
| DX-03 | Dejar de versionar `report/index.html` y reubicar `software_arquitecture.pdf` | S |
| DX-01, SEC-10 | Reparar Docker (`config/`, modelo, compilador, TLS, usuario no root) y construirlo en CI, o retirarlo | M |
| TEST-03, TEST-04 | Ampliar el gate de cobertura a `main.py`, `storage` y `api/v2`, y dar a CI servicios PostgreSQL y Redis y la ruta portable de `bus.jpg` | M |
| DEBT-02 | Borrar las seis rutas v1 sin consumidor y migrar las vivas por grupos | M–L |
| DEBT-03 | Unificar los dos ORM de `Zone` y `Recording`, empezando por mover `get_session_factory` a `backend/storage/` | L |

### Fase 8. Validación con cámara real y dirección del producto

Los checkpoints de `STATE.md` siguen siendo necesarios y tienen más sentido al final, cuando el sistema ya graba y retiene bien. La prueba de resistencia de 8 h debería repetirse tras la Fase 3, porque ahora mediría también las fugas corregidas.

Para después quedan tres opciones que dependen de cómo se use el sistema. La puesta en marcha guiada (DIR-06) convertiría los checkpoints sueltos en una pantalla con mediciones y umbrales sugeridos, y merece la pena solo si se va a recalibrar con frecuencia. El PTZ por cámara (DIR-05) necesita antes un diseño, porque zonas y líneas son coordenadas de imagen y mover la cámara las desalinea sin aviso. El arreglo del atajo de teclado de `dashboard-ptz.js`, que captura flechas y Espacio sobre botones y pestañas, es pequeño y puede hacerse antes.

## Decisiones pendientes

Cada una tiene una opción recomendada para no frenar el trabajo.

| Decisión | Fase | Recomendación |
|---|---|---|
| ¿Qué eventos graban por defecto? | 4 | Intrusión y persona desconocida. `OBJECT_LEFT` no, hasta calibrar `object_person_radius_px` |
| ¿Se retienen igual todos los tipos de evento? | 3 | Sí, 30 días para todos, salvo los que tengan clip asociado, que siguen al clip |
| ¿Qué se hace con el límite de 60/min? | 5 | Mantenerlo, reducir el sondeo y corregir el contador antes de plantearse subirlo |
| ¿Se mantiene Docker? | 7 | Retirarlo salvo que se vaya a usar: hoy el proyecto corre en Windows con el `.venv` |
| ¿Se mantiene `watchdog.py`? | 7 | Retirarlo: nada lo referencia y su `terminate()` impide un apagado limpio |
| ¿Se activa la RTX 2070 SUPER? | 3 bis | No por velocidad: la CPU ya cumple. Sí si el banco DET-03 muestra que un modelo mayor o `imgsz` más alto mejora el conteo, aceptando el consumo de una GPU encendida 24/7 |
| ¿Se adoptan los cambios DET-04 a DET-07 sin banco? | 3 bis | No: primero DET-03, porque alteran el conteo |

## Registro de hallazgos

Las evidencias de la tabla apuntan al commit citado. Confianza: A significa leído en el código; M, señal fuerte pendiente de medir.

| Id | Evidencia principal | Riesgo del arreglo | Confianza |
|---|---|---|---|
| TEST-01 | `pytest.ini:2`, `tests/test_architecture.py` | Medio: aflorarán fallos | A |
| TEST-02 | `.github/workflows/tests.yml:64` | Bajo | A |
| SEC-01 | `backend/main.py:721`, `:803`, `:807`, `:814` | Bajo | A |
| SEC-02 | `backend/config.py:440`, `:446-455`, `backend/notifier.py:48-54` | Bajo | A |
| SEC-03 | `frontend/js/components/personGallery.js:28`, `:33` | Bajo | A |
| SEC-04 | `backend/auth.py:56-61`, `backend/api/v2/deps.py:24-26` | Medio | A |
| SEC-05 | `backend/main.py:737-751` | Medio | M |
| SEC-06 | `backend/auth.py:17-18`, `:55` | Bajo | A |
| SEC-07 | `backend/events/rules.py:28`, `:61`, `backend/events/actions.py:92-95` | Bajo | A |
| SEC-08 | `backend/main.py:1083-1085`, `backend/run.py:42` | Bajo | M |
| SEC-09 | `backend/main.py:744`, `:748`, `frontend/index.html:7` | Medio | A |
| SEC-10 | `Dockerfile:1-19`, `docker-compose.yml:8` | Medio | A |
| SEC-11 | `backend/ssl_utils.py:18-19`, `:92-96` | Bajo | A |
| BUG-01 | `backend/main.py:302`, `:476`, `backend/pipeline/factory.py:92` | Bajo | A |
| BUG-02 | `backend/database.py:273`, `:441`, `backend/main.py:386-416` | Medio: borra datos | A |
| BUG-03 | `backend/pipeline/manager.py:110`, `:418-425`, `backend/pipeline/capture.py:75-81` | Medio | A |
| BUG-04 | `backend/main.py:85-87`, `:100-102`, `:370-380` | Medio | A |
| BUG-05 | `backend/pipeline/supervisor.py:166-173`, `backend/pipeline/detection.py:260-279` | Bajo | A |
| BUG-06 | `backend/pipeline/supervisor.py:181`, `backend/pipeline/broker.py:69-75` | Bajo | A |
| BUG-07 | `backend/main.py:585-592`, `backend/pipeline/recording.py:235`, `:268` | Bajo | A |
| BUG-08 | `backend/pipeline/factory.py:113`, `backend/pipeline/recording.py:243` | Bajo | A |
| BUG-09 | `backend/gdrive.py:134-138`, `backend/storage/repositories.py:571-587` | Bajo | A |
| BUG-10 | `backend/pipeline/recording.py:195-196`, `:282-287`, `backend/pipeline/rate.py:75-76` | Medio | M |
| BUG-11 | `backend/pipeline/recording.py:114-116`, `:282-287` | Bajo | A |
| PERF-01 | `backend/main.py:1052`, `backend/api/v2/cameras.py:198`, `:220` | Bajo | A |
| DIR-01 | `backend/main.py:685`, `config/rules.yaml:23`, `:31` | Medio: disco y cuota de Drive | A |
| DIR-02 | `backend/main.py:694`, `backend/events/actions.py:121`, `backend/events/types.py:35` | Medio | A |
| DIR-03 | `backend/gdrive.py:47`, `:71-87` | Medio | A |
| DIR-04 | `frontend/js/views/camera.js:108`, `:160` | Bajo | A |
| DEBT-01 | `frontend/js/views/dashboard-events.js:56`, `frontend/index.html:7-10` | Bajo | A; sin reproducir en navegador |
| DET-01 | `ultralytics/__init__.py:10-11`, `ultralytics/utils/torch_utils.py:255` | Bajo | A; medido |
| DET-02 | `backend/events/engine.py:117-118`, `backend/tracker.py:96-98` | Medio: cambia cuándo salen los eventos | A; 110 de 561 reentradas |
| DET-04 | `backend/detector.py:107-110`, `backend/tracker.py:30`, `supervision/tracker/byte_tracker/core.py:170-174` | Medio: altera el conteo | A; beneficio sin medir |
| DET-05 | `backend/tracker.py:30`, `supervision/tracker/byte_tracker/core.py:44` | Bajo | A; beneficio sin medir |
| DET-06 | `backend/tracker.py:35`, `supervision/detection/tools/smoother.py:65`, `:89-95` | Medio | M |
| DET-07 | `backend/tracker.py:23`, `:170-173`, `backend/pipeline/detection.py:477-482` | Bajo | A |
| DET-08 | `backend/pipeline/rate.py:26`, `:75` | Bajo | A; calculado, sin medir con cámara |
| DET-09 | `backend/pipeline/detection.py:232-241` | Medio: riesgo de perder a alguien inmóvil | M; ahorro por medir |
| DET-10 | `backend/pipeline/capture.py:149-150`, `backend/config.py:107-108` | Bajo | M: falta la resolución nativa |
| DET-11 | `data/events.db`, tabla `lines` | Bajo | M: depende de la escena |
| DET-12 | `backend/inference/device.py`, `torch 2.11.0+cpu` | Medio | A |

Se revisaron y descartaron como hallazgos el SSRF en webhooks (las reglas no aportan URL), el path traversal en clips, la inyección SQL y la exposición de secretos en `GET /api/v2/config`. Tampoco compensa trocear `config_schema.py`, que es casi todo declaración de datos, ni `repositories.py` fuera de DEBT-03, ni reescribir el historial de git para quitar pesos, ni indexar `recordings` con el volumen previsto.

Esta revisión no cubre CVE de dependencias, porque `pip_audit` no está instalado. Tampoco se ejecutó `docker build`, ni se probó nada con la cámara real o con carga prolongada. En `supervision`, el suavizado libera sus tracks y `LineZone` conserva una entrada mínima por `tracker_id` que nunca borra, un crecimiento despreciable. La frecuencia de las carreras, el hueco tras el pre-buffer y la velocidad de los clips deben medirse antes de darlos por ciertos.