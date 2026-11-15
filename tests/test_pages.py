"""HTML page tests (test_pages, Section 17)."""
from datetime import UTC, datetime

from tests.conftest import auth, image_file, make_institution


def test_public_pages_200(client):
    for path in ("/", "/how-it-works", "/institutions", "/login", "/register"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_protected_pages_redirect_anonymous(client):
    for path in ("/dashboard", "/profile", "/notifications", "/browse", "/claims"):
        r = client.get(path)
        assert r.status_code in (302, 308), path


def test_dashboard_renders_for_user(client, db):
    auth(client, "dash@x.com", "D")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Dashboard" in r.get_data(as_text=True)


def test_report_form_renders(client, db):
    auth(client, "form@x.com", "F")
    r = client.get("/report/lost")
    assert r.status_code == 200
    r = client.get("/report/found")
    assert r.status_code == 200


def test_base_template_renders_everywhere(client):
    r = client.get("/")
    assert "TRACEBACK" in r.get_data(as_text=True)
    assert "not proof of ownership" in r.get_data(as_text=True)


def test_qr_landing_prefills_institution(client, db):
    make_institution(db, name="Prefill Inst", slug="prefill-inst")
    r = client.get("/i/prefill-inst")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "prefill-inst" in body


def test_report_detail_page_for_owner(client, db):
    auth(client, "det@x.com", "D")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "Detail test keys",
        "description": "Description for the detail page render test keys.",
        "incident_date": datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": image_file()}, content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    r = client.get(f"/reports/{rid}")
    assert r.status_code == 200
    assert "Detail test keys" in r.get_data(as_text=True)


def test_error_pages(client):
    r = client.get("/definitely-not-a-page")
    assert r.status_code == 404
    assert "404" in r.get_data(as_text=True)


def test_admin_page_blocks_normal_user(client, db):
    auth(client, "norm@x.com", "N")
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/users").status_code == 404
