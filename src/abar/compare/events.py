"""Compare Core event catalog."""

from abar.foundation.replay import EventAuthority, EventSchema

AUTHORITATIVE = (
    "audio.imported",
    "audio.slice.created",
    "material.added",
    "variant.created",
    "render.completed",
    "prepared_pair.created",
    "comparison.planned",
    "session.planned",
    "session.started",
    "session.blocked",
    "session.paused",
    "session.ended",
    "session.revealed",
    "comparison.delivered",
    "judgment.recorded",
    "comparison.skipped",
)
OBSERVATIONAL = (
    "variant.provenance.observed",
    "variant.materialized",
    "render.nondeterministic_detected",
)

EVENT_SCHEMAS = {
    **{
        event_type: EventSchema(EventAuthority.AUTHORITATIVE, frozenset({1}))
        for event_type in AUTHORITATIVE
    },
    **{
        event_type: EventSchema(EventAuthority.OBSERVATIONAL, frozenset({1}))
        for event_type in OBSERVATIONAL
    },
}
