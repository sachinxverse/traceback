# Create the eval/ folder skeleton + CSV template (Issue 2.1).
# Usage: python eval/make_template.py [--with-synthetic]
"""Creates eval/objects/, eval/synthetic/, and an empty eval/pairs.csv
template with the correct header. --with-synthetic also generates the
SYNTHETIC smoke-test set (programmatically drawn images + csv), clearly
labelled as synthetic. Real photo collection is described in eval/README.md."""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

HEADER = ["pair_id", "category", "split",
          "lost_image", "lost_title", "lost_desc", "lost_place",
          "lost_lat", "lost_lng", "lost_time",
          "found_image", "found_title", "found_desc", "found_place",
          "found_lat", "found_lng", "found_time",
          "is_same_item"]

CATEGORIES = "BAGS, ELECTRONICS, WALLETS_CARDS, KEYS, CLOTHING, JEWELLERY, BOOKS_STATIONERY, BOTTLES, UMBRELLAS, OTHER".split(", ")


def template_rows(n=8):
    """Empty example rows for humans to fill in."""
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "pair_id": f"real_{i:03d}", "category": CATEGORIES[i % len(CATEGORIES)],
            "split": "tune" if i % 3 else "test",
            "lost_image": f"objects/object_{i:02d}_a.jpg",
            "lost_title": "", "lost_desc": "", "lost_place": "",
            "lost_lat": "", "lost_lng": "", "lost_time": "",
            "found_image": f"objects/object_{i:02d}_b.jpg",
            "found_title": "", "found_desc": "", "found_place": "",
            "found_lat": "", "found_lng": "", "found_time": "",
            "is_same_item": 1,
        })
    return rows


def make_synthetic(out_dir, n_objects=25, seed=7):
    """SYNTHETIC smoke set: programmatically drawn objects, two views each,
    plus hard-negative distractors. Labelled synthetic everywhere."""
    import random

    import numpy as np
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    np.random.seed(seed)
    os.makedirs(out_dir, exist_ok=True)

    base_colours = [(30, 90, 200), (200, 40, 40), (30, 160, 90), (240, 200, 30),
                    (150, 60, 200), (240, 130, 20), (20, 40, 60), (90, 200, 220)]
    kinds = ["bag", "bottle", "wallet", "umbrella", "book", "headphones", "lunchbox", "toy"]
    places = ["railway station", "college canteen", "library", "bus terminal",
              "sports ground", "main gate"]
    rows = []

    def draw_object(colour, shape, jitter, bg, seed_i, view):
        import colorsys
        img = Image.new("RGB", (240, 200), bg)
        d = ImageDraw.Draw(img)
        cx, cy = 120 + jitter[0], 100 + jitter[1]
        # per-object unique pattern so different objects are visually distinct
        hue = (seed_i * 0.618) % 1.0
        rgb = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.65, 0.9))
        accent = tuple(int(c * 255) for c in colorsys.hsv_to_rgb((hue + 0.35) % 1.0, 0.8, 0.9))
        if shape == 0:
            d.rounded_rectangle([cx - 55, cy - 40, cx + 55, cy + 45], 12, fill=rgb)
            d.rectangle([cx - 55, cy - 8, cx + 55, cy + 8], fill=accent)
        elif shape == 1:
            d.ellipse([cx - 30, cy - 55, cx + 30, cy + 55], fill=rgb)
            d.ellipse([cx - 12, cy - 37, cx + 12, cy - 13], fill=accent)
        elif shape == 2:
            d.polygon([(cx, cy - 50), (cx + 50, cy + 40), (cx - 50, cy + 40)], fill=rgb)
            d.polygon([(cx, cy - 20), (cx + 20, cy + 15), (cx - 20, cy + 15)], fill=accent)
        else:
            d.rectangle([cx - 50, cy - 35, cx + 50, cy + 35], fill=rgb)
            for k in range(4):
                d.line([cx - 50 + k * 25, cy - 35, cx - 50 + k * 25, cy + 35], fill=accent, width=5)
        # background texture varies per view
        for _ in range(6):
            x0 = rng.randint(0, 220)
            d.line([x0, 0, x0 + 20, 200], fill=bg)
        return img

    for i in range(1, n_objects + 1):
        colour = base_colours[i % len(base_colours)]
        kind = kinds[i % len(kinds)]
        bg_a = (rng.randint(200, 255),) * 3
        bg_b = (rng.randint(180, 230),) * 3
        a = draw_object(colour, i % 4, (rng.randint(-15, 15), rng.randint(-10, 10)), bg_a, i, "a")
        b = draw_object(colour, i % 4, (rng.randint(-15, 15), rng.randint(-10, 10)), bg_b, i, "b")
        pa = os.path.join(out_dir, f"obj_{i:02d}_a.png")
        pb = os.path.join(out_dir, f"obj_{i:02d}_b.png")
        a.save(pa)
        b.save(pb)
        place = places[i % len(places)]
        lat, lng = 30.30 + (i % 5) * 0.01, 78.02 + (i % 4) * 0.01
        day = 1 + (i % 20)
        rel = os.path.relpath(out_dir, HERE).replace("\\", "/")
        desc_a = f"a {kind} seen near the {place}, colour block pattern"
        desc_b = f"one {kind} with a solid colour surface found at the {place}"
        rows.append({
            "pair_id": f"syn_pos_{i:02d}", "category": "OTHER", "split": "tune" if i <= 18 else "test",
            "lost_image": f"{rel}/obj_{i:02d}_a.png", "lost_title": f"Lost {kind} {i}",
            "lost_desc": desc_a, "lost_place": place, "lost_lat": lat, "lost_lng": lng,
            "lost_time": f"2026-10-{day:02d}T09:00:00",
            "found_image": f"{rel}/obj_{i:02d}_b.png", "found_title": f"Found {kind} {i}",
            "found_desc": desc_b, "found_place": place, "found_lat": lat, "found_lng": lng,
            "found_time": f"2026-10-{min(day + 1, 28):02d}T15:00:00",
            "is_same_item": 1,
        })

    # negatives: different objects, same/similar colour + same place (hard)
    neg_count = 0
    for i in range(1, n_objects + 1):
        for j in (i + 1, i + 3, i + 6):
            k = ((j - 1) % n_objects) + 1
            if k == i:
                continue
            pa = os.path.join(out_dir, f"obj_{i:02d}_a.png")
            pb = os.path.join(out_dir, f"obj_{k:02d}_b.png")
            place = places[i % len(places)]
            lat, lng = 30.30 + (i % 5) * 0.01, 78.02 + (i % 4) * 0.01
            neg_count += 1
            rel = os.path.relpath(out_dir, HERE).replace("\\", "/")
            rows.append({
                "pair_id": f"syn_neg_{neg_count:02d}", "category": "OTHER",
                "split": "tune" if neg_count % 5 else "test",
                "lost_image": pa, "lost_title": f"Lost {kinds[i % len(kinds)]} {i}",
                "lost_desc": f"lost a {kinds[i % len(kinds)]} at the {place}",
                "lost_place": place, "lost_lat": lat, "lost_lng": lng,
                "lost_time": f"2026-10-{1 + (i % 20):02d}T10:00:00",
                "found_image": pb, "found_title": f"Found {kinds[k % len(kinds)]} {k}",
                "found_desc": f"found a {kinds[k % len(kinds)]} near the {place}",
                "found_place": place, "found_lat": lat, "found_lng": lng,
                "found_time": f"2026-10-{2 + (i % 20):02d}T16:00:00",
                "is_same_item": 0,
            })

    out_csv = os.path.join(out_dir, "smoke.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    print(f"SYNTHETIC smoke set written: {out_csv} "
          f"({sum(1 for r in rows if r['is_same_item'] == 1)} positives, "
          f"{neg_count} negatives) — labelled synthetic, NOT real-photo results.")


def main():
    os.makedirs(os.path.join(HERE, "objects"), exist_ok=True)
    pairs_path = os.path.join(HERE, "pairs.csv")
    if not os.path.exists(pairs_path):
        with open(pairs_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=HEADER)
            w.writeheader()
            for row in template_rows():
                w.writerow(row)
        print(f"template written: {pairs_path}")
    else:
        print(f"already exists: {pairs_path}")
    if "--with-synthetic" in sys.argv:
        make_synthetic(os.path.join(HERE, "synthetic"))


if __name__ == "__main__":
    main()
