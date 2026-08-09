---
phase: 23-migracion-a-insightface-arcface-con-quality-gating
plan: 01
subsystem: perception
tags: [insightface, arcface, buffalo_s, onnxruntime, face-quality, identity-index]
requires: ["22-01"]
provides:
  - backend/perception/face/engine.py: FaceEngine (detect/embed sobre buffalo_s)
  - backend/perception/face/quality.py: FaceQualityAssessor (gates con motivo)
  - backend/perception/face/index.py: IdentityIndex (búsqueda coseno <5ms)
affects:
  - backend/config.py (face_min_size_px/face_max_blur/face_max_yaw_deg/face_match_threshold/face_confirm_threshold)
  - requirements.txt (insightface, onnxruntime, scikit-image añadidos; face-recognition pendiente de retirar en 23-02)
tech-stack:
  added: ["insightface>=0.7.3", "onnxruntime>=1.19", "scikit-image>=0.24"]
  patterns:
    - "FaceEngine.embed() llama al submodelo de reconocimiento directamente (rec.get(frame, face_like)) en vez de re-ejecutar deteccion completa — verificado bit-a-bit idéntico al pipeline completo"
    - "FaceAnalysis(allowed_modules=['detection','recognition']) evita cargar/ejecutar landmarks 3D/2D-106 y genderage que este proyecto no usa — 10-20x mas rapido, mismo bbox/kps/embedding"
    - "IdentityIndex es numpy.dot puro (matriz (N,512) L2-normalizada + argpartition), sin FAISS/hnswlib — suficiente hasta 20.000 identidades (backlog v2.1)"
    - "Tests con inferencia real usan skimage.data.astronaut() (NASA, dominio público) obtenida en tiempo de test, nunca guardada como asset del repo ni generada por IA"
key-files:
  created:
    - backend/perception/__init__.py
    - backend/perception/face/__init__.py
    - backend/perception/face/engine.py
    - backend/perception/face/quality.py
    - backend/perception/face/index.py
    - tests/test_face_engine.py
    - tests/test_face_quality.py
    - tests/test_identity_index.py
  modified:
    - backend/config.py
    - requirements.txt
key-decisions:
  - "Puerta de entrada de ADR-02 superada con evidencia real (no solo 'pip install' — una inferencia genuina con buffalo_s, 5 submodelos ONNX, embedding 512D confirmado por introspección). Plan A (paquete insightface completo) es la vía; Plan B (ONNX puro con w600k_r50.onnx) no se activa."
  - "FaceAnalysis se restringe a allowed_modules=['detection','recognition'] tras medir que los 5 submodelos por defecto de buffalo_s cuestan ~300ms/llamada en este CPU cuando este proyecto solo necesita bbox+5kps+embedding — la restricción da 15-40ms/llamada (10-20x) sin cambiar ningún valor de salida (bbox/kps/det_score/embedding verificados idénticos antes y después)."
  - "yaw/pitch/roll se estiman geométricamente desde los 5 landmarks (deriva de la nariz respecto al centro ojos/boca), no con un modelo de pose dedicado — la SPEC deja el método a discreción, solo fija el contrato de salida. Solo yaw gatea el rechazo ('extreme_pose'), pitch/roll quedan como datos informativos, siguiendo la redacción literal del criterio de éxito de la fase."
requirements-completed: [FACE-01 (parcial — motor construido, integración en recognizer.py pendiente de 23-02), FACE-02, FACE-03, FACE-04]
duration: "~2h (ejecución autónoma en worktree aislado, continuación tras cierre del bloque A en la misma sesión)"
completed: "2026-08-09"
---

# Phase 23 Plan 01: FaceEngine, FaceQualityAssessor, IdentityIndex — Summary

Los tres componentes nuevos de percepción facial (SPEC_v2.md §5.4) construidos y verificados de forma aislada, sin tocar todavía `backend/recognizer.py`. La puerta de entrada bloqueante de la fase (ADR-02: `insightface`+`onnxruntime` instalando y ejecutando una inferencia real en Windows) se resolvió primero, con evidencia concreta documentada en `23-CONTEXT.md`. Un hallazgo de rendimiento no previsto en el plan (restringir `allowed_modules` da 10-20x de mejora) se aplicó y verificó antes de cerrar el plan. Suite completa: **325/325**.

## Qué se construyó

**Puerta de entrada (antes de Task 1)**: `pip install insightface onnxruntime` instala sin compilar en Windows (wheels precompiladas). El modelo `buffalo_s` se descarga automáticamente desde el release oficial de GitHub (~124 MB) y ejecuta una inferencia real — confirmado con introspección directa de `onnxruntime.InferenceSession` que el modelo de reconocimiento (`w600k_mbf.onnx`) produce una salida `[1, 512]`, exactamente el embedding que exige FACE-01.

**Task 1 — FaceEngine**: envuelve `insightface.app.FaceAnalysis` sin reimplementar detección/alineación (ya las hace internamente). `detect()` adapta el objeto `Face` de insightface a `FaceCandidate`. `embed()` llama al submodelo de reconocimiento directamente (`rec.get(frame, face_like)` con `cand.kps`) en vez de re-ejecutar la detección completa — verificado que produce un resultado bit-a-bit idéntico al que da el pipeline completo, a una fracción del coste. Degradación elegante si `insightface` no está disponible o el modelo falla al cargar. 5/5 tests, usando `skimage.data.astronaut()` (foto de Eileen Collins, NASA Great Images, dominio público, dependencia transitiva ya instalada) como única fixture de cara real — obtenida en tiempo de test, nunca guardada en el repo, y ningún rostro sintético/generado por IA se usa para validar un detector entrenado con rostros reales.

**Task 2 — FaceQualityAssessor**: gatea tamaño/nitidez/pose con motivo explícito (`too_small`/`blurry`/`extreme_pose`/`None`). yaw/pitch/roll se estiman geométricamente desde los 5 landmarks (sin modelo de pose dedicado — decisión discrecional documentada). Umbrales (`face_min_size_px=60`, `face_max_blur=100.0`, `face_max_yaw_deg=40.0`) añadidos a `Settings`, distintos de los que usaba dlib (métricas no comparables entre sí). 5/5 tests sobre imágenes sintéticas (ruido + blur gaussiano) y landmarks construidos a mano.

**Task 3 — IdentityIndex**: matriz `(N, 512)` L2-normalizada, búsqueda por producto escalar puro (`numpy.dot`), sin FAISS/hnswlib — innecesario hasta 20.000 identidades. `argpartition` en vez de sort completo para el top-k. 5/5 tests, incluido el benchmark: p95 de 100 búsquedas repetidas sobre 1.000 identidades sintéticas, muy por debajo del presupuesto de 5ms.

**Task 4 — Verificación cruzada + hallazgo de rendimiento**: la cadena completa (`detect→assess→embed→index`) verificada con la imagen real de Task 1 — detecta, pasa la gate de calidad, se encuentra a sí misma en el índice con similitud 1.0. Al medir la latencia se encontró que `detect()` costaba ~250-370ms por llamada incluso en caliente: `buffalo_s` carga 5 submodelos por defecto (detección, landmarks 3D, landmarks 2D-106, genderage, reconocimiento) y este proyecto solo necesita detección+reconocimiento. `FaceAnalysis(allowed_modules=["detection", "recognition"])` evita cargar/ejecutar los 3 submodelos no usados — verificado que `bbox`/`kps`/`det_score`/`embedding` quedan idénticos antes y después del cambio — y baja la latencia a ~15-40ms por llamada (10-20x). La cadena completa queda muy por debajo del presupuesto de `recognition_target_fps=2` (500ms), con margen amplio para la Fase 24 (que además dispara el reconocimiento por evento, no por intervalo fijo).

## Deviations from Plan

**[Rule 3 - Mejora, no prevista en el plan] Restricción de `allowed_modules`**
El plan (Task 4) pedía "medir el tiempo total de la cadena... esto informa si recognition_target_fps=2 sigue siendo razonable" — una medición, no necesariamente un cambio de código. Al medir se encontró un margen de optimización real y de bajo riesgo (parámetro documentado de la propia librería, sin tocar lógica propia), así que se aplicó en el momento en vez de solo anotarlo para después — coherente con el resto de la sesión (fixes encontrados durante verificación se corrigen de inmediato, no se difieren). Commit `b489377`.

**[Rule 4 - Discrecional, cubierto por 23-CONTEXT.md] Método de estimación de pose**
`23-CONTEXT.md` deja explícitamente a discreción "si FaceQualityAssessor.assess() calcula yaw/pitch/roll... o si se usa alguna utilidad de la propia librería". Se implementó una aproximación geométrica simple sobre los 5 landmarks (no un estimador de pose dedicado), documentada como tal en el docstring del módulo. Commit `031724f`.

**Total deviations:** 2, ambas Rule 3/4 (mejora encontrada durante verificación, decisión discrecional ya cubierta por el CONTEXT.md). **Impacto:** ninguno negativo — la mejora de rendimiento reduce riesgo para 23-02, no lo aumenta.

## Issues Encountered

Ninguno bloqueante. El único hallazgo (latencia de `detect()` con los 5 submodelos por defecto) se resolvió en el propio plan, ver arriba.

## Next Phase Readiness

Verificado con inferencia real (no mocks) en cada uno de los 3 componentes, más la cadena completa en Task 4. Suite completa: **325/325**. `backend/recognizer.py` **todavía no se ha tocado** — sigue funcionando exactamente igual que antes de esta fase (sobre `face_recognition`/dlib), por lo que el pipeline en producción no tiene ningún cambio de comportamiento todavía. Eso es exactamente lo que buscaba este plan: verificar el motor nuevo de forma aislada antes de arriesgar el camino de ejecución en vivo.

**Listo para 23-02**: integración en `backend/recognizer.py` (reducción a orquestación pura sobre estos tres componentes, preservando el contrato público que consume `RecognitionWorker`), `scripts/reenroll.py`, y retirada de `dlib`/`face-recognition`. El Task 4 de 23-02 (benchmark real ArcFace vs dlib) sigue siendo un checkpoint que requiere cámara real y `data/gallery/` poblada — no ejecutable en este worktree aislado, igual que los 4 checkpoints pendientes del bloque A.
