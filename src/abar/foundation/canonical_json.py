import hashlib
import json
import math
import unicodedata

from abar.foundation.json_types import JSONValue


class CanonicalJSONError(ValueError):
    """Raised when a value cannot be represented by ABAR canonical JSON."""


def _normalize(value: JSONValue) -> JSONValue:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJSONError("NaN and infinity are not valid canonical JSON numbers")
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    normalized: dict[str, JSONValue] = {}
    for key, item in value.items():
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in normalized:
            raise CanonicalJSONError(
                f"object keys collide after NFC normalization: {normalized_key!r}"
            )
        normalized[normalized_key] = _normalize(item)
    return normalized


def canonical_json_bytes(value: JSONValue) -> bytes:
    """Serialize a JSON value with stable ordering, UTF-8 NFC, and finite numbers."""

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: JSONValue) -> str:
    """Return the lowercase SHA-256 digest of a canonical JSON value."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
