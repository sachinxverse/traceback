"""Health endpoint and geocode proxy."""
from flask import Blueprint, current_app, jsonify, request

from ..extensions import db
from sqlalchemy import text

health_bp = Blueprint("health", __name__, url_prefix="")


@health_bp.get("/health")
def health():
    db_ok = True
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    backend = current_app.config.get("EMBEDDING_BACKEND", "stub")
    status = "ok" if db_ok else "degraded"
    return jsonify({"status": status, "db": "ok" if db_ok else "error",
                    "embedding_backend": backend})


@health_bp.get("/geocode")
def geocode():
    """Nominatim search proxy with simple 1 req/sec in-memory cache/limit."""
    import time

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"data": []})
    cache = _geocode_cache()
    now = time.time()
    if now - cache["t"] < 1.0 and cache["q"] == q:
        return jsonify({"data": cache["results"]})
    if now - cache["t"] < 1.0:
        return jsonify({"error": {"code": "RATE_LIMITED", "message": "Max 1 geocode per second"}}), 429

    import urllib.request
    import urllib.parse
    import json as _json
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=5&q="
           + urllib.parse.quote(q))
    req = urllib.request.Request(url, headers={"User-Agent": "TRACEBACK/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            results = _json.loads(resp.read().decode("utf-8"))
        out = [{"label": r.get("display_name"),
                "lat": float(r["lat"]), "lng": float(r["lon"])} for r in results]
    except Exception:
        out = []
    cache.update({"q": q, "t": now, "results": out})
    return jsonify({"data": out})


def _geocode_cache():
    global _cache
    if not _cache:
        _cache = {"q": None, "t": 0.0, "results": []}
    return _cache


_cache = {}
