"""Canonical event payload construction shared by application use cases."""

from abar.compare.audio.importing import InputAudioMetadata
from abar.compare.models import (
    AudioObject,
    Clip,
    ComparisonPlan,
    CriterionSnapshot,
    Delivery,
    Judgment,
    Material,
    PreparedPair,
    RecipeRef,
    Session,
)
from abar.foundation.json_types import JSONValue


def audio_payload(
    audio: AudioObject,
    *,
    provenance: str,
    input_source: InputAudioMetadata | None = None,
) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "audio_id": audio.id,
        "object_id": audio.object_id,
        "pcm_sha": audio.pcm_sha,
        "sample_rate": audio.sample_rate,
        "channel_layout": audio.channel_layout,
        "frames": audio.frames,
        "provenance_kind": provenance,
    }
    if input_source is not None:
        payload["input_source"] = {
            "container": input_source.container,
            "subtype": input_source.subtype,
            "original_sha": input_source.original_sha,
            "decoder": input_source.decoder,
            "decoder_version": input_source.decoder_version,
        }
    return payload


def material_payload(material: Material, clips: tuple[Clip, ...]) -> dict[str, JSONValue]:
    return {
        "material_id": material.id,
        "name": material.name,
        "source_audio_id": material.source_audio_id,
        "source_group": material.source_group,
        "clips": [
            {
                "id": item.id,
                "material_id": item.material_id,
                "start_frame": item.start_frame,
                "frames": item.frames,
                "role": item.role,
                "selector_id": item.selector_id,
                "selector_version": item.selector_version,
                "seed": item.seed,
            }
            for item in clips
        ],
    }


def recipe_payload(recipe: RecipeRef) -> dict[str, JSONValue]:
    return {"id": recipe.id, "version": recipe.version, "config": recipe.config}


def prepared_payload(pair: PreparedPair) -> dict[str, JSONValue]:
    output_audio: dict[str, JSONValue] = {
        str(key): value for key, value in pair.output_audio_by_input_key.items()
    }
    return {
        "prepared_pair_id": pair.id,
        "input_audio_ids": list(pair.input_audio_ids),
        "recipe": recipe_payload(pair.recipe),
        "output_audio_by_input_key": output_audio,
        "features": pair.features,
        "warnings": list(pair.warnings),
        "no_effect": pair.no_effect,
    }


def comparison_payload(comparison: ComparisonPlan) -> dict[str, JSONValue]:
    return {
        "comparison_id": comparison.id,
        "pair": [
            {
                "input_key": item.input_key,
                "audio_id": item.audio_id,
                "provenance_ref": item.provenance_ref,
            }
            for item in comparison.pair
        ],
        "recipe": recipe_payload(comparison.recipe),
        "prepared_pair_id": comparison.prepared_pair_id,
    }


def criterion_payload(criterion: CriterionSnapshot | None) -> dict[str, JSONValue] | None:
    if criterion is None:
        return None
    return {
        "text": criterion.text,
        "source": criterion.source,
        "source_event_seq": criterion.source_event_seq,
    }


def session_payload(
    session: Session,
    *,
    criterion_override: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    return {
        "session_id": session.id,
        "items": [
            {
                "id": item.id,
                "comparison_id": item.comparison_id,
                "sequence_index": item.sequence_index,
            }
            for item in session.items
        ],
        "presentation": session.presentation,
        "reveal_policy": session.reveal_policy,
        "criterion": criterion_override
        if criterion_override is not None
        else criterion_payload(session.criterion),
    }


def delivery_payload(delivery: Delivery) -> dict[str, JSONValue]:
    assignment: dict[str, JSONValue] = {
        str(slot): value for slot, value in delivery.slot_assignment.items()
    }
    return {
        "delivery_id": delivery.id,
        "session_id": delivery.session_id,
        "session_item_id": delivery.session_item_id,
        "comparison_id": delivery.comparison_id,
        "slot_assignment": assignment,
        "presentation": delivery.presentation,
        "sequence_index": delivery.sequence_index,
    }


def judgment_payload(judgment: Judgment) -> dict[str, JSONValue]:
    listen_ms: dict[str, JSONValue] = {
        str(slot): value for slot, value in judgment.telemetry.listen_ms.items()
    }
    return {
        "judgment_id": judgment.id,
        "delivery_id": judgment.delivery_id,
        "preference": judgment.preference,
        "blockers": {
            slot: {"selected": value.selected, "note": value.note}
            for slot, value in judgment.blockers.items()
        },
        "comment": judgment.comment,
        "identity_visible_at_answer": judgment.identity_visible_at_answer,
        "telemetry": {
            "listen_ms": listen_ms,
            "switches": judgment.telemetry.switches,
            "answer_ms": judgment.telemetry.answer_ms,
        },
    }
