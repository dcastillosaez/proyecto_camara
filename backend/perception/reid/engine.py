"""ReIDEngine — embeddings de apariencia con OSNet sobre ONNXRuntime (SPEC_v2.md §5.6).

Thin adapter sobre onnxruntime.InferenceSession, mismo rol que FaceEngine para
insightface: aisla al resto del codebase del modelo concreto y degrada con
available=False si el fichero del modelo falta o tiene el eje de batch fijo,
en vez de lanzar. A diferencia de FaceEngine, aqui onnxruntime es dependencia
dura desde la Fase 23 — lo que degrada es el fichero del modelo descargado
por scripts/fetch_models.py, no el import de la libreria.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)


class ReIDEngine:
    """Embeddings de apariencia 512D con osnet_x0_25 (MSMT17) sobre ONNXRuntime CPU.

    Degrada como FaceEngine: sin modelo, available=False y embed() devuelve None.
    """

    INPUT_HW = (256, 128)                                   # H, W del export ONNX
    # Valores de preprocesado de la implementacion de referencia (boxmot
    # reid/core/preprocessing.py): resize a 128x256 INTER_LINEAR, BGR2RGB,
    # /255, media/desviacion de ImageNet. Usar otra normalizacion no falla,
    # solo degrada la calidad de los embeddings en silencio.
    _MEAN = np.array([0.485, 0.456, 0.406], np.float32).reshape(3, 1, 1)
    _STD = np.array([0.229, 0.224, 0.225], np.float32).reshape(3, 1, 1)

    def __init__(self, model_path: str, intra_op_threads: int = 1) -> None:
        self._available = False
        self._sess = None
        try:
            so = ort.SessionOptions()
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # 1 hilo: el worker comparte CPU con YOLO. Medido en el research de
            # la Fase 25: 12,16 ms p50 con 1 hilo vs 4,97 ms sin limite -- sigue
            # muy por debajo de los 20 ms del criterio 1 y no le roba cores al
            # DetectionWorker.
            so.intra_op_num_threads = intra_op_threads
            so.inter_op_num_threads = intra_op_threads
            self._sess = ort.InferenceSession(
                model_path, sess_options=so, providers=["CPUExecutionProvider"]
            )
            self._in = self._sess.get_inputs()[0].name
            self._out = self._sess.get_outputs()[0].name
            batch_dim = self._sess.get_inputs()[0].shape[0]
            if isinstance(batch_dim, int) and batch_dim != 1:
                # El export publico viene con batch FIJO 16: una inferencia
                # suelta costaria 84,5 ms en vez de 4,97 ms y el criterio 1
                # fallaria por 4x. scripts/fetch_models.py reescribe ese eje;
                # si no se ejecuto, mejor deshabilitar que arrastrar 84 ms.
                logger.error(
                    "ReIDEngine: modelo con batch fijo %s — ejecutar "
                    "scripts/fetch_models.py", batch_dim
                )
                return
            self._available = True
        except Exception:
            logger.exception("ReIDEngine: fallo al cargar %s", model_path)

    @property
    def available(self) -> bool:
        return self._available

    def embed(self, person_crop: np.ndarray | None) -> np.ndarray | None:
        """512D L2-normalizado (float32). None si el motor no esta o el crop es vacio."""
        if not self._available or person_crop is None or person_crop.size == 0:
            return None
        h, w = self.INPUT_HW
        x = cv2.resize(person_crop, (w, h), interpolation=cv2.INTER_LINEAR)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = (np.transpose(x, (2, 0, 1)) - self._MEAN) / self._STD
        try:
            raw = self._sess.run([self._out], {self._in: x[None]})[0][0]
        except Exception:
            logger.exception("ReIDEngine: fallo en la inferencia")
            return None
        # El modelo NO normaliza: norma cruda medida ~52,4. SPEC §5.6 exige 512D
        # normalizado y el coseno de TrackGallery lo da por hecho. float32, no
        # float64: la galeria guarda 2 KB por entrada, no 4 KB.
        return (raw / np.linalg.norm(raw)).astype(np.float32)
