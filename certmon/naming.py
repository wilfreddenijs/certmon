import re
import uuid


def safe_slug(value, *, max_length=80):
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value[:max_length]


def new_certificate_id(*, identifiers=(), profile=None, device_name=None, issuer_type=None):
    parts = []
    for value in (device_name, next(iter(identifiers), None), issuer_type, profile):
        part = safe_slug(value)
        if part and part not in parts:
            parts.append(part)
    base = "-".join(parts) or "certificate"
    return f"{base}-{uuid.uuid4().hex[:8]}"
