"""Embedding backends (Section 9.2) and blob helpers (Section 5.3).

Embeddings are stored as L2-normalised float32 bytes so that cosine similarity
is a plain dot product. A missing embedding is NULL, never a zero vector.
"""
import hashlib
import threading

import numpy as np

IMAGE_DIM = 512   # OpenCLIP ViT-B-32 (both stub, onnx and real produce this)
TEXT_DIM = 384    # all-MiniLM-L6-v2 (stub, onnx and real all produce this)

# embedding_model identifiers stored next to every vector; matching only
# compares vectors that share the same model id (never mixes spaces)
MODEL_STUB = "stub-bow-v1"        # text+image hashed signatures
MODEL_ONNX = "onnx-minilm-l6-v2+nomic-vision-v15-q:v1"
MODEL_REAL = "openclip-vitb32-laion2b+minilm-l6-v2:v1"


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


# ------------------------------------------------------------------- onnx
class OnnxEmbedder:
    """ONNX Runtime backend (Issue 1): real models without PyTorch.

    Text:  sentence-transformers/all-MiniLM-L6-v2 (384d, ~90 MB fp32 ONNX)
    Image: nomic-ai/nomic-embed-vision-v1.5-Q (768d, quantised, ~100 MB)
    served by fastembed (ONNX Runtime). Measured on Windows (psutil):
    interpreter+text ≈ 200 MB RSS, +image ≈ 250-290 MB — fits a 512 MB
    container with one Gunicorn worker and ~25% headroom; two workers do
    NOT fit, production therefore runs -w 1 --threads 8.

    Text and image models load independently: if the image model cannot be
    loaded (e.g. out of memory), embed_image raises EmbeddingUnavailable and
    the caller falls back to text-only matching instead of crashing.
    """

    _text_model_name = "sentence-transformers/all-MiniLM-L6-v2"
    _image_model_name = "nomic-ai/nomic-embed-vision-v1.5-Q"

    def __init__(self):
        self._text = None
        self._image = None
        self._lock = threading.Lock()

    @property
    def text_model(self):
        with self._lock:
            if self._text is None:
                from fastembed import TextEmbedding
                self._text = TextEmbedding(model_name=self._text_model_name)
            return self._text

    @property
    def image_model(self):
        with self._lock:
            if self._image is None:
                from fastembed import ImageEmbedding
                self._image = ImageEmbedding(model_name=self._image_model_name)
            return self._image

    def embed_text(self, text: str) -> np.ndarray:
        vecs = list(self.text_model.embed([text or ""]))
        return np.asarray(vecs[0], dtype=np.float32)

    def embed_image(self, data: bytes) -> np.ndarray:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(data)).convert("RGB")
        vecs = list(self.image_model.embed([img]))
        return np.asarray(vecs[0], dtype=np.float32)


class EmbeddingUnavailable(RuntimeError):
    """A backend component failed to load (OOM, missing model, ...)."""


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
                elif backend == "onnx":
                    _embedder = OnnxEmbedder()
                else:
                    _embedder = StubEmbedder()
    return _embedder


def backend_model_name(backend: str) -> str:
    """The embedding_model id vectors produced by this backend carry."""
    return {"stub": MODEL_STUB, "onnx": MODEL_ONNX, "real": MODEL_REAL}[backend]


def reset_embedder() -> None:
    global _embedder
    _embedder = None
