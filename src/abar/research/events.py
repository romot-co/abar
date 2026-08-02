"""Research Workflow event catalog."""

from abar.foundation.replay import EventAuthority, EventSchema

AUTHORITATIVE = ("project_session.created",)
OBSERVATIONAL = (
    "indicator.registered",
    "indicator.updated",
    "indicator.value.recorded",
    "note.updated",
    "session.memo.recorded",
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
