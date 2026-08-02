"""Short-lived opaque tokens for browser audio delivery."""

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock


@dataclass(slots=True)
class AudioTokenStore:
    lifetime_seconds: float = 300.0
    _records: dict[str, tuple[Path, str, float]] = field(
        default_factory=dict[str, tuple[Path, str, float]]
    )
    _lock: Lock = field(default_factory=Lock)

    def issue(self, root: Path, audio_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._records[token] = (
                root,
                audio_id,
                time.monotonic() + self.lifetime_seconds,
            )
        return f"/api/audio/{token}"

    def consume(self, token: str) -> tuple[Path, str] | None:
        now = time.monotonic()
        with self._lock:
            record = self._records.get(token)
            if record is None or record[2] < now:
                self._records.pop(token, None)
                return None
            root, audio_id, _expires_at = record
            return root, audio_id
