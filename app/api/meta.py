"""Public metadata and stats endpoints (Part D2).

- GET /meta: one shared source of enums/categories/types + map defaults,
  so JS and templates never duplicate them.
- GET /stats/public: landing-page counters, cached for 5 minutes.
"""
from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify

from ..models import Institution, Report
from ..models.enums import Category, ClaimStatus, InstitutionType, ReportStatus

meta_bp = Blueprint("meta", __name__)


@meta_bp.get("/meta")
def meta():
    return jsonify({"data": {
        "categories": [c.value for c in Category],
        "institution_types": [t.value for t in InstitutionType],
        "report_statuses": [s.value for s in ReportStatus],
        "claim_statuses": [s.value for s in ClaimStatus],
        "map_default_center": current_app.config.get("MAP_DEFAULT_CENTER", [30.0668, 79.0193]),
        "limits": {
            "max_image_mb": current_app.config.get("MAX_IMAGE_MB", 5),
            "max_images_per_report": current_app.config.get("MAX_IMAGES_PER_REPORT", 4),
            "otp_expires_seconds": current_app.config.get("OTP_EXPIRES_SECONDS", 300),
            "otp_resend_after": current_app.config.get("OTP_RESEND_COOLDOWN_SECONDS", 30),
        },
    }})


_stats_cache = {"value": None, "at": 0.0}
STATS_TTL_SECONDS = 300  # 5 minutes


def public_stats_data() -> dict:
    """Landing-page counters with a 5-minute cache (Part D2)."""
    import time
    now = time.time()
    if _stats_cache["value"] is not None and now - _stats_cache["at"] < STATS_TTL_SECONDS:
        return _stats_cache["value"]
    data = {
        "recovered": Report.query.filter_by(status=ReportStatus.RECOVERED).count(),
        "institutions": Institution.query.filter_by(is_active=True).count(),
        "reports": Report.query.count(),
    }
    _stats_cache["value"] = data
    _stats_cache["at"] = now
    return data


@meta_bp.get("/stats/public")
def public_stats():
    """Landing-page counters: total recovered, active institutions, reports."""
    return jsonify({"data": public_stats_data()})
