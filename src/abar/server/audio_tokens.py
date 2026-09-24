"""Short-lived opaque grants to already-resolved immutable audio objects.

Object identities stay server-side; delivery does not need to replay the workspace.
"""

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

    def issue(self, root: Path, object_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            self._records[token] = (root, object_id, now + self.lifetime_seconds)
        return f"/api/audio/{token}"

    def consume(self, token: str) -> tuple[Path, str] | None:
        """Resolve a grant; it stays valid until it expires (players may refetch)."""

        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            record = self._records.get(token)
            if record is None:
                return None
            root, object_id, _expires_at = record
            return root, object_id

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def _purge_expired(self, now: float) -> None:
        # Grants are issued per Deck view, so without purging a long-running UI
        # server accumulates every grant it ever issued.
        expired = [token for token, record in self._records.items() if record[2] < now]
        for token in expired:
            del self._records[token]
