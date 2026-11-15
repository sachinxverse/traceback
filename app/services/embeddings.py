"""Embedding backends (Section 9.2) and blob helpers (Section 5.3).

Embeddings are stored as L2-normalised float32 bytes so that cosine similarity
is a plain dot product. A missing embedding is NULL, never a zero vector.
"""
import hashlib
import threading

import numpy as np

IMAGE_DIM = 512   # OpenCLIP ViT-B-32
TEXT_DIM = 384    # all-MiniLM-L6-v2


# ---------------------------------------------------------------- blob helpers
def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes | None, dim: int) -> np.ndarray | None:
    if blob is None:
        return None
    if len(blob) != dim * 4:  # float32
        return None
    return np.frombuffer(blob, dtype=np.float32)


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
    Image: 512-d projection of an 8x8x3 colour block PLUS a strong border
    colour signature (4 one-hot bins per RGB channel) so that items of
    different colour no longer look near-identical (review C2: the bright
    label box used to dominate the cosine). Identical images score 1.0.
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
        arr = np.asarray(img, dtype=np.float32)  # 8x8x3
        raw = (arr.flatten() / 255.0) * 0.5      # 192 dims, muted weight
        # border colour signature: mean of the 4 corner patches -> one-hot
        # bins (4 per channel), strongly weighted so colour drives similarity
        corners = np.concatenate([
            arr[:2, :2].reshape(-1, 3), arr[:2, -2:].reshape(-1, 3),
            arr[-2:, :2].reshape(-1, 3), arr[-2:, -2:].reshape(-1, 3)])
        border = corners.mean(axis=0)
        sig = np.zeros(12, dtype=np.float32)
        for ch in range(3):
            sig[ch * 4 + min(int(border[ch] // 64), 3)] = 2.5
        base = np.concatenate([raw, sig])        # 204 dims
        vec = np.zeros(IMAGE_DIM, dtype=np.float32)
        reps = IMAGE_DIM // base.size
        filled = 0
        for _ in range(reps):
            vec[filled:filled + base.size] = base
            filled += base.size
        vec[filled:filled + (IMAGE_DIM - filled)] = base[:IMAGE_DIM - filled]
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
                import open_clip
                import torch
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


def reset_embedder() -> None:
    global _embedder
    _embedder = None
