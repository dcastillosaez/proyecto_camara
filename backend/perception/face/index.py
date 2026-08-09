"""IdentityIndex — (N, 512) matrix of L2-normalized embeddings, searched by dot product.

SPEC_v2.md §5.4: "Matriz (N, 512) normalizada. Similitud = producto escalar."
For up to ~1000 identities this is faster and simpler than any ANN library
(FAISS/hnswlib) — a single matrix-vector multiply already clears the <5ms
budget. hnswlib is deferred to v2.1, only if identity count exceeds 20,000
(REQUIREMENTS.md backlog) — out of scope here.
"""

from __future__ import annotations

import numpy as np


class IdentityIndex:
    def __init__(self) -> None:
        self._person_ids: list[int] = []
        self._matrix: np.ndarray | None = None  # (N, 512) float32, L2-normalized

    def add(self, person_id: int, emb: np.ndarray) -> None:
        vec = self._normalize(emb).reshape(1, -1)
        self._person_ids.append(person_id)
        self._matrix = vec if self._matrix is None else np.vstack([self._matrix, vec])

    def search(self, emb: np.ndarray, top_k: int = 3) -> list[tuple[int, float]]:
        if self._matrix is None or len(self._person_ids) == 0:
            return []
        query = self._normalize(emb)
        sims = self._matrix @ query  # cosine similarity, both sides already normalized
        k = min(top_k, len(sims))
        top_idx = np.argpartition(-sims, k - 1)[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        return [(self._person_ids[i], float(sims[i])) for i in top_idx]

    def rebuild(self, entries: list[tuple[int, np.ndarray]]) -> None:
        """Replace the index contents wholesale from (person_id, embedding) pairs."""
        self._person_ids = []
        self._matrix = None
        for person_id, emb in entries:
            self.add(person_id, emb)

    @staticmethod
    def _normalize(emb: np.ndarray) -> np.ndarray:
        vec = np.asarray(emb, dtype=np.float32)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec
