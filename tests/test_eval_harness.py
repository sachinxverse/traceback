"""Issue 2 test: the evaluation harness must run end-to-end on a tiny
labelled fixture (tests/fixtures/eval_smoke) with sample sizes reported."""
import csv
import os
import sys

import pytest

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "eval_smoke", "smoke.csv")


def test_eval_script_runs_on_fixture(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "evaluate_matching.py", FIXTURE,
        "--backend", "stub", "--label", "synthetic", "--split", "test"])
    import scripts.evaluate_matching as ev
    rc = ev.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "pairs scored" in out
    # sample sizes must always be stated (honesty rule, Issue 2)
    assert "positives 1" in out and "negatives 2" in out
    assert "Precision@1" in out and "bootstrap CI" in out
    assert "FPR" in out


def test_fixture_csv_shape():
    with open(FIXTURE, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert sum(1 for r in rows if r["is_same_item"] == "1") == 1
    for r in rows:
        assert os.path.exists(os.path.join(os.path.dirname(FIXTURE), r["lost_image"]))
        assert os.path.exists(os.path.join(os.path.dirname(FIXTURE), r["found_image"]))
