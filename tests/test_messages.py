"""Messaging tests (F9, Section 10.4)."""
from datetime import UTC, datetime, timedelta

from tests.conftest import CsrfClient, auth, login


def _img(colour):
    import io

    from PIL import Image
    from werkzeug.datastructures import FileStorage
    buf = io.BytesIO()
    Image.new("RGB", (220, 180), colour).save(buf, format="PNG")
    buf.seek(0)
    return FileStorage(stream=buf, filename="p.png", content_type="image/png")


def _setup_with_claim(client):
    auth(client, "owner@test.com", "Owner")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS", "title": "Lost wallet",
        "description": "Lost my wallet near the cafe with a zip pocket.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((120, 70, 20))}, content_type="multipart/form-data")
    lost_id = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    auth(client, "finder@test.com", "Finder")
    r = client.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "WALLETS_CARDS", "title": "Wallet found",
        "description": "A wallet with a zip pocket was found near the cafe area.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "custody": "WITH_FINDER", "images": _img((125, 75, 25))},
        content_type="multipart/form-data")
    found_id = r.get_json()["data"]["id"]
    match_id = client.get(f"/api/v1/reports/{found_id}/matches").get_json()["data"][0]["id"]
    return lost_id, found_id, match_id


def test_messaging_blocked_before_claim(client):
    lost_id, found_id, match_id = _setup_with_claim(client)
    r = client.get(f"/api/v1/matches/{match_id}/messages")
    assert r.status_code == 409
    r = client.post(f"/api/v1/matches/{match_id}/messages", json={"message": "hi"})
    assert r.status_code == 409


def test_messaging_flow_and_polling(client):
    lost_id, found_id, match_id = _setup_with_claim(client)
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    claim_id = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": "It has a gym membership card and a cracked corner."},
        content_type="multipart/form-data").get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    r = client.post(f"/api/v1/matches/{match_id}/messages", json={"message": "Hello, when can we meet?"})
    assert r.status_code == 201
    mid = r.get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")

    login(client, "owner@test.com")
    r = client.get(f"/api/v1/matches/{match_id}/messages")
    msgs = r.get_json()["data"]
    assert len(msgs) == 1
    r = client.get(f"/api/v1/matches/{match_id}/messages?after_id={mid}")
    assert r.get_json()["data"] == []
    client.post("/api/v1/auth/logout")

    # third party cannot read
    auth(client, "stranger@test.com", "Stranger")
    r = client.get(f"/api/v1/matches/{match_id}/messages")
    assert r.status_code == 404


def test_message_escaping_and_length(client, db):
    lost_id, found_id, match_id = _setup_with_claim(client)
    client.post("/api/v1/auth/logout")
    login(client, "owner@test.com")
    claim_id = client.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": "It has a gym membership card and a cracked corner."},
        content_type="multipart/form-data").get_json()["data"]["id"]
    client.post("/api/v1/auth/logout")
    login(client, "finder@test.com")
    client.post(f"/api/v1/claims/{claim_id}/approve", json={})
    r = client.post(f"/api/v1/matches/{match_id}/messages", json={"message": "<script>alert(1)</script>"})
    assert r.status_code == 201
    r = client.post(f"/api/v1/matches/{match_id}/messages", json={"message": "x" * 1001})
    assert r.status_code == 400


def test_message_rate_limit(app, db):
    import app.services.storage as storage_mod
    from app import create_app
    from app.services.embeddings import reset_embedder
    reset_embedder()
    storage_mod.reset_storage()
    app2 = create_app("testing", ratelimit_enabled=True)
    app2.test_client_class = CsrfClient
    with app2.app_context():
        db.create_all()
    client2 = app2.test_client()

    auth(client2, "rl-owner@test.com", "Owner")
    r = client2.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "WALLETS_CARDS", "title": "Lost wallet rl",
        "description": "Lost my wallet near the cafe with a zip pocket here.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        "images": _img((120, 70, 20))}, content_type="multipart/form-data")
    r.get_json()["data"]["id"]
    client2.post("/api/v1/auth/logout")
    auth(client2, "rl-finder@test.com", "Finder")
    r = client2.post("/api/v1/reports", data={
        "report_type": "FOUND", "category": "WALLETS_CARDS", "title": "Wallet found rl",
        "description": "A wallet with a zip pocket was found near the cafe area.",
        "incident_date": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S"),
        "custody": "WITH_FINDER", "images": _img((125, 75, 25))},
        content_type="multipart/form-data")
    found_id = r.get_json()["data"]["id"]
    match_id = client2.get(f"/api/v1/reports/{found_id}/matches").get_json()["data"][0]["id"]
    client2.post("/api/v1/auth/logout")

    login(client2, "rl-owner@test.com")
    claim_id = client2.post(f"/api/v1/matches/{match_id}/claims", data={
        "claim_details": "It has a gym membership card and a cracked corner."},
        content_type="multipart/form-data").get_json()["data"]["id"]
    client2.post("/api/v1/auth/logout")
    login(client2, "rl-finder@test.com")
    client2.post(f"/api/v1/claims/{claim_id}/approve", json={})

    statuses = []
    for i in range(25):
        r = client2.post(f"/api/v1/matches/{match_id}/messages",
                         json={"message": f"msg number {i} for rate limiting test"})
        statuses.append(r.status_code)
    assert 429 in statuses
