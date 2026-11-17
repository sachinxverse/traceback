# eval/ — labelled matching evaluation set (Issue 2)

This directory holds the **labelled evaluation data** for the matching
engine. It is deliberately separate from the demo seed data
(`scripts/seed_demo.py`), which exists for demos only and must never be
used to quote accuracy numbers.

## Layout (created by `python scripts/../eval/make_template.py` or by hand)

```
eval/
├── README.md            this file
├── objects/             eval/object_XX_a.jpg (view A) / _b.jpg (view B)
├── synthetic/           clearly-marked SYNTHETIC smoke-test images + csv
└── pairs.csv            the labelled pair list (see schema below)
```

## How we collect REAL photos (per team member)

1. Take **10–15 everyday objects** (bag, bottle, umbrella, wallet, glasses
   case, headphones, book, lunchbox, shoes, toy…).
2. Photograph **each object twice**: view A and view B must differ in
   angle, lighting and background. No retouching, no edits.
3. Save as `eval/objects/object_01_a.jpg` / `object_01_b.jpg` etc.
4. **A different team member writes the descriptions** (title + free-text
   description, 15–40 words) for every object, without seeing how the
   photos were taken. Use different wording than the other member.
5. Log the object in `eval/pairs.csv` (schema below) with a plausible
   place/time spread.

## pairs.csv schema

```
pair_id, category, split,
lost_image, lost_title, lost_desc, lost_place, lost_lat, lost_lng, lost_time,
found_image, found_title, found_desc, found_place, found_lat, found_lng, found_time,
is_same_item
```

- `split` is `tune` or `test`. **Tune weights/thresholds only on `tune`;
  report final numbers on `test` only.**
- Positives: `is_same_item=1` and the two images show the same physical
  object (different photo). Negatives: `is_same_item=0` — include **hard
  negatives**: same category, similar colour/brand, same place, close
  dates, but different objects.
- Target minimum (Issue 2.1): **≥ 100 true pairs and ≥ 300 negatives**.
  The current checked-in set is SYNTHETIC (see below) and is only a
  smoke test; real-photo collection is tracked in the team checklist.

## Honesty rules

- Photos must be real photographs of real objects. Do **not** generate
  images with AI and present them as real.
- Anything under `eval/synthetic/` is programmatically drawn and must be
  labelled SYNTHETIC in every result it produces
  (`python scripts/evaluate_matching.py --pairs eval/synthetic/smoke.csv`).
- Numbers reported publicly must state: dataset kind (synthetic or real),
  number of positives/negatives, split, and the 95% bootstrap CI.
