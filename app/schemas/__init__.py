"""Marshmallow schemas for request validation (Section 7.1: unknown fields rejected)."""
import re
from datetime import datetime, date

from marshmallow import Schema, ValidationError, fields, validate, validates, validates_schema, post_load, EXCLUDE

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _not_future(value):
    if isinstance(value, datetime):
        if value > datetime.utcnow():
            raise ValidationError("Date cannot be in the future.")
    elif isinstance(value, date):
        if value > date.today():
            raise ValidationError("Date cannot be in the future.")
    return value


class BaseSchema(Schema):
    class Meta:
        unknown = EXCLUDE  # reject unknown fields


class RegisterSchema(BaseSchema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=120))
    email = fields.Email(required=True, validate=validate.Length(max=255))
    password = fields.Str(required=True, load_only=True)
    phone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=30))

    @validates("password")
    def password_policy(self, value, **kwargs):
        if len(value) < 8:
            raise ValidationError("Password must be at least 8 characters.")
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValidationError("Password must contain at least one letter and one digit.")


class LoginSchema(BaseSchema):
    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True)


class ChangePasswordSchema(BaseSchema):
    current_password = fields.Str(required=True, load_only=True)
    new_password = fields.Str(required=True, load_only=True)

    @validates("new_password")
    def password_policy(self, value, **kwargs):
        if len(value) < 8:
            raise ValidationError("Password must be at least 8 characters.")
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValidationError("Password must contain at least one letter and one digit.")


class UpdateProfileSchema(BaseSchema):
    name = fields.Str(required=False, validate=validate.Length(min=2, max=120))
    phone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=30))


class ReportCreateSchema(BaseSchema):
    report_type = fields.Str(required=True, validate=validate.OneOf(["LOST", "FOUND"]))
    category = fields.Str(required=True, validate=validate.OneOf([
        "ELECTRONICS", "BAGS", "WALLETS_CARDS", "KEYS", "CLOTHING",
        "JEWELRY_ACCESSORIES", "DOCUMENTS_ID", "BOOKS_STATIONERY",
        "BOTTLES_LUNCHBOXES", "SPORTS", "OTHER",
    ]))
    title = fields.Str(required=True, validate=validate.Length(min=3, max=150))
    description = fields.Str(required=True, validate=validate.Length(min=10, max=2000))
    private_details = fields.Str(required=False, allow_none=True, validate=validate.Length(max=1000))
    incident_date = fields.DateTime(required=True, validate=_not_future)
    latitude = fields.Float(required=False, allow_none=True, validate=validate.Range(-90, 90))
    longitude = fields.Float(required=False, allow_none=True, validate=validate.Range(-180, 180))
    location_text = fields.Str(required=False, allow_none=True, validate=validate.Length(max=255))
    institution_id = fields.Int(required=False, allow_none=True)
    custody = fields.Str(required=False, allow_none=True,
                         validate=validate.OneOf(["WITH_FINDER", "AT_INSTITUTION"]))

    @validates_schema
    def custody_required_for_found(self, data, **kwargs):
        if data.get("report_type") == "FOUND" and not data.get("custody"):
            raise ValidationError({"custody": ["custody is required for FOUND reports."]})


class ReportUpdateSchema(BaseSchema):
    category = fields.Str(required=False, validate=validate.OneOf([
        "ELECTRONICS", "BAGS", "WALLETS_CARDS", "KEYS", "CLOTHING",
        "JEWELRY_ACCESSORIES", "DOCUMENTS_ID", "BOOKS_STATIONERY",
        "BOTTLES_LUNCHBOXES", "SPORTS", "OTHER",
    ]))
    title = fields.Str(required=False, validate=validate.Length(min=3, max=150))
    description = fields.Str(required=False, validate=validate.Length(min=10, max=2000))
    private_details = fields.Str(required=False, allow_none=True, validate=validate.Length(max=1000))
    incident_date = fields.DateTime(required=False, validate=_not_future)
    latitude = fields.Float(required=False, allow_none=True, validate=validate.Range(-90, 90))
    longitude = fields.Float(required=False, allow_none=True, validate=validate.Range(-180, 180))
    location_text = fields.Str(required=False, allow_none=True, validate=validate.Length(max=255))
    custody = fields.Str(required=False, allow_none=True,
                         validate=validate.OneOf(["WITH_FINDER", "AT_INSTITUTION"]))


class ClaimCreateSchema(BaseSchema):
    claim_details = fields.Str(required=True, validate=validate.Length(min=20, max=1500))


class MessageCreateSchema(BaseSchema):
    message = fields.Str(required=True, validate=validate.Length(min=1, max=1000))


class InstitutionCreateSchema(BaseSchema):
    name = fields.Str(required=True, validate=validate.Length(min=2, max=200))
    institution_type = fields.Str(required=False, allow_none=True, validate=validate.OneOf([
        "COLLEGE", "RAILWAY", "METRO", "AIRPORT", "BUS_TERMINAL",
        "MALL", "VENUE", "HOTEL", "PUBLIC", "OTHER",
    ]))
    address = fields.Str(required=False, allow_none=True)
    latitude = fields.Float(required=False, allow_none=True, validate=validate.Range(-90, 90))
    longitude = fields.Float(required=False, allow_none=True, validate=validate.Range(-180, 180))
    contact_email = fields.Email(required=False, allow_none=True)
    verified = fields.Bool(required=False)


class InstitutionUpdateSchema(InstitutionCreateSchema):
    name = fields.Str(required=False, validate=validate.Length(min=2, max=200))
    is_active = fields.Bool(required=False)


class AdminUserPatchSchema(BaseSchema):
    role = fields.Str(required=False, validate=validate.OneOf(["USER", "STAFF", "ADMIN"]))
    is_active = fields.Bool(required=False)
    institution_id = fields.Int(required=False, allow_none=True)


class ReviewNoteSchema(BaseSchema):
    review_note = fields.Str(required=False, allow_none=True, validate=validate.Length(max=1000))


class RejectSchema(BaseSchema):
    review_note = fields.Str(required=True, validate=validate.Length(min=5, max=1000))


class DisputeSchema(BaseSchema):
    reason = fields.Str(required=True, validate=validate.Length(min=5, max=1000))


class RemoveReportSchema(BaseSchema):
    reason = fields.Str(required=True, validate=validate.Length(min=3, max=255))


class ResolveSchema(BaseSchema):
    decision = fields.Str(required=True, validate=validate.OneOf(["APPROVE", "REJECT"]))
    note = fields.Str(required=False, allow_none=True)


def load_json(schema, data):
    """Validate and load; raise ApiError with 400 on failure."""
    try:
        return schema.load(data or {})
    except ValidationError as e:
        from .. import ApiError
        raise ApiError("VALIDATION_ERROR", "Invalid input", status=400, details=e.messages)
