"""Report endpoints (Section 7.4)."""

from flask import Blueprint, current_app, jsonify, request

from .. import ApiError
from ..extensions import db, limiter
from ..models import Match, Report, ReportImage
from ..models.enums import (
    Category,
    Custody,
    MatchStatus,
    ProcessingStatus,
    ReportStatus,
    ReportType,
)
from ..schemas import ReportCreateSchema, ReportUpdateSchema, load_json
from ..services import images as image_service
from ..services.jobs import enqueue_report_processing
from ._auth import current_user, get_report_or_404
from ._paging import page_params, paginated

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")

MATCHING_FIELDS = ("category", "title", "description", "incident_date",
                   "latitude", "longitude", "location_text")


def _parse_coordinates(data):
    lat = data.get("latitude")
    lng = data.get("longitude")
    if (lat is None) != (lng is None):
        raise ApiError("VALIDATION_ERROR", "latitude and longitude must be provided together",
                       details={"latitude": ["Provide both latitude and longitude or neither"]})
    return lat, lng


def _create_report(user, data, files):
    report = Report(
        user_id=user.id,
        report_type=ReportType(data["report_type"]),
        category=Category(data["category"]),
        title=data["title"].strip(),
        description=data["description"].strip(),
        private_details=(data.get("private_details") or "").strip() or None,
        incident_date=data["incident_date"],
        location_text=(data.get("location_text") or "").strip() or None,
    )
    lat, lng = _parse_coordinates(data)
    report.latitude = lat
    report.longitude = lng

    if data.get("institution_id"):
        from ..models import Institution
        inst = db.session.get(Institution, data["institution_id"])
        if inst is None:
            raise ApiError("VALIDATION_ERROR", "Unknown institution",
                           details={"institution_id": ["Unknown institution"]})
        report.institution_id = inst.id
    elif user.institution_id:
        report.institution_id = user.institution_id

    if report.is_found:
        report.custody = Custody(data["custody"])
        if not data.get("institution_id") and user.institution_id is None:
            pass  # finder custody does not need an institution
    else:
        report.custody = None

    # validate images first so a bad file aborts before anything is saved
    existing = 0
    image_service.save_report_images(
        report, files, existing_count=existing,
        max_images=current_app.config["MAX_IMAGES_PER_REPORT"],
        max_mb=current_app.config["MAX_IMAGE_MB"])

    db.session.add(report)
    db.session.commit()
    enqueue_report_processing(current_app._get_current_object(), report.id)
    return report


@reports_bp.post("")
@limiter.limit("20 per hour")
def create_report():
    user = current_user()
    form = request.form
    data = load_json(ReportCreateSchema(), {k: form[k] for k in form})
    files = [f for f in request.files.getlist("images") if f and f.filename]
    if len(files) > current_app.config["MAX_IMAGES_PER_REPORT"]:
        raise ApiError("BAD_REQUEST",
                       f"At most {current_app.config['MAX_IMAGES_PER_REPORT']} images per report",
                       status=400)
    report = _create_report(user, data, files)
    return jsonify({"data": report.owner_dict()}), 201


@reports_bp.get("/mine")
def my_reports():
    user = current_user()
    rtype = request.args.get("type")
    status = request.args.get("status")
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)

    q = Report.query.filter_by(user_id=user.id)
    if rtype:
        q = q.filter(Report.report_type == ReportType(rtype))
    if status:
        q = q.filter(Report.status == ReportStatus(status))
    q = q.order_by(Report.created_at.desc())
    pag = q.paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for r in pag.items:
        d = r.owner_dict()
        d["match_count"], d["top_score"] = _match_stats(r)
        d["image_urls"] = [img.url for img in r.images]
        items.append(d)
    return jsonify({"data": items, "meta": {
        "page": pag.page, "per_page": pag.per_page, "total": pag.total, "pages": pag.pages}})


def _match_stats(report):
    if report.is_lost:
        q = Match.query.filter(Match.lost_report_id == report.id)
    else:
        q = Match.query.filter(Match.found_report_id == report.id)
    q = q.filter(Match.status != MatchStatus.EXPIRED)
    top = q.order_by(Match.total_score.desc()).first()
    return (q.count(), round(top.total_score * 100) if top else None)


@reports_bp.get("/browse")
def browse():
    """Authenticated browse of ACTIVE found reports (public fields only)."""
    current_user()  # auth guard
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    q = Report.query.filter(Report.report_type == ReportType.FOUND,
                            Report.status == ReportStatus.ACTIVE)
    if request.args.get("category"):
        q = q.filter(Report.category == Category(request.args["category"]))
    if request.args.get("institution_id"):
        q = q.filter(Report.institution_id == int(request.args["institution_id"]))
    if request.args.get("date_from"):
        from datetime import datetime
        q = q.filter(Report.incident_date >= datetime.fromisoformat(request.args["date_from"]))
    if request.args.get("date_to"):
        from datetime import datetime
        q = q.filter(Report.incident_date <= datetime.fromisoformat(request.args["date_to"]))
    if request.args.get("q"):
        kw = f"%{request.args['q'].strip()}%"
        q = q.filter((Report.title.ilike(kw)) | (Report.description.ilike(kw)))
    q = q.order_by(Report.created_at.desc())
    pag = q.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"data": [r.public_dict() for r in pag.items], "meta": {
        "page": pag.page, "per_page": pag.per_page, "total": pag.total, "pages": pag.pages}})


@reports_bp.get("/<int:report_id>")
def get_report(report_id):
    user = current_user()
    report = get_report_or_404(report_id, user)
    is_owner = report.user_id == user.id
    if is_owner or user.role.value == "ADMIN" or (
            user.role.value == "STAFF" and user.institution_id == report.institution_id):
        d = report.owner_dict()
    else:
        d = report.public_dict()
    d["image_urls"] = [img.url for img in report.images]
    return jsonify({"data": d})


@reports_bp.patch("/<int:report_id>")
def update_report(report_id):
    user = current_user()
    report = get_report_or_404(report_id, user, level="owner")
    if report.status != ReportStatus.ACTIVE:
        raise ApiError("CONFLICT", "Only ACTIVE reports can be edited", status=409)
    data = load_json(ReportUpdateSchema(), request.get_json(silent=True) or {})
    relevant_change = False
    for field in ("title", "description", "private_details", "location_text"):
        if field in data:
            val = data[field]
            if isinstance(val, str):
                val = val.strip()
                val = val or None if field == "private_details" else val
            setattr(report, field, val)
            if field in MATCHING_FIELDS:
                relevant_change = True
    if "category" in data:
        report.category = Category(data["category"])
        relevant_change = True
    if "incident_date" in data:
        report.incident_date = data["incident_date"]
        relevant_change = True
    if "custody" in data and report.is_found:
        report.custody = Custody(data["custody"]) if data["custody"] else report.custody
    if "latitude" in data or "longitude" in data:
        lat, lng = _parse_coordinates(data)
        report.latitude = lat if lat is not None else report.latitude
        report.longitude = lng if lng is not None else report.longitude
        relevant_change = True
    db.session.commit()
    if relevant_change:
        report.processing_status = ProcessingStatus.PENDING
        db.session.commit()
        enqueue_report_processing(current_app._get_current_object(), report.id)
    return jsonify({"data": report.owner_dict()})


@reports_bp.post("/<int:report_id>/close")
def close_report(report_id):
    user = current_user()
    report = get_report_or_404(report_id, user, level="owner")
    if report.status == ReportStatus.RECOVERED:
        raise ApiError("CONFLICT", "Recovered reports cannot be closed", status=409)
    if any(c.verification_status == ClaimStatus.APPROVED for m in _matches_of(report)
           for c in m.claims):
        raise ApiError("CONFLICT", "Cannot close a report with an approved claim", status=409)
    report.status = ReportStatus.CLOSED
    # A3: reject every live claim linked to this report, release counterparts,
    # expire matches and notify the affected users.
    from ..services import claims as claim_service
    claim_service.close_claims_for_report(report, actor=user)
    for m in _matches_of(report):
        if m.status in (MatchStatus.SUGGESTED, MatchStatus.CLAIMED):
            m.status = MatchStatus.EXPIRED
    db.session.commit()
    return jsonify({"data": report.owner_dict()})


def _matches_of(report):
    if report.is_lost:
        return Match.query.filter(Match.lost_report_id == report.id).all()
    return Match.query.filter(Match.found_report_id == report.id).all()


from ..models.enums import ClaimStatus


@reports_bp.post("/<int:report_id>/images")
def add_images(report_id):
    user = current_user()
    report = get_report_or_404(report_id, user, level="owner")
    files = [f for f in request.files.getlist("images") if f and f.filename]
    existing = len(report.images)
    image_service.save_report_images(
        report, files, existing_count=existing,
        max_images=current_app.config["MAX_IMAGES_PER_REPORT"],
        max_mb=current_app.config["MAX_IMAGE_MB"])
    report.processing_status = ProcessingStatus.PENDING
    db.session.commit()
    enqueue_report_processing(current_app._get_current_object(), report.id)
    return jsonify({"data": report.owner_dict()}), 201


@reports_bp.delete("/<int:report_id>/images/<int:image_id>")
def delete_image(report_id, image_id):
    user = current_user()
    report = get_report_or_404(report_id, user, level="owner")
    img = ReportImage.query.filter_by(id=image_id, report_id=report.id).first()
    if img is None:
        raise ApiError("NOT_FOUND", "Image not found", status=404)
    db.session.delete(img)
    report.processing_status = ProcessingStatus.PENDING
    db.session.commit()
    enqueue_report_processing(current_app._get_current_object(), report.id)
    return jsonify({"data": {"ok": True}})


@reports_bp.get("/<int:report_id>/matches")
def report_matches(report_id):
    user = current_user()
    report = get_report_or_404(report_id, user)
    page, per_page = page_params()
    if report.is_lost:
        q = Match.query.filter(Match.lost_report_id == report.id)
        for_lost = True
        dismissed = Match.lost_dismissed
    else:
        q = Match.query.filter(Match.found_report_id == report.id)
        for_lost = False
        dismissed = Match.found_dismissed
    q = q.filter(dismissed.is_(False), Match.status != MatchStatus.EXPIRED)
    q = q.options(db.joinedload(Match.lost_report).joinedload(Report.images),
                  db.joinedload(Match.found_report).joinedload(Report.images))
    return jsonify(paginated(q, page, per_page,
                             lambda m: m.to_dict(for_lost_side=for_lost),
                             order_by=Match.total_score.desc()))


@reports_bp.post("/<int:report_id>/rematch")
def rematch(report_id):
    user = current_user()
    report = get_report_or_404(report_id, user, level="owner")
    report.processing_status = ProcessingStatus.PENDING
    db.session.commit()
    from ..services.jobs import process_report
    process_report(report.id)
    return jsonify({"data": report.owner_dict()})
