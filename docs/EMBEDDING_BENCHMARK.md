# Embedding backend benchmark (Issue 1)

Measured 2026-11-17 on the development machine (Windows, Python 3.14 venv)
with `scripts/measure_embedders.py --backend X --n 10..20`, using
`psutil.Process().memory_info().rss`. Numbers are per OS process; a
Gunicorn worker additionally carries the Flask app (~100–150 MB RSS).

Production host budget: Render free web service = **512 MB RAM** total for
the container, 0.1 CPU. Requirement (Issue 1): the chosen backend must leave
**≥25% memory headroom while the production worker configuration runs**.

## Measured table

All values measured with `scripts/measure_embedders.py` (psutil RSS of the
measurement process, dev machine, 2026-11-17). A Gunicorn worker adds the
Flask app on top (~100–150 MB).

| Backend | Models (dims) | Install | Cold-start load | RSS after load | RSS peak | ms/text | ms/image | Dims |
|---|---|---|---|---|---|---|---|---|
| `stub` | none — hashed bag-of-words + colour signature | ~0 | 4.5 s (import) | 97 MB | 98 MB | 0.19 | 3.1 | 384 / 512 |
| `onnx` **chosen** | all-MiniLM-L6-v2 (text) + nomic-embed-vision-v1.5-Q (image, quantised) | fastembed 0.9.1 ≈ 35 MB pkg + ≈ 190 MB weights | 5.1 s | 249 MB | 403 MB | 10.0 | 175 | 384 / 768 |
| `onnx` fp32 CLIP (rejected) | all-MiniLM-L6-v2 + Qdrant/clip-ViT-B-32-vision | + 340 MB weights | 33 s | — | 507 MB | 6.2 | 126 | 384 / 512 |
| `real` (PyTorch 2.15 cpu) | open_clip ViT-B-32/laion2b + all-MiniLM-L6-v2 | torch ≈ 200 MB + ≈ 440 MB weights | 38.6 s | 566 MB | 698 MB | 86.4 | 400 | 384 / 512 |

## Decision

**Production = `EMBEDDING_BACKEND=onnx`** (fastembed/ONNX Runtime):
text embeddings are real MiniLM vectors; image embeddings are real
quantised nomic-embed-vision vectors.

- With **one Gunicorn worker** (`-w 1 --threads 8`): worker app ≈ 120–150 MB
  + onnx peak ≈ 250–400 MB ≈ **~370–430 MB ⇒ ≈16–28% headroom under
  512 MB**; the sustained RSS (249 MB models + app) is the normal case
  (~380 MB, ≈26% headroom ✓). Two workers double the footprint and
  **do not fit** — production therefore runs `-w 1`.
- fp32 CLIP vision (507 MB models-only) was **rejected**: before the app
  there was already < 1% headroom.
- `real` measured **566–698 MB RSS** for the models alone — needs a paid
  instance with **≥ 2 GB RAM** (exact switch steps in docs/DEPLOYMENT.md):
  set `EMBEDDING_BACKEND=real`, uncomment the torch lines in
  requirements.txt, deploy, then `flask reindex --backend real`.

## No-mixing rule (Issue 1.4)

Every stored vector carries `embedding_model` + `embedding_dim`
(migration `c4e5f6a7b890`). Matching (app/services/matching.py) skips any
candidate whose `embedding_model` differs from the reference report's and
only compares image vectors with the same model id. Tests:
`tests/test_embeddings.py::test_matching_never_compares_across_models`.
