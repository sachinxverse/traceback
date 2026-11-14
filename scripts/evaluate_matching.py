"""Matching evaluation script (Section 9.8).

Reads a CSV of labelled pairs (lost_id, found_id, is_same_item) - the seeded
demo data ships labels in scripts/labels.csv - runs the scoring for all pairs
and prints precision@1, precision@3, recall@3, false-positive rate at the
MATCH_MIN_SCORE threshold, and a score histogram. Always exits 0.
"""
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def evaluate(labels_path):
    from app import create_app
    from app.extensions import db
    from app.models import Report
    from app.services.matching import (component_scores, combined_score,
                                       _weights)
    from app.services.embeddings import from_blob, IMAGE_DIM, TEXT_DIM

    app = create_app(os.environ.get("APP_CONFIG", "development"))
    with app.app_context():
        rows = list(csv.DictReader(open(labels_path)))
        pairs = []
        for row in rows:
            lost = db.session.get(Report, int(row["lost_id"]))
            found = db.session.get(Report, int(row["found_id"]))
            if lost is None or found is None:
                continue
            pairs.append((lost, found, row["is_same_item"].strip().lower() in ("1", "true", "yes")))

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
            scored.append((total or 0.0, label))

        min_score = app.config["MATCH_MIN_SCORE"]
        pos = [s for s, l in scored if l]
        neg = [s for s, l in scored if not l]

        # precision@k on ranked positives assuming a candidate pool per lost item
        ranked = sorted(scored, key=lambda x: -x[0])
        def precision_at(k):
            top = [l for _, l in ranked[:k]]
            return (sum(top) / k) if k else 0.0
        recall3 = (sum(l for _, l in ranked[:3]) / len(pos)) if pos else 0.0
        fpr = (sum(1 for s in neg if s >= min_score) / len(neg)) if neg else 0.0

        hist = Counter()
        for s, _ in scored:
            bucket = min(int(s * 10), 9)
            hist[f"{bucket * 10}-{bucket * 10 + 10}%"] += 1

        print(f"Pairs evaluated: {len(scored)} (positive: {len(pos)}, negative: {len(neg)})")
        print(f"Threshold (MATCH_MIN_SCORE): {min_score}")
        print(f"precision@1: {precision_at(1):.3f}")
        print(f"precision@3: {precision_at(3):.3f}")
        print(f"recall@3:    {recall3:.3f}")
        print(f"false-positive rate at threshold: {fpr:.3f}")
        print("score histogram (10% buckets):")
        for bucket in sorted(hist, key=lambda b: int(b.split('-')[0])):
            print(f"  {bucket}: {hist[bucket]}")
    return 0


if __name__ == "__main__":
    labels = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "labels.csv")
    sys.exit(evaluate(labels))
