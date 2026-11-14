"""Background job runner (Section 2/9.1): ThreadPoolExecutor with max 2
workers. Jobs enqueue after a report is saved; TestingConfig sets JOBS_SYNC so
matching completes inside the request."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("traceback.jobs")

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _get_executor(app):
    global _executor
    if _executor is None:
        with _lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=app.config.get("JOBS_MAX_WORKERS", 2),
                    thread_name_prefix="traceback-job",
                )
    return _executor


def enqueue_report_processing(app, report_id: int):
    """Queue process_report for a saved report (sync when JOBS_SYNC)."""
    from flask import has_app_context
    if app.config.get("JOBS_SYNC"):
        if has_app_context():
            # Already inside the request's app context: run in-place so the
            # caller sees the updated processing status.
            process_report(report_id)
        else:
            with app.app_context():
                process_report(report_id)
        return

    def _run():
        with app.app_context():
            try:
                process_report(report_id)
            except Exception:  # pragma: no cover
                log.exception("Report processing job failed for report %s", report_id)

    _get_executor(app).submit(_run)


def process_report(report_id: int):
    """Generate embeddings for a report and run matching (Section 9.1)."""
    from ..extensions import db
    from ..models import Report, ReportImage
    from ..models.enums import ProcessingStatus
    from .embeddings import get_embedder, to_blob, from_blob, IMAGE_DIM
    from .matching import find_and_store_matches

    report = db.session.get(Report, report_id)
    if report is None:
        return
    app = None  # current app context
    from flask import current_app
    app = current_app._get_current_object()
    try:
        embedder = get_embedder(app)
        storage_backend_module = None
        from .storage import get_storage
        storage = get_storage(app)

        for img in report.images:
            if img.embedding is None:
                try:
                    data = storage.open(img.storage_key)
                    img.embedding = to_blob(embedder.embed_image(data))
                except Exception:
                    log.exception("Failed to embed image %s of report %s", img.id, report.id)

        report.text_embedding = to_blob(
            embedder.embed_text(f"{report.category.value.lower()}. {report.title}. {report.description}"))

        report.processing_status = ProcessingStatus.READY
        db.session.commit()
        find_and_store_matches(report)
    except Exception:
        db.session.rollback()
        report = db.session.get(Report, report_id)
        if report is not None:
            report.processing_status = ProcessingStatus.FAILED
            db.session.commit()
        log.exception("Embedding/matching failed for report %s", report_id)


def reindex_all(app):
    """Recompute all embeddings and matches (flask reindex)."""
    from ..extensions import db
    from ..models import Report, ReportImage
    from ..models.enums import ProcessingStatus
    from .embeddings import get_embedder, to_blob
    from .matching import find_and_store_matches

    with app.app_context():
        embedder = get_embedder(app)
        from .storage import get_storage
        storage = get_storage(app)
        for report in Report.query.all():
            for img in report.images:
                try:
                    data = storage.open(img.storage_key)
                    img.embedding = to_blob(embedder.embed_image(data))
                except Exception:
                    log.exception("Reindex: failed to embed image %s", img.id)
            report.text_embedding = to_blob(
                embedder.embed_text(
                    f"{report.category.value.lower()}. {report.title}. {report.description}"))
            report.processing_status = ProcessingStatus.READY
        db.session.commit()
        for report in Report.query.all():
            find_and_store_matches(report, notify=False)
