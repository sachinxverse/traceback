"""Authorised image serving (Section 8): files are never public static."""
import io

from flask import Blueprint, Response, current_app, send_file

from .. import ApiError
from ..models import ClaimImage, ReportImage
from ._auth import current_user, can_view_claim

images_bp = Blueprint("images", __name__, url_prefix="")


def _serve(storage_key):
    from ..services.storage import get_storage
    data = get_storage().open(storage_key)
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
