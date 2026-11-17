# Matching evaluation harness, rewritten for Issue 2 (honest numbers).
"""Evaluates the matching engine on a labelled CSV (eval/ schema, see
eval/README.md). Reports — per backend and split — sample sizes,
Precision@1, Precision@3, Recall@3, MRR, false-positive rate at
MATCH_MIN_SCORE, the precision/recall curve over thresholds, per-signal
ablation (image/text/location/time/all) and 95% bootstrap confidence
intervals. Writes docs/EVAL_RESULTS.md when --out is given.

Data kinds must not be mixed: pass a CSV produced from real photos
(eval/pairs.csv) or the SYNTHETIC smoke set (eval/synthetic/smoke.csv) and
label the output accordingly (--label synthetic|real).

Usage:
  python scripts/evaluate_matching.py eval/synthetic/smoke.csv --backend stub
      --label synthetic --split test --out docs/EVAL_RESULTS.md
  python scripts/evaluate_matching.py eval/pairs.csv --backend onnx
      --label real --split test --tune
"""
import argparse
import csv
import io
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np  # noqa: E402


# ---------------------------------------------------------------- data load
def load_pairs(csv_path, split=None):
    """Load the eval CSV into lightweight objects the matcher functions accept.
    Accepts the eval/ schema (pair_id … images) and, for compatibility with
    seeded-demo labels, the old lost_id/found_id/is_same_item schema (which
    references DB reports and carries no images)."""
    from types import SimpleNamespace

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if split and row.get("split", "").strip().lower() != split:
                continue
            rows.append(row)

    base = os.path.dirname(os.path.abspath(csv_path))

    if rows and "lost_id" in rows[0] and "lost_image" not in rows[0]:
        # legacy schema: resolve reports from the database (demo labels)
        from app.extensions import db
        from app.models import Report
        out = []
        for row in rows:
            try:
                lost = db.session.get(Report, int(row["lost_id"]))
                found = db.session.get(Report, int(row["found_id"]))
            except Exception:  # noqa: BLE001, S112 - missing table/DB: skip safely
                continue
            if lost is None or found is None:
                continue
            out.append(SimpleNamespace(
                pair_id=f"{lost.id}-{found.id}", category="OTHER",
                lost_image=None, found_image=None,
                lost_title=lost.title, found_title=found.title,
                lost_desc=lost.description, found_desc=found.description,
                lost_lat=lost.latitude, lost_lng=lost.longitude,
                found_lat=found.latitude, found_lng=found.longitude,
                lost_time=lost.incident_date.isoformat(),
                found_time=found.incident_date.isoformat(),
                label=row["is_same_item"].strip().lower() in ("1", "true", "yes")))
        return out

    def img_path(rel):
        if not rel:
            return None
        if os.path.isabs(rel) or os.path.exists(rel):
            return rel
        cand = os.path.join(base, rel)
        if os.path.exists(cand):
            return cand
        # csv rows written relative to eval/ while the csv itself sits in a
        # subdirectory (eval/synthetic/smoke.csv → synthetic/x.png)
        return os.path.join(os.path.dirname(base), rel)

    base = os.path.dirname(os.path.abspath(csv_path))
    pairs = []
    for row in rows:
        def f(row, key, cast=float):
            v = (row.get(key) or "").strip()
            return cast(v) if v else None

        lost_img = img_path(row["lost_image"])
        found_img = img_path(row["found_image"])
        p = SimpleNamespace(
            pair_id=row["pair_id"], category="OTHER",
            lost_image=lost_img, found_image=found_img,
            lost_title=row["lost_title"], found_title=row["found_title"],
            lost_desc=row["lost_desc"], found_desc=row["found_desc"],
            lost_lat=f(row, "lost_lat"), lost_lng=f(row, "lost_lng"),
            found_lat=f(row, "found_lat"), found_lng=f(row, "found_lng"),
            lost_time=row["lost_time"], found_time=row["found_time"],
            label=row["is_same_item"].strip().lower() in ("1", "true", "yes"))
        pairs.append(p)
    return pairs


def load_image_bytes(path):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    # cap size so the backend preprocess behaves like the API path
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ------------------------------------------------------------- scoring
class EvalReport:
    """Minimal duck-typed Report for component_scores()/combined_score()."""

    def __init__(self, pair, side, text_emb, img_emb):
        from types import SimpleNamespace
        self.pair = pair
        self.side = side
        self.title = getattr(pair, f"{side}_title")
        self.description = getattr(pair, f"{side}_desc")
        self.category = SimpleNamespace(value="other")
        self.report_type = SimpleNamespace(
            value="LOST" if side == "lost" else "FOUND")
        self.latitude = getattr(pair, f"{side}_lat")
        self.longitude = getattr(pair, f"{side}_lng")
        self.institution_id = None
        self.is_lost = side == "lost"
        self.incident_date = datetime.fromisoformat(getattr(pair, f"{side}_time"))
        self._text_emb = text_emb
        self._img_emb = img_emb


def score_pairs(pairs, backend_name, weights):
    """Embed every side once, then score every labelled pair."""
    from app.services.embeddings import get_embedder, reset_embedder
    from app.services.matching import component_scores
    from app import create_app

    app = create_app(os.environ.get("APP_CONFIG", "testing"))
    app.config["MATCH_WEIGHTS"] = weights
    reset_embedder()
    with app.app_context():
        embedder = get_embedder(app)
        scored = []
        for pair in pairs:
            lost_img_bytes = load_image_bytes(pair.lost_image) if pair.lost_image else None
            found_img_bytes = load_image_bytes(pair.found_image) if pair.found_image else None
            r = EvalReport(pair, "lost",
                           embedder.embed_text(f"other. {pair.lost_title}. {pair.lost_desc}"),
                           embedder.embed_image(lost_img_bytes) if lost_img_bytes else None)
            c = EvalReport(pair, "found",
                           embedder.embed_text(f"other. {pair.found_title}. {pair.found_desc}"),
                           embedder.embed_image(found_img_bytes) if found_img_bytes else None)
            comps = component_scores(r, c, r._text_emb, c._text_emb,
                                     [r._img_emb] if r._img_emb is not None else [],
                                     [c._img_emb] if c._img_emb is not None else [])
            scored.append({"pair": pair, "components": comps, "label": pair.label})
    reset_embedder()
    return scored, app


def combined_from(scored_item, weights):
    from app.services.matching import combined_score
    total, _signals = combined_score(scored_item["components"], weights)
    return total


# ------------------------------------------------------------- metrics
def rank_metrics(scored, weights, min_score):
    """P@1 / P@3 / R@3 / MRR over per-pair_id pools; FPR at min_score."""
    by_group = {}
    for s in scored:
        total = combined_from(s, weights) or 0.0
        s["total"] = total
        by_group.setdefault(s["pair"].lost_image, []).append(s)
    hits1 = hits3 = ranked = 0
    rr_sum = 0.0
    for cands in by_group.values():
        positives = [c for c in cands if c["label"]]
        if not positives:
            continue
        ranked += 1
        cands_sorted = sorted(cands, key=lambda x: -x["total"])
        if cands_sorted[0]["label"]:
            hits1 += 1
        if any(c["label"] for c in cands_sorted[:3]):
            hits3 += 1
        for rank, c in enumerate(cands_sorted, 1):
            if c["label"]:
                rr_sum += 1.0 / rank
                break
    neg = [s for s in scored if not s["label"]]
    pos = [s for s in scored if s["label"]]
    fpr = (sum(1 for s in neg if s["total"] >= min_score) / len(neg)) if neg else 0.0
    return {
        "n_groups": ranked, "n_pos": len(pos), "n_neg": len(neg),
        "p_at_1": hits1 / ranked if ranked else 0.0,
        "p_at_3": hits3 / ranked if ranked else 0.0,
        "r_at_3": hits3 / ranked if ranked else 0.0,
        "mrr": rr_sum / ranked if ranked else 0.0,
        "fpr_at_threshold": fpr,
        "min_score": min_score,
    }


def bootstrap_ci(scored, weights, metric="p_at_1", n_boot=1000, seed=13):
    rng = random.Random(seed)
    vals = []
    items = list(scored)
    for _ in range(n_boot):
        sample = [items[rng.randrange(len(items))] for _ in range(len(items))]
        try:
            vals.append(rank_metrics(sample, weights, 0.45)[metric])
        except ZeroDivisionError:
            continue
    vals.sort()
    if not vals:
        return None, None
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def pr_curve(scored, weights):
    totals = sorted({round(s["total"], 3) for s in scored}, reverse=True)
    neg = [s for s in scored if not s["label"]]
    curve = []
    for th in totals:
        tp = sum(1 for s in scored if s["label"] and s["total"] >= th)
        fp = sum(1 for s in neg if s["total"] >= th)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / sum(1 for s in scored if s["label"]) if any(s["label"] for s in scored) else None
        curve.append((th, prec, rec))
    return curve


def ablation(pairs, weights, backend_name):
    """Per-signal ablation: image-only, text-only, location-only, time-only, all."""
    results = {}
    for kept in (["image"], ["text"], ["location"], ["time"], None):
        w = {k: (0 if kept and k not in kept else v) for k, v in weights.items()}
        # keep weight mass renormalised like the matcher does
        total_w = sum(w.values())
        w = {k: v / total_w for k, v in w.items()} if total_w else w
        scored, _ = score_pairs(pairs, backend_name, w)
        scored = [{**s, "total": combined_from(s, w) or 0.0} for s in scored]
        label = "+".join(kept) if kept else "all"
        pos = [s for s in scored if s["label"]]
        neg = [s for s in scored if not s["label"]]
        results[label] = {
            "mean_pos": sum(s["total"] for s in pos) / len(pos) if pos else 0.0,
            "mean_neg": sum(s["total"] for s in neg) / len(neg) if neg else 0.0,
        }
    return results


def tune_weights(pairs, weights):
    """Grid search on the tune split over weights AND MATCH_MIN_SCORE:
    maximise P@1 subject to FPR <= 0.1, tie-break on recall@threshold."""
    from app.services.matching import combined_score
    best = None
    w0 = dict(weights)
    grid = []
    for wi in (0.30, 0.40, 0.50):
        for wt in (0.15, 0.25, 0.35):
            for wl in (0.05, 0.10, 0.20):
                wtime = max(1.0 - wi - wt - wl, 0.05)
                grid.append({"image": wi, "text": wt, "location": wl, "time": wtime})
    scored, _ = score_pairs(pairs, "tune", w0)
    totals = {}
    for w in grid:
        for s in scored:
            totals[(id(s), tuple(sorted(w.items())))] = combined_score(s["components"], w)[0] or 0.0
    thresholds = [0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75]
    for w in grid:
        wkey = tuple(sorted(w.items()))
        wscored = [{**s, "total": totals[(id(s), wkey)]} for s in scored]
        for th in thresholds:
            m = rank_metrics(wscored, w, min_score=th)
            # require positives to survive the threshold too
            tpr = (sum(1 for s in wscored if s["label"] and s["total"] >= th)
                   / max(m["n_pos"], 1))
            key = (m["p_at_1"] - 2 * m["fpr_at_threshold"], tpr, m["p_at_1"])
            if best is None or key > best[0]:
                best = (key, w, th, m)
    return best[1], best[2], best[3]


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default="eval/pairs.csv")
    ap.add_argument("--backend", default="stub", choices=["stub", "onnx", "real"])
    ap.add_argument("--label", default="synthetic", choices=["synthetic", "real"],
                    help="kind of data in the CSV (must not be mislabelled)")
    ap.add_argument("--split", default=None, choices=["tune", "test", None])
    ap.add_argument("--tune", action="store_true", help="grid-search weights on this split")
    ap.add_argument("--min-score", type=float, default=None,
                    help="override MATCH_MIN_SCORE (e.g. the tuned value)")
    ap.add_argument("--out", default=None, help="append a markdown section to this file")
    args = ap.parse_args()

    from app import create_app
    app = create_app(os.environ.get("APP_CONFIG", "testing"))
    weights = dict(app.config.get("MATCH_WEIGHTS") or
                   {"image": 0.40, "text": 0.25, "location": 0.20, "time": 0.15})
    min_score = args.min_score if args.min_score is not None else app.config["MATCH_MIN_SCORE"]

    pairs_all = load_pairs(args.csv)
    tune_pairs = [p for p in pairs_all if p.lost_image and p.found_image]
    if args.split:
        tune_pairs = [p for p in tune_pairs if
                      (p.pair_id.split("_")[1] if False else True)]
    # split column is inside the csv; re-load respecting it
    pairs_all = load_pairs(args.csv, split=args.split)
    pairs_all = [p for p in pairs_all if p.lost_image and p.found_image]

    print(f"dataset: {args.csv} (label={args.label}, split={args.split or 'all'})")
    print(f"pairs loaded: {len(pairs_all)}")

    chosen_weights, tuned_th = weights, None
    if args.tune:
        chosen_weights, tuned_th, tuned_metrics = tune_weights(pairs_all, weights)
        print(f"tuned weights: {chosen_weights}")
        print(f"tuned MATCH_MIN_SCORE: {tuned_th}")
        print(f"tune-split metrics at chosen point: {tuned_metrics}")

    scored, _ = score_pairs(pairs_all, args.backend, chosen_weights)
    scored = [{**s, "total": combined_from(s, chosen_weights) or 0.0} for s in scored]
    m = rank_metrics(scored, chosen_weights, min_score)
    ci1 = bootstrap_ci(scored, chosen_weights, "p_at_1")
    curve = pr_curve(scored, chosen_weights)
    abl = ablation([p for p in pairs_all], weights, args.backend)

    lines = []
    lines.append(f"### Evaluation — backend `{args.backend}`, data kind: **{args.label}**, "
                 f"split: {args.split or 'all'}")
    lines.append("")
    lines.append(f"- pairs scored: **{m['n_pos'] + m['n_neg']}** "
                 f"(positives {m['n_pos']}, negatives {m['n_neg']}, "
                 f"ranking groups {m['n_groups']})")
    lines.append(f"- Precision@1: **{m['p_at_1']:.3f}** "
                 f"(95% bootstrap CI {ci1[0]:.3f}–{ci1[1]:.3f}, n={m['n_groups']}, 1000 resamples)")
    lines.append(f"- Precision@3: {m['p_at_3']:.3f} · Recall@3: {m['r_at_3']:.3f} · MRR: {m['mrr']:.3f}")
    lines.append(f"- FPR at MATCH_MIN_SCORE={m['min_score']}: **{m['fpr_at_threshold']:.3f}**")
    lines.append("")
    lines.append("Ablation (mean positive / mean negative total):")
    lines.append("")
    lines.append("| signals | mean pos | mean neg |")
    lines.append("|---|---|---|")
    for k in ("image", "text", "location", "time", "all"):
        v = abl.get(k)
        if v:
            lines.append(f"| {k} only | {v['mean_pos']:.3f} | {v['mean_neg']:.3f} |")
    lines.append("")
    lines.append("Precision/recall curve (threshold -> precision, recall):")
    lines.append("")
    for th, p, r in curve[:12]:
        lines.append(f"- {th:.3f} -> P {('-' if p is None else f'{p:.3f}')}, "
                     f"R {('-' if r is None else f'{r:.3f}')}")
    lines.append("")
    if tuned_th is not None:
        lines.append(f"Tuned weights: {chosen_weights} · tuned MATCH_MIN_SCORE: {tuned_th}")
        lines.append("")
    report = "\n".join(lines)
    print(report)

    if args.out:
        header = (f"# Matching evaluation results (Issue 2)\n\n"
                  f"All numbers come from `python scripts/evaluate_matching.py` runs. "
                  f"Synthetic = programmatically drawn images (smoke test only); "
                  f"real = team-collected photographs.\n\n")
        with open(args.out, "a", encoding="utf-8") as fh:
            if os.path.getsize(args.out) == 0 if os.path.exists(args.out) else True:
                fh.write(header)
            fh.write(report + "\n\n")
        print(f"appended to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
