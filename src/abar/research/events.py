"""Research Workflow event catalog."""

from abar.foundation.replay import EventAuthority, EventSchema

AUTHORITATIVE = ("project_session.created",)
OBSERVATIONAL = (
    "indicator.registered",
    "indicator.updated",
    "indicator.value.recorded",
    "note.updated",
    "symptom.opened",
    "symptom.updated",
    "symptom.resolved",
    "symptom.reopened",
    "symptom.withdrawn",
    "verification.recorded",
    "baseline.recorded",
    "current_best.flagged",
)

EVENT_SCHEMAS = {
    **{
        event_type: EventSchema(EventAuthority.AUTHORITATIVE, frozenset({1, 2}))
        for event_type in AUTHORITATIVE
    },
    **{
        event_type: EventSchema(EventAuthority.OBSERVATIONAL, frozenset({1}))
        for event_type in OBSERVATIONAL
    },
}
