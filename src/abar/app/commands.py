"""Stable application command facade grouped by use-case modules.

Every command validates against a projection and then appends events. The event
store refuses a write when another writer appended after that projection was read
(two browser tabs, the UI and an agent CLI, or a double submit), so the facade
re-runs the command against fresh state under the same idempotency key. A retry
therefore either re-validates and succeeds, is rejected by the ordinary checks,
or returns the result the concurrent request with the same key already recorded.
"""

from collections.abc import Callable
from functools import wraps
from typing import cast

from abar.app import (
    catalog_commands,
    materialization_commands,
    observation_commands,
    project_commands,
    project_session_commands,
    session_commands,
)
from abar.app.command_support import CommandError, operation_key
from abar.app.project_session_commands import SessionPreparationProgress
from abar.infrastructure.sqlite_event_store import ConcurrentWriteError

_MAX_ATTEMPTS = 5


def _serialized[**P, R](command: Callable[P, R]) -> Callable[P, R]:
    @wraps(command)
    def run(*args: P.args, **kwargs: P.kwargs) -> R:
        options = cast(dict[str, object], kwargs)
        # Fix the key before the first attempt so a retry is the same operation.
        options["idempotency_key"] = operation_key(cast(str | None, options.get("idempotency_key")))
        for _attempt in range(_MAX_ATTEMPTS - 1):
            try:
                return command(*args, **kwargs)
            except ConcurrentWriteError:
                continue
        try:
            return command(*args, **kwargs)
        except ConcurrentWriteError:
            raise CommandError(
                "concurrent_modification",
                "Workspace kept changing while the command ran; retry the request",
            ) from None

    return run


add_clip = _serialized(catalog_commands.add_clip)
add_material = _serialized(catalog_commands.add_material)
add_materials = _serialized(catalog_commands.add_materials)
add_variant = _serialized(catalog_commands.add_variant)
add_variant_archive = _serialized(catalog_commands.add_variant_archive)
import_audio = _serialized(catalog_commands.import_audio)
init_project = _serialized(catalog_commands.init_project)
materialize_variant = _serialized(materialization_commands.materialize_variant)
record_indicator_value = _serialized(observation_commands.record_indicator_value)
register_indicator = _serialized(observation_commands.register_indicator)
update_indicator = _serialized(observation_commands.update_indicator)
write_note = _serialized(observation_commands.write_note)
change_brief = _serialized(project_commands.change_brief)
configure_project = _serialized(project_commands.configure_project)
create_simplification = _serialized(project_commands.create_simplification)
decide_simplification = _serialized(project_commands.decide_simplification)
export_project = _serialized(project_commands.export_project)
set_current_best_manual = _serialized(project_commands.set_current_best_manual)
close_project_session = _serialized(project_session_commands.close_project_session)
create_best_update_session = _serialized(project_session_commands.create_best_update_session)
create_observation_session = _serialized(project_session_commands.create_observation_session)
abandon_session = _serialized(session_commands.abandon_session)
create_quick_listen = _serialized(session_commands.create_quick_listen)
pause_session = _serialized(session_commands.pause_session)
record_judgment = _serialized(session_commands.record_judgment)
reveal_session = _serialized(session_commands.reveal_session)
skip_delivery = _serialized(session_commands.skip_delivery)
start_session = _serialized(session_commands.start_session)

__all__ = [
    "CommandError",
    "SessionPreparationProgress",
    "abandon_session",
    "add_clip",
    "add_material",
    "add_materials",
    "add_variant",
    "add_variant_archive",
    "change_brief",
    "close_project_session",
    "configure_project",
    "create_best_update_session",
    "create_observation_session",
    "create_quick_listen",
    "create_simplification",
    "decide_simplification",
    "export_project",
    "import_audio",
    "init_project",
    "materialize_variant",
    "operation_key",
    "pause_session",
    "record_indicator_value",
    "record_judgment",
    "register_indicator",
    "reveal_session",
    "set_current_best_manual",
    "skip_delivery",
    "start_session",
    "update_indicator",
    "write_note",
]
