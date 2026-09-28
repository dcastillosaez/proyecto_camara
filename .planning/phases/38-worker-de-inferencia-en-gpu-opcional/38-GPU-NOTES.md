# Fase 38 — Notas de cierre: GPU, batching y el criterio 3

Esta fase deja el pipeline preparado para usar una GPU cuando exista, sin tocar la ruta
CPU. Tres de los seis criterios del ROADMAP necesitan una explicación aparte, porque se
cierran con una decisión de alcance o con un instrumento y no con código ni con una cifra.
Aquí quedan las tres.

## Criterio 1 — DirectML queda fuera de alcance

El criterio habla de "CUDA / DirectML", pero solo se ha implementado CUDA con fallback a
CPU. Fue una decisión del usuario, recogida en `38-CONTEXT.md`: DirectML no se puede
verificar en esta máquina y duplicaría la matriz de pruebas sin que ninguna de las
combinaciones nuevas fuera comprobable.

El selector está pensado para que eso cambie sin dolor. Añadir DirectML mañana consiste en
meter una entrada nueva en el dict `ONNX_PROVIDERS` de `backend/inference/device.py`
(`("DmlExecutionProvider", "CPUExecutionProvider")`) y escribir su sonda al lado de
`_ort_cuda_available()`. La lógica de `resolve_device()` y el cableado a los motores no se
tocan.

## Criterio 3 — el ≥3× queda PENDIENTE, con el instrumento listo

No hay cifra, y no la hay a propósito. El `.venv` tiene `torch 2.11.0+cpu` y un
`onnxruntime 1.28.0` compilado para CPU, cuyos providers disponibles son
`['AzureExecutionProvider', 'CPUExecutionProvider']`. El usuario decidió que esta fase no
tocara `requirements.txt` ni el entorno, así que no hay nada acelerado que medir.

Lo que sí queda es el instrumento. `tests/test_inference_benchmark.py` construye un
detector en CPU y otro en CUDA, mide el p50 de ambos intercalando las muestras y exige un
cociente de al menos 3. Sin CUDA se salta solo, con un mensaje que apunta a este fichero, y
un segundo test comprueba que ese salto ocurre antes de cargar ningún modelo.

### Checklist para el día que se instale el stack GPU

1. Comprobar primero que CUDA 13 mantiene el soporte de Turing (SM 7.5), porque la GPU es
   una RTX 2070 SUPER. Si no lo mantiene, fijar `onnxruntime-gpu <= 1.26`, que va sobre
   CUDA 12.8.
2. Decidir entre un `requirements-gpu.txt` aparte o el `.venv` principal. En ningún caso
   instalar `onnxruntime` y `onnxruntime-gpu` en el mismo entorno: se pisan entre sí.
3. Ejecutar `.venv/Scripts/python.exe -m pytest tests/ -q -m perf -s` y anotar en este
   fichero el p50 de CPU, el p50 de CUDA y el cociente.
4. Revalidar el fallback con el CUDA EP presente de verdad. Es el único caso que hoy no se
   puede probar: todos los tests del fallback usan dobles (`38-RESEARCH.md`, sección
   "Válido hasta").
5. Medir el consumo de VRAM con N cámaras antes de fijar cualquier techo. Cada pipeline
   carga su propio YOLO, así que la VRAM crece con el número de cámaras.

## Criterio 6 — batching multi-cámara: NO se implementa

El criterio pide que el batching sea opcional y desactivable. Tras el research la
conclusión fue no escribirlo, por cinco razones:

1. Broker, hilo y modelo son por cámara por diseño explícito de la Fase 36. Lo dice el
   docstring de `backend/pipeline/factory.py`: cada cámara recibe su propio
   `detector`/`tracker` y nunca se comparte un modelo YOLO entre pipelines. Batchear exige
   justo lo contrario, un modelo compartido alimentado por un colector que lea de N
   brokers. Eso es rediseñar el punto más delicado del pipeline, no añadir una opción.
2. Rompe el invariante 2 de `CLAUDE.md`, "cada worker consume del broker a su ritmo".
   Esperar a que N cámaras tengan frame ata la latencia de cada una a la de la más lenta,
   y cerrar el lote por timeout mete un temporizador nuevo en la ruta caliente.
3. Cada cámara tiene su propio `AdaptiveRate` con sus escalones
   (`backend/pipeline/rate.py:26`, `STEPS = (12.0, 8.0, 5.0, 3.0)`) y, desde la Fase 36,
   un techo externo por reparto de CPU. Dos cámaras a 12 y a 3 FPS no forman lotes.
4. Hoy hay una sola cámara, así que el lote sería de tamaño 1: el código actual con una
   capa de indirección encima. Y con varias, YOLO26n a 640 px en una 2070 SUPER no satura
   la GPU a 8 FPS por cámara. El cuello estaría en la decodificación RTSP y en el pre y
   post-proceso, que el batching no toca.
5. Ya figuraba como diferible en `38-CONTEXT.md`, sección Deferred Ideas.

### Condición de reapertura

Más de 3 cámaras simultáneas **y** una utilización de GPU medida por encima del 70 %.
Mientras no se cumplan las dos cosas a la vez, el batching sigue descartado.

## Cómo queda cubierto el criterio 6

Con esta decisión, el estado por defecto y único del batching es "desactivado", con la
justificación y la condición de reapertura por escrito. No queda código muerto que
mantener ni un flag que nadie va a activar.

## Qué queda observable hoy

Tres cosas. La clave `devices` de `GET /api/v2/cameras/{id}/health`, con el modo pedido y
el dispositivo efectivo de `yolo`, `reid` y `face`. Una línea de log por motor en el
arranque (`Motor yolo en cpu`, `Motor reid en cpu`, `Motor face en cpu`), precedida por la
decisión del selector. Y el evento `DEGRADED_MODE` con el motivo real cuando el
dispositivo efectivo no coincide con el pedido, emitido una sola vez por motor y proceso.
