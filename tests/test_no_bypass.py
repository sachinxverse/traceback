"""Part E — no-bypass and hard-coded-data guard tests (C6, D2)."""
import glob
import os
import re

import pytest


# ------------------------------------------------------------------- C6 bypass
def test_cookies_only_set_after_otp(app, client, monkeypatch):
    """Hook set_access_cookies: it must fire ONLY on OTP-verified login,
    register verify, refresh, and the post-OTP password change."""
    calls = []

    import flask_jwt_extended
    real = flask_jwt_extended.set_access_cookies
    def spy(resp, token, max_age=None):
        calls.append(token)
        return real(resp, token, max_age=max_age)
    monkeypatch.setattr(flask_jwt_extended, "set_access_cookies", spy)
    # also patch the reference imported inside app.api.auth
    import app.api.auth as auth_mod
    monkeypatch.setattr(auth_mod, "set_access_cookies", spy)

    # step 1 (credentials only) must NOT set cookies
    client.post("/api/v1/auth/register", json={
        "name": "Bypass U", "email": "bypass@x.com", "password": "Password1"})
    client.post("/api/v1/auth/logout")
    calls.clear()
    r = client.post("/api/v1/auth/user/login",
                    json={"email": "bypass@x.com", "password": "Password1"})
    assert r.status_code == 200
    assert calls == [], "cookies were set before OTP verification!"

    # step 2 (OTP) sets cookies exactly once
    from tests.conftest import otp_code
    cid = r.get_json()["data"]["challenge_id"]
    calls.clear()
    r = client.post("/api/v1/auth/user/verify-otp",
                    json={"challenge_id": cid, "otp": otp_code("bypass@x.com")})
    assert r.status_code == 200
    assert len(calls) == 1


def test_no_skip_otp_flag_outside_testing_config():
    """No config may offer a way to skip OTP (only the test sender exists)."""
    src = open("config.py", encoding="utf-8").read()
    assert "SKIP_OTP" not in src
    for f in glob.glob("app/**/*.py", recursive=True):
        s = open(f, encoding="utf-8").read()
        assert "SKIP_OTP" not in s, f
        assert "otp_required = False" not in s, f


def test_production_refuses_dev_echo_and_mail_off():
    from config import ProductionConfig
    import os
    env = {
        "SECRET_KEY": "s" * 40, "JWT_SECRET_KEY": "j" * 40,
        "DATABASE_URL": "postgresql+psycopg2://u:p@localhost/db",
        "MAIL_ENABLED": "true", "STORAGE_BACKEND": "s3", "S3_BUCKET": "b",
    }
    old = {k: os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        ProductionConfig.validate()  # baseline passes
        os.environ["OTP_DEV_ECHO"] = "true"
        with pytest.raises(RuntimeError, match="OTP_DEV_ECHO"):
            ProductionConfig.validate()
        os.environ["OTP_DEV_ECHO"] = "false"
        os.environ["MAIL_ENABLED"] = "false"
        with pytest.raises(RuntimeError, match="MAIL_ENABLED"):
            ProductionConfig.validate()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_seed_demo_refuses_in_production():
    from scripts.seed_demo import run_seed
    class FakeApp:
        config = {"APP_CONFIG": "production"}
    with pytest.raises(RuntimeError, match="refuses to run"):
        run_seed(FakeApp())


# --------------------------------------------------------- D2 hard-coded data
@pytest.mark.parametrize("path", glob.glob("app/templates/**/*.html", recursive=True)
                         + glob.glob("app/static/js/*.js"))
def test_no_hardcoded_localhost_or_dummy_links(path):
    s = open(path, encoding="utf-8").read()
    if "skip-link" in s:
        # the skip link's href="#main" is a legitimate a11y pattern
        s = s.replace('href="#main"', "")
    # no localhost / 127.0.0.1 in app templates or JS
    assert "localhost" not in s, f"{path} contains localhost"
    assert "127.0.0.1" not in s, f"{path} contains 127.0.0.1"
    # no javascript: URLs
    assert "javascript:" not in s, f"{path} contains javascript: URL"
    # links must not be dead anchors: href="#" without data-bs-toggle or
    # data-status (Bootstrap dropdown toggles / JS-bound filters are allowed)
    for m in re.finditer(r'href="#"', s):
        line = s[max(0, m.start() - 120):m.end() + 80]
        assert ("data-bs-toggle" in line or "data-status" in line
                or "dropdown" in line), f"{path}: dead anchor href=#"


def test_no_demo_credentials_on_pages():
    """Demo accounts exist only through the seed script, never shown on pages."""
    forbidden = ["admin@traceback.local", "staff@traceback.local",
                 "alice@example.com", "bob@example.com", "User@12345",
                 "Admin@12345", "Staff@12345"]
    paths = (glob.glob("app/templates/**/*.html", recursive=True)
             + glob.glob("app/static/js/*.js")
             + glob.glob("app/static/css/*.css"))
    for p in paths:
        s = open(p, encoding="utf-8").read()
        for cred in forbidden:
            assert cred not in s, f"demo credential {cred} leaked into {p}"


def test_no_plain_otp_or_password_logging():
    """Service code must not log the OTP value; the console sender is the only print."""
    s = open("app/services/otp.py", encoding="utf-8").read()
    # ConsoleOtpSender is the only place allowed to print the code
    assert s.count("print(") == 1
    assert "[OTP]" in s
    # any logger statement must never reference the code value
    for line in s.splitlines():
        if "logger." in line:
            assert "code" not in line.lower(), line


def test_meta_endpoint_serves_enums_and_map_center(client):
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert "WALLETS_CARDS" in d["categories"]
    assert "COLLEGE" in d["institution_types"]
    assert len(d["map_default_center"]) == 2


def test_stats_public_endpoint_cached_and_real(client, db):
    import app.api.meta as meta_mod
    meta_mod._stats_cache.update({"value": None, "at": 0.0})  # test isolation
    r = client.get("/api/v1/stats/public")
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert set(d) == {"recovered", "institutions", "reports"}
    assert all(isinstance(v, int) for v in d.values())
    # empty database shows real zeros (friendly empty state, D4)
    assert d["reports"] == 0 and d["recovered"] == 0 and d["institutions"] == 0
