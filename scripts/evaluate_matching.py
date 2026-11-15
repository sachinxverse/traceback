"""Matching evaluation harness (Section 9.8, review C2).

Reads a CSV of labelled pairs (lost_id, found_id, is_same_item) - the seeded
demo data ships labels in scripts/labels.csv - scores every pair and prints:
precision@1, precision@3, recall@3, false-positive rate at MATCH_MIN_SCORE,
mean positive score and a score histogram. --pairs prints the per-pair table.
Always exits 0.
"""
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def evaluate(labels_path, show_pairs=False):
    from app import create_app
    from app.extensions import db
    from app.models import Report
    from app.services.embeddings import IMAGE_DIM, TEXT_DIM, from_blob
    from app.services.matching import _weights, combined_score, component_scores

    app = create_app(os.environ.get("APP_CONFIG", "development"))
    with app.app_context():
        with open(labels_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        pairs = []
        for row in rows:
            try:
                lost = db.session.get(Report, int(row["lost_id"]))
                found = db.session.get(Report, int(row["found_id"]))
            except Exception:  # noqa: BLE001, S112 - missing table/DB: skip safely
                continue
            if lost is None or found is None:
                continue
            pairs.append((lost, found,
                          row["is_same_item"].strip().lower() in ("1", "true", "yes")))

        scored = []
        for lost, found, label in pairs:
            textr = from_blob(lost.text_embedding, TEXT_DIM)
            textc = from_blob(found.text_embedding, TEXT_DIM)
            imgr = [from_blob(i.embedding, IMAGE_DIM) for i in lost.images]
            imgc = [from_blob(i.embedding, IMAGE_DIM) for i in found.images]
            imgr = [v for v in imgr if v is not None]
            imgc = [v for v in imgc if v is not None]
            scores = component_scores(lost, found, textr, textc, imgr, imgc)
            total, _ = combined_score(scores, _weights(app))
            scored.append({"lost": lost, "found": found, "label": label,
                           "components": scores, "total": total or 0.0})

        min_score = app.config["MATCH_MIN_SCORE"]
        notify_score = app.config["NOTIFY_MIN_SCORE"]
        pos = [s for s in scored if s["label"]]
        neg = [s for s in scored if not s["label"]]

        # per-lost-item ranking: positives must win their own candidate pool
        by_lost = {}
        for s in scored:
            by_lost.setdefault(s["lost"].id, []).append(s)
        hits1 = hits3 = ranked_lost = 0
        for cands in by_lost.values():
            cands = sorted(cands, key=lambda x: -x["total"])
            positives = [c for c in cands if c["label"]]
            if not positives:
                continue
            ranked_lost += 1
            if cands[0]["label"]:
                hits1 += 1
            if any(c["label"] for c in cands[:3]):
                hits3 += 1
        precision_at_1 = hits1 / ranked_lost if ranked_lost else 0.0
        precision_at_3 = hits3 / ranked_lost if ranked_lost else 0.0
        recall_at_3 = precision_at_3  # one true pair per ranked lost item
        fpr = (sum(1 for s in neg if s["total"] >= min_score) / len(neg)) if neg else 0.0
        mean_pos = (sum(s["total"] for s in pos) / len(pos)) if pos else 0.0
        medium_or_high = sum(1 for s in pos if s["total"] >= notify_score)

        if show_pairs:
            print(f"{'lost':>4} {'found':>5} {'label':>5} {'score':>6} "
                  f"{'img':>5} {'txt':>5} {'loc':>5} {'time':>5}  title")
            for s in sorted(scored, key=lambda x: -x["total"]):
                c = s["components"]
                print(f"{s['lost'].id:>4} {s['found'].id:>5} "
                      f"{'POS' if s['label'] else 'NEG':>5} {s['total']:>6.3f} "
                      f"{c['image']:>5.2f} {c['text']:>5.2f} {c['location']:>5.2f} "
                      f"{c['time']:>5.2f}  {s['lost'].title[:24]} vs {s['found'].title[:24]}")

        hist = Counter()
        for s in scored:
            bucket = min(int(s["total"] * 10), 9)
            hist[f"{bucket * 10}-{bucket * 10 + 10}%"] += 1

        print(f"Pairs evaluated: {len(scored)} (positive: {len(pos)}, negative: {len(neg)})")
        print(f"Threshold (MATCH_MIN_SCORE): {min_score}, notify: {notify_score}")
        print(f"precision@1: {precision_at_1:.3f}")
        print(f"precision@3: {precision_at_3:.3f}")
        print(f"recall@3:    {recall_at_3:.3f}")
        print(f"false-positive rate at threshold: {fpr:.3f}")
        print(f"mean positive score: {mean_pos:.3f}")
        print(f"positives at MEDIUM/HIGH (>= {notify_score}): "
              f"{medium_or_high}/{len(pos)}")
        print("score histogram (10% buckets):")
        for bucket in sorted(hist, key=lambda b: int(b.split('-')[0])):
            print(f"  {bucket}: {hist[bucket]}")
    return 0


if __name__ == "__main__":
    labels = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") \
        else os.path.join(os.path.dirname(__file__), "labels.csv")
    show = "--pairs" in sys.argv
    sys.exit(evaluate(labels, show_pairs=show))
