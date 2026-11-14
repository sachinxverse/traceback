"""Image upload pipeline (Section 8)."""
import io
import uuid
from datetime import datetime

from PIL import Image, ImageOps

from .. import ApiError
from ..extensions import db
from ..models import ReportImage, ClaimImage

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MIN_DIMENSION = 100
MAX_DIMENSION = 8000
MAX_EDGE = 1600
JPEG_QUALITY = 85


def _check_size_limits(data: bytes, max_mb: int):
    if len(data) > max_mb * 1024 * 1024:
        raise ApiError("FILE_TOO_LARGE", f"Image exceeds the {max_mb} MB limit", status=413)


def validate_and_process(data: bytes, filename: str, max_mb: int = 5) -> dict:
    """Validate one uploaded image and return (processed_jpeg_bytes, metadata).

    Pipeline: verify content with Pillow, enforce dimension limits, apply
    exif_transpose, convert to RGB, resize longest edge to <=1600 px, re-encode
    as JPEG quality 85 (which strips all EXIF/GPS metadata).
    """
    _check_size_limits(data, max_mb)

    ext = (filename.rsplit(".", 1)[-1] or "").lower() if "." in (filename or "") else ""
    if ext not in ALLOWED_EXTENSIONS:
        # content sniffing still allowed below if extension unknown? Spec says
        # check extension AND verify content; unknown extension is rejected.
        raise ApiError("BAD_REQUEST", "Unsupported file type (use JPEG, PNG or WEBP)", status=400)

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception:
        raise ApiError("BAD_REQUEST", "Not a valid image file", status=400)

    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if w < MIN_DIMENSION or h < MIN_DIMENSION or w > MAX_DIMENSION or h > MAX_DIMENSION:
            raise ApiError(
                "BAD_REQUEST",
                f"Image must be between {MIN_DIMENSION}x{MIN_DIMENSION} and "
                f"{MAX_DIMENSION}x{MAX_DIMENSION} px", status=400)
        if max(img.size) > MAX_EDGE:
            img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        buf.seek(0)
        out = buf.getvalue()
    except ApiError:
        raise
    except Exception:
        raise ApiError("BAD_REQUEST", "Could not process image", status=400)

    processed = Image.open(io.BytesIO(out))
    return {
        "data": out,
        "mime_type": "image/jpeg",
        "width": processed.width,
        "height": processed.height,
        "size_bytes": len(out),
    }


def make_storage_key() -> str:
    now = datetime.utcnow()
    return f"{now:%Y}/{now:%m}/{uuid.uuid4()}.jpg"


def save_report_images(report, files, existing_count=0, max_images=4, max_mb=5):
    """Validate, process and persist uploaded image files for a report.

    Returns the list of created ReportImage rows. Raises ApiError on any
    invalid file (nothing is saved when validation fails).
    """
    from ..services.storage import get_storage
    if len(files) + existing_count > max_images:
        raise ApiError("BAD_REQUEST", f"At most {max_images} images per report", status=400)
    processed_list = []
    for f in files:
        if f is None or not f.filename:
            continue
        data = f.read()
        meta = validate_and_process(data, f.filename, max_mb=max_mb)
        processed_list.append(meta)
    storage = get_storage()
    created = []
    base_pos = existing_count
    for i, meta in enumerate(processed_list):
        key = make_storage_key()
        storage.save(meta["data"], key)
        img = ReportImage(
            report=report,
            storage_key=key,
            mime_type=meta["mime_type"],
            width=meta["width"],
            height=meta["height"],
            size_bytes=meta["size_bytes"],
            position=base_pos + i,
        )
        db.session.add(img)
        created.append(img)
    return created


def save_claim_images(claim, files, max_images=2, max_mb=5):
    """Validate, process and persist proof images for a claim."""
    from ..services.storage import get_storage
    if len(files) > max_images:
        raise ApiError("BAD_REQUEST", f"At most {max_images} images per claim", status=400)
    processed_list = []
    for f in files:
        if f is None or not f.filename:
            continue
        data = f.read()
        processed_list.append(validate_and_process(data, f.filename, max_mb=max_mb))
    storage = get_storage()
    created = []
    for meta in processed_list:
        key = make_storage_key()
        storage.save(meta["data"], key)
        img = ClaimImage(claim=claim, storage_key=key, mime_type=meta["mime_type"],
                         size_bytes=meta["size_bytes"])
        db.session.add(img)
        created.append(img)
    return created
