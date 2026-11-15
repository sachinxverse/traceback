"""AI matching engine (Section 9): candidate retrieval, component scores,
combined score with renormalisation, match upsert and notifications."""
import logging
from datetime import timedelta

import numpy as np

from ..extensions import db
from ..models import Match, Report
from ..models.enums import (
    Category,
    MatchStatus,
    ProcessingStatus,
    ReportStatus,
    ReportType,
)
from .geo import haversine_km

log = logging.getLogger("traceback.matching")


def _weights(app):
    return app.config.get("MATCH_WEIGHTS") or {
        "image": 0.40, "text": 0.25, "location": 0.20, "time": 0.15}


def _category_compatible(a: Category, b: Category) -> bool:
    return a == b or a == Category.OTHER or b == Category.OTHER


def get_candidates(report: Report):
    """Hard filters (Section 9.3). Candidates are opposite-type reports that
    are ACTIVE/CLAIM_PENDING, READY, not removed, not the same user, category
    compatible, time-plausible and distance-plausible."""
    opposite = ReportType.FOUND if report.is_lost else ReportType.LOST

    base = Report.query.filter(
        Report.report_type == opposite,
        Report.status.in_([ReportStatus.ACTIVE, ReportStatus.CLAIM_PENDING]),
        Report.processing_status == ProcessingStatus.READY,
        Report.user_id != report.user_id,
        Report.id != report.id,
    )

    candidates = []
    for c in base.all():
        if c.removed:
            continue
        if not _category_compatible(report.category, c.category):
            continue
        lost_date = report.incident_date if report.is_lost else c.incident_date
        found_date = c.incident_date if report.is_lost else report.incident_date
        # found >= lost - 24h and found - lost <= MATCH_MAX_DAYS
        if found_date < lost_date - timedelta(hours=24):
            continue
        if (found_date - lost_date) > timedelta(days=app_max_days()):
            continue
        # distance: only enforce when BOTH have coordinates
        if report.latitude is not None and report.longitude is not None \
                and c.latitude is not None and c.longitude is not None:
            d = haversine_km(report.latitude, report.longitude, c.latitude, c.longitude)
            if d > app_max_distance_km():
                continue
        candidates.append(c)
    return candidates


_app = None


def _app_cfg(key, default=None):
    from flask import current_app
    try:
        return current_app.config.get(key, default)
    except RuntimeError:
        return default


def app_max_days():
    return _app_cfg("MATCH_MAX_DAYS", 90)


def app_max_distance_km():
    return _app_cfg("MATCH_MAX_DISTANCE_KM", 50)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def component_scores(report: Report, candidate: Report, text_emb_r, text_emb_c,
                     img_embs_r, img_embs_c):
    """Compute per-signal scores (0..1) or None when the input is missing.

    image: max pairwise cosine rescaled from [IMG_LOW, IMG_HIGH] to [0, 1].
    text: cosine rescaled from [TXT_LOW, TXT_HIGH] to [0, 1].
    location: exp(-d / LOC_DECAY_KM); same-institution pairs without
              coordinates get 1.0.
    time: exp(-delta_days / TIME_DECAY_DAYS).
    """
    cfg_img_low = _app_cfg("IMG_LOW", 0.55)
    cfg_img_high = _app_cfg("IMG_HIGH", 0.92)
    cfg_txt_low = _app_cfg("TXT_LOW", 0.25)
    cfg_txt_high = _app_cfg("TXT_HIGH", 0.85)
    cfg_loc_decay = _app_cfg("LOC_DECAY_KM", 1.0)
    cfg_time_decay = _app_cfg("TIME_DECAY_DAYS", 7)

    scores = {"image": None, "text": None, "location": None, "time": None}

    # image
    if img_embs_r and img_embs_c:
        cos_max = max(cosine(a, b) for a in img_embs_r for b in img_embs_c)
        scores["image"] = float(np.clip(
            (cos_max - cfg_img_low) / (cfg_img_high - cfg_img_low), 0.0, 1.0))

    # text
    if text_emb_r is not None and text_emb_c is not None:
        cos = cosine(text_emb_r, text_emb_c)
        scores["text"] = float(np.clip(
            (cos - cfg_txt_low) / (cfg_txt_high - cfg_txt_low), 0.0, 1.0))

    # location
    if report.latitude is not None and report.longitude is not None \
            and candidate.latitude is not None and candidate.longitude is not None:
        d = haversine_km(report.latitude, report.longitude,
                         candidate.latitude, candidate.longitude)
        scores["location"] = float(np.exp(-d / cfg_loc_decay))
    elif (report.institution_id is not None and candidate.institution_id is not None
            and report.institution_id == candidate.institution_id):
        scores["location"] = 1.0

    # time
    lost_date = report.incident_date if report.is_lost else candidate.incident_date
    found_date = candidate.incident_date if report.is_lost else report.incident_date
    delta_days = abs((found_date - lost_date).total_seconds()) / 86400.0
    if delta_days <= 1.0:
        delta_days = 0.0
    scores["time"] = float(np.exp(-delta_days / cfg_time_decay))

    return scores


def combined_score(scores: dict, weights: dict) -> tuple | None:
    """Renormalised weighted mean over available signals (Section 9.5).
    Returns (total, signals_used) or (None, []) when no content signal."""
    available = {s: v for s, v in scores.items() if v is not None}
    if "image" not in available and "text" not in available:
        return None, []
    denom = sum(weights[s] for s in available)
    total = sum(weights[s] * available[s] for s in available) / denom
    if len(available) == 1:
        total *= 0.85  # low-evidence penalty
    return round(float(min(total, 1.0)), 4), list(available.keys())


def find_and_store_matches(report: Report, notify: bool = True) -> None:
    """Run matching for one report, upserting Match rows (Section 9.6)."""
    from flask import current_app

    from .embeddings import IMAGE_DIM, TEXT_DIM, from_blob

    app = current_app._get_current_object()
    weights = _weights(app)
    min_score = app.config["MATCH_MIN_SCORE"]
    top_n = app.config["MATCH_TOP_N"]
    notify_min = app.config["NOTIFY_MIN_SCORE"]

    text_emb_r = from_blob(report.text_embedding, TEXT_DIM)
    img_embs_r = [from_blob(i.embedding, IMAGE_DIM) for i in report.images]
    img_embs_r = [v for v in img_embs_r if v is not None]

    results = []
    for candidate in get_candidates(report):
        text_emb_c = from_blob(candidate.text_embedding, TEXT_DIM)
        img_embs_c = [from_blob(i.embedding, IMAGE_DIM) for i in candidate.images]
        img_embs_c = [v for v in img_embs_c if v is not None]

        scores = component_scores(report, candidate, text_emb_r, text_emb_c,
                                  img_embs_r, img_embs_c)
        total, signals = combined_score(scores, weights)
        if total is None:
            continue
        if total >= min_score:
            results.append((candidate, scores, total, signals))

    # keep at most top_n by score
    results.sort(key=lambda r: r[2], reverse=True)
    results = results[:top_n]

    new_matches = []
    kept_ids = set()
    for candidate, scores, total, signals in results:
        lost_report = report if report.is_lost else candidate
        found_report = candidate if report.is_lost else report
        match = Match.query.filter_by(
            lost_report_id=lost_report.id, found_report_id=found_report.id).first()
        if match is None:
            match = Match(lost_report=lost_report, found_report=found_report)
            db.session.add(match)
            new_matches.append(match)
        match.image_score = scores["image"]
        match.text_score = scores["text"]
        match.location_score = scores["location"]
        match.time_score = scores["time"]
        match.total_score = total
        match.signals_used = signals
        # SUGGESTED rows that fall below the minimum become EXPIRED (handled by
        # expiry pass below). Status is otherwise not changed on update.
        if match.status == MatchStatus.SUGGESTED:
            pass
        kept_ids.add(candidate.id)

    # expire SUGGESTED matches of this report that no longer meet the minimum
    col = Match.lost_report_id if report.is_lost else Match.found_report_id
    for match in Match.query.filter(
            col == report.id, Match.status == MatchStatus.SUGGESTED).all():
        other_id = (match.found_report_id if report.is_lost else match.lost_report_id)
        if other_id not in kept_ids:
            match.status = MatchStatus.EXPIRED

    db.session.commit()

    if notify:
        for match in new_matches:
            if match.total_score >= notify_min:
                _notify_new_match(match)
    return new_matches


def _notify_new_match(match: Match):
    from .notifications import notify
    lost_owner = match.lost_report.user_id
    finder = match.found_report.user_id
    notify(
        lost_owner, "MATCH_FOUND",
        f'A possible match for your lost item "{match.lost_report.title}" was found',
        link=f"/matches/{match.id}",
        related_report_id=match.lost_report_id, related_match_id=match.id,
    )
    notify(
        finder, "MATCH_FOUND",
        f'A possible owner may exist for found item "{match.found_report.title}"',
        link=f"/matches/{match.id}",
        related_report_id=match.found_report_id, related_match_id=match.id,
    )
