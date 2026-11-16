"""Institution endpoints (Section 7.6 / 13)."""
import io

from flask import Blueprint, Response, jsonify, request
from qrcode import QRCode
from qrcode.constants import ERROR_CORRECT_M

from .. import ApiError
from ..extensions import db
from ..models import Institution
from ..models.enums import InstitutionType, Role
from ..schemas import InstitutionCreateSchema, InstitutionUpdateSchema, load_json
from ._auth import current_user, roles_required

institutions_bp = Blueprint("institutions", __name__, url_prefix="/institutions")


@institutions_bp.get("")
def list_institutions():
    q = Institution.query.filter_by(is_active=True)
    if request.args.get("q"):
        kw = f"%{request.args['q'].strip()}%"
        q = q.filter(Institution.name.ilike(kw))
    if request.args.get("type"):
        q = q.filter(Institution.institution_type == InstitutionType(request.args["type"]))
    q = q.order_by(Institution.name)
    return jsonify({"data": [i.to_dict() for i in q.all()]})


@institutions_bp.get("/by-slug/<slug>")
def by_slug(slug):
    inst = Institution.query.filter_by(slug=slug, is_active=True).first()
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found", status=404)
    return jsonify({"data": inst.to_dict()})


@institutions_bp.post("")
@roles_required(Role.ADMIN)
def create():
    data = load_json(InstitutionCreateSchema(), request.get_json(silent=True) or {})
    inst = Institution(
        name=data["name"].strip(),
        slug=Institution.unique_slug(data["name"].strip()),
        institution_type=InstitutionType(data["institution_type"]) if data.get("institution_type") else None,
        address=data.get("address"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        contact_email=data.get("contact_email"),
        verified=data.get("verified", False),
    )
    db.session.add(inst)
    db.session.commit()
    return jsonify({"data": inst.to_dict(public=False)}), 201


@institutions_bp.patch("/<int:inst_id>")
def update(inst_id):
    user = current_user()
    inst = db.session.get(Institution, inst_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found", status=404)
    if user.role != Role.ADMIN:
        raise ApiError("FORBIDDEN", "Admin only", status=403)
    data = load_json(InstitutionUpdateSchema(), request.get_json(silent=True) or {})
    for field in ("name", "address", "latitude", "longitude", "contact_email"):
        if field in data:
            setattr(inst, field, data[field])
    if "institution_type" in data:
        inst.institution_type = InstitutionType(data["institution_type"]) if data["institution_type"] else None
    if "verified" in data:
        inst.verified = data["verified"]
    if "is_active" in data:
        inst.is_active = data["is_active"]
    db.session.commit()
    return jsonify({"data": inst.to_dict(public=False)})


@institutions_bp.get("/<int:inst_id>/qr.png")
def qr_png(inst_id):
    user = current_user()
    inst = db.session.get(Institution, inst_id)
    if inst is None:
        raise ApiError("NOT_FOUND", "Institution not found", status=404)
    if user.role != Role.ADMIN and not user.is_staff_of(inst.id):
        raise ApiError("FORBIDDEN", "Not allowed", status=403)
    size = request.args.get("size", type=int) or 400
    size = max(200, min(size, 1000))
    base_url = _base_url()
    qr = QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(f"{base_url}/i/{inst.slug}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size, size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png",
                    headers={"Content-Disposition": f'inline; filename="{inst.slug}-qr.png"'})


def _base_url():
    from flask import current_app
    return current_app.config.get("BASE_URL", "").rstrip("/")
