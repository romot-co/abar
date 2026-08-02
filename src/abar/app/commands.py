"""Stable application command facade grouped by use-case modules."""

from abar.app.catalog_commands import (
    add_clip,
    add_material,
    add_materials,
    add_variant,
    add_variant_archive,
    import_audio,
    init_project,
)
from abar.app.command_support import CommandError, operation_key
from abar.app.materialization_commands import materialize_variant
from abar.app.observation_commands import (
    record_indicator_value,
    record_session_memo,
    register_indicator,
    update_indicator,
    write_note,
)
from abar.app.project_commands import (
    change_brief,
    configure_project,
    create_simplification,
    decide_simplification,
    export_project,
    set_current_best_manual,
)
from abar.app.project_session_commands import (
    SessionPreparationProgress,
    close_project_session,
    create_best_update_session,
    create_observation_session,
)
from abar.app.session_commands import (
    abandon_session,
    create_quick_listen,
    pause_session,
    record_judgment,
    reveal_session,
    skip_delivery,
    start_session,
)

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
    "record_session_memo",
    "register_indicator",
    "reveal_session",
    "set_current_best_manual",
    "skip_delivery",
    "start_session",
    "update_indicator",
    "write_note",
]
