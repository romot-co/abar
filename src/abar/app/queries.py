"""Stable query facade for bounded read-model modules."""

from abar.app.agent_queries import entity, history, project_view
from abar.app.dashboard_queries import project_dashboard, status
from abar.app.session_queries import active_deck, session_completion, session_result

__all__ = [
    "active_deck",
    "entity",
    "history",
    "project_dashboard",
    "project_view",
    "session_completion",
    "session_result",
    "status",
]
