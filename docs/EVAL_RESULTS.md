# Matching evaluation results (Issue 2)

All numbers come from `python scripts/evaluate_matching.py` runs. Synthetic = programmatically drawn images (smoke test only); real = team-collected photographs.

### Evaluation — backend `onnx`, data kind: **synthetic**, split: tune

- pairs scored: **78** (positives 18, negatives 60, ranking groups 18)
- Precision@1: **1.000** (95% bootstrap CI 1.000–1.000, n=18, 1000 resamples)
- Precision@3: 1.000 · Recall@3: 1.000 · MRR: 1.000
- FPR at MATCH_MIN_SCORE=0.45: **0.817**

Ablation (mean positive / mean negative total):

| signals | mean pos | mean neg |
|---|---|---|
| image only | 0.807 | 0.847 |
| text only | 0.602 | 0.139 |
| location only | 1.000 | 1.000 |
| time only | 0.837 | 0.836 |
| all only | 0.799 | 0.699 |

Precision/recall curve (threshold -> precision, recall):

- 0.814 -> P -, R 0.000
- 0.801 -> P 1.000, R 0.611
- 0.727 -> P 0.929, R 0.722
- 0.674 -> P 0.867, R 0.722
- 0.650 -> P 0.867, R 0.722
- 0.622 -> P 0.241, R 0.722
- 0.616 -> P 0.230, R 0.778
- 0.607 -> P 0.242, R 0.833
- 0.603 -> P 0.250, R 0.889
- 0.595 -> P 0.262, R 0.944
- 0.590 -> P 0.262, R 0.944
- 0.452 -> P 0.269, R 1.000

Tuned weights: {'image': 0.3, 'text': 0.35, 'location': 0.05, 'time': 0.3} · tuned MATCH_MIN_SCORE: 0.75


### Evaluation — backend `onnx`, data kind: **synthetic**, split: test

- pairs scored: **22** (positives 7, negatives 15, ranking groups 7)
- Precision@1: **1.000** (95% bootstrap CI 1.000–1.000, n=7, 1000 resamples)
- Precision@3: 1.000 · Recall@3: 1.000 · MRR: 1.000
- FPR at MATCH_MIN_SCORE=0.75: **0.533**

Ablation (mean positive / mean negative total):

| signals | mean pos | mean neg |
|---|---|---|
| image only | 0.903 | 0.769 |
| text only | 0.603 | 0.128 |
| location only | 1.000 | 1.000 |
| time only | 0.837 | 0.836 |
| all only | 0.837 | 0.665 |

Precision/recall curve (threshold -> precision, recall):

- 0.877 -> P 1.000, R 0.714
- 0.868 -> P 1.000, R 0.857
- 0.760 -> P 0.429, R 0.857
- 0.740 -> P 0.375, R 0.857
- 0.605 -> P 0.375, R 0.857
- 0.495 -> P 0.412, R 1.000
- 0.486 -> P 0.368, R 1.000
- 0.485 -> P 0.350, R 1.000
- 0.482 -> P 0.350, R 1.000
- 0.462 -> P 0.318, R 1.000


### Evaluation — backend `stub`, data kind: **synthetic**, split: test

- pairs scored: **22** (positives 7, negatives 15, ranking groups 7)
- Precision@1: **1.000** (95% bootstrap CI 1.000–1.000, n=7, 1000 resamples)
- Precision@3: 1.000 · Recall@3: 1.000 · MRR: 1.000
- FPR at MATCH_MIN_SCORE=0.75: **0.533**

Ablation (mean positive / mean negative total):

| signals | mean pos | mean neg |
|---|---|---|
| image only | 0.903 | 0.769 |
| text only | 0.603 | 0.128 |
| location only | 1.000 | 1.000 |
| time only | 0.837 | 0.836 |
| all only | 0.837 | 0.665 |

Precision/recall curve (threshold -> precision, recall):

- 0.877 -> P 1.000, R 0.714
- 0.868 -> P 1.000, R 0.857
- 0.760 -> P 0.429, R 0.857
- 0.740 -> P 0.375, R 0.857
- 0.605 -> P 0.375, R 0.857
- 0.495 -> P 0.412, R 1.000
- 0.486 -> P 0.368, R 1.000
- 0.485 -> P 0.350, R 1.000
- 0.482 -> P 0.350, R 1.000
- 0.462 -> P 0.318, R 1.000


