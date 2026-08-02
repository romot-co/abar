"""Non-authoritative research observations: notes, memos, and indicators."""

import hashlib
import math
from pathlib import Path
from typing import Literal

from abar.app.actors import Actor
from abar.app.command_support import CommandError, existing_operation, operation_key, request_hash
from abar.app.events import draft
from abar.app.repository import WorkspaceRepository
from abar.foundation.json_types import JSONValue
from abar.research.models import Indicator


def write_note(
    repository: WorkspaceRepository,
    markdown: str,
    *,
    actor_id: str,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    fingerprint = request_hash("note.write", {"markdown": markdown, "actor_id": actor_id})
    if (
        existing_operation(
            repository,
            key,
            "note.updated",
            request_hash=fingerprint,
        )
        is not None
    ):
        return
    data = markdown.encode("utf-8")
    if len(data) > 64 * 1024:
        raise CommandError("Note exceeds 64 KiB")
    project = repository.state().project.project
    if project is None:
        raise CommandError("Project does not exist")
    repository.events.append(
        draft(
            "note.updated",
            {
                "project_id": project.id,
                "markdown": markdown,
                "content_sha": f"sha256:{hashlib.sha256(data).hexdigest()}",
                "actor_id": actor_id,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )


def record_session_memo(
    repository: WorkspaceRepository,
    project_session_id: str,
    text: str,
    *,
    idempotency_key: str | None = None,
) -> bool:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "session_memo.record",
        {"project_session_id": project_session_id, "text": text},
    )
    if (
        existing_operation(
            repository,
            key,
            "session.memo.recorded",
            request_hash=fingerprint,
        )
        is not None
    ):
        return True
    if not text:
        return False
    if len(text) > 500:
        raise CommandError("session memo exceeds 500 code points")
    state = repository.state()
    project_session = state.research.project_sessions[project_session_id]
    if state.compare.session_runtime[project_session.core_session_id].status != "ended":
        raise CommandError("session memo requires an ended Session")
    repository.events.append(
        draft(
            "session.memo.recorded",
            {
                "project_session_id": project_session_id,
                "text": text,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
    return True


def register_indicator(
    repository: WorkspaceRepository,
    *,
    indicator_id: str,
    label: str,
    description: str,
    definition_path: Path,
    subject_kind: Literal["audio", "prepared_pair"],
    unit: str,
    role: Literal["target", "guard", "none"] = "none",
    actor_id: str,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    data = definition_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    definition_sha = f"sha256:{digest}"
    definition_ref = f"obj_{digest}"
    fingerprint = request_hash(
        "indicator.register",
        {
            "indicator_id": indicator_id,
            "label": label,
            "description": description,
            "definition_sha": definition_sha,
            "subject_kind": subject_kind,
            "unit": unit,
            "role": role,
            "actor_id": actor_id,
        },
    )
    if (
        existing_operation(repository, key, "indicator.registered", request_hash=fingerprint)
        is not None
    ):
        return
    indicator = Indicator(
        id=indicator_id,
        label=label,
        description=description,
        definition_ref=definition_ref,
        definition_sha=definition_sha,
        subject_kind=subject_kind,
        unit=unit,
        role=role,
    )
    stored_definition = repository.objects.put(data)
    if stored_definition.object_id != definition_ref:
        raise CommandError("indicator_definition_store_failed")
    repository.events.append(
        draft(
            "indicator.registered",
            {
                "indicator_id": indicator.id,
                "label": indicator.label,
                "description": indicator.description,
                "definition_ref": indicator.definition_ref,
                "definition_sha": indicator.definition_sha,
                "subject_kind": indicator.subject_kind,
                "unit": indicator.unit,
                "role": indicator.role,
                "evidence_session_ids": [],
                "actor_id": actor_id,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )


def update_indicator(
    repository: WorkspaceRepository,
    indicator_id: str,
    *,
    role: Literal["target", "guard", "none"] | None = None,
    evidence_session_ids: tuple[str, ...] | None = None,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "indicator.update",
        {
            "indicator_id": indicator_id,
            "role": role,
            "evidence_session_ids": None
            if evidence_session_ids is None
            else list(evidence_session_ids),
        },
    )
    if (
        existing_operation(repository, key, "indicator.updated", request_hash=fingerprint)
        is not None
    ):
        return
    state = repository.state()
    if indicator_id not in state.research.indicators:
        raise CommandError("unknown Indicator")
    if evidence_session_ids is not None and any(
        item not in state.research.project_sessions for item in evidence_session_ids
    ):
        raise CommandError("unknown evidence Session")
    payload: dict[str, JSONValue] = {
        "indicator_id": indicator_id,
        "request_hash": fingerprint,
    }
    if role is not None:
        payload["role"] = role
    if evidence_session_ids is not None:
        payload["evidence_session_ids"] = list(evidence_session_ids)
    repository.events.append(draft("indicator.updated", payload, idempotency_key=key))


def record_indicator_value(
    repository: WorkspaceRepository,
    *,
    indicator_id: str,
    subject_id: str,
    variant_id: str,
    value: float,
    guard_result: Literal["pass", "fail"] | None = None,
    actor: Actor,
    artifact: bytes | None = None,
    idempotency_key: str | None = None,
) -> None:
    if not math.isfinite(value):
        raise CommandError("Indicator value must be finite")
    key = operation_key(idempotency_key)
    artifact_sha = None if artifact is None else f"sha256:{hashlib.sha256(artifact).hexdigest()}"
    fingerprint = request_hash(
        "indicator_value.record",
        {
            "indicator_id": indicator_id,
            "subject_id": subject_id,
            "variant_id": variant_id,
            "value": value,
            "guard_result": guard_result,
            "producer": actor.id,
            "artifact_sha": artifact_sha,
        },
    )
    if (
        existing_operation(repository, key, "indicator.value.recorded", request_hash=fingerprint)
        is not None
    ):
        return
    state = repository.state()
    indicator = state.research.indicators.get(indicator_id)
    if indicator is None:
        raise CommandError("unknown Indicator")
    if variant_id != "source" and variant_id not in state.compare.variants:
        raise CommandError("unknown Indicator Variant")
    if indicator.role != "guard" and guard_result is not None:
        raise CommandError("guard result requires a guard Indicator")
    known = (
        subject_id in state.compare.audio
        if indicator.subject_kind == "audio"
        else subject_id in state.compare.prepared_pairs
    )
    if not known:
        raise CommandError("unknown Indicator subject")
    artifact_id = repository.objects.put(artifact).object_id if artifact is not None else None
    repository.events.append(
        draft(
            "indicator.value.recorded",
            {
                "indicator_id": indicator_id,
                "subject_id": subject_id,
                "variant_id": variant_id,
                "value": value,
                "guard_result": guard_result,
                "producer": actor.id,
                "artifact_id": artifact_id,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
