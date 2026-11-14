"""HTML page routes (Section 11.3)."""
from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from ..extensions import db
from ..models import Institution, Report, User
from ..models.enums import InstitutionType

web_bp = Blueprint("web", __name__)


def _current_user():
    """Best-effort current user for templates (None when anonymous)."""
    try:
        verify_jwt_in_request()
        uid = get_jwt_identity()
        return db.session.get(User, int(uid)) if uid else None
    except Exception:
        return None


@web_bp.app_context_processor
def inject_globals():
    return {
        "nav_user": _current_user(),
        "now": datetime.utcnow(),
    }


def _require_login():
    user = _current_user()
    if user is None:
        abort(redirect("/login?next=" + request.path))
    return user


def _require_admin():
    user = _require_login()
    if user.role.value == "USER":
        abort(404)
    return user


@web_bp.get("/")
def index():
    from ..models import Report, Match, Institution
    recovered = Report.query.filter_by(status="RECOVERED").count()
    insts = Institution.query.filter_by(is_active=True).all()
    stats = {"recovered": recovered, "institutions": len(insts),
             "reports": Report.query.count()}
    return render_template("pages/index.html", stats=stats, institutions=insts)


@web_bp.get("/how-it-works")
def how_it_works():
    return render_template("pages/how-it-works.html")


@web_bp.get("/institutions")
def institutions():
    q = Institution.query.filter_by(is_active=True)
    search = request.args.get("q", "").strip()
    if search:
        q = q.filter(Institution.name.ilike(f"%{search}%"))
    return render_template("pages/institutions.html", institutions=q.all(), q=search)


@web_bp.get("/i/<slug>")
def qr_landing(slug):
    inst = Institution.query.filter_by(slug=slug, is_active=True).first()
    if inst is None:
        abort(404)
    return render_template("pages/qr_landing.html", institution=inst)


@web_bp.get("/register")
def register_page():
    return render_template("pages/register.html")


@web_bp.get("/login")
def login_page():
    return render_template("pages/login.html")


@web_bp.get("/dashboard")
def dashboard():
    user = _require_login()
    from ..models import Match, Claim
    from ..models.enums import ClaimStatus
    reports = Report.query.filter_by(user_id=user.id).order_by(Report.created_at.desc()).all()
    report_data = []
    for r in reports:
        if r.is_lost:
            mq = Match.query.filter(Match.lost_report_id == r.id)
        else:
            mq = Match.query.filter(Match.found_report_id == r.id)
        mq = mq.filter(Match.status != "EXPIRED")
        top = mq.order_by(Match.total_score.desc()).first()
        report_data.append({
            "report": r,
            "top_score": round(top.total_score * 100) if top else None,
            "match_count": mq.count(),
        })
    lost_active = sum(1 for d in report_data
                      if d["report"].report_type.value == "LOST"
                      and d["report"].status.value == "ACTIVE")
    found_active = sum(1 for d in report_data
                       if d["report"].report_type.value == "FOUND"
                       and d["report"].status.value == "ACTIVE")
    new_matches = sum(d["match_count"] for d in report_data)
    pending_claims = Claim.query.filter_by(claimant_id=user.id).filter(
        Claim.verification_status.in_(
            [ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED])).count()
    recovered_count = sum(1 for d in report_data
                          if d["report"].status.value == "RECOVERED")
    cards = {
        "lost_active": lost_active,
        "found_active": found_active,
        "new_matches": new_matches,
        "pending_claims": pending_claims,
        "recovered": recovered_count,
    }
    return render_template("pages/dashboard.html", report_data=report_data, cards=cards)


@web_bp.get("/report/lost")
@web_bp.get("/report/found")
def report_form():
    user = _require_login()
    rtype = "lost" if request.path.endswith("/lost") else "found"
    institutions = Institution.query.filter_by(is_active=True).all()
    prefill_slug = request.args.get("institution")
    prefill = None
    if prefill_slug:
        prefill = Institution.query.filter_by(slug=prefill_slug).first()
    from ..models.enums import Category
    return render_template("pages/report_form.html", report_type=rtype,
                           institutions=institutions, prefill=prefill,
                           categories=[c.value for c in Category])


@web_bp.get("/reports/<int:report_id>")
def report_detail(report_id):
    user = _require_login()
    report = db.session.get(Report, report_id)
    if report is None or not _can_view(user, report):
        abort(404)
    full_view = report.user_id == user.id or user.role.value in ("ADMIN",) or (
        user.role.value == "STAFF" and user.institution_id == report.institution_id)
    return render_template("pages/report_detail.html", report=report,
                           full_view=full_view, images=report.images)


def _can_view(user, report):
    from ..api._auth import can_view_report
    return can_view_report(user, report)


@web_bp.get("/matches/<int:match_id>")
def match_detail(match_id):
    user = _require_login()
    from ..models import Match
    from ..api._auth import can_participate_in_match
    match = db.session.get(Match, match_id)
    if match is None or not can_participate_in_match(user, match):
        abort(404)
    from ..services.geo import haversine_km
    a, b = match.lost_report, match.found_report
    distance = None
    if a.latitude is not None and b.latitude is not None:
        distance = round(haversine_km(a.latitude, a.longitude, b.latitude, b.longitude), 2)
    from ..models.enums import ClaimStatus
    live_claim = None
    for c in match.claims:
        if c.verification_status in (ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED):
            live_claim = c
            break
    is_lost_side = match.lost_report.user_id == user.id
    return render_template("pages/match_detail.html", match=match,
                           for_lost=is_lost_side, distance=distance,
                           live_claim=live_claim)


@web_bp.get("/claims")
def claims_page():
    user = _require_login()
    from ..models import Claim
    mine = Claim.query.filter_by(claimant_id=user.id).order_by(Claim.created_at.desc()).all()
    incoming = _reviewable_claims(user)
    return render_template("pages/claims.html", my_claims=mine, incoming=incoming)


def _reviewable_claims(user):
    from ..models import Claim
    from ..models.enums import Custody, Role
    claims = Claim.query.order_by(Claim.created_at.desc()).all()
    out = []
    for c in claims:
        if c.can_review(user):
            out.append(c)
    return out


@web_bp.get("/claims/<int:claim_id>")
def claim_detail(claim_id):
    user = _require_login()
    from ..models import Claim
    claim = db.session.get(Claim, claim_id)
    if claim is None or not (claim.claimant_id == user.id or claim.can_review(user)
                             or claim.match.lost_report.user_id == user.id
                             or user.role.value == "ADMIN"):
        abort(404)
    is_reviewer = claim.can_review(user)
    return render_template("pages/claim_detail.html", claim=claim,
                           is_reviewer=is_reviewer, is_claimant=claim.claimant_id == user.id)


@web_bp.get("/browse")
def browse():
    user = _require_login()
    q = Report.query.filter_by(report_type="FOUND", status="ACTIVE")
    category = request.args.get("category", "")
    if category:
        q = q.filter(Report.category == category)
    kw = request.args.get("q", "").strip()
    if kw:
        q = q.filter((Report.title.ilike(f"%{kw}%")) | (Report.description.ilike(f"%{kw}%")))
    reports = q.order_by(Report.created_at.desc()).limit(60).all()
    from ..models.enums import Category
    return render_template("pages/browse.html", reports=reports,
                           categories=[c.value for c in Category],
                           category=category, q=kw)


@web_bp.get("/notifications")
def notifications_page():
    user = _require_login()
    from ..models import Notification
    items = Notification.query.filter_by(user_id=user.id).order_by(
        Notification.created_at.desc()).limit(100).all()
    return render_template("pages/notifications.html", notifications=items)


@web_bp.get("/profile")
def profile():
    user = _require_login()
    return render_template("pages/profile.html", user=user)


# ------------------------------------------------------------------ admin
@web_bp.get("/admin")
def admin_home():
    user = _require_admin()
    return render_template("pages/admin/dashboard.html", user=user)


@web_bp.get("/admin/reports")
def admin_reports():
    _require_admin()
    return render_template("pages/admin/reports.html")


@web_bp.get("/admin/claims")
def admin_claims():
    _require_admin()
    return render_template("pages/admin/claims.html")


@web_bp.get("/admin/users")
def admin_users():
    user = _require_admin()
    if user.role.value != "ADMIN":
        abort(404)
    return render_template("pages/admin/users.html")


@web_bp.get("/admin/institutions")
def admin_institutions():
    user = _require_admin()
    if user.role.value != "ADMIN":
        abort(404)
    insts = Institution.query.order_by(Institution.created_at.desc()).all()
    return render_template("pages/admin/institutions.html", institutions=insts)


@web_bp.get("/admin/institutions/<int:inst_id>/poster")
def institution_poster(inst_id):
    _require_admin()
    inst = db.session.get(Institution, inst_id)
    if inst is None:
        abort(404)
    return render_template("pages/admin/poster.html", institution=inst)


@web_bp.get("/admin/recoveries")
def admin_recoveries():
    _require_admin()
    return render_template("pages/admin/recoveries.html")


@web_bp.get("/admin/audit")
def admin_audit():
    user = _require_admin()
    if user.role.value != "ADMIN":
        abort(404)
    from ..models import AuditLog
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(200).all()
    return render_template("pages/admin/audit.html", logs=logs)
