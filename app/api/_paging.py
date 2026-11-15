"""Shared pagination helper (Section 7.1: page/per_page with meta)."""
from flask import request

from .. import ApiError


def page_params(default_per_page=20, max_per_page=100):
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per_page = min(max(int(request.args.get("per_page", default_per_page)), 1),
                       max_per_page)
    except (TypeError, ValueError):
        raise ApiError("VALIDATION_ERROR", "page/per_page must be integers",
                       status=400)
    return page, per_page


def paginated(q, page, per_page, serializer, order_by=None):
    """Paginate a SQLAlchemy query and serialize items with meta."""
    if order_by is not None:
        q = q.order_by(order_by)
    pag = q.paginate(page=page, per_page=per_page, error_out=False)
    return {
        "data": [serializer(item) for item in pag.items],
        "meta": {"page": pag.page, "per_page": pag.per_page,
                 "total": pag.total, "pages": pag.pages},
    }
