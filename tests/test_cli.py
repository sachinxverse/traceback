"""CLI tests (Section 15.3)."""
import os
from datetime import datetime

from tests.conftest import auth, image_file


def test_seed_demo_idempotent(app, client):
    from scripts.seed_demo import run_seed
    with app.app_context():
        result = run_seed(app)
        assert isinstance(result, dict)
        again = run_seed(app)
        assert again == "already seeded"


def test_create_admin_command(app, runner=None):
    from click.testing import CliRunner
    runner = CliRunner()
    from app.cli import register as register_cli
    # commands are registered on the app; invoke via app.cli
    result = runner.invoke(
        app.cli.commands["create-admin"],
        ["--email", "cli-admin@x.com", "--name", "CLI Admin"],
        input="StrongPass1\nStrongPass1\n")
    assert "Admin created" in result.output, result.output
    from app.models import User
    with app.app_context():
        u = User.query.filter_by(email="cli-admin@x.com").first()
        assert u is not None and u.role.value == "ADMIN"


def test_expire_reports(app, db):
    from app.models import Report
    from app.models.enums import ReportStatus
    auth(client := app.test_client(), "exp@x.com", "E")
    r = client.post("/api/v1/reports", data={
        "report_type": "LOST", "category": "KEYS", "title": "Old keys",
        "description": "A report that will be expired by the CLI command.",
        "incident_date": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")},
        content_type="multipart/form-data")
    rid = r.get_json()["data"]["id"]
    rep = db.session.get(Report, rid)
    rep.created_at = datetime(2000, 1, 1)
    db.session.commit()
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app.cli.commands["expire-reports"])
    assert "Expired" in result.output
    assert db.session.get(Report, rid).status == ReportStatus.EXPIRED


def test_reindex_command(app, db):
    auth(app.test_client(), "rx@x.com", "R")
    from click.testing import CliRunner
    result = CliRunner().invoke(app.cli.commands["reindex"])
    assert "Reindex complete" in result.output
