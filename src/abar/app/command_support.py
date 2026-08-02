"""Shared command-boundary errors and idempotency policy."""

import secrets
from collections.abc import Mapping

from abar.app.repository import WorkspaceRepository
from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.events import EventEnvelope
from abar.foundation.json_types import JSONValue

_ERROR_CODES = {
    "idempotency key was already used for another operation": "idempotency_conflict",
    "idempotency key was reused with a different request": "idempotency_conflict",
    "Judgment is immutable once recorded": "judgment_already_recorded",
    "Judgment requires an active Session": "session_not_active",
    "answered Delivery cannot be skipped": "delivery_already_answered",
    "Delivery can only be skipped in an active Session": "session_not_active",
    "another Project Session is active": "project_session_already_active",
    "an unfinished Session with the same fingerprint already exists": "duplicate_session",
    "Session is not ready": "session_not_ready",
    "Session is not active": "session_not_active",
    "evidence protocol invalid": "project_session_blocked",
    "skip_confirmation_required": "skip_confirmation_required",
    "human authority is required": "human_required",
    "Best Update proposal must differ from Current Best": "best_update_same_variant",
    "Best Update has no audible evidence; create a Simplification Plan instead": (
        "best_update_no_effect"
    ),
}


class CommandError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        resolved_message = code if message is None else message
        self.code = (
            _ERROR_CODES.get(resolved_message, "command_rejected") if message is None else code
        )
        super().__init__(resolved_message)


def operation_key(value: str | None = None) -> str:
    return value or f"op_{secrets.token_urlsafe(18)}"


def request_hash(command: str, request: Mapping[str, JSONValue]) -> str:
    return f"sha256:{canonical_sha256({'command': command, 'request': dict(request)})}"


def existing_operation(
    repository: WorkspaceRepository,
    key: str,
    expected_event_type: str,
    expected_payload: Mapping[str, JSONValue] | None = None,
    request_hash: str | None = None,
) -> EventEnvelope | None:
    events = repository.events.read_operation(key)
    if not events:
        return None
    matching = next((item for item in events if item.event_type == expected_event_type), None)
    if matching is None:
        raise CommandError("idempotency key was already used for another operation")
    if expected_payload is not None and any(
        matching.payload.get(name) != value for name, value in expected_payload.items()
    ):
        raise CommandError("idempotency key was reused with a different request")
    if request_hash is not None and matching.payload.get("request_hash") != request_hash:
        raise CommandError("idempotency key was reused with a different request")
    return matching
