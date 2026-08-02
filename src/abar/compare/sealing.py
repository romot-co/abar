"""The single blind secret-to-public conversion boundary."""

from dataclasses import dataclass

from abar.compare.models import ComparisonPlan, Delivery, Session


@dataclass(frozen=True, slots=True)
class PublicDelivery:
    delivery_id: str
    session_id: str
    sequence_index: int
    total: int
    presentation: str
    criterion: str | None
    revealed: bool
    identity_by_slot: dict[str, dict[str, object]] | None


def public_delivery(
    session: Session,
    delivery: Delivery,
    comparison: ComparisonPlan,
    *,
    session_revealed: bool,
    delivery_answered: bool,
) -> PublicDelivery:
    may_reveal = session.presentation == "open" or session_revealed
    if session.reveal_policy == "after_answer_or_manual" and delivery_answered:
        may_reveal = True
    identity: dict[str, dict[str, object]] | None = None
    if may_reveal:
        by_key = {operand.input_key: operand for operand in comparison.pair}
        identity = {
            slot: {
                "audio_id": by_key[input_key].audio_id,
                "provenance": by_key[input_key].provenance_ref,
            }
            for slot, input_key in delivery.slot_assignment.items()
        }
    return PublicDelivery(
        delivery_id=delivery.id,
        session_id=session.id,
        sequence_index=delivery.sequence_index,
        total=len(session.items),
        presentation=session.presentation,
        criterion=None if session.criterion is None else session.criterion.text,
        revealed=may_reveal,
        identity_by_slot=identity,
    )
