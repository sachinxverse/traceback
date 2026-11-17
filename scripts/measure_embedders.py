# Measure candidate embedding backends (Issue 1).
# Usage: .venv/Scripts/python.exe scripts/measure_embedders.py --backend stub|onnx|real [--n 5]
"""Reports, for one embedding backend: cold-start load time, peak RSS,
time per text, time per image, and embedding dimension. Results are meant
to be pasted into docs/EMBEDDING_BENCHMARK.md. Run with --n 20 for stable
per-call numbers."""
import argparse
import io
import json
import sys
import time

# psutil is a runtime dependency of this measurement script only.
import psutil

sys.path.insert(0, ".")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

SPECS = {
    "stub": {"models": "none (pure Python hashing)", "install": "~0 (in requirements.txt already)"},
    "onnx": {
        "models": "sentence-transformers/all-MiniLM-L6-v2 (text, 384d) + "
                  "nomic-ai/nomic-embed-vision-v1.5-Q (image, 768d, quantised), "
                  "via fastembed/ONNX Runtime",
        "install": "fastembed 0.9.1 (~35 MB package + ~190 MB model weights on first load)"},
    "real": {
        "models": "open_clip ViT-B-32/laion2b_s34b_b79k (image, 512d) + "
                  "sentence-transformers/all-MiniLM-L6-v2 (text, 384d), PyTorch CPU",
        "install": "torch CPU ~200 MB + open_clip_torch + sentence-transformers + ~350 MB weights"},
}


def make_test_image() -> bytes:
    img = Image.new("RGB", (320, 240))
    for x in range(320):
        for y in range(240):
            if (x // 40 + y // 40) % 2 == 0:
                img.putpixel((x, y), (30, 90, 200))
            else:
                img.putpixel((x, y), (240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def build(backend: str):
    if backend == "stub":
        from app.services.embeddings import StubEmbedder
        return StubEmbedder()
    if backend == "onnx":
        from app.services.embeddings import OnnxEmbedder
        return OnnxEmbedder()
    if backend == "real":
        from app.services.embeddings import RealEmbedder
        return RealEmbedder("ViT-B-32", "laion2b_s34b_b79k", "all-MiniLM-L6-v2")
    raise SystemExit(f"unknown backend {backend}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=list(SPECS))
    ap.add_argument("--n", type=int, default=5, help="calls per timing sample")
    args = ap.parse_args()

    proc = psutil.Process()
    text = ("Lost blue iPhone 13 near the main gate of the railway station, "
            "black cover, cracked screen at the corner, last seen around 6 pm")
    img_bytes = make_test_image()

    result = {"backend": args.backend, "n_per_sample": args.n, **SPECS[args.backend]}

    t0 = time.perf_counter()
    emb = build(args.backend)
    _ = emb.embed_text(text)
    load_s = time.perf_counter() - t0
    result["cold_start_load_s"] = round(load_s, 3)
    result["rss_after_load_mb"] = round(proc.memory_info().rss / 1e6, 1)

    # warm up caches, then time per call
    emb.embed_text(text)
    emb.embed_image(img_bytes)

    t0 = time.perf_counter()
    for _ in range(args.n):
        emb.embed_text(text)
    result["ms_per_text"] = round((time.perf_counter() - t0) * 1000 / args.n, 2)

    t0 = time.perf_counter()
    for _ in range(args.n):
        emb.embed_image(img_bytes)
    result["ms_per_image"] = round((time.perf_counter() - t0) * 1000 / args.n, 2)

    result["rss_peak_mb"] = round(psutil.Process().memory_info().rss / 1e6, 1)
    result["text_dim"] = len(emb.embed_text(text))
    result["image_dim"] = len(emb.embed_image(img_bytes))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
