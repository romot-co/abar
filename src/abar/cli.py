"""ABAR v2 command-line adapter."""

import json
import secrets
import tempfile
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from pydantic import BaseModel, ConfigDict, TypeAdapter

from abar.app import commands
from abar.app.actors import Actor
from abar.app.queries import entity, history, project_view, session_result, status
from abar.app.repository import WorkspaceError, WorkspaceRepository, default_workspace_path
from abar.compare.bundles import build_command_bundle
from abar.compare.models import RecipeRef
from abar.foundation.json_types import JSONValue

app = typer.Typer(no_args_is_help=True, add_completion=False)
project_app = typer.Typer(no_args_is_help=True)
project_brief_app = typer.Typer(no_args_is_help=True)
project_recipe_app = typer.Typer(no_args_is_help=True)
project_config_app = typer.Typer(no_args_is_help=True)
project_best_app = typer.Typer(no_args_is_help=True)
project_session_app = typer.Typer(no_args_is_help=True)
project_simplification_app = typer.Typer(no_args_is_help=True)
material_app = typer.Typer(no_args_is_help=True)
material_clip_app = typer.Typer(no_args_is_help=True)
variant_app = typer.Typer(no_args_is_help=True)
note_app = typer.Typer(no_args_is_help=True)
indicator_app = typer.Typer(no_args_is_help=True)
indicator_value_app = typer.Typer(no_args_is_help=True)

app.add_typer(project_app, name="project")
project_app.add_typer(project_brief_app, name="brief")
project_app.add_typer(project_recipe_app, name="recipe")
project_app.add_typer(project_config_app, name="config")
project_app.add_typer(project_best_app, name="best")
project_app.add_typer(project_session_app, name="session")
project_app.add_typer(project_simplification_app, name="simplification")
app.add_typer(material_app, name="material")
material_app.add_typer(material_clip_app, name="clip")
app.add_typer(variant_app, name="variant")
app.add_typer(note_app, name="note")
app.add_typer(indicator_app, name="indicator")
indicator_app.add_typer(indicator_value_app, name="value")

_DEFAULT_WORKSPACE = default_workspace_path()
_JSON_OBJECT = TypeAdapter(dict[str, JSONValue])
_AUDIO_FILE_HELP = "Input audio file (WAV, MP3, FLAC, AIFF, OGG, or CAF)"
_AUDIO_OPERAND_HELP = f"{_AUDIO_FILE_HELP} or an audio/source/variant operand"


class IndicatorBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    indicator_id: str
    subject_id: str
    variant_id: str
    value: float
    guard_result: Literal["pass", "fail"] | None = None


_INDICATOR_BATCH = TypeAdapter(list[IndicatorBatchItem])


@dataclass(frozen=True, slots=True)
class Context:
    workspace: Path
    json_output: bool
    actor: str | None
    idempotency_key: str | None


@app.callback()
def main(
    context: typer.Context,
    workspace: Annotated[Path, typer.Option("--workspace", file_okay=False)] = _DEFAULT_WORKSPACE,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    actor: Annotated[str | None, typer.Option("--actor")] = None,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    context.obj = Context(workspace.expanduser(), json_output, actor, idempotency_key)


@project_app.command("init")
def project_init(
    context: typer.Context,
    name: Annotated[str, typer.Option("--name")],
    brief: Annotated[str, typer.Option("--brief")],
    material: Annotated[
        list[Path] | None, typer.Option("--material", help=_AUDIO_FILE_HELP)
    ] = None,
    existing_material: Annotated[
        list[str] | None,
        typer.Option(
            "--existing-material",
            help="Existing Material ID to attach; repeat for multiple IDs",
        ),
    ] = None,
    current_best: Annotated[str, typer.Option("--current-best")] = "source",
) -> None:
    cli = _ctx(context)
    _run(
        cli,
        lambda repository: commands.init_project(
            repository,
            name=name,
            brief=brief,
            material_paths=tuple(material or ()),
            material_ids=tuple(existing_material or ()),
            current_best=current_best,
            idempotency_key=cli.idempotency_key,
        ),
        "Projectを作成しました",
    )


@project_app.command("show")
def project_show(
    context: typer.Context, since: Annotated[int, typer.Option("--since")] = 0
) -> None:
    cli = _ctx(context)
    _read(
        cli,
        lambda repository: project_view(repository, since=since),
        "Projectを表示しました",
    )


@project_brief_app.command("set")
def brief_set(
    context: typer.Context,
    text: Annotated[str, typer.Option("--text")],
    quote: Annotated[str | None, typer.Option("--quote")] = None,
) -> None:
    cli = _ctx(context)
    if cli.json_output:
        if cli.actor is None or quote is None:
            raise typer.BadParameter("--json brief set requires --actor and --quote")
        human_quote = quote
        actor = cli.actor
    else:
        typer.confirm(f"目的を「{text}」へ変更しますか?", abort=True)
        human_quote = text
        actor = "human"
    _run(
        cli,
        lambda repository: commands.change_brief(
            repository,
            text=text,
            human_quote=human_quote,
            actor_id=actor,
            idempotency_key=cli.idempotency_key,
        ),
        "目的を更新しました",
    )


@project_recipe_app.command("set")
def recipe_set(
    context: typer.Context,
    recipe: Annotated[Literal["native", "aligned", "matched"], typer.Option("--recipe")],
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.configure_project(
            repository,
            recipe=RecipeRef(recipe),
            idempotency_key=cli.idempotency_key,
        ),
        "primary Recipeを更新しました",
    )


@project_config_app.command("set")
def config_set(
    context: typer.Context,
    ready_session_limit: Annotated[int, typer.Option("--ready-session-limit", min=1)],
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.configure_project(
            repository,
            ready_session_limit=ready_session_limit,
            idempotency_key=cli.idempotency_key,
        ),
        "ready Session上限を更新しました",
    )


@project_best_app.command("set")
def best_set(
    context: typer.Context,
    variant: Annotated[str, typer.Argument()],
    ack: Annotated[str, typer.Option("--ack")],
) -> None:
    cli = _ctx(context)
    _human_only(cli)
    _run(
        cli,
        lambda repository: commands.set_current_best_manual(
            repository,
            variant,
            ack=ack,
            actor=Actor("human", "human"),
            idempotency_key=cli.idempotency_key,
        ),
        "現在最良を手動設定しました",
    )


@project_app.command("export")
def project_export(
    context: typer.Context,
    variant: Annotated[str, typer.Argument()],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
    render_clips: Annotated[Path | None, typer.Option("--render-clips", file_okay=False)] = None,
) -> None:
    cli = _ctx(context)
    _human_only(cli)
    _run(
        cli,
        lambda repository: commands.export_project(
            repository,
            variant,
            output=output,
            actor=Actor("human", "human"),
            render_clips=render_clips,
            idempotency_key=cli.idempotency_key,
        ),
        "Projectを書き出しました",
    )


@material_app.command("add")
def material_add(
    context: typer.Context,
    files: Annotated[
        list[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            help=f"{_AUDIO_FILE_HELP}; accepts multiple files",
        ),
    ],
    source_group: Annotated[str | None, typer.Option("--source-group")] = None,
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: _add_material_set(
            repository,
            tuple(files),
            source_group=source_group,
            idempotency_key=cli.idempotency_key,
        ),
        "素材を追加しました",
    )


def _add_material_set(
    repository: WorkspaceRepository,
    files: tuple[Path, ...],
    *,
    source_group: str | None,
    idempotency_key: str | None,
) -> tuple[dict[str, object], ...]:
    material_ids = commands.add_materials(
        repository,
        files,
        source_group=source_group,
        idempotency_key=idempotency_key,
    )
    state = repository.state()
    return tuple(
        {
            "material_id": material_id,
            "clip_ids": list(state.compare.materials[material_id].clip_ids),
        }
        for material_id in material_ids
    )


@material_clip_app.command("add")
def material_clip_add(
    context: typer.Context,
    material: Annotated[str, typer.Argument()],
    start: Annotated[float, typer.Option("--start", min=0.0)],
    duration: Annotated[float, typer.Option("--duration", min=0.001)],
    role: Annotated[str | None, typer.Option("--role")] = None,
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.add_clip(
            repository,
            material,
            start_seconds=start,
            duration_seconds=duration,
            role=role,
            idempotency_key=cli.idempotency_key,
        ),
        "Clipを追加しました",
    )


@variant_app.command("add")
def variant_add(
    context: typer.Context,
    manifest: Annotated[
        Path | None,
        typer.Option(
            "--manifest",
            exists=True,
            dir_okay=False,
            help="Advanced Variant manifest; use --bundle for the standard command contract",
        ),
    ] = None,
    archive: Annotated[Path | None, typer.Option("--archive", exists=True, dir_okay=False)] = None,
    bundle: Annotated[
        Path | None,
        typer.Option(
            "--bundle",
            exists=True,
            file_okay=False,
            help="Renderer directory to package deterministically",
        ),
    ] = None,
    entry: Annotated[
        str | None,
        typer.Option(
            "--entry",
            help="Bundle-relative executable using INPUT_WAV PARAMS_JSON OUTPUT_WAV arguments",
        ),
    ] = None,
    timeout: Annotated[int, typer.Option("--timeout", min=1, max=120)] = 120,
    seeded: Annotated[bool, typer.Option("--seeded")] = False,
    params: Annotated[Path | None, typer.Option("--params", exists=True, dir_okay=False)] = None,
    label: Annotated[str | None, typer.Option("--label")] = None,
    provenance: Annotated[
        Path | None, typer.Option("--provenance", exists=True, dir_okay=False)
    ] = None,
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    if bundle is not None:
        if manifest is not None or archive is not None:
            raise typer.BadParameter("--bundle cannot be combined with --manifest or --archive")
        if entry is None:
            raise typer.BadParameter("--bundle requires --entry")
        built = build_command_bundle(
            bundle,
            entry,
            timeout_seconds=timeout,
            seed_mode="required" if seeded else "none",
        )
        manifest_document = built.manifest
        archive_bytes = built.archive
    else:
        if manifest is None:
            raise typer.BadParameter("provide --bundle with --entry, or provide --manifest")
        if entry is not None or seeded or timeout != 120:
            raise typer.BadParameter("--entry, --seeded, and --timeout belong to --bundle")
        manifest_document = _json_file(manifest)
        archive_bytes = None if archive is None else archive.read_bytes()
    params_document = {} if params is None else _json_file(params)
    provenance_document = None if provenance is None else _json_file(provenance)

    def register(repository: WorkspaceRepository) -> str:
        if archive_bytes is None:
            return commands.add_variant(
                repository,
                manifest_document,
                params=params_document,
                label=label,
                provenance=provenance_document,
                idempotency_key=cli.idempotency_key,
            )
        return commands.add_variant_archive(
            repository,
            manifest_document,
            archive_bytes,
            params=params_document,
            label=label,
            provenance=provenance_document,
            idempotency_key=cli.idempotency_key,
        )

    _run(
        cli,
        register,
        "Variantを登録しました",
    )


@variant_app.command("materialize")
def variant_materialize(
    context: typer.Context,
    variant: Annotated[str, typer.Argument()],
    clip: Annotated[
        list[str],
        typer.Option(
            "--clip",
            help="Attached Project Clip ID; repeat for multiple exact WAV outputs",
        ),
    ],
    output: Annotated[Path, typer.Option("--output", file_okay=False)],
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run_view(
        cli,
        lambda repository: commands.materialize_variant(
            repository,
            variant,
            clip_ids=tuple(clip),
            output=output,
            idempotency_key=cli.idempotency_key,
        ),
        "Variant音声をmaterializeしました",
    )


@project_session_app.command("create")
def session_create(
    context: typer.Context,
    first: Annotated[str, typer.Option("--a")],
    second: Annotated[str, typer.Option("--b")],
    focus: Annotated[str, typer.Option("--focus")],
    size: Annotated[Literal["short", "standard"], typer.Option("--size")] = "short",
    evidence_count: Annotated[
        int | None,
        typer.Option(
            "--evidence-count",
            help="Evidence comparisons for a standard Session (default 3, minimum 3)",
        ),
    ] = None,
    recipe: Annotated[
        Literal["native", "aligned", "matched"] | None, typer.Option("--recipe")
    ] = None,
    topic: Annotated[str | None, typer.Option("--topic")] = None,
    clip: Annotated[
        list[str] | None,
        typer.Option(
            "--clip",
            help="Evidence Clip ID; repeat once per comparison. Explicit order is preserved.",
        ),
    ] = None,
    same_check: Annotated[bool, typer.Option("--same-check")] = False,
    repeat_check: Annotated[bool, typer.Option("--repeat-check")] = False,
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.create_observation_session(
            repository,
            first_variant=first,
            second_variant=second,
            focus=focus,
            size=size,
            evidence_count=evidence_count,
            recipe=None if recipe is None else RecipeRef(recipe),
            topic_key=topic,
            clip_ids=tuple(clip or ()),
            same_check=same_check,
            repeat_check=repeat_check,
            actor_id=cli.actor or "human",
            actor_type="agent" if cli.actor else "human",
            idempotency_key=cli.idempotency_key,
            progress=_session_progress(cli),
        ),
        "Sessionを準備しました",
    )


@project_session_app.command("best-update")
def session_best_update(
    context: typer.Context,
    proposed: Annotated[str, typer.Option("--proposed")],
    topic: Annotated[str | None, typer.Option("--topic")] = None,
    clip: Annotated[list[str] | None, typer.Option("--clip")] = None,
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.create_best_update_session(
            repository,
            proposed_variant=proposed,
            topic_key=topic,
            clip_ids=tuple(clip or ()),
            actor_id=cli.actor or "human",
            actor_type="agent" if cli.actor else "human",
            idempotency_key=cli.idempotency_key,
            progress=_session_progress(cli),
        ),
        "Current Best確認Sessionを準備しました",
    )


@project_session_app.command("close")
def session_close(
    context: typer.Context, project_session_id: Annotated[str, typer.Argument()]
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.close_project_session(
            repository,
            project_session_id,
            actor_id=cli.actor or "",
            idempotency_key=cli.idempotency_key,
        ),
        "Sessionを閉じました",
    )


@project_session_app.command("result")
def session_result_command(
    context: typer.Context,
    project_session_id: Annotated[str, typer.Argument()],
) -> None:
    cli = _ctx(context)
    _read(
        cli,
        lambda repository: session_result(repository, project_session_id),
        "Session結果を表示しました",
    )


@project_simplification_app.command("create")
def simplification_create(
    context: typer.Context,
    simple: Annotated[str, typer.Option("--simple")],
    reason: Annotated[str, typer.Option("--reason")],
    clip: Annotated[list[str], typer.Option("--clip")],
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.create_simplification(
            repository,
            simple_variant_id=simple,
            reason=reason,
            scope_clip_ids=tuple(clip),
            idempotency_key=cli.idempotency_key,
        ),
        "Simplification確認を準備しました",
    )


@note_app.command("write")
def note_write(
    context: typer.Context,
    file: Annotated[Path, typer.Option("--file", exists=True, dir_okay=False)],
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.write_note(
            repository,
            file.read_text(encoding="utf-8"),
            actor_id=cli.actor or "",
            idempotency_key=cli.idempotency_key,
        ),
        "ノートを更新しました",
    )


@indicator_app.command("add")
def indicator_add(
    context: typer.Context,
    indicator_id: Annotated[str, typer.Option("--id")],
    label: Annotated[str, typer.Option("--label")],
    description: Annotated[str, typer.Option("--description")],
    definition: Annotated[Path, typer.Option("--definition", exists=True, dir_okay=False)],
    subject: Annotated[Literal["audio", "prepared_pair"], typer.Option("--subject")],
    unit: Annotated[str, typer.Option("--unit")],
    role: Annotated[Literal["target", "guard", "none"], typer.Option("--role")] = "none",
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.register_indicator(
            repository,
            indicator_id=indicator_id,
            label=label,
            description=description,
            definition_path=definition,
            subject_kind=subject,
            unit=unit,
            role=role,
            actor_id=cli.actor or "",
            idempotency_key=cli.idempotency_key,
        ),
        "Indicatorを登録しました",
    )


@indicator_app.command("set")
def indicator_set(
    context: typer.Context,
    indicator_id: Annotated[str, typer.Argument()],
    role: Annotated[Literal["target", "guard", "none"] | None, typer.Option("--role")] = None,
    evidence: Annotated[list[str] | None, typer.Option("--evidence")] = None,
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    _run(
        cli,
        lambda repository: commands.update_indicator(
            repository,
            indicator_id,
            role=role,
            evidence_session_ids=None if evidence is None else tuple(evidence),
            idempotency_key=cli.idempotency_key,
        ),
        "Indicatorを更新しました",
    )


@indicator_value_app.command("record")
def indicator_value_record(
    context: typer.Context,
    indicator: Annotated[str | None, typer.Option("--indicator")] = None,
    subject: Annotated[str | None, typer.Option("--subject")] = None,
    variant: Annotated[str | None, typer.Option("--variant")] = None,
    value: Annotated[float | None, typer.Option("--value")] = None,
    guard_result: Annotated[Literal["pass", "fail"] | None, typer.Option("--guard-result")] = None,
    artifact: Annotated[
        Path | None, typer.Option("--artifact", exists=True, dir_okay=False)
    ] = None,
    batch: Annotated[Path | None, typer.Option("--batch", exists=True, dir_okay=False)] = None,
) -> None:
    cli = _ctx(context)
    _agent_required(cli)
    if batch is not None:
        raw = _INDICATOR_BATCH.validate_json(batch.read_text(encoding="utf-8"))

        def record_batch(repository: WorkspaceRepository) -> int:
            for index, item in enumerate(raw):
                commands.record_indicator_value(
                    repository,
                    indicator_id=item.indicator_id,
                    subject_id=item.subject_id,
                    variant_id=item.variant_id,
                    value=item.value,
                    guard_result=item.guard_result,
                    actor=Actor(cli.actor or "human", "agent" if cli.actor else "human"),
                    artifact=None,
                    idempotency_key=f"{cli.idempotency_key}:{index}"
                    if cli.idempotency_key
                    else None,
                )
            return len(raw)

        _run(cli, record_batch, "Indicator値を一括記録しました")
        return
    if indicator is None or subject is None or variant is None or value is None:
        raise typer.BadParameter(
            "single record requires --indicator, --subject, --variant, and --value"
        )
    _run(
        cli,
        lambda repository: commands.record_indicator_value(
            repository,
            indicator_id=indicator,
            subject_id=subject,
            variant_id=variant,
            value=value,
            guard_result=guard_result,
            actor=Actor(cli.actor or "human", "agent" if cli.actor else "human"),
            artifact=None if artifact is None else artifact.read_bytes(),
            idempotency_key=cli.idempotency_key,
        ),
        "Indicator値を記録しました",
    )


@app.command("status")
def status_command(context: typer.Context) -> None:
    cli = _ctx(context)
    _read(cli, status, "状態を表示しました")


@app.command("history")
def history_command(
    context: typer.Context, since: Annotated[int, typer.Option("--since")] = 0
) -> None:
    cli = _ctx(context)
    _read(cli, lambda repository: history(repository, since=since), "履歴を表示しました")


@app.command("show")
def show_command(context: typer.Context, entity_id: Annotated[str, typer.Argument()]) -> None:
    cli = _ctx(context)
    _read(cli, lambda repository: entity(repository, entity_id), "詳細を表示しました")


@app.command("rebuild")
def rebuild_command(context: typer.Context) -> None:
    cli = _ctx(context)
    repository = WorkspaceRepository.open(cli.workspace)
    try:
        result = repository.replay()
        _emit(
            cli,
            {
                "result": "ok" if result.degraded is None else "degraded",
                "event_seq": result.processed_through_event_seq,
            },
            "projectionを再構築しました",
        )
    finally:
        repository.close()


@app.command("listen")
def listen(
    context: typer.Context,
    first: Annotated[str, typer.Argument(help=_AUDIO_OPERAND_HELP)],
    second: Annotated[str, typer.Argument(help=_AUDIO_OPERAND_HELP)],
    recipe: Annotated[
        Literal["native", "aligned", "matched"], typer.Option("--recipe")
    ] = "aligned",
    blind: Annotated[bool, typer.Option("--blind/--open")] = False,
    range_value: Annotated[str | None, typer.Option("--range")] = None,
    no_save: Annotated[bool, typer.Option("--no-save")] = False,
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
) -> None:
    cli = _ctx(context)
    if range_value is not None:
        try:
            start_text, duration_text = range_value.split(":", 1)
            start, duration = float(start_text), float(duration_text)
        except ValueError:
            raise typer.BadParameter("--range must be START:DURATION") from None
        if start < 0 or duration <= 0:
            raise typer.BadParameter("--range must be non-negative with positive duration")
        first = f"file:{first}#{start}+{duration}"
        second = f"file:{second}#{start}+{duration}"
    if no_save:
        with tempfile.TemporaryDirectory(prefix="abar-quick-") as temporary:
            temporary_cli = Context(
                Path(temporary), cli.json_output, cli.actor, cli.idempotency_key
            )
            _create_and_serve_quick(temporary_cli, first, second, recipe, blind, port)
    else:
        _create_and_serve_quick(cli, first, second, recipe, blind, port)


@app.command("ui")
def ui(
    context: typer.Context,
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8765,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
) -> None:
    _serve(_ctx(context), port=port, open_browser=open_browser)


def _create_and_serve_quick(
    cli: Context, first: str, second: str, recipe: str, blind: bool, port: int
) -> None:
    repository = WorkspaceRepository.open(cli.workspace)
    try:
        session_id = commands.create_quick_listen(
            repository,
            first,
            second,
            recipe=RecipeRef(recipe),  # type: ignore[arg-type]
            presentation="blind" if blind else "open",
            idempotency_key=cli.idempotency_key,
        )
        commands.start_session(repository, session_id)
    finally:
        repository.close()
    _serve(cli, port=port, open_browser=True)


def _interaction_secret(workspace: Path) -> str:
    """workspaceごとに固定のUI接続secret。ブラウザCookieが再起動をまたいで有効になる。"""
    path = workspace / ".ui-secret"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    workspace.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    path.touch(mode=0o600)
    path.chmod(0o600)
    path.write_text(value, encoding="utf-8")
    return value


def _serve(cli: Context, *, port: int, open_browser: bool) -> None:
    import uvicorn

    from abar.server import create_app
    from abar.server.workspaces import discover_project_workspaces

    automation_token = secrets.token_urlsafe(32)
    interaction_token = _interaction_secret(cli.workspace)
    origin = f"http://127.0.0.1:{port}"
    application = create_app(
        cli.workspace,
        workspace_roots=discover_project_workspaces(cli.workspace),
        automation_token=automation_token,
        interaction_token=interaction_token,
        allowed_origins=frozenset({origin}),
    )
    interaction_url = f"{origin}/#token={interaction_token}"
    automation_url = f"{origin}/#token={automation_token}"
    if cli.json_output:
        typer.echo(
            json.dumps(
                {"schema_version": 2, "url": automation_url, "token": automation_token},
                separators=(",", ":"),
            )
        )
    else:
        typer.echo(f"ABAR: {interaction_url}")
        typer.echo(f"接続済みのブラウザは {origin} だけで開けます")
    if open_browser:
        webbrowser.open(interaction_url)
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


def _run[ValueT](
    cli: Context,
    operation: Callable[[WorkspaceRepository], ValueT],
    message: str,
) -> None:
    try:
        repository = WorkspaceRepository.open(cli.workspace)
        try:
            value = operation(repository)
        finally:
            repository.close()
        _emit(cli, {"schema_version": 2, "result": value}, message)
    except (commands.CommandError, WorkspaceError, ValueError, OSError) as error:
        _fail(cli, getattr(error, "code", "operation_failed"), str(error))


def _session_progress(
    cli: Context,
) -> Callable[[commands.SessionPreparationProgress], None]:
    def emit(progress: commands.SessionPreparationProgress) -> None:
        if cli.json_output:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": 2,
                        "type": "session_preparation_progress",
                        "stage": progress.stage,
                        "current": progress.current,
                        "total": progress.total,
                        "clip_id": progress.clip_id,
                        "material_id": progress.material_id,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                err=True,
            )
        else:
            label = "準備中" if progress.stage == "started" else "準備完了"
            typer.echo(
                f"{label} {progress.current}/{progress.total}: {progress.material_id}",
                err=True,
            )

    return emit


def _read[ValueT: BaseModel](
    cli: Context,
    operation: Callable[[WorkspaceRepository], ValueT],
    message: str,
) -> None:
    try:
        repository = WorkspaceRepository.open(cli.workspace)
        try:
            value = operation(repository)
        finally:
            repository.close()
        _emit(cli, value, message)
    except (WorkspaceError, ValueError, OSError) as error:
        _fail(cli, getattr(error, "code", "operation_failed"), str(error))


def _run_view[ValueT: BaseModel](
    cli: Context,
    operation: Callable[[WorkspaceRepository], ValueT],
    message: str,
) -> None:
    try:
        repository = WorkspaceRepository.open(cli.workspace)
        try:
            value = operation(repository)
        finally:
            repository.close()
        _emit(cli, value, message)
    except (commands.CommandError, WorkspaceError, ValueError, OSError) as error:
        _fail(cli, getattr(error, "code", "operation_failed"), str(error))


def _emit(cli: Context, value: BaseModel | dict[str, object], message: str) -> None:
    if cli.json_output:
        if isinstance(value, BaseModel):
            typer.echo(value.model_dump_json())
        else:
            typer.echo(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    else:
        typer.echo(message)


def _fail(cli: Context, code: str, message: str) -> None:
    payload = {"schema_version": 2, "error": {"code": code, "message": message}}
    if cli.json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), err=False)
    else:
        typer.echo(message, err=True)
    raise typer.Exit(3)


def _agent_required(cli: Context) -> None:
    if cli.json_output and not cli.actor:
        raise typer.BadParameter("agent JSON writes require --actor")


def _human_only(cli: Context) -> None:
    if cli.json_output or cli.actor is not None:
        raise typer.BadParameter("this operation requires the human interaction path")


def _json_file(path: Path) -> dict[str, JSONValue]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise typer.BadParameter(f"{path} must contain a JSON object")
    return _JSON_OBJECT.validate_python(cast(object, value))


def _ctx(context: typer.Context) -> Context:
    return context.obj  # type: ignore[return-value]
