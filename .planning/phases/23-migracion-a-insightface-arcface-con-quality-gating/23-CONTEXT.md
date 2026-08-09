# Phase 23: Migración a InsightFace/ArcFace con quality gating - Context

**Milestone:** v2.0 — Plataforma de Video Analytics
**Spec:** propuesta_mejora/SPEC_v2.md §5.4, ADR-02, Phase 23 (bloque B)
**Requirements:** FACE-01, FACE-02, FACE-03, FACE-04, FACE-05, FACE-06

<domain>
## Phase Boundary

Primera fase del bloque B. Sustituye `face_recognition`/dlib (embeddings 128D) por `insightface`/ArcFace (embeddings 512D) sobre ONNXRuntime CPU, con quality gating explícito y búsqueda de identidad indexada.

**Dentro:** `FaceEngine` (detección + alineación + embedding ArcFace), `FaceQualityAssessor` (tamaño/nitidez/pose con motivo de descarte), `IdentityIndex` (búsqueda por similitud coseno, <5ms sobre 1.000 identidades), reducción de `backend/recognizer.py` a orquestación pura sobre estos tres componentes, `scripts/reenroll.py` para reconstruir identidades desde `data/gallery/`, y la retirada de `dlib`/`face-recognition` de `requirements.txt`.

**Fuera:** `IdentityStateMachine`/`TemporalVoter` (máquina de estados de 4 fases, votación temporal) — eso es la Fase 24 completa, con su propio requisito de "el reconocimiento se dispara por evento, no cada N frames a ciegas". Esta fase mantiene el *calling convention* actual de `PersonRecognizer` (gating por `RECOG_INTERVAL`/`REVERIFY_INTERVAL` en `should_attempt`, voto simple por mayoría en `_votes`) — solo cambia qué corre *dentro* de `process_crop`, no cuándo se llama. `RecognitionWorker` (`backend/pipeline/recognition.py`) no debería necesitar ningún cambio: su única dependencia es la interfaz pública de `PersonRecognizer` (`available`, `process_crop(crop, tracker_id) -> (pid, name, is_new)`, `prune(active_ids)`), que se preserva.

**Criterio dominante:** la tasa de aciertos de ArcFace sobre un set de validación real (≥50 recortes) es igual o mejor que la de dlib con las mismas identidades, documentada — no asumida — en el SUMMARY.
</domain>

<decisions>
## Implementation Decisions

### Puerta de entrada superada — evidencia del spike (2026-08-09)
`pip install insightface>=0.7.3 onnxruntime>=1.19` instala limpio en el entorno Windows del proyecto (Python 3.12.10): wheels precompiladas para ambos paquetes y sus dependencias transitivas (`onnx`, `scikit-image`, `ml_dtypes`, etc.), **sin compilación**. `onnxruntime.get_available_providers()` → `['AzureExecutionProvider', 'CPUExecutionProvider']` (esperado, sin GPU). El modelo `buffalo_s` (~124 MB comprimido) se descargó automáticamente desde `https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip` sin intervención — confirma acceso de red a GitHub releases desde este entorno. `FaceAnalysis(name="buffalo_s").prepare()` + `.get(frame)` ejecutó una inferencia real (detección + landmarks 2D/3D + genderage + reconocimiento, 5 sub-modelos ONNX) sobre un frame en blanco en 63 ms, devolviendo 0 caras (comportamiento correcto, no un fallo). El modelo de reconocimiento (`w600k_mbf.onnx`, variante MobileFaceNet de `buffalo_s`) confirma vía introspección de `onnxruntime.InferenceSession` una salida `[1, 512]` — exactamente el embedding 512D que exige FACE-01.

**Conclusión: Plan A de ADR-02 (paquete `insightface` completo) es viable. No se activa el Plan B (ONNX puro con `w600k_r50.onnx` sin el paquete `insightface`).**

### FaceEngine envuelve InsightFace, no lo sustituye
`insightface.app.FaceAnalysis` ya implementa detección (SCRFD), landmarks y embedding en una sola llamada `.get(frame)` que devuelve objetos `Face` con `.bbox`, `.kps`, `.det_score`, `.embedding`, `.normed_embedding`. `FaceEngine.detect()`/`.embed()` de la SPEC son una capa fina sobre esto — no hay que reimplementar SCRFD ni la alineación por landmarks, `insightface` ya la hace internamente antes de generar el embedding. El trabajo real de `FaceEngine` es adaptar el formato de salida a `FaceCandidate`/`FaceQuality` de la SPEC y aislar el resto del código de la API de `insightface` (mismo patrón que `PersonDetector` aísla a `ultralytics`).

### El modelo se descarga en caliente, no se versiona en el repo
`insightface` gestiona su propio caché en `~/.insightface/models/` (fuera del repo, ~281 MB con `buffalo_s` + sus 5 sub-modelos). No hay que añadir el `.onnx` a git ni a `.gitignore` explícitamente — ya vive fuera del árbol del proyecto. `scripts/fetch_models.py` (mencionado en la SPEC) es principalmente documentación/verificación de que el modelo esperado está disponible antes de arrancar en producción, no un paso de empaquetado.

### Migración de embeddings: no hay conversión 128D→512D posible
Los embeddings dlib (128D) y ArcFace (512D) no son compatibles matemáticamente — no existe una transformación que preserve similitud entre ambos espacios. La única vía es **re-enrolar**: `scripts/reenroll.py` recorre `data/gallery/{person_id}/*.jpg` (las capturas automáticas que ya se guardan desde la Fase 9), ejecuta `FaceEngine` sobre cada imagen, y reconstruye `persons`/`face_encodings` desde cero con los nuevos embeddings 512D. Antes de tocar la tabla, se respalda `data/persons.db` (mismo patrón que `scripts/migrate_embeddings.py` de la Fase 22 — backup con timestamp en `data/backups/`). Identidades sin ninguna imagen en `data/gallery/` (nunca se activó `on_identified`, o llevan `persons_retention_days` fuera de ventana) no se pueden migrar — el script debe reportarlas explícitamente como "no migradas", nunca fallar en silencio ni inventar un embedding.

### Umbrales de calidad y de match: los de la SPEC, no los de dlib
La SPEC fija valores por defecto explícitos (`face_min_size_px=60`, `face_max_blur=100.0`, `face_max_yaw_deg=40`, `face_match_threshold=0.45`, `face_confirm_threshold=0.55`) — no son los mismos números que `PersonRecognizer.MIN_FACE_SIZE=60`/`BLUR_THRESHOLD=60.0`/`TOLERANCE=0.55` actuales (misma familia de idea, distinta métrica: distancia euclídea de dlib vs. similitud coseno de ArcFace, no son comparables directamente). Se usan los valores de la SPEC como default, configurables vía `Settings` siguiendo el patrón ya establecido (`yolo_confidence`, `detection_target_fps`, etc.).

### Claude's Discretion
- Si `FaceQualityAssessor.assess()` calcula yaw/pitch/roll a partir de los 5 landmarks de InsightFace (geometría simple) o si se usa alguna utilidad de la propia librería — la SPEC no especifica el método, solo el contrato de salida.
- Formato exacto del reporte de `scripts/reenroll.py` (migradas vs. no migradas) — mismo espíritu que `scripts/migrate_embeddings.py`.
- Si `IdentityIndex` normaliza los embeddings al añadirlos (`add`) o exige que ya lleguen L2-normalizados desde `FaceEngine.embed()` — cualquiera es válido si el contrato queda documentado y testeado.
</decisions>

<canonical_refs>
## Canonical References

### Especificación
- `propuesta_mejora/SPEC_v2.md` §5.4 (contratos exactos de `FaceCandidate`, `FaceQuality`, `FaceQualityAssessor`, `FaceEngine`, `IdentityIndex`, tabla de umbrales por defecto)
- `propuesta_mejora/SPEC_v2.md` ADR-02 (decisión InsightFace/ArcFace, riesgo de instalación en Windows y plan B)
- `propuesta_mejora/SPEC_v2.md` Phase 23 (líneas ~935-960: goal, puerta de entrada, success criteria, ficheros, riesgos)
- `propuesta_mejora/SPEC_v2.md` §5.5 (máquina de estados — **fuera de esta fase**, referencia para no invadir su alcance)

### Código existente que se toca
- `backend/recognizer.py` — módulo completo (544 líneas); queda reducido a orquestación: `should_attempt`/gating se mantiene, `process_crop`/`identify_or_register`/`enroll_named_face` pasan a delegar en `FaceEngine`+`FaceQualityAssessor`+`IdentityIndex` en vez de llamar a `face_recognition` directamente
- `backend/pipeline/recognition.py` — **no debería necesitar cambios**: solo consume la interfaz pública de `PersonRecognizer`
- `backend/main.py:382-397` (`_save_gallery_capture`) — fuente de las imágenes que `scripts/reenroll.py` reconstruye
- `backend/config.py` — añadir settings de umbrales (`face_min_size_px`, `face_max_blur`, `face_max_yaw_deg`, `face_match_threshold`, `face_confirm_threshold`)
- `requirements.txt` — añadir `insightface>=0.7.3`, `onnxruntime>=1.19`; retirar `face-recognition` (FACE-06, solo al final, tras verificar que el re-enrolamiento funcionó)

### Planificación
- `.planning/ROADMAP.md` § Phase 23 (goal, depends_on: Phase 22, requirements FACE-01..06, success criteria, plans placeholder)
- `.planning/REQUIREMENTS.md` § FACE-01..06
- `.planning/STATE.md` — nota "Puerta bloqueante en la Fase 23" y "Migración de embeddings: ArcFace 512D no es compatible con dlib 128D — exige re-enrolamiento desde data/gallery/"
- `.planning/phases/22-seguridad-y-gestion-de-memoria/22-01-SUMMARY.md` — recomendación de entrada al bloque B, mismo spike documentado ahí de forma resumida
</canonical_refs>

<specifics>
## Specific Ideas

- El objeto `Face` que devuelve `insightface.app.FaceAnalysis.get()` ya trae `.normed_embedding` (L2-normalizado) además de `.embedding` (crudo) — `FaceEngine.embed()` debería devolver el normalizado directamente, evitando que cada consumidor tenga que normalizar por su cuenta.
- `IdentityIndex` como "matriz (N, 512) normalizada, similitud = producto escalar" es literalmente `numpy.dot(matrix, query)` una vez que todo está L2-normalizado — no hace falta ninguna librería de ANN (FAISS, hnswlib) para 1.000 identidades; una multiplicación matriz-vector en numpy ya cumple el objetivo de <5ms sin dependencia nueva. `hnswlib` está explícitamente en el backlog v2.1 "solo si el número de identidades supera 20.000" (REQUIREMENTS.md, fuera de alcance).
- El benchmark del criterio 5 (tasa de aciertos ArcFace vs. dlib sobre ≥50 recortes reales) necesita datos reales del propio proyecto — este worktree aislado no tiene `data/gallery/` poblada (sin cámara real conectada en ninguna sesión hasta ahora). Es, en la práctica, otro checkpoint que depende de haber corrido el sistema con la cámara real el tiempo suficiente para acumular capturas de al menos unas pocas personas — probablemente necesite ejecutarse junto con (o después de) los checkpoints pendientes del bloque A.
- `data/backups/` ya existe como convención (usado por `scripts/migrate_embeddings.py`, Fase 22) — reutilizar el mismo directorio y esquema de nombre (`persons-YYYYMMDD-HHMMSS.db`) para el backup pre-reenrolamiento.
</specifics>

<deferred>
## Deferred Ideas

- `IdentityStateMachine`, `TemporalVoter`, disparo de reconocimiento por evento en vez de por intervalo → Fase 24 completa.
- ReID (OSNet, continuidad sin cara visible) → Fase 25.
- Aceleración GPU para ONNXRuntime → Fase 38 (bloque D, opcional), y de todas formas `CPUExecutionProvider` ya es el objetivo explícito de ADR-02.
- Índice ANN (FAISS/hnswlib) para >20.000 identidades → backlog v2.1.

---
*Context creado: 2026-08-09*
