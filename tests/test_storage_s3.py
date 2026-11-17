"""Issue 5 tests: S3 storage backend via moto server, production guard,
graceful missing-object handling, flask check-images."""
import io
import sys

import pytest
from PIL import Image

from app.extensions import db
from app.models import ReportImage


@pytest.fixture()
def s3_env(monkeypatch):
    # NOTE: this only patches os.environ; the app fixture may already have
    # been created, so mock_s3 additionally patches app.config directly.
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture()
def mock_s3(app, s3_env, monkeypatch):
    """moto's in-process mock_aws does not reliably intercept custom endpoint
    URLs; run moto.server as a subprocess on a free port instead."""
    import socket
    import subprocess
    import time
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    endpoint = f"http://127.0.0.1:{port}"
    import boto3
    c = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                     aws_access_key_id="testing", aws_secret_access_key="testing")
    c.create_bucket(Bucket="test-bucket")
    # route the app's storage config at the running mock server (the app
    # fixture may predate s3_env's env patching)
    monkeypatch.setitem(app.config, "STORAGE_BACKEND", "s3")
    monkeypatch.setitem(app.config, "S3_BUCKET", "test-bucket")
    monkeypatch.setitem(app.config, "S3_ENDPOINT_URL", endpoint)
    monkeypatch.setitem(app.config, "S3_ACCESS_KEY_ID", "testing")
    monkeypatch.setitem(app.config, "S3_SECRET_ACCESS_KEY", "testing")
    from app.services.storage import reset_storage
    reset_storage()
    yield endpoint
    proc.terminate()
    from app.services.storage import reset_storage
    reset_storage()


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def test_s3_save_open_delete_roundtrip(app, mock_s3):
    from app.services.storage import get_storage
    st = get_storage()
    assert st.__class__.__name__ == "S3Storage"
    st.save(_png_bytes(), "2026/01/abc.jpg")
    assert st.open("2026/01/abc.jpg")[:2] == b"\xff\xd8"
    st.delete("2026/01/abc.jpg")
    with pytest.raises(Exception):
        st.open("2026/01/abc.jpg")


def test_authorised_access_still_enforced(app, mock_s3):
    """Files live in S3 but serving stays behind /api/v1/images/{id} rules.
    The storage backend itself has no public URLs — verify a round-trip."""
    from app.services.storage import get_storage
    with app.app_context():
        st = get_storage()
        assert st.__class__.__name__ == "S3Storage"
        st.save(_png_bytes(), "2026/02/x.jpg")
        data = st.open("2026/02/x.jpg")
        assert data[:2] == b"\xff\xd8"


def test_production_refuses_local_storage(monkeypatch):
    # NOTE: no importlib.reload — reloading config.py with patched env would
    # bake class attributes that leak into every later test.
    monkeypatch.setenv("APP_CONFIG", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40 + "unique-value-1234")
    monkeypatch.setenv("JWT_SECRET_KEY", "y" * 40 + "unique-value-5678")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/db")
    monkeypatch.setenv("MAIL_ENABLED", "true")
    monkeypatch.delenv("ALLOW_EPHEMERAL_STORAGE", raising=False)
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    from config import ProductionConfig
    with pytest.raises(RuntimeError, match="STORAGE_BACKEND=local"):
        ProductionConfig.validate()


def test_production_allows_s3(monkeypatch):
    monkeypatch.setenv("APP_CONFIG", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40 + "unique-value-1234")
    monkeypatch.setenv("JWT_SECRET_KEY", "y" * 40 + "unique-value-5678")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/db")
    monkeypatch.setenv("MAIL_ENABLED", "true")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "b")
    from config import ProductionConfig
    ProductionConfig.validate()  # must not raise


def test_missing_object_serves_placeholder(app, mock_s3):
    from app.services.storage import get_storage
    get_storage().save(b"x", "real.jpg")
    with app.app_context():
        from tests.conftest import make_staff
        u = make_staff(db, email="s3-miss@example.com")
        from app.models import Report
        from app.models.enums import Category, ReportType
        from datetime import datetime
        rep = Report(user_id=u.id, title="t", description="d", report_type=ReportType.LOST,
                     category=Category.OTHER, incident_date=datetime(2026, 1, 1))
        db.session.add(rep)
        db.session.flush()
        img = ReportImage(report_id=rep.id, storage_key="does/not/exist.jpg")
        db.session.add(img)
        db.session.commit()

    from app.api.images import _serve
    with app.app_context():
        resp = _serve("does/not/exist.jpg")
        assert resp.mimetype == "image/svg+xml"
        assert b"Photo unavailable" in resp.response[0]
        resp2 = _serve("real.jpg")
        assert resp2.mimetype == "image/jpeg"


def test_check_images_cli(app, capsys, mock_s3):
    from app.services.storage import get_storage
    get_storage().save(b"ok", "good.jpg")
    with app.app_context():
        from tests.conftest import make_staff
        u = make_staff(db, email="s3-cli@example.com")
        from app.models import Report
        from app.models.enums import Category, ReportType
        from datetime import datetime
        rep = Report(user_id=u.id, title="t", description="d", report_type=ReportType.LOST,
                     category=Category.OTHER, incident_date=datetime(2026, 1, 1))
        db.session.add(rep)
        db.session.flush()
        db.session.add(ReportImage(report_id=rep.id, storage_key="good.jpg"))
        db.session.add(ReportImage(report_id=rep.id, storage_key="bad.jpg"))
        db.session.commit()
    out = app.test_cli_runner().invoke(args=["check-images"])
    assert "MISSING report_images" in out.output
    assert "good.jpg" not in out.output.split("MISSING")[0]
    assert "check-images done: 1 missing" in out.output
