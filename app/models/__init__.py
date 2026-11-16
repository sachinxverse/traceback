"""Database models for Project TRACEBACK (Section 5 of the spec)."""
import uuid
from datetime import UTC, datetime

from ..extensions import db

Column = db.Column
Integer = db.Integer
String = db.String
Text = db.Text
Float = db.Float
Boolean = db.Boolean
DateTime = db.DateTime
LargeBinary = db.LargeBinary
JSON = db.JSON
ForeignKey = db.ForeignKey
Index = db.Index
UniqueConstraint = db.UniqueConstraint
Enum = lambda *values, name=None: db.Enum(*values, name=name, native_enum=False)


def utcnow():
    """Naive UTC timestamp used for all model timestamps (spec: timezone-naive UTC)."""
    return datetime.now(UTC).replace(tzinfo=None)


def new_uuid():
    return str(uuid.uuid4())


def utc_iso(dt):
    """Serialise a naive-UTC datetime as ISO-8601 Z string."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# Import submodules so that all tables register on db.metadata.
from .claim import Claim  # noqa: F401
from .institution import Institution  # noqa: F401
from .match import Match  # noqa: F401
from .misc import AuditLog, ClaimImage, Message, Notification, TokenBlocklist  # noqa: F401
from .otp import OtpChallenge  # noqa: F401
from .report import Report, ReportImage  # noqa: F401
from .user import User  # noqa: F401
