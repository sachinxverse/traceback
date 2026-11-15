"""Matching engine tests (F4, F5, Section 9, acceptance A3-A5)."""
from datetime import datetime, timedelta, timezone

from tests.conftest import auth, register, login, image_file


def _patterned_png(colour, name, size=(220, 180)):
    """Image dominated by the given colour (small white mark in a corner) so
    the stub embedder distinguishes different colours by direction."""
    import io
    from PIL import Image, ImageDraw
    from werkzeug.datastructures import FileStorage
    img = Image.new("RGB", size, colour)
    d = ImageDraw.Draw(img)
    d.line([size[0] - 30, 0, size[0] - 10, 20], fill="white", width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename=name, content_type="image/png")


def _submit(client, report_type, title, desc, days_ago, images_spec,
            lat=None, lng=None, category="WALLETS_CARDS", custody=None, inst=None):
    data = {
        "report_type": report_type, "category": category,
        "title": title, "description": desc,
        "incident_date": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if lat is not None:
        data["latitude"] = str(lat)
        data["longitude"] = str(lng)
    if custody:
        data["custody"] = custody
    if inst:
        data["institution_id"] = str(inst)
    payload = {**data}
    for i, (colour, name) in enumerate(images_spec):
        payload[f"images"] = _patterned_png(colour, name)
    return client.post("/api/v1/reports", data=payload, content_type="multipart/form-data")


def _red_png(name):
    import io
    from PIL import Image
    from werkzeug.datastructures import FileStorage
    buf = io.BytesIO()
    Image.new("RGB", (220, 180), (180, 30, 30)).save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename=name, content_type="image/png")


def test_full_match_flow_lost_first_then_found(client, app):
    """A3: lost then found of the same item with different wording -> HIGH/MEDIUM."""
    auth(client, "u1@test.com", "User1")
    r = _submit(client, "LOST", "Lost my red school backpack",
                "I lost my red backpack with two straps and a broken zip near the park gate.",
                2, [((180, 30, 30), "lost.png")])
    assert r.status_code == 201
    lost = r.get_json()["data"]
    client.post("/api/v1/auth/logout")

    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Backpack found at entrance",
                "A red double-strap schoolbag was found at the park entrance and handed in.",
                1, [((185, 40, 35), "found.png")], custody="WITH_FINDER")
    found = r.get_json()["data"]
    assert found["processing_status"] == "READY"

    r = client.get(f"/api/v1/reports/{found['id']}/matches")
    matches = r.get_json()["data"]
    assert len(matches) == 1
    m = matches[0]
    assert m["confidence"] in ("HIGH", "MEDIUM")
    assert "counterpart" in m
    client.post("/api/v1/auth/logout")

    # the lost side sees the match too
    login(client, "u1@test.com")
    r = client.get(f"/api/v1/reports/{lost['id']}/matches")
    assert len(r.get_json()["data"]) == 1


def test_match_flow_found_first(client, app):
    """A3 in the other creation order."""
    auth(client, "u1@test.com", "User1")
    r = _submit(client, "FOUND", "Wallet found on bench",
                "A brown leather wallet was found on a bench and deposited at the desk.",
                1, [((120, 70, 20), "f.png")], custody="WITH_FINDER")
    found = r.get_json()["data"]
    client.post("/api/v1/auth/logout")

    auth(client, "u2@test.com", "User2")
    r = _submit(client, "LOST", "Lost brown leather wallet",
                "I lost my brown wallet made of leather today near the bench area.",
                2, [((118, 75, 22), "l.png")])
    lost = r.get_json()["data"]
    r = client.get(f"/api/v1/reports/{lost['id']}/matches")
    matches = r.get_json()["data"]
    assert len(matches) >= 1
    assert matches[0]["confidence"] in ("HIGH", "MEDIUM")


def test_unrelated_item_not_matched(client, app):
    """A4: same category but a genuinely different object must not reach the
    minimum score (no shared keywords, distinct colours)."""
    auth(client, "u1@test.com", "User1")
    r = _submit(client, "LOST", "Lost silver metal thermos flask",
                "I misplaced my silver metal thermos flask at the swimming pool.",
                1, [((205, 205, 205), "l.png")], category="SPORTS")
    client.post("/api/v1/auth/logout")
    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Red bicycle helmet handed in",
                "A red cycling helmet was handed in at the reception desk tonight.",
                1, [((200, 30, 30), "f.png")], category="SPORTS", custody="WITH_FINDER")
    found = r.get_json()["data"]
    r = client.get(f"/api/v1/reports/{found['id']}/matches")
    matches = r.get_json()["data"]
    assert not matches


def test_same_user_reports_never_match(client, app):
    auth(client, "u1@test.com", "User1")
    r = _submit(client, "LOST", "Lost blue notebook",
                "Lost my blue spiral notebook with notes inside, near the canteen.",
                1, [((20, 40, 200), "l.png")])
    r2 = _submit(client, "FOUND", "Blue notebook found",
                 "A blue spiral notebook was found near the canteen area.",
                 0, [((20, 40, 200), "f.png")], custody="WITH_FINDER")
    found = r2.get_json()["data"]
    r = client.get(f"/api/v1/reports/{found['id']}/matches")
    assert r.get_json()["data"] == []


def test_missing_location_and_images_still_process(client, app):
    """A5: no location, no photo — renormalised scoring, signals shown."""
    auth(client, "u1@test.com", "User1")
    r = _submit(client, "LOST", "Lost silver watch",
                "I lost my silver wristwatch with a leather band in the library hall.",
                1, [])
    assert r.status_code == 201
    lost = r.get_json()["data"]
    assert lost["processing_status"] == "READY"
    client.post("/api/v1/auth/logout")

    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Wristwatch handed in",
                "A silver watch with a leather band was handed in at the library desk.",
                0, [], custody="WITH_FINDER")
    found = r.get_json()["data"]
    r = client.get(f"/api/v1/reports/{found['id']}/matches")
    matches = r.get_json()["data"]
    assert matches
    m = matches[0]
    assert "image" not in m["signals_used"]
    assert m["breakdown"]["image"] is None


def test_category_filter_blocks_match(client, app):
    auth(client, "u1@test.com", "User1")
    _submit(client, "LOST", "Lost red ball",
            "I lost my red football on the field yesterday evening.", 1,
            [((200, 40, 40), "l.png")], category="SPORTS")
    client.post("/api/v1/auth/logout")
    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Red ball found",
                "A red football was found near the field and kept at the desk.",
                1, [((200, 45, 40), "f.png")], category="ELECTRONICS", custody="WITH_FINDER")
    found = r.get_json()["data"]
    r = client.get(f"/api/v1/reports/{found['id']}/matches")
    assert r.get_json()["data"] == []


def test_time_window_blocks_match(client, app):
    auth(client, "u1@test.com", "User1")
    _submit(client, "LOST", "Lost green flask",
            "I lost my green water flask in the sports hall this week.", 1,
            [((20, 150, 60), "l.png")], category="BOTTLES_LUNCHBOXES")
    client.post("/api/v1/auth/logout")
    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Green flask found",
                "A green water flask was found in the sports hall yesterday.", 120,
                [((20, 150, 60), "f.png")], category="BOTTLES_LUNCHBOXES", custody="WITH_FINDER")
    found = r.get_json()["data"]
    r = client.get(f"/api/v1/reports/{found['id']}/matches")
    assert r.get_json()["data"] == []


def test_distance_filter_blocks_match(client, app):
    auth(client, "u1@test.com", "User1")
    _submit(client, "LOST", "Lost yellow pouch",
            "I lost my small yellow pouch near the north city bus station.", 1,
            [((230, 200, 40), "l.png")], lat=30.10, lng=78.10)
    client.post("/api/v1/auth/logout")
    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Yellow pouch found",
                "A small yellow pouch was found near the south bus station area.", 0,
                [((230, 200, 40), "f.png")], lat=31.10, lng=79.10,
                category="BAGS", custody="WITH_FINDER")
    found = r.get_json()["data"]
    r = client.get(f"/api/v1/reports/{found['id']}/matches")
    assert r.get_json()["data"] == []


def test_no_duplicate_matches_on_rerun(client, app, db):
    from app.models import Match
    auth(client, "u1@test.com", "User1")
    r = _submit(client, "LOST", "Lost purple hat",
                "I lost my purple beanie hat outside the gym yesterday.", 1,
                [((140, 40, 160), "l.png")])
    lost_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Purple hat found",
                "A purple beanie hat was found outside the gym entrance.", 1,
                [((140, 40, 160), "f.png")], custody="WITH_FINDER")
    found_id = r.get_json()["data"]["id"]

    from app.services.jobs import process_report
    with app.app_context():
        from app.models import Report
        report = db.session.get(Report, lost_id)
        process_report(lost_id)
        count = Match.query.filter_by(lost_report_id=lost_id,
                                      found_report_id=found_id).count()
        assert count == 1
        process_report(lost_id)
        count = Match.query.filter_by(lost_report_id=lost_id,
                                      found_report_id=found_id).count()
        assert count == 1


def test_scores_update_when_report_edited(client, app, db):
    auth(client, "u1@test.com", "User1")
    r = _submit(client, "LOST", "Lost orange cap",
                "I lost my orange baseball cap at the pool today.", 1,
                [((240, 140, 30), "l.png")])
    lost_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    auth(client, "u2@test.com", "User2")
    r = _submit(client, "FOUND", "Orange cap found",
                "An orange baseball cap was found at the pool side.", 1,
                [((240, 140, 30), "f.png")], custody="WITH_FINDER")
    found_id = r.get_json()["data"]["id"]
    from app.models import Match, Report
    with app.app_context():
        m = Match.query.filter_by(lost_report_id=lost_id, found_report_id=found_id).first()
        before = m.total_score
    # switch back to the owner of the lost report and edit it
    client.post("/api/v1/auth/logout")
    login(client, "u1@test.com")
    r = client.patch(f"/api/v1/reports/{lost_id}",
                     json={"description": "Completely different words about a metal teapot and cups."})
    assert r.status_code == 200
    with app.app_context():
        m = Match.query.filter_by(lost_report_id=lost_id, found_report_id=found_id).first()
        assert m.total_score != before or m.status.value == "EXPIRED"
