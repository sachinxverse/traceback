"""Report + image tests (F2, F3)."""
import io
from datetime import datetime, timedelta

from PIL import Image
from tests.conftest import register, login, auth, image_file, make_png


def _auth_client(client):
    auth(client, "owner@test.com", "Owner")
    return client


def test_create_lost_report(client, db):
    _auth_client(client)
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS",
        "title": "Lost my keys", "description": "A bunch of keys lost near the library entrance.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }, content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json()["data"]["status"] == "ACTIVE"


def test_create_found_requires_custody(client, db):
    _auth_client(client)
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "KEYS",
        "title": "Found keys", "description": "A bunch of keys found near the library entrance.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400


def test_future_date_rejected(client, db):
    _auth_client(client)
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS",
        "title": "Lost my keys", "description": "A bunch of keys lost near the library entrance.",
        "incident_date": (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
    }, content_type="multipart/form-data")
    assert r.status_code == 400


def test_unknown_field_rejected(client, db):
    _auth_client(client)
    r = client.post("/api/v1/reports", json={
        "report_type": "LOST", "category": "KEYS", "title": "x", "description": "y",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "evil_field": "1"})
    assert r.status_code == 400


def test_bad_image_type_rejected(client, db):
    _auth_client(client)
    from werkzeug.datastructures import FileStorage
    bad = FileStorage(stream=io.BytesIO(b"not an image at all"), filename="x.png",
                      content_type="image/png")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS",
        "title": "Lost keys", "description": "Keys lost near the library.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "images": bad}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_oversize_image_rejected(app, client, db):
    _auth_client(client)
    big = io.BytesIO()
    Image.new("RGB", (9000, 9000), "red").save(big, format="PNG")
    big.seek(0)
    from werkzeug.datastructures import FileStorage
    fs = FileStorage(stream=big, filename="big.png", content_type="image/png")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS",
        "title": "Lost keys", "description": "Keys lost near the library.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "images": fs}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_exif_stripped_and_resized(client, db):
    _auth_client(client)
    img = Image.new("RGB", (3000, 1500), (10, 120, 200))
    exif = img.getexif()
    exif[0x010F] = "TestCam"  # Make tag incl. fake metadata
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    from werkzeug.datastructures import FileStorage
    fs = FileStorage(stream=buf, filename="photo.jpg", content_type="image/jpeg")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS",
        "title": "Lost bag", "description": "A brown leather bag lost in the cafeteria.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "images": fs}, content_type="multipart/form-data")
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert len(data["image_urls"]) == 1
    # fetch the served image: must be <=1600px longest edge and no EXIF
    img_url = data["image_urls"][0]
    r2 = client.get(img_url)
    assert r2.status_code == 200
    served = Image.open(io.BytesIO(r2.data))
    assert max(served.size) <= 1600
    served_exif = served.getexif()
    assert dict(served_exif) == {} or 0x010F not in served_exif


def test_max_four_images(client, db):
    _auth_client(client)
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS",
        "title": "Lost bag", "description": "A brown leather bag lost in the cafeteria.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        **{f"images{i}": image_file((i * 40, 30, 30)) for i in range(5)},
        "images": image_file()}, content_type="multipart/form-data")
    # 6 image fields -> the API counts files under "images"; with mixed names
    # only files in `images` are used. Upload 5 files named images:
    files = [image_file((i * 40, 30, 30), f"{i}.png") for i in range(5)]
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS",
        "title": "Lost bag", "description": "A brown leather bag lost in the cafeteria.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        "images": files},
        content_type="multipart/form-data")
    assert r.status_code == 400


def test_owner_only_edit(client, db):
    _auth_client(client)
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS",
        "title": "Lost bag", "description": "A brown leather bag lost in the cafeteria.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    report_id = r.get_json()["data"]["id"]

    # another user cannot edit
    client.post("/api/v1/auth/logout")
    auth(client, "other@test.com", "Other")
    r = client.patch(f"/api/v1/reports/{report_id}", json={"title": "Hacked"})
    assert r.status_code == 404


def test_edit_requeues_processing(client, db):
    from app.models import Report
    from app.models.enums import ProcessingStatus
    _auth_client(client)
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS",
        "title": "Lost bag", "description": "A brown leather bag lost in the cafeteria.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    report_id = r.get_json()["data"]["id"]
    report = db.session.get(Report, report_id)
    assert report.processing_status == ProcessingStatus.READY
    r = client.patch(f"/api/v1/reports/{report_id}", json={"description": "A brand new edited description text."})
    assert r.status_code == 200
    report = db.session.get(Report, report_id)
    assert report.processing_status == ProcessingStatus.READY  # sync job re-processed


def test_close_report(client, db):
    _auth_client(client)
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "BAGS",
        "title": "Lost bag", "description": "A brown leather bag lost in the cafeteria.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    report_id = r.get_json()["data"]["id"]
    r = client.post(f"/api/v1/reports/{report_id}/close")
    assert r.status_code == 200
    assert r.get_json()["data"]["status"] == "CLOSED"
