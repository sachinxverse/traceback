"""Issue 1 tests: embedding provenance, no cross-model matching, health."""
import numpy as np

from app.extensions import db
from app.models import Report
from app.models.enums import Category, Custody, ProcessingStatus, ReportStatus, ReportType
from app.models.report import ReportImage
from app.services import matching as matching_svc
from app.services.embeddings import (MODEL_ONNX, MODEL_STUB, StubEmbedder,
                                     backend_model_name, from_blob, to_blob)
from tests.conftest import make_staff


def _mk_report(user, title, rtype, model, **kw):
    from datetime import datetime
    now_args = dict(
        user_id=user.id, title=title,
        description=kw.pop("description", "a blue bag near the station"),
        report_type=rtype, category=Category.BAGS,
        incident_date=kw.pop("incident_date", datetime(2026, 11, 1, 12, 0)),
        latitude=kw.pop("latitude", 30.3165),
        longitude=kw.pop("longitude", 78.0322),
        status=ReportStatus.ACTIVE,
        **kw)
    if rtype == ReportType.FOUND:
        now_args["custody"] = Custody.AT_INSTITUTION
    r = Report(**now_args)
    # text embedding from the *stub* space by default; model id overridable
    vec = StubEmbedder().embed_text(f"bags. {title}. {now_args['description']}")
    r.text_embedding = to_blob(vec)
    r.embedding_model = model
    r.embedding_dim = len(vec)
    db.session.add(r)
    return r


def test_backend_model_names_distinct():
    assert len({MODEL_STUB, MODEL_ONNX, backend_model_name("real")}) == 3
    assert backend_model_name("stub") == MODEL_STUB


def test_matching_never_compares_across_models(app, monkeypatch):
    """A candidate from a different embedding space must never be scored
    or stored as a match, even when its text is nearly identical."""
    with app.app_context():
        u = make_staff(db, email="emb-a@example.com")
        u2 = make_staff(db, email="emb-a2@example.com")
        lost = _mk_report(u, "Blue backpack", ReportType.LOST, MODEL_STUB,
                          processing_status=ProcessingStatus.READY)
        # candidate text is IDENTICAL but claims a different embedding model
        found = _mk_report(u2, "Blue backpack", ReportType.FOUND, MODEL_ONNX,
                           processing_status=ProcessingStatus.READY)
        db.session.flush()

        called = []
        real_scores = matching_svc.component_scores
        monkeypatch.setattr(matching_svc, "component_scores",
                            lambda *a, **k: called.append(1) or {})
        matching_svc.find_and_store_matches(lost, notify=False)
        assert called == [], "component_scores must not be called across models"
        from app.models import Match
        assert (Match.query.filter_by(lost_report_id=lost.id).count() == 0 and
                Match.query.filter_by(found_report_id=found.id).count() == 0)

        # now a same-model candidate IS scored — restore the real scorer
        found2 = _mk_report(u2, "Blue backpack", ReportType.FOUND, MODEL_STUB,
                            processing_status=ProcessingStatus.READY)
        db.session.flush()
        called.clear()
        def real_wrapped(*a, **k):
            called.append(1)
            return real_scores(*a, **k)
        monkeypatch.setattr(matching_svc, "component_scores", real_wrapped)
        matching_svc.find_and_store_matches(lost, notify=False)
        assert called, "same-model candidate must be scored"
        assert Match.query.filter_by(lost_report_id=lost.id,
                                     found_report_id=found2.id).count() == 1


def test_image_vectors_only_same_model(app):
    with app.app_context():
        u = make_staff(db, email="emb-b@example.com")
        lost = _mk_report(u, "Red umbrella", ReportType.LOST, MODEL_STUB)
        # two candidate images: same text model id as reference, but one
        # image vector claims a different image model — it must be excluded
        found = _mk_report(u, "Red umbrella", ReportType.FOUND, MODEL_STUB)
        db.session.flush()
        stub_vec = np.ones(512, dtype=np.float32) / np.sqrt(512)
        other_vec = np.ones(768, dtype=np.float32) / np.sqrt(768)
        img_same = ReportImage(
            report_id=found.id, storage_key="k1", embedding=to_blob(stub_vec),
            embedding_model=MODEL_STUB, embedding_dim=512)
        img_other = ReportImage(
            report_id=found.id, storage_key="k2", embedding=to_blob(other_vec),
            embedding_model=MODEL_ONNX, embedding_dim=768)
        db.session.add_all([img_same, img_other])
        db.session.flush()

        eligible = [from_blob(i.embedding, i.embedding_dim) for i in found.images
                    if i.embedding_model == MODEL_STUB]
        assert len(eligible) == 1, "only same-model image vectors are eligible"
        assert eligible[0].shape == (512,)


def test_health_reports_model(app, client):
    resp = client.get("/api/v1/health")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["embedding_backend"] == app.config["EMBEDDING_BACKEND"]
    assert body["model"] == backend_model_name(app.config["EMBEDDING_BACKEND"])
