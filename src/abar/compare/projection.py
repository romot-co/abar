"""Projection for Compare Core facts."""

from dataclasses import dataclass, field, replace
from typing import Literal, cast

from abar.compare.models import (
    AudioObject,
    BlockerInput,
    Clip,
    ComparisonPlan,
    CriterionSnapshot,
    Delivery,
    Judgment,
    Material,
    PreparedPair,
    RecipeRef,
    ResolvedOperand,
    Session,
    SessionItem,
    Telemetry,
    Variant,
)
from abar.foundation.events import EventEnvelope
from abar.foundation.json_types import JSONValue


@dataclass(frozen=True, slots=True)
class SessionRuntime:
    status: str = "ready"
    deliveries: tuple[str, ...] = ()
    skipped_item_ids: frozenset[str] = frozenset()
    invalid_item_ids: frozenset[str] = frozenset()
    revealed: bool = False
    ended_event_seq: int | None = None
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class CompareState:
    audio: dict[str, AudioObject] = field(default_factory=dict[str, AudioObject])
    materials: dict[str, Material] = field(default_factory=dict[str, Material])
    clips: dict[str, Clip] = field(default_factory=dict[str, Clip])
    variants: dict[str, Variant] = field(default_factory=dict[str, Variant])
    manifests: dict[str, dict[str, JSONValue]] = field(
        default_factory=dict[str, dict[str, JSONValue]]
    )
    provenance: dict[str, tuple[dict[str, JSONValue], ...]] = field(
        default_factory=dict[str, tuple[dict[str, JSONValue], ...]]
    )
    prepared_pairs: dict[str, PreparedPair] = field(default_factory=dict[str, PreparedPair])
    comparisons: dict[str, ComparisonPlan] = field(default_factory=dict[str, ComparisonPlan])
    sessions: dict[str, Session] = field(default_factory=dict[str, Session])
    session_runtime: dict[str, SessionRuntime] = field(default_factory=dict[str, SessionRuntime])
    deliveries: dict[str, Delivery] = field(default_factory=dict[str, Delivery])
    judgments: dict[str, Judgment] = field(default_factory=dict[str, Judgment])
    render_audio: dict[str, str] = field(default_factory=dict[str, str])

    def effective_judgment(self, delivery_id: str) -> Judgment | None:
        return self.judgments.get(delivery_id)


def reduce_compare(state: CompareState, event: EventEnvelope) -> CompareState:
    p = event.payload
    event_type = event.event_type
    if event_type in {"audio.imported", "audio.slice.created"}:
        audio = AudioObject(
            id=_str(p, "audio_id"),
            object_id=_str(p, "object_id"),
            pcm_sha=_str(p, "pcm_sha"),
            sample_rate=_int(p, "sample_rate"),
            channel_layout=cast(Literal["mono", "stereo"], p["channel_layout"]),
            frames=_int(p, "frames"),
        )
        next_state = replace(state, audio={**state.audio, audio.id: audio})
        clip_payload = p.get("clip")
        if event_type == "audio.slice.created" and isinstance(clip_payload, dict):
            clip = _clip(cast(dict[str, JSONValue], clip_payload))
            material = next_state.materials[clip.material_id]
            return replace(
                next_state,
                clips={**next_state.clips, clip.id: clip},
                materials={
                    **next_state.materials,
                    clip.material_id: replace(
                        material,
                        clip_ids=material.clip_ids
                        if clip.id in material.clip_ids
                        else (*material.clip_ids, clip.id),
                    ),
                },
            )
        return next_state
    if event_type == "material.added":
        clips = tuple(_clip(item) for item in _list_dict(p, "clips"))
        material = Material(
            id=_str(p, "material_id"),
            name=_str(p, "name"),
            source_audio_id=_str(p, "source_audio_id"),
            source_group=cast(str | None, p.get("source_group")),
            clip_ids=tuple(item.id for item in clips),
        )
        return replace(
            state,
            materials={**state.materials, material.id: material},
            clips={**state.clips, **{item.id: item for item in clips}},
        )
    if event_type == "variant.created":
        variant = Variant(
            id=_str(p, "variant_id"),
            label=cast(str | None, p.get("label")),
            manifest_id=_str(p, "manifest_id"),
            resolved_params=cast(dict[str, JSONValue], p["resolved_params"]),
            render_contract=cast(Literal["renderable", "finite_rendered"], p["render_contract"]),
        )
        manifest = cast(dict[str, JSONValue], p["manifest"])
        existing_variant = state.variants.get(variant.id)
        if existing_variant is not None and existing_variant != variant:
            raise ValueError("Variant definition is immutable")
        existing_manifest = state.manifests.get(variant.manifest_id)
        if existing_manifest is not None and existing_manifest != manifest:
            raise ValueError("Variant manifest is immutable")
        return replace(
            state,
            variants={**state.variants, variant.id: variant},
            manifests={**state.manifests, variant.manifest_id: manifest},
        )
    if event_type == "variant.provenance.observed":
        variant_id = _str(p, "variant_id")
        observed = cast(dict[str, JSONValue], p["provenance"])
        return replace(
            state,
            provenance={
                **state.provenance,
                variant_id: (*state.provenance.get(variant_id, ()), observed),
            },
        )
    if event_type == "render.completed":
        key = f"{_str(p, 'variant_id')}:{_str(p, 'material_id')}:{_str(p, 'runtime_fingerprint')}"
        audio = AudioObject(
            id=_str(p, "audio_id"),
            object_id=_str(p, "object_id"),
            pcm_sha=_str(p, "pcm_sha"),
            sample_rate=_int(p, "sample_rate"),
            channel_layout=cast(Literal["mono", "stereo"], p["channel_layout"]),
            frames=_int(p, "frames"),
        )
        return replace(
            state,
            audio={**state.audio, audio.id: audio},
            render_audio={**state.render_audio, key: audio.id},
        )
    if event_type == "prepared_pair.created":
        recipe = _recipe(cast(dict[str, JSONValue], p["recipe"]))
        pair = PreparedPair(
            id=_str(p, "prepared_pair_id"),
            input_audio_ids=tuple(cast(list[str], p["input_audio_ids"])),  # type: ignore[arg-type]
            recipe=recipe,
            output_audio_by_input_key=cast(
                dict[Literal["p1", "p2"], str], p["output_audio_by_input_key"]
            ),
            features=cast(dict[str, JSONValue], p["features"]),
            warnings=tuple(cast(list[str], p["warnings"])),
            no_effect=cast(bool, p["no_effect"]),
        )
        return replace(state, prepared_pairs={**state.prepared_pairs, pair.id: pair})
    if event_type == "comparison.planned":
        pair_items = cast(list[dict[str, JSONValue]], p["pair"])
        comparison = ComparisonPlan(
            id=_str(p, "comparison_id"),
            pair=tuple(
                ResolvedOperand(
                    input_key=cast(Literal["p1", "p2"], item["input_key"]),
                    audio_id=cast(str, item["audio_id"]),
                    provenance_ref=cast(dict[str, JSONValue], item["provenance_ref"]),
                )
                for item in pair_items
            ),  # type: ignore[arg-type]
            recipe=_recipe(cast(dict[str, JSONValue], p["recipe"])),
            prepared_pair_id=_str(p, "prepared_pair_id"),
        )
        return replace(state, comparisons={**state.comparisons, comparison.id: comparison})
    if event_type == "session.planned":
        criterion_payload = cast(dict[str, JSONValue] | None, p.get("criterion"))
        criterion = (
            None
            if criterion_payload is None
            else CriterionSnapshot(
                text=cast(str, criterion_payload["text"]),
                source=cast(
                    Literal["focus", "project_brief"] | None,
                    criterion_payload.get("source"),
                ),
                source_event_seq=cast(int | None, criterion_payload.get("source_event_seq")),
            )
        )
        items = tuple(
            SessionItem(
                id=cast(str, item["id"]),
                comparison_id=cast(str, item["comparison_id"]),
                sequence_index=cast(int, item["sequence_index"]),
            )
            for item in _list_dict(p, "items")
        )
        session = Session(
            id=_str(p, "session_id"),
            items=items,
            presentation=cast(Literal["open", "blind"], p["presentation"]),
            reveal_policy=cast(
                Literal["immediate", "after_answer_or_manual", "on_end"],
                p["reveal_policy"],
            ),
            criterion=criterion,
        )
        return replace(
            state,
            sessions={**state.sessions, session.id: session},
            session_runtime={**state.session_runtime, session.id: SessionRuntime()},
        )
    if event_type == "session.started":
        return _runtime(state, _str(p, "session_id"), status="active")
    if event_type == "session.blocked":
        return _runtime(
            state,
            _str(p, "session_id"),
            status="blocked",
            outcome=_str(p, "reason"),
        )
    if event_type == "session.paused":
        return _runtime(
            state,
            _str(p, "session_id"),
            status="paused" if cast(bool, p["paused"]) else "active",
        )
    if event_type == "session.ended":
        return _runtime(
            state,
            _str(p, "session_id"),
            status="closed" if p.get("outcome") == "closed" else "ended",
            ended_event_seq=event.event_seq,
            outcome=cast(str, p["outcome"]),
        )
    if event_type == "session.revealed":
        return _runtime(state, _str(p, "session_id"), revealed=True)
    if event_type == "comparison.delivered":
        delivery = Delivery(
            id=_str(p, "delivery_id"),
            session_id=_str(p, "session_id"),
            session_item_id=_str(p, "session_item_id"),
            comparison_id=_str(p, "comparison_id"),
            slot_assignment=cast(
                dict[Literal["A", "B"], Literal["p1", "p2"]], p["slot_assignment"]
            ),
            presentation=cast(Literal["open", "blind"], p["presentation"]),
            sequence_index=_int(p, "sequence_index"),
        )
        runtime = state.session_runtime[delivery.session_id]
        runtimes = {
            **state.session_runtime,
            delivery.session_id: replace(runtime, deliveries=(*runtime.deliveries, delivery.id)),
        }
        return replace(
            state,
            deliveries={**state.deliveries, delivery.id: delivery},
            session_runtime=runtimes,
        )
    if event_type == "judgment.recorded":
        blockers_payload = cast(dict[str, dict[str, JSONValue]], p["blockers"])
        telemetry_payload = cast(dict[str, JSONValue], p["telemetry"])
        judgment = Judgment(
            id=_str(p, "judgment_id"),
            delivery_id=_str(p, "delivery_id"),
            preference=cast(Literal[1, 2, 3, 4, 5], p["preference"]),
            blockers={
                cast(Literal["a", "b"], slot): BlockerInput(
                    selected=cast(bool, value["selected"]),
                    note=cast(str | None, value.get("note")),
                )
                for slot, value in blockers_payload.items()
            },  # type: ignore[arg-type]
            comment=cast(str | None, p.get("comment")),
            identity_visible_at_answer=cast(bool, p["identity_visible_at_answer"]),
            telemetry=Telemetry(
                listen_ms=cast(dict[Literal["a", "b"], int], telemetry_payload["listen_ms"]),
                switches=cast(int, telemetry_payload["switches"]),
                answer_ms=cast(int, telemetry_payload["answer_ms"]),
            ),
        )
        if judgment.delivery_id in state.judgments:
            raise ValueError("Judgment is immutable once recorded")
        delivery = state.deliveries[judgment.delivery_id]
        runtime = state.session_runtime[delivery.session_id]
        return replace(
            state,
            judgments={**state.judgments, judgment.delivery_id: judgment},
            session_runtime={
                **state.session_runtime,
                delivery.session_id: replace(
                    runtime,
                    skipped_item_ids=runtime.skipped_item_ids - {delivery.session_item_id},
                ),
            },
        )
    if event_type == "comparison.skipped":
        session_id = _str(p, "session_id")
        runtime = state.session_runtime[session_id]
        return replace(
            state,
            session_runtime={
                **state.session_runtime,
                session_id: replace(
                    runtime,
                    skipped_item_ids=runtime.skipped_item_ids | {_str(p, "session_item_id")},
                ),
            },
        )
    if event_type == "comparison.protocol_invalidated":
        session_id = _str(p, "session_id")
        runtime = state.session_runtime[session_id]
        return replace(
            state,
            session_runtime={
                **state.session_runtime,
                session_id: replace(
                    runtime,
                    invalid_item_ids=runtime.invalid_item_ids | {_str(p, "session_item_id")},
                ),
            },
        )
    return state


def _runtime(state: CompareState, session_id: str, **changes: object) -> CompareState:
    runtime = state.session_runtime[session_id]
    return replace(
        state,
        session_runtime={**state.session_runtime, session_id: replace(runtime, **changes)},
    )


def _clip(payload: dict[str, JSONValue]) -> Clip:
    return Clip(
        id=cast(str, payload["id"]),
        material_id=cast(str, payload["material_id"]),
        start_frame=cast(int, payload["start_frame"]),
        frames=cast(int, payload["frames"]),
        role=cast(str | None, payload.get("role")),
        selector_id=cast(str | None, payload.get("selector_id")),
        selector_version=cast(int | None, payload.get("selector_version")),
        seed=cast(int | None, payload.get("seed")),
    )


def _recipe(payload: dict[str, JSONValue]) -> RecipeRef:
    return RecipeRef(
        id=cast(Literal["native", "aligned", "matched"], payload["id"]),
        version=cast(Literal[1], payload["version"]),
        config=cast(dict[str, JSONValue], payload.get("config", {})),
    )


def _str(payload: dict[str, JSONValue], key: str) -> str:
    return cast(str, payload[key])


def _int(payload: dict[str, JSONValue], key: str) -> int:
    return cast(int, payload[key])


def _list_dict(payload: dict[str, JSONValue], key: str) -> list[dict[str, JSONValue]]:
    return cast(list[dict[str, JSONValue]], payload[key])
