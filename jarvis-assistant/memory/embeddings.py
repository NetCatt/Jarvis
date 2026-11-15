import os

import numpy as np

_MODEL = None


def _get_model():
    """Lazy-loaded static embedding model (NumPy-only inference, no torch/onnxruntime)."""
    global _MODEL
    if _MODEL is None:
        from model2vec import StaticModel

        _MODEL = StaticModel.from_pretrained(os.getenv("EMBEDDING_MODEL", "minishlab/potion-base-8M"))
    return _MODEL


def embed(text: str) -> np.ndarray:
    model = _get_model()
    vec = model.encode([text])[0]
    return np.asarray(vec, dtype=np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-8
    return float(np.dot(a, b) / denom)
