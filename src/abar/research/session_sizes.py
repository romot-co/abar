"""Project Session size contracts."""

from typing import Literal

SessionSize = Literal["short", "standard"]

_STANDARD_DEFAULT = 3


def resolve_evidence_count(size: str, requested_count: int | None = None) -> int:
    if size == "short":
        if requested_count not in {None, 1}:
            raise ValueError("short Session requires exactly one evidence item")
        return 1
    if size != "standard":
        raise ValueError("Session size must be short or standard")
    count = _STANDARD_DEFAULT if requested_count is None else requested_count
    if count < _STANDARD_DEFAULT:
        raise ValueError("standard Session requires at least three evidence items")
    return count


def favored_count(evidence_items: int) -> int:
    return 1 if evidence_items == 1 else (2 * evidence_items + 2) // 3
