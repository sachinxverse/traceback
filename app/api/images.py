"""Authorised image serving (Section 8): files are never public static."""

from flask import Blueprint, Response

from .. import ApiError
from ..models import ClaimImage, ReportImage
from ._auth import current_user

images_bp = Blueprint("images", __name__, url_prefix="")


PLACEHOLDER_SVG = (b"<svg xmlns='http://www.w3.org/2000/svg' width='320' height='240'>"
                   b"<rect width='100%' height='100%' fill='#F5F7FA'/>"
                   b"<text x='50%' y='50%' font-family='sans-serif' font-size='14' "
                   b"fill='#5A6472' text-anchor='middle'>Photo unavailable</text></svg>")


def _serve(storage_key):
    from ..services.storage import get_storage
    try:
        data = get_storage().open(storage_key)
    except Exception:  # noqa: BLE001 - missing object must not 500 (Issue 5)
        import logging
        logging.getLogger("traceback.images").warning(
            "Image object missing in storage: %s", storage_key)
        resp = Response(PLACEHOLDER_SVG, mimetype="image/svg+xml")
        resp.headers["Cache-Control"] = "private, max-age=60"
        return resp
    resp = Response(data, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@images_bp.get("/images/<int:image_id>")
def get_report_image(image_id):
    user = current_user()
    img = db_get(ReportImage, image_id)
    if img is None:
        raise ApiError("NOT_FOUND", "Image not found", status=404)
    report = img.report
    from ._auth import can_view_report
    if not can_view_report(user, report):
        raise ApiError("NOT_FOUND", "Image not found", status=404)
    return _serve(img.storage_key)


@images_bp.get("/claim-images/<int:image_id>")
def get_claim_image(image_id):
    user = current_user()
    img = db_get(ClaimImage, image_id)
    if img is None:
        raise ApiError("NOT_FOUND", "Image not found", status=404)
    claim = img.claim
    if not (claim.claimant_id == user.id or claim.can_review(user)
            or user.role.value == "ADMIN"):
        raise ApiError("NOT_FOUND", "Image not found", status=404)
    return _serve(img.storage_key)


def db_get(model, id_):
    from ..extensions import db
    return db.session.get(model, id_)
