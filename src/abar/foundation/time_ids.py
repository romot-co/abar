"""RFC 9562 UUIDv7 identifiers with domain prefixes."""

import secrets
import threading
import time
import uuid

_LOCK = threading.Lock()
_last_millisecond: int = -1
_sequence: int = 0


def uuid7() -> uuid.UUID:
    """Return a monotonic UUIDv7 for this process."""

    global _last_millisecond, _sequence
    with _LOCK:
        millisecond = time.time_ns() // 1_000_000
        if millisecond == _last_millisecond:
            _sequence = (_sequence + 1) & 0xFFF
            if _sequence == 0:
                while millisecond <= _last_millisecond:
                    millisecond = time.time_ns() // 1_000_000
        else:
            _sequence = secrets.randbits(12)
        _last_millisecond = millisecond
        random_b = secrets.randbits(62)

    value = (millisecond & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= (_sequence & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_b
    return uuid.UUID(int=value)


def new_id(prefix: str) -> str:
    if not prefix or not prefix.endswith("_"):
        raise ValueError("ID prefix must be non-empty and end with '_'")
    return f"{prefix}{uuid7()}"
