"""Shared pytest fixtures and factories (Section 17)."""
import io
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from flask.testing import FlaskClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from werkzeug.datastructures import FileStorage

from app import create_app
from app.extensions import db as _db
from app.models import Institution, User
from app.models.enums import Role


class CsrfClient(FlaskClient):
    """Test client that automatically adds the X-CSRF-TOKEN header from the
    csrf_access_token cookie, mirroring the browser behaviour of api.js."""

    def open(self, *args, **kwargs):
        method = (kwargs.get("method") or (args[1] if len(args) > 1 else "GET")).upper()
        if method not in ("GET", "HEAD", "OPTIONS"):
            path = args[0] if args else kwargs.get("path", "")
            names = ("csrf_refresh_token",) if str(path).endswith("/auth/refresh") \
                else ("csrf_access_token",)
            for cookie_name in names:
                try:
                    cookie = self.get_cookie(cookie_name)
                    if cookie is not None:
                        headers = list(kwargs.get("headers") or [])
                        headers.append(("X-CSRF-TOKEN", cookie.value))
                        kwargs["headers"] = headers
                        break
                except Exception:
                    pass
        return super().open(*args, **kwargs)




@pytest.fixture()
def app(tmp_path):
    import app.services.storage as storage_mod
    from app.services.embeddings import reset_embedder
    reset_embedder()
    storage_mod.reset_storage()
    app = create_app("testing")
    app.test_client_class = CsrfClient
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")
    app.config["WTF_CSRF_ENABLED"] = False
    storage_mod.reset_storage()
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.fixture()
def db(app):
    with app.app_context():
        yield _db


def make_png(colour=(200, 30, 30), size=(200, 150), label=None):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size, colour)
    if label:
        d = ImageDraw.Draw(img)
        d.text((10, 60), label, fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def image_file(colour=(200, 30, 30), name="photo.png"):
    return FileStorage(stream=make_png(colour), filename=name, content_type="image/png")


def register(client, email, name="Test User", password="Password1"):
    return client.post("/api/v1/auth/register", json={
        "name": name, "email": email, "password": password})


def login(client, email, password="Password1"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def auth(client, email, name="Test User", password="Password1"):
    """Register (if needed) and log in; returns the response."""
    if len(name) < 2:
        name = "Test " + name
    r = register(client, email, name, password)
    if r.status_code == 409:
        pass
    r = login(client, email, password)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r


def create_report(client, report_type="LOST", category="WALLETS_CARDS",
                  title=None, description=None, days_ago=1,
                  lat=None, lng=None, images=0, custody=None,
                  institution_id=None, private_details=None, location_text=None):
    data = {
        "report_type": report_type,
        "category": category,
        "title": title or f"{report_type.title()} {category} item",
        "description": description or "A detailed description of the item for matching purposes.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if lat is not None:
        data["latitude"] = str(lat)
    if lng is not None:
        data["longitude"] = str(lng)
    if institution_id:
        data["institution_id"] = str(institution_id)
    if custody:
        data["custody"] = custody
    if private_details:
        data["private_details"] = private_details
    if location_text:
        data["location_text"] = location_text
    files = []
    payload = dict(data)
    for i in range(images):
        colour = (200, 30, 30) if report_type == "LOST" else (30, 30, 200)
        files.append((image_file(colour, f"{i}.png"),))
    return client.post("/api/v1/reports", data={**payload,
                       **{f"images": image_file() for _ in range(images)}},
                       content_type="multipart/form-data")


def create_report_with_images(client, report_type, images_spec, **kwargs):
    """images_spec: list of (colour, filename) for deterministic stub embeddings."""
    from datetime import timedelta
    data = {
        "report_type": report_type,
        "category": kwargs.get("category", "WALLETS_CARDS"),
        "title": kwargs.get("title", f"{report_type.title()} test item"),
        "description": kwargs.get("description", "A detailed description for the test item."),
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=kwargs.get("days_ago", 1))).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if kwargs.get("lat") is not None:
        data["latitude"] = str(kwargs["lat"])
    if kwargs.get("lng") is not None:
        data["longitude"] = str(kwargs["lng"])
    if kwargs.get("institution_id"):
        data["institution_id"] = str(kwargs["institution_id"])
    if kwargs.get("custody"):
        data["custody"] = kwargs["custody"]
    if kwargs.get("private_details"):
        data["private_details"] = kwargs["private_details"]
    if kwargs.get("location_text"):
        data["location_text"] = kwargs["location_text"]
    # multiple images fields
    form = {**data}
    builders = []
    for colour, fname in images_spec:
        builders.append(lambda c=colour, n=fname: image_file(c, n))
    return client.post("/api/v1/reports", data={**form, **{k: b() for k, b in zip(["images"] * len(builders), builders)}},
                       content_type="multipart/form-data")


def make_institution(db, name="Test College", slug=None, lat=30.4, lng=78.0):
    inst = Institution(name=name, slug=slug or Institution.unique_slug(name),
                       latitude=lat, longitude=lng)
    db.session.add(inst)
    db.session.commit()
    return inst


def make_staff(db, email="staff@x.com", inst_id=None):
    u = User(name="Staff Person", email=email, role=Role.STAFF,
             institution_id=inst_id)
    u.set_password("Password1")
    db.session.add(u)
    db.session.commit()
    return u


def wait_processing(app, timeout=5):
    """In tests jobs run synchronously; nothing to wait for."""
    return True
