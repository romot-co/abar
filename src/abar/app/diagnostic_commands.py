"""Observational diagnosis commands, separate from listening and adoption authority."""

from dataclasses import asdict
from typing import Literal, cast

from abar.app.command_support import CommandError, existing_operation, operation_key, request_hash
from abar.app.events import draft
from abar.app.repository import WorkspaceRepository
from abar.compare.models import TimeRange
from abar.foundation.json_types import JSONValue
from abar.foundation.time_ids import new_id
from abar.research.models import Symptom, validate_focus
from abar.research.verification import VerificationReport


def add_symptom(
    repository: WorkspaceRepository,
    *,
    delivery_id: str,
    side: Literal["a", "b"],
    title: str | None = None,
    context_seconds: float = 0.5,
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "symptom.add",
        {
            "delivery_id": delivery_id,
            "side": side,
            "title": title,
            "context_seconds": context_seconds,
            "actor_id": actor_id,
        },
    )
    existing = existing_operation(repository, key, "symptom.opened", request_hash=fingerprint)
    if existing is not None:
        return cast(str, existing.payload["id"])
    state = repository.state()
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    delivery = state.compare.deliveries.get(delivery_id)
    if delivery is None or side not in {"a", "b"}:
        raise CommandError("unknown Delivery or side")
    runtime = state.compare.session_runtime[delivery.session_id]
    if runtime.status != "ended" or not (
        runtime.revealed or state.compare.sessions[delivery.session_id].presentation == "open"
    ):
        raise CommandError("symptom registration requires an ended, revealed Session")
    judgment = state.compare.effective_judgment(delivery_id)
    if judgment is None:
        raise CommandError("symptom registration requires a human Judgment")
    blocker = judgment.blockers[side]
    if not blocker.selected or blocker.range is None:
        raise CommandError("symptom registration requires a ranged blocker")
    comparison = state.compare.comparisons[delivery.comparison_id]
    input_key = delivery.slot_assignment["A" if side == "a" else "B"]
    operand = next(item for item in comparison.pair if item.input_key == input_key)
    provenance = operand.provenance_ref
    clip_id = provenance.get("clip_id")
    if not isinstance(clip_id, str) or clip_id not in state.compare.clips:
        raise CommandError("symptom requires a Material Clip comparison")
    clip = state.compare.clips[clip_id]
    if clip.material_id not in project.material_ids:
        raise CommandError("symptom Material must belong to the Project")
    source = state.compare.audio[state.compare.materials[clip.material_id].source_audio_id]
    pair = state.compare.prepared_pairs[comparison.prepared_pair_id]
    audio = state.compare.audio[pair.output_audio_by_input_key[input_key]]
    lag = int(str(pair.features.get("alignment_lag_frames", 0)))
    trim = max(0, lag if input_key == "p1" else -lag) / audio.sample_rate
    offset = clip.start_frame / source.sample_rate + trim
    symptom = Symptom(
        id=new_id("sym_"),
        project_id=project.id,
        title=title if title is not None else blocker.note or "",
        source_delivery_id=delivery_id,
        source_slot=side,
        variant_id=str(provenance.get("variant_ref", "source")),
        material_id=clip.material_id,
        clip_id=clip.id,
        range=TimeRange(blocker.range.start_seconds + offset, blocker.range.end_seconds + offset),
        context_seconds=context_seconds,
        audio_pcm_sha=audio.pcm_sha,
        status="open",
        facts="",
        hypotheses="",
        dictionary_terms=(),
        created_event_seq=0,
    )
    payload = cast(dict[str, JSONValue], asdict(symptom))
    payload["dictionary_terms"] = []
    payload.update({"actor_id": actor_id, "request_hash": fingerprint})
    repository.events.append(draft("symptom.opened", payload, idempotency_key=key))
    return symptom.id


def update_symptom(
    repository: WorkspaceRepository,
    symptom_id: str,
    *,
    facts: str | None = None,
    hypotheses: str | None = None,
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    return _symptom_event(
        repository,
        symptom_id,
        "symptom.updated",
        {
            "facts": facts,
            "hypotheses": hypotheses,
        },
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )


def transition_symptom(
    repository: WorkspaceRepository,
    symptom_id: str,
    *,
    action: Literal["resolve", "reopen", "withdraw"],
    reason: str,
    session_id: str | None = None,
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    if not reason.strip():
        raise CommandError("symptom transition requires a reason")
    event_type = {
        "resolve": "symptom.resolved",
        "reopen": "symptom.reopened",
        "withdraw": "symptom.withdrawn",
    }[action]
    return _symptom_event(
        repository,
        symptom_id,
        event_type,
        {"reason": reason, "session_id": session_id},
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )


def _symptom_event(
    repository: WorkspaceRepository,
    symptom_id: str,
    event_type: str,
    data: dict[str, JSONValue],
    *,
    actor_id: str,
    idempotency_key: str | None,
) -> str:
    key = operation_key(idempotency_key)
    payload: dict[str, JSONValue] = {"symptom_id": symptom_id, "actor_id": actor_id, **data}
    fingerprint = request_hash(event_type, payload)
    if existing_operation(repository, key, event_type, request_hash=fingerprint) is not None:
        return symptom_id
    state = repository.state()
    symptom = state.research.symptoms.get(symptom_id)
    if symptom is None:
        raise CommandError("unknown Symptom")
    session_id = data.get("session_id")
    if isinstance(session_id, str):
        session = state.research.project_sessions.get(session_id)
        if (
            session is None
            or state.compare.session_runtime[session.core_session_id].status != "ended"
        ):
            raise CommandError("symptom evidence requires a completed Project Session")
    targets = {
        "symptom.resolved": "resolved",
        "symptom.reopened": "open",
        "symptom.withdrawn": "withdrawn",
    }
    if event_type in targets and symptom.status == targets[event_type]:
        raise CommandError("Symptom is already in that state")
    if event_type == "symptom.updated":
        payload["facts"] = symptom.facts if data.get("facts") is None else data["facts"]
        payload["hypotheses"] = (
            symptom.hypotheses if data.get("hypotheses") is None else data["hypotheses"]
        )
        payload["dictionary_terms"] = list(symptom.dictionary_terms)
    repository.events.append(
        draft(event_type, {**payload, "request_hash": fingerprint}, idempotency_key=key)
    )
    return symptom_id


def record_verification(
    repository: WorkspaceRepository,
    report: VerificationReport,
    *,
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    data = cast(dict[str, JSONValue], report.model_dump(mode="json"))
    fingerprint = request_hash("verification.record", {"report": data, "actor_id": actor_id})
    existing = existing_operation(
        repository, key, "verification.recorded", request_hash=fingerprint
    )
    if existing is not None:
        return cast(str, existing.payload["verification_id"])
    state = repository.state()
    project = state.project.project
    if project is None or report.material_id not in project.material_ids:
        raise CommandError("verification requires a Project Material")
    if report.variant_id != "source" and report.variant_id not in state.compare.variants:
        raise CommandError("unknown verification Variant")
    for check in report.checks:
        if (
            check.against is not None
            and check.against != "source"
            and check.against not in state.compare.variants
        ):
            raise CommandError("unknown verification counterpart")
        if check.symptom_id is not None and check.symptom_id not in state.research.symptoms:
            raise CommandError("unknown verification Symptom")
    verification_id = new_id("ver_")
    repository.events.append(
        draft(
            "verification.recorded",
            {
                "verification_id": verification_id,
                "report": data,
                "actor_id": actor_id,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
    return verification_id


def record_baseline(
    repository: WorkspaceRepository,
    variant_id: str,
    *,
    label: str,
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    validate_focus(label)
    return _project_observation(
        repository,
        "baseline.recorded",
        {
            "variant_id": variant_id,
            "label": label,
        },
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )


def flag_current_best(
    repository: WorkspaceRepository,
    *,
    symptom_id: str,
    session_id: str,
    reason: str,
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    if not reason.strip():
        raise CommandError("flag requires a reason")
    return _project_observation(
        repository,
        "current_best.flagged",
        {
            "symptom_id": symptom_id,
            "session_id": session_id,
            "reason": reason,
        },
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )


def _project_observation(
    repository: WorkspaceRepository,
    event_type: str,
    data: dict[str, JSONValue],
    *,
    actor_id: str,
    idempotency_key: str | None,
) -> str:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(event_type, {**data, "actor_id": actor_id})
    existing = existing_operation(repository, key, event_type, request_hash=fingerprint)
    if existing is not None:
        return cast(str, existing.payload["variant_id"])
    state = repository.state()
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    variant_id = cast(str, data.get("variant_id", project.current_best_variant_id))
    if variant_id != "source" and variant_id not in state.compare.variants:
        raise CommandError("unknown Variant")
    if event_type == "current_best.flagged":
        symptom_id = cast(str, data["symptom_id"])
        session_id = cast(str, data["session_id"])
        session = state.research.project_sessions.get(session_id)
        if symptom_id not in state.research.symptoms or session is None:
            raise CommandError("unknown Symptom or Project Session")
        if state.compare.session_runtime[session.core_session_id].status != "ended":
            raise CommandError("flag requires a completed Project Session")
        if variant_id not in session.pair or session.symptom_id != symptom_id:
            raise CommandError(
                "flag evidence must compare current best under the specified Symptom"
            )
    repository.events.append(
        draft(
            event_type,
            {
                **data,
                "project_id": project.id,
                "variant_id": variant_id,
                "actor_id": actor_id,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
    return variant_id
