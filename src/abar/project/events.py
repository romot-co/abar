"""Project Authority event catalog."""

from abar.foundation.replay import EventAuthority, EventSchema

AUTHORITATIVE = (
    "project.created",
    "project.config.changed",
    "project.material.attached",
    "project.brief.changed",
    "best_update.planned",
    "simplification.planned",
    "simplification.decided",
    "current_best.changed",
    "in_use.recorded",
)

EVENT_SCHEMAS = {
    event_type: EventSchema(EventAuthority.AUTHORITATIVE, frozenset({1}))
    for event_type in AUTHORITATIVE
}
