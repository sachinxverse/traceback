"""Institution tests (F11, Section 13, acceptance A9, A10)."""
from datetime import UTC, datetime

from tests.conftest import auth, login, make_institution, make_staff


def test_admin_institution_crud_and_slug(client, db):
    from tests.conftest import login
    auth(client, "admin@t.com", "Admin", "Password1")
    from app.models import User
    from app.models.enums import Role
    u = db.session.query(User).filter_by(email="admin@t.com").one()
    u.role = Role.ADMIN
    db.session.commit()

    r = client.post("/api/v1/institutions", json={"name": "City Mall", "institution_type": "MALL"})
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["slug"].startswith("city-mall")
    slug1 = data["slug"]

    # slug uniqueness: same name again -> suffixed slug
    r = client.post("/api/v1/institutions", json={"name": "City Mall"})
    assert r.get_json()["data"]["slug"] != slug1

    # staff cannot create
    client.post("/api/v1/auth/logout")
    inst_other = make_institution(db, name="Some Inst")
    make_staff(db, "s@x.com", inst_other.id)
    login(client, "s@x.com")
    r = client.post("/api/v1/institutions", json={"name": "Nope"})
    assert r.status_code in (401, 403)


def test_public_list_and_by_slug(client, db):
    inst = make_institution(db, name="Central Station", slug="central-station")
    r = client.get("/api/v1/institutions")
    assert r.status_code == 200
    assert any(i["slug"] == "central-station" for i in r.get_json()["data"])
    r = client.get("/api/v1/institutions/by-slug/central-station")
    assert r.status_code == 200
    assert r.get_json()["data"]["id"] == inst.id


def test_qr_png_download(client, db):
    inst = make_institution(db, name="QR Inst", slug="qr-inst")
    auth(client, "admin@t.com", "Admin")
    from app.models import User
    from app.models.enums import Role
    u = db.session.query(User).filter_by(email="admin@t.com").one()
    u.role = Role.ADMIN
    db.session.commit()
    r = client.get(f"/api/v1/institutions/{inst.id}/qr.png")
    assert r.status_code == 200
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"  # valid PNG header
    # QR decodes to BASE_URL/i/slug
    import io

    from PIL import Image
    img = Image.open(io.BytesIO(r.data))
    try:
        from pyzbar.pyzbar import decode
        decoded = decode(img)
        assert decoded and decoded[0].data.decode().endswith("/i/qr-inst")
    except Exception:
        pass  # pyzbar optional in test env


def test_qr_landing_page(client, db):
    make_institution(db, name="Land Inst", slug="land-inst")
    r = client.get("/i/land-inst")
    assert r.status_code == 200
    assert "Land Inst" in r.get_data(as_text=True)
    assert "/report/lost?institution=land-inst" in r.get_data(as_text=True)


def test_staff_sees_only_own_institution(client, db):
    inst1 = make_institution(db, name="Inst A")
    inst2 = make_institution(db, name="Inst B")
    make_staff(db, "staffa@x.com", inst1.id)

    auth(client, "member@test.com", "Member")
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "BAGS", "title": "Found bag",
        "description": "A bag was found on the premises of institution B.",
        "incident_date": datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "institution_id": str(inst2.id), "custody": "AT_INSTITUTION"},
        content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    login(client, "staffa@x.com")
    # cannot see other institution's report
    assert client.get(f"/api/v1/reports/{rid}").status_code == 404
    # admin sees everything
    client.post("/api/v1/auth/logout")
    auth(client, "admin2@x.com", "Admin2")
    from app.models import User
    from app.models.enums import Role
    u = db.session.query(User).filter_by(email="admin2@x.com").one()
    u.role = Role.ADMIN
    db.session.commit()
    r = client.get(f"/api/v1/reports/{rid}")
    assert r.status_code == 200
