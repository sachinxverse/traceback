"""Embedding backends (Section 9.2) and blob helpers (Section 5.3).

Embeddings are stored as L2-normalised float32 bytes so that cosine similarity
is a plain dot product. A missing embedding is NULL, never a zero vector.
"""
import hashlib
import threading
from typing import Optional

import numpy as np

IMAGE_DIM = 512   # OpenCLIP ViT-B-32
TEXT_DIM = 384    # all-MiniLM-L6-v2


# ---------------------------------------------------------------- blob helpers
def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: Optional[bytes], dim: int) -> Optional[np.ndarray]:
    if blob is None:
        return None
    vec = np.frombuffer(blob, dtype=np.float32)
    if vec.size != dim:
        return None
    return vec


def l2normalise(vec: np.ndarray) -> np.ndarray:
    vec = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm == 0:
        norm = 1.0
    return (vec / norm).astype(np.float32)


# ------------------------------------------------------------------- stub
class StubEmbedder:
    """Deterministic embedder for tests and quick demos: no model downloads.

    Text: hashed bag-of-words into TEXT_DIM dims (token -> md5 mod dim),
    counts, L2-normalised. Similar wording yields high cosine similarity.
    Image: 512-d projection of an 8x8x3 colour histogram (resize to 8x8,
    flatten, repeat/pad to 512, normalise). Identical images score 1.0.
    """

    def embed_text(self, text: str) -> np.ndarray:
        vec = np.zeros(TEXT_DIM, dtype=np.float32)
        tokens = "".join(c.lower() if c.isalnum() else " " for c in text or "").split()
        for token in tokens:
            idx = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % TEXT_DIM
            vec[idx] += 1.0
        return l2normalise(vec)

    def embed_image(self, data: bytes) -> np.ndarray:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB").resize((8, 8))
        arr = np.asarray(img, dtype=np.float32).flatten()  # 8*8*3 = 192
        # repeat to reach 512 dims, then pad with zeros
        vec = np.zeros(IMAGE_DIM, dtype=np.float32)
        reps = IMAGE_DIM // arr.size
        filled = 0
        for _ in range(reps):
            vec[filled:filled + arr.size] = arr
            filled += arr.size
        vec[filled:filled + (IMAGE_DIM - filled)] = arr[:IMAGE_DIM - filled]
        return l2normalise(vec)


# ------------------------------------------------------------------- real
class RealEmbedder:
    """Real model backend: OpenCLIP ViT-B-32 (laion2b_s34b_b79k) for images and
    sentence-transformers/all-MiniLM-L6-v2 for text. Runs on CPU unless CUDA
    is available. Models load lazily on first use."""

    _instance = None

    def __init__(self, clip_model: str, clip_pretrained: str, text_model: str):
        self.clip_model_name = clip_model
        self.clip_pretrained = clip_pretrained
        self.text_model_name = text_model
        self._clip = None
        self._clip_preprocess = None
        self._st = None
        self._lock = threading.Lock()

    @property
    def clip(self):
        with self._lock:
            if self._clip is None:
                import torch
                import open_clip
                device = "cuda" if torch.cuda.is_available() else "cpu"
                model, _, preprocess = open_clip.create_model_and_transforms(
                    self.clip_model_name, pretrained=self.clip_pretrained)
                model = model.to(device).eval()
                self._clip = model
                self._clip_preprocess = preprocess
                self._clip_device = device
            return self._clip

    @property
    def st_model(self):
        with self._lock:
            if self._st is None:
                from sentence_transformers import SentenceTransformer
                self._st = SentenceTransformer(self.text_model_name, device="cpu")
            return self._st

    def embed_text(self, text: str) -> np.ndarray:
        vec = self.st_model.encode(text or "", normalize_embeddings=True)
        return np.asarray(vec, dtype=np.float32)

    def embed_image(self, data: bytes) -> np.ndarray:
        import io
        import torch
        from PIL import Image
        model = self.clip
        img = Image.open(io.BytesIO(data)).convert("RGB")
        tensor = self._clip_preprocess(img).unsqueeze(0).to(self._clip_device)
        with torch.no_grad():
            feats = model.encode_image(tensor)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.squeeze(0).cpu().numpy().astype(np.float32)


# ------------------------------------------------------------ singleton
_embedder = None
_embedder_lock = threading.Lock()


def get_embedder(app=None):
    """Create the embedder lazily as a singleton. Loading models must never
    happen at import time."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                from flask import current_app
                backend = (app.config["EMBEDDING_BACKEND"] if app
                           else current_app.config["EMBEDDING_BACKEND"])
                if backend == "real":
                    cfg = app.config if app else current_app.config
                    _embedder = RealEmbedder(cfg["CLIP_MODEL"], cfg["CLIP_PRETRAINED"],
                                             cfg["TEXT_MODEL"])
                else:
                    _embedder = StubEmbedder()
    return _embedder


def reset_embedder():
    global _embedder
    _embedder = None
