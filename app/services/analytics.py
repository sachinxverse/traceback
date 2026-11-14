"""Analytics aggregate queries (Section 14)."""
from datetime import datetime, timedelta

from sqlalchemy import func

from ..extensions import db
from ..models import Claim, Institution, Match, Report, User
from ..models.enums import ClaimStatus, MatchStatus, ReportStatus, ReportType


def summary(user=None, from_date=None, to_date=None):
    """KPI summary. STAFF are scoped to their institution."""
    q = Report.query
    inst_id = None
    if user is not None and user.role.value == "STAFF":
        inst_id = user.institution_id
        q = q.filter(Report.institution_id == inst_id)
    if from_date:
        q = q.filter(Report.created_at >= from_date)
    if to_date:
        q = q.filter(Report.created_at < to_date)
    reports = q.all()

    total = len(reports)
    lost = sum(1 for r in reports if r.report_type == ReportType.LOST)
    found = sum(1 for r in reports if r.report_type == ReportType.FOUND)
    active = sum(1 for r in reports if r.status == ReportStatus.ACTIVE)
    recovered = sum(1 for r in reports if r.status == ReportStatus.RECOVERED)

    # matched reports (>=1 non-expired match)
    matched_ids = set()
    mq = Match.query.filter(Match.status != MatchStatus.EXPIRED)
    matches = mq.all()
    for m in matches:
        matched_ids.add(m.lost_report_id)
        matched_ids.add(m.found_report_id)
    matched_reports = sum(1 for r in reports if r.id in matched_ids)

    cq = Claim.query
    if inst_id:
        cq = cq.join(Report, Claim.report_id == Report.id).filter(
            Report.institution_id == inst_id)
    claims = cq.all()
    open_claims = sum(1 for c in claims if c.verification_status in
                      (ClaimStatus.PENDING, ClaimStatus.APPROVED, ClaimStatus.DISPUTED))
    disputed = sum(1 for c in claims if c.verification_status == ClaimStatus.DISPUTED)
    decided = [c for c in claims if c.verification_status in
               (ClaimStatus.REJECTED, ClaimStatus.COMPLETED)]
    rejected = sum(1 for c in decided if c.verification_status == ClaimStatus.REJECTED)
    false_candidate_rate = (rejected / len(decided)) if decided else 0.0

    all_reports_count = total if not inst_id else total
    verified_recovery_rate = (recovered / all_reports_count) if all_reports_count else 0.0
    potential_match_rate = (matched_reports / all_reports_count) if all_reports_count else 0.0

    # avg hours to first candidate
    deltas = []
    match_first = {}
    for m in matches:
        for rid in (m.lost_report_id, m.found_report_id):
            if rid not in match_first or (m.created_at and m.created_at < match_first[rid]):
                match_first[rid] = m.created_at
    for r in reports:
        t0 = match_first.get(r.id)
        if t0 and r.created_at:
            deltas.append((t0 - r.created_at).total_seconds() / 3600.0)
    avg_hours = sum(deltas) / len(deltas) if deltas else None

    active_users_30d = User.query.filter(
        User.is_active.is_(True),
        User.last_login_at >= datetime.utcnow() - timedelta(days=30)).count() \
        if inst_id is None else None
    institutions_count = Institution.query.filter_by(is_active=True).count() \
        if inst_id is None else None

    return {
        "total_reports": total,
        "lost_reports": lost,
        "found_reports": found,
        "active_reports": active,
        "matched_reports": matched_reports,
        "recovered_reports": recovered,
        "open_claims": open_claims,
        "disputed_claims": disputed,
        "report_completion_rate": None,  # not trackable server-side
        "potential_match_rate": round(potential_match_rate, 4) if all_reports_count else None,
        "verified_recovery_rate": round(verified_recovery_rate, 4) if all_reports_count else None,
        "avg_hours_to_first_candidate": round(avg_hours, 2) if avg_hours is not None else None,
        "false_candidate_rate": round(false_candidate_rate, 4) if decided else None,
        "active_users_30d": active_users_30d,
        "institutions_count": institutions_count,
    }


def timeseries(user=None, from_date=None, to_date=None):
    """Daily counts of lost/found/recovered reports. Default last 30 days."""
    end = to_date or datetime.utcnow()
    start = from_date or (end - timedelta(days=30))
    q = Report.query.filter(Report.created_at >= start, Report.created_at < end)
    if user is not None and user.role.value == "STAFF":
        q = q.filter(Report.institution_id == user.institution_id)
    points = {}
    for r in q.all():
        d = r.created_at.strftime("%Y-%m-%d")
        slot = points.setdefault(d, {"date": d, "lost": 0, "found": 0, "recovered": 0})
        if r.report_type == ReportType.LOST:
            slot["lost"] += 1
        else:
            slot["found"] += 1
        if r.status == ReportStatus.RECOVERED:
            slot["recovered"] += 1
    # fill gaps
    out = []
    d = start.date()
    endd = end.date()
    while d <= endd:
        key = d.strftime("%Y-%m-%d")
        out.append(points.get(key, {"date": key, "lost": 0, "found": 0, "recovered": 0}))
        d += timedelta(days=1)
    return {"interval": "day", "points": out}


def categories(user=None, from_date=None, to_date=None):
    q = Report.query
    if user is not None and user.role.value == "STAFF":
        q = q.filter(Report.institution_id == user.institution_id)
    if from_date:
        q = q.filter(Report.created_at >= from_date)
    if to_date:
        q = q.filter(Report.created_at < to_date)
    rows = q.with_entities(
        Report.category,
        Report.report_type,
        func.count(Report.id)).group_by(Report.category, Report.report_type).all()
    data = {}
    for cat, rtype, count in rows:
        slot = data.setdefault(cat.value, {"category": cat.value, "lost": 0, "found": 0, "recovered": 0})
        if rtype == ReportType.LOST:
            slot["lost"] += count
        else:
            slot["found"] += count
    # recovered per category
    rq = Report.query.filter(Report.status == ReportStatus.RECOVERED)
    if user is not None and user.role.value == "STAFF":
        rq = rq.filter(Report.institution_id == user.institution_id)
    for cat, count in rq.with_entities(Report.category, func.count(Report.id)).group_by(Report.category).all():
        data.setdefault(cat.value, {"category": cat.value, "lost": 0, "found": 0, "recovered": 0})["recovered"] += count
    return list(data.values())


def heatmap(user=None, from_date=None, to_date=None):
    """Grid-aggregated counts rounded to 3 decimals; cells with count < 2 are
    omitted for privacy."""
    q = Report.query.filter(Report.latitude.isnot(None), Report.longitude.isnot(None))
    if user is not None and user.role.value == "STAFF":
        q = q.filter(Report.institution_id == user.institution_id)
    if from_date:
        q = q.filter(Report.created_at >= from_date)
    if to_date:
        q = q.filter(Report.created_at < to_date)
    cells = {}
    for r in q.all():
        lat = round(r.latitude, 3)
        lng = round(r.longitude, 3)
        key = (lat, lng)
        slot = cells.setdefault(key, {"lat": lat, "lng": lng, "count": 0, "lost": 0, "found": 0})
        slot["count"] += 1
        if r.report_type == ReportType.LOST:
            slot["lost"] += 1
        else:
            slot["found"] += 1
    return [c for c in cells.values() if c["count"] >= 2]
