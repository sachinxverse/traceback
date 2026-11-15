"""Admin endpoints (Section 7.6)."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from .. import ApiError
from ..extensions import db, limiter
from ..models import AuditLog, Claim, Match, Report, User
from ..models.enums import (ClaimStatus, MatchStatus, ProcessingStatus,
                            ReportStatus, Role)
from ..schemas import AdminUserPatchSchema, RemoveReportSchema, ResolveSchema, load_json
from ._auth import current_user, roles_required
from ..services.audit import log_action
from ..services.notifications import notify

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _staff_scope(user, query):
    """STAFF see only their institution's rows; ADMIN sees everything."""
    if user.role == Role.STAFF:
        return query.filter(Report.institution_id == user.institution_id)
    return query


# ------------------------------------------------------------------ users
@admin_bp.get("/users")
@roles_required(Role.ADMIN)
def list_users():
    q = User.query
    if request.args.get("q"):
        kw = f"%{request.args['q'].strip()}%"
        q = q.filter((User.name.ilike(kw)) | (User.email.ilike(kw)))
    if request.args.get("role"):
        q = q.filter(User.role == Role(request.args["role"]))
    if request.args.get("is_active") is not None:
        val = request.args["is_active"].lower() in ("true", "1")
        q = q.filter(User.is_active.is_(val))
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    pag = q.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"data": [u.to_dict() for u in pag.items], "meta": {
        "page": pag.page, "per_page": pag.per_page, "total": pag.total, "pages": pag.pages}})


@admin_bp.patch("/users/<int:user_id>")
@roles_required(Role.ADMIN)
def patch_user(user_id):
    admin = current_user()
    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError("NOT_FOUND", "User not found", status=404)
    if user.id == admin.id:
        raise ApiError("CONFLICT", "Admins cannot change their own role or status", status=409)
    data = load_json(AdminUserPatchSchema(), request.get_json(silent=True) or {})
    before = user.to_dict()
    if "role" in data:
        user.role = Role(data["role"])
        if user.role != Role.STAFF:
            user.institution_id = None
    if "is_active" in data:
        user.is_active = data["is_active"]
    if "institution_id" in data:
        user.institution_id = data["institution_id"]
    db.session.commit()
    log_action("user_update", actor=admin, target_type="user", target_id=user.id,
               details={"before": before, "after": user.to_dict()})
    return jsonify({"data": user.to_dict()})


# ------------------------------------------------------------------ reports
@admin_bp.get("/reports")
@roles_required(Role.ADMIN, Role.STAFF)
def admin_reports():
    user = current_user()
    q = Report.query
    q = _staff_scope(user, q)
    if request.args.get("type"):
        from ..models.enums import ReportType
        q = q.filter(Report.report_type == ReportType(request.args["type"]))
    if request.args.get("status"):
        q = q.filter(Report.status == ReportStatus(request.args["status"]))
    if request.args.get("category"):
        from ..models.enums import Category
        q = q.filter(Report.category == Category(request.args["category"]))
    if request.args.get("date_from"):
        q = q.filter(Report.created_at >= datetime.fromisoformat(request.args["date_from"]))
    if request.args.get("date_to"):
        q = q.filter(Report.created_at <= datetime.fromisoformat(request.args["date_to"]))
    if request.args.get("q"):
        kw = f"%{request.args['q'].strip()}%"
        q = q.filter((Report.title.ilike(kw)) | (Report.description.ilike(kw)))
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    pag = q.order_by(Report.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"data": [r.owner_dict() for r in pag.items], "meta": {
        "page": pag.page, "per_page": pag.per_page, "total": pag.total, "pages": pag.pages}})


@admin_bp.post("/reports/<int:report_id>/remove")
@roles_required(Role.ADMIN, Role.STAFF)
def remove_report(report_id):
    user = current_user()
    report = db.session.get(Report, report_id)
    if report is None:
        raise ApiError("NOT_FOUND", "Report not found", status=404)
    if user.role == Role.STAFF and user.institution_id != report.institution_id:
        raise ApiError("NOT_FOUND", "Report not found", status=404)
    data = load_json(RemoveReportSchema(), request.get_json(silent=True) or {})
    report.status = ReportStatus.REMOVED
    report.removed_reason = data["reason"]
    # A3: moderation removal must also cancel live claims and notify users.
    from ..services import claims as claim_service
    claim_service.close_claims_for_report(report, actor=user,
                                          reason="Item report was removed by moderators")
    _expire_matches(report)
    db.session.commit()
    notify(report.user_id, "REPORT_REMOVED",
           f"Your report was removed by moderators: {data['reason']}",
           link=f"/reports/{report.id}", related_report_id=report.id)
    log_action("report_remove", actor=user, target_type="report", target_id=report.id,
               details={"reason": data["reason"]})
    return jsonify({"data": report.owner_dict()})


@admin_bp.post("/reports/<int:report_id>/restore")
@roles_required(Role.ADMIN)
def restore_report(report_id):
    user = current_user()
    report = db.session.get(Report, report_id)
    if report is None:
        raise ApiError("NOT_FOUND", "Report not found", status=404)
    if report.status != ReportStatus.REMOVED:
        raise ApiError("CONFLICT", "Only REMOVED reports can be restored", status=409)
    report.status = ReportStatus.ACTIVE
    report.removed_reason = None
    report.processing_status = ProcessingStatus.PENDING
    db.session.commit()
    from ..services.jobs import process_report
    process_report(report.id)
    log_action("report_restore", actor=user, target_type="report", target_id=report.id)
    return jsonify({"data": report.owner_dict()})


def _expire_matches(report):
    cols = [Match.lost_report_id, Match.found_report_id]
    for m in Match.query.filter(
            (Match.lost_report_id == report.id) | (Match.found_report_id == report.id)).all():
        if m.status in (MatchStatus.SUGGESTED, MatchStatus.CLAIMED):
            m.status = MatchStatus.EXPIRED


# ------------------------------------------------------------------ claims
@admin_bp.get("/claims")
@roles_required(Role.ADMIN, Role.STAFF)
def admin_claims():
    user = current_user()
    status = request.args.get("status", "PENDING")
    try:
        wanted = ClaimStatus(status)
    except ValueError:
        raise ApiError("VALIDATION_ERROR", "Unknown status", details={"status": ["Unknown status"]})
    claims = Claim.query.filter(Claim.verification_status == wanted).all()
    if user.role == Role.STAFF:
        claims = [c for c in claims
                  if c.report.institution_id == user.institution_id]
    claims.sort(key=lambda c: c.created_at, reverse=True)
    return jsonify({"data": [c.to_dict(user) for c in claims]})


@admin_bp.post("/claims/<int:claim_id>/resolve")
@roles_required(Role.ADMIN)
def resolve_claim(claim_id):
    user = current_user()
    claim = db.session.get(Claim, claim_id)
    if claim is None:
        raise ApiError("NOT_FOUND", "Claim not found", status=404)
    data = load_json(ResolveSchema(), request.get_json(silent=True) or {})
    from ..services import claims as claim_service
    try:
        if data["decision"] == "APPROVE":
            claim_service.approve_claim(claim, user, data.get("note"))
        else:
            note = data.get("note") or "Resolved by admin."
            if len(note) < 5:
                note = note + " (admin)"
            claim_service.reject_claim(claim, user, note)
    except claim_service.TransitionError as e:
        raise ApiError("CONFLICT", str(e), status=409)
    log_action("claim_resolve", actor=user, target_type="claim", target_id=claim.id,
               details={"decision": data["decision"], "note": data.get("note")})
    return jsonify({"data": claim.to_dict(user)})


@admin_bp.get("/recoveries")
@roles_required(Role.ADMIN, Role.STAFF)
def recoveries():
    user = current_user()
    claims = Claim.query.filter(Claim.verification_status == ClaimStatus.COMPLETED).all()
    if user.role == Role.STAFF:
        claims = [c for c in claims if c.report.institution_id == user.institution_id]
    data = []
    for c in claims:
        duration_hours = None
        if c.received_confirmed_at and c.created_at:
            duration_hours = round(
                (c.received_confirmed_at - c.created_at).total_seconds() / 3600, 2)
        data.append({
            "claim_id": c.id,
            "match_id": c.match_id,
            "found_report_id": c.report_id,
            "lost_report_title": c.match.lost_report.title,
            "claimant_id": c.claimant_id,
            "created_at": c.created_at.isoformat() + "Z",
            "handed_over_at": c.handed_over_at.isoformat() + "Z" if c.handed_over_at else None,
            "received_confirmed_at": c.received_confirmed_at.isoformat() + "Z"
            if c.received_confirmed_at else None,
            "duration_hours": duration_hours,
        })
    return jsonify({"data": data})


@admin_bp.get("/audit-logs")
@roles_required(Role.ADMIN)
def audit_logs():
    q = AuditLog.query
    if request.args.get("action"):
        q = q.filter(AuditLog.action == request.args["action"])
    if request.args.get("actor_id"):
        q = q.filter(AuditLog.actor_id == int(request.args["actor_id"]))
    if request.args.get("date_from"):
        q = q.filter(AuditLog.timestamp >= datetime.fromisoformat(request.args["date_from"]))
    if request.args.get("date_to"):
        q = q.filter(AuditLog.timestamp <= datetime.fromisoformat(request.args["date_to"]))
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    pag = q.order_by(AuditLog.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"data": [a.to_dict() for a in pag.items], "meta": {
        "page": pag.page, "per_page": pag.per_page, "total": pag.total, "pages": pag.pages}})


# ------------------------------------------------------------------ analytics
@admin_bp.get("/analytics/summary")
@roles_required(Role.ADMIN, Role.STAFF)
def analytics_summary():
    from ..services import analytics
    user = current_user()
    return jsonify({"data": analytics.summary(user=user,
                    from_date=_date_arg("from"), to_date=_date_arg("to"))})


@admin_bp.get("/analytics/timeseries")
@roles_required(Role.ADMIN, Role.STAFF)
def analytics_timeseries():
    from ..services import analytics
    user = current_user()
    return jsonify({"data": analytics.timeseries(user=user,
                    from_date=_date_arg("from"), to_date=_date_arg("to"))})


@admin_bp.get("/analytics/categories")
@roles_required(Role.ADMIN, Role.STAFF)
def analytics_categories():
    from ..services import analytics
    user = current_user()
    return jsonify({"data": analytics.categories(user=user,
                    from_date=_date_arg("from"), to_date=_date_arg("to"))})


@admin_bp.get("/analytics/heatmap")
@roles_required(Role.ADMIN, Role.STAFF)
def analytics_heatmap():
    from ..services import analytics
    user = current_user()
    return jsonify({"data": analytics.heatmap(user=user,
                    from_date=_date_arg("from"), to_date=_date_arg("to"))})


def _date_arg(name):
    if request.args.get(name):
        return datetime.fromisoformat(request.args[name])
    return None
