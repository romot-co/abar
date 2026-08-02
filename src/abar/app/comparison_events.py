"""The single persistence path for resolved and prepared comparisons."""

from collections.abc import Sequence

from abar.app.event_payloads import audio_payload, comparison_payload, prepared_payload
from abar.app.events import child_key, draft
from abar.compare.models import ComparisonPlan, PreparedPair
from abar.compare.service import PreparedComparison
from abar.infrastructure.sqlite_event_store import EventTransaction


def append_prepared_comparisons(
    tx: EventTransaction,
    operation_key: str,
    comparisons: Sequence[PreparedComparison],
    *,
    start_index: int = 0,
    same_comparison: ComparisonPlan | None = None,
) -> int:
    index = start_index
    seen_audio: set[str] = set()
    seen_pairs: set[str] = set()
    seen_comparisons: set[str] = set()
    for built in comparisons:
        pair = built.prepared_pair
        comparison = built.comparison
        for resolution in (built.left, built.right):
            for effect in resolution.effects:
                if effect.audio.id in seen_audio:
                    continue
                seen_audio.add(effect.audio.id)
                event_type = (
                    "render.completed"
                    if effect.kind == "render"
                    else "audio.slice.created"
                    if effect.kind == "slice"
                    else "audio.imported"
                )
                payload = audio_payload(
                    effect.audio,
                    provenance=effect.kind,
                    input_source=effect.input_source,
                )
                if effect.kind == "slice":
                    payload.update(
                        {
                            "source_audio_id": effect.source_audio_id,
                            "start_frame": effect.start_frame,
                        }
                    )
                if effect.render is not None:
                    payload.update(
                        {
                            "variant_id": str(resolution.operand.provenance_ref.get("variant_ref")),
                            "material_id": effect.render.material_id,
                            "runtime_fingerprint": effect.render.runtime_fingerprint,
                            "raw_render_id": effect.render.raw_render_id,
                            "invocation_identity": effect.render.invocation_identity,
                        }
                    )
                tx.append(
                    draft(
                        event_type,
                        payload,
                        idempotency_key=child_key(operation_key, index),
                    )
                )
                index += 1
                if effect.render is not None and effect.render.nondeterministic_hashes is not None:
                    tx.append(
                        draft(
                            "render.nondeterministic_detected",
                            {
                                "variant_id": str(
                                    resolution.operand.provenance_ref.get("variant_ref")
                                ),
                                "material_id": effect.render.material_id,
                                "output_hashes": list(effect.render.nondeterministic_hashes),
                            },
                            idempotency_key=child_key(operation_key, index),
                        )
                    )
                    index += 1
        for audio in built.output_audio:
            if audio.id in seen_audio:
                continue
            seen_audio.add(audio.id)
            tx.append(
                draft(
                    "audio.imported",
                    audio_payload(audio, provenance="prepared_audio"),
                    idempotency_key=child_key(operation_key, index),
                )
            )
            index += 1
        if pair.id not in seen_pairs:
            seen_pairs.add(pair.id)
            tx.append(
                draft(
                    "prepared_pair.created",
                    prepared_payload(pair),
                    idempotency_key=child_key(operation_key, index),
                )
            )
            index += 1
        if comparison.id not in seen_comparisons:
            seen_comparisons.add(comparison.id)
            tx.append(
                draft(
                    "comparison.planned",
                    comparison_payload(comparison),
                    idempotency_key=child_key(operation_key, index),
                )
            )
            index += 1
    if same_comparison is not None:
        same_pair_id = same_comparison.prepared_pair_id
        if same_pair_id not in seen_pairs:
            source = comparisons[0].prepared_pair.output_audio_by_input_key["p1"]
            same_pair = PreparedPair(
                same_pair_id,
                (source, source),
                same_comparison.recipe,
                {"p1": source, "p2": source},
                {},
                (),
                True,
            )
            tx.append(
                draft(
                    "prepared_pair.created",
                    prepared_payload(same_pair),
                    idempotency_key=child_key(operation_key, index),
                )
            )
            index += 1
        if same_comparison.id not in seen_comparisons:
            tx.append(
                draft(
                    "comparison.planned",
                    comparison_payload(same_comparison),
                    idempotency_key=child_key(operation_key, index),
                )
            )
            index += 1
    return index
