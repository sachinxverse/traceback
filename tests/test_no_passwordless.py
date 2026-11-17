# Guard: the word "passwordless" must not reappear (Issue 3).
# The login flow is two-step verification (password + one-time code);
# "passwordless" means no password at all and is factually wrong here.
"""Scans app/, docs/, README.md, scripts/ and tests/ for the banned term.
Skips this file itself and the PDF binaries."""
import os
import subprocess

BANNED = ("passwordless", "password-less")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ["app", "docs", "scripts", "tests", "eval", "migrations"]
SELF = os.path.abspath(__file__)


def repo_files():
    for d in SCAN_DIRS:
        full = os.path.join(ROOT, d)
        for base, _dirs, files in os.walk(full):
            for name in files:
                if name.endswith((".py", ".md", ".html", ".js", ".css", ".txt", ".yaml", ".yml", ".toml")):
                    yield os.path.join(base, name)
    yield os.path.join(ROOT, "README.md")


def test_no_passwordless_wording():
    hits = []
    for path in repo_files():
        if os.path.abspath(path) == SELF or not os.path.exists(path):
            continue
        if "no_passwordless" in os.path.basename(path):
            continue  # references to the guard's own name are not wording claims
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for i, line in enumerate(fh, 1):
                low = line.lower()
                # skip lines that merely name the guard file (its own name
                # embeds the banned term by design)
                if "no_passwordless.py" in low:
                    continue
                if any(b in low for b in BANNED):
                    hits.append(f"{os.path.relpath(path, ROOT)}:{i}: {line.strip()[:80]}")
    assert not hits, ("'passwordless' wording found (the flow is two-step "
                     "verification: password + one-time code):\n" + "\n".join(hits))


def test_login_flow_mentions_two_step():
    with open(os.path.join(ROOT, "docs", "DECISIONS.md"), encoding="utf-8") as fh:
        assert "two-step" in fh.read().lower()
