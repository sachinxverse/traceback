"""Staff-portal endpoints (Part B): scoped to the staff member's institution."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from .. import ApiError
from ..extensions import db
from ..models import Claim, Match, Report, User
from ..models.enums import ClaimStatus, ReportStatus, Role
from ..services import analytics
from ._auth import current_user, session_portal

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")


@staff_bp.before_request
def _require_staff_portal():
    """B1.3: /api/v1/staff/* needs a token from the staff portal and the
    STAFF role."""
    if session_portal() != "staff":
        raise ApiError("FORBIDDEN", "Not allowed", status=403)
    user = current_user()
    if user.role != Role.STAFF:
        raise ApiError("FORBIDDEN", "Not allowed", status=403)


def _inst_id():
    return current_user().institution_id


@staff_bp.get("/dashboard")
def dashboard():
    inst = _inst_id()
    reports = Report.query.filter_by(institution_id=inst)
    claims_q = (Claim.query.join(Match, Claim.match_id == Match.id)
                .join(Report, Match.found_report_id == Report.id)
                .filter(Report.institution_id == inst,
                        Claim.verification_status.in_(
                            [ClaimStatus.PENDING, ClaimStatus.DISPUTED])))
    recovered = Report.query.filter_by(institution_id=inst, status=ReportStatus.RECOVERED).count()
    return jsonify({"data": {
        "institution": {"id": inst},
        "active_reports": reports.filter(Report.status.in_(
            [ReportStatus.ACTIVE, ReportStatus.CLAIM_PENDING])).count(),
        "found_reports": reports.filter_by(report_type="FOUND").count(),
        "pending_claims": claims_q.count(),
        "recovered": recovered,
    }})


@staff_bp.get("/reports")
def reports():
    inst = _inst_id()
    q = (Report.query.filter_by(institution_id=inst)
         .order_by(Report.created_at.desc()).limit(200).all())
    return jsonify({"data": [_report_row(r) for r in q]})


def _report_row(r: Report) -> dict:
    mq = (Match.query.filter(Match.status != "EXPIRED")
          .filter((Match.lost_report_id == r.id) | (Match.found_report_id == r.id)))
    top = mq.order_by(Match.total_score.desc()).first()
    return {
        "id": r.id, "title": r.title, "type": r.report_type.value,
        "status": r.status.value, "created_at": r.created_at.isoformat() + "Z",
        "match_count": mq.count(),
        "top_score": round(top.total_score * 100) if top else None,
    }


@staff_bp.get("/claims")
def claims_to_review():
    """Claims the staff member can review: found side of their institution."""
    inst = _inst_id()
    rows = (Claim.query.join(Match, Claim.match_id == Match.id)
            .join(Report, Match.found_report_id == Report.id)
            .filter(Report.institution_id == inst)
            .order_by(Claim.created_at.desc()).limit(200).all())
    out = []
    for c in rows:
        if c.can_review(current_user()) or c.verification_status in (
                ClaimStatus.PENDING, ClaimStatus.DISPUTED):
            out.append({
                "claim_id": c.id,
                "match_id": c.match_id,
                "status": c.verification_status.value,
                "created_at": c.created_at.isoformat() + "Z",
                "lost_report_title": c.match.lost_report.title,
                "found_report_title": c.match.found_report.title,
            })
    return jsonify({"data": out})


@staff_bp.get("/recoveries")
def recoveries():
    inst = _inst_id()
    rows = (Claim.query.join(Match, Claim.match_id == Match.id)
            .join(Report, Match.found_report_id == Report.id)
            .filter(Report.institution_id == inst,
                    Claim.verification_status == ClaimStatus.COMPLETED)
            .order_by(Claim.id.desc())
            .limit(100).all())
    out = []
    for c in rows:
        out.append({
            "claim_id": c.id,
            "lost_report_title": c.match.lost_report.title,
            "handed_over_at": c.handed_over_at.isoformat() + "Z" if c.handed_over_at else None,
            "received_confirmed_at": (c.received_confirmed_at.isoformat() + "Z"
                                      if getattr(c, "received_confirmed_at", None) else None),
        })
    return jsonify({"data": out})


@staff_bp.get("/analytics")
def staff_analytics():
    user = current_user()
    from_date = None
    to_date = None
    if request.args.get("from"):
        from_date = datetime.fromisoformat(request.args["from"])
    if request.args.get("to"):
        to_date = datetime.fromisoformat(request.args["to"])
    return jsonify({"data": analytics.heatmap(user=user, from_date=from_date, to_date=to_date)})


@staff_bp.get("/summary")
def staff_summary():
    """Institution-scoped KPI summary for the staff dashboard."""
    inst = _inst_id()
    reports = Report.query.filter_by(institution_id=inst)
    counts = {
        "total": reports.count(),
        "active": reports.filter_by(status=ReportStatus.ACTIVE).count(),
        "claim_pending": reports.filter_by(status=ReportStatus.CLAIM_PENDING).count(),
        "recovered": reports.filter_by(status=ReportStatus.RECOVERED).count(),
        "lost": reports.filter_by(report_type="LOST").count(),
        "found": reports.filter_by(report_type="FOUND").count(),
    }
    return jsonify({"data": counts})
