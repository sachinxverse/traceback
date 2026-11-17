"""Issue 7 tests: who may file FOUND reports (Mode A/B, parameterised),
and the custody-based claim reviewer rule (the review table)."""
from datetime import UTC, datetime, timedelta

import pytest

from app.extensions import db
from app.models import Report
from app.models.enums import Category, ClaimStatus, Custody, MatchStatus, ReportType
from tests.conftest import (auth, create_report, login, make_institution,
                            make_staff, wait_processing)


@pytest.fixture()
def inst(db):
    return make_institution(db, name="Mode Test College")


def test_mode_b_default_user_can_file_found(client, app, inst):
    assert app.config["ALLOW_PUBLIC_FOUND_REPORTS"] is True
    auth(client, "m7-user@test.com", "ModeUser")
    r = create_report(client, report_type="FOUND", category="BAGS",
                          title="Found grey backpack", institution_id=inst.id,
                          custody="AT_INSTITUTION")
    assert r.status_code == 201, r.get_json()


def test_mode_a_user_cannot_file_found(app, monkeypatch):
    monkeypatch.setitem(app.config, "ALLOW_PUBLIC_FOUND_REPORTS", False)
    with app.test_request_context():
        pass
    from app.api.reports import _create_report
    from app.models import User
    from app import ApiError
    with app.app_context():
        user = make_staff(db, email="m7-plain@example.com")
        user.role = __import__("app.models.enums", fromlist=["Role"]).Role.USER
        db.session.commit()
        data = {"report_type": "FOUND", "category": "BAGS",
                "title": "Found grey backpack", "description": "found a grey backpack near the canteen",
                "custody": "AT_INSTITUTION",
                "incident_date": datetime.now(UTC).replace(tzinfo=None).isoformat()}
        data["incident_date"] = datetime.fromisoformat(data["incident_date"])
        with pytest.raises(ApiError) as ei:
            _create_report(user, data, [])
        assert ei.value.args or True
        assert ei.value.code == "FORBIDDEN"
        assert "institution staff" in ei.value.message


def test_mode_a_staff_can_file_found(app, monkeypatch, inst):
    monkeypatch.setitem(app.config, "ALLOW_PUBLIC_FOUND_REPORTS", False)
    with app.app_context():
        from app.api.reports import _create_report
        staff = make_staff(db, email="m7-staff2@example.com", inst_id=inst.id)
        data = {"report_type": "FOUND", "category": "BAGS",
                "title": "Found grey backpack", "description": "found a grey backpack near the canteen",
                "custody": "AT_INSTITUTION", "institution_id": inst.id,
                "incident_date": datetime.now(UTC).replace(tzinfo=None).isoformat()}
        data["incident_date"] = datetime.fromisoformat(data["incident_date"])
        report = _create_report(staff, data, [])
        assert report.custody == Custody.AT_INSTITUTION


def test_reviewer_rule_table(app, db, inst):
    """Issue 7 review table: AT_INSTITUTION → institution STAFF reviews and
    marks handed over, claimant confirms; WITH_FINDER → the finder reviews
    and hands over, claimant confirms; ADMIN can override either."""
    from app.models import Claim, Match, User
    from app.models.enums import Role

    with app.app_context():
        owner = make_staff(db, email="m7-own@example.com")   # lost reporter
        finder = make_staff(db, email="m7-find@example.com")  # found reporter
        inst_staff = make_staff(db, email="m7-inst@example.com", inst_id=inst.id)
        outsider = make_staff(db, email="m7-out@example.com")

        def report(user, rtype, custody=None):
            r = Report(user_id=user.id, title="t", description="a grey backpack near the canteen",
                       report_type=rtype, category=Category.BAGS,
                       incident_date=datetime(2026, 11, 1, 12, 0),
                       latitude=inst.latitude, longitude=inst.longitude,
                       institution_id=inst.id if rtype == ReportType.FOUND else None,
                       custody=custody)
            db.session.add(r)
            return r

        r_lost = report(owner, ReportType.LOST)
        r_found_inst = report(finder, ReportType.FOUND, Custody.AT_INSTITUTION)
        r_found_finder = report(finder, ReportType.FOUND, Custody.WITH_FINDER)
        db.session.flush()

        def claim_for(found):
            m = Match(lost_report_id=r_lost.id, found_report_id=found.id,
                      status=MatchStatus.SUGGESTED, total_score=0.9,
                      signals_used=["text"])
            db.session.add(m)
            db.session.flush()
            c = Claim(match_id=m.id, claimant_id=owner.id, report_id=found.id,
                      claim_details="Serial SN-1234 and a scratch on the left buckle are mine")
            db.session.add(c)
            db.session.flush()
            return c

        c_inst = claim_for(r_found_inst)
        c_find = claim_for(r_found_finder)

        # AT_INSTITUTION: staff of the institution reviews; outsider & finder no
        assert c_inst.can_review(inst_staff) is True
        assert c_inst.can_review(outsider) is False
        assert c_inst.can_review(finder) is False
        assert c_inst.can_review(owner) is False  # claimant can't review own
        assert c_inst.review_target == "institution"
        # WITH_FINDER: the finder reviews; institution staff doesn't
        assert c_find.can_review(finder) is True
        assert c_find.can_review(inst_staff) is False
        assert c_find.review_target == "finder"
        # ADMIN override on both
        admin = User.query.filter_by(role=Role.ADMIN).first()
        if admin is None:
            admin = User(name="Admin", email="m7-admin@example.com", role=Role.ADMIN)
            admin.set_password("Password1")
            db.session.add(admin)
            db.session.flush()
        assert c_inst.can_review(admin) is True
        assert c_find.can_review(admin) is True


def test_ui_text_matches_custody_rule(client, app):
    auth(client, "m7-ui@test.com", "ModeUI")
    r = client.get("/report/found")
    html = r.data.decode()
    assert "will verify" in html
    assert "The finder (you) will verify" in html
    assert "institution's staff will verify" in html
