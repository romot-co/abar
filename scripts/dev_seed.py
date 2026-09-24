"""開発用ダミーデータ投入スクリプト。

UIの表示・動作確認用に、状態ごとのWorkspaceを同じ親ディレクトリへ作る。
UIのProject切替(同じ親ディレクトリのWorkspaceを列挙)で各状態を行き来できる。

    standard        進行中・準備済み・完了Session、Indicator、ノート(従来のseed)
    fresh           Project作成直後。現在最良は原音、準備済みSessionだけ
    all-done        全Session完了。受信箱が空の状態
    quick-listen    ProjectとblindのQuick Listen(進行中)
    simplification  簡素化(byte-identical)の確認待ち
    blocked         音声欠落で開始できなかったSession
    degraded        replayが停止したWorkspace(復旧案内の表示)
    no-project      Projectのない空のWorkspace(主Workspaceに指定したときだけ表示)

通常は `scripts/dev.py` から使う。単体で使う場合:
    uv run python scripts/dev_seed.py                      # .dev-workspaces/ に全シナリオ
    uv run python scripts/dev_seed.py --reset              # 作り直し
    uv run python scripts/dev_seed.py --scenario fresh     # 指定シナリオだけ
    uv run python scripts/dev_seed.py --root /tmp/abar-dev
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np

from abar.app import commands
from abar.app.actors import Actor
from abar.app.events import child_key, draft
from abar.app.repository import WorkspaceRepository
from abar.compare.audio.content import decode_wav_bytes, encode_float32_wav
from abar.compare.audio.importing import import_canonical_wav_bytes
from abar.compare.models import AudioObject, BlockerInput, Telemetry
from abar.foundation.json_types import JSONValue
from abar.infrastructure.object_store import ImmutableObjectStore

SAMPLE_RATE = 44_100
SECONDS = 14


def _tone(frequency: float, *, vibrato: float = 0.0, harmonics: float = 0.25) -> np.ndarray:
    time = np.arange(SAMPLE_RATE * SECONDS, dtype=np.float32) / SAMPLE_RATE
    envelope = (0.55 + 0.45 * np.sin(2.0 * np.pi * 0.11 * time)).astype(np.float32)
    base = np.sin(2.0 * np.pi * frequency * time + vibrato * np.sin(2.0 * np.pi * 5.0 * time))
    overtone = harmonics * np.sin(2.0 * np.pi * frequency * 2.0 * time)
    return (0.22 * envelope * (base + overtone)).astype(np.float32).reshape(-1, 1)


def _write_wav(directory: Path, name: str, pcm: np.ndarray) -> Path:
    path = directory / name
    path.write_bytes(encode_float32_wav(pcm, SAMPLE_RATE))
    return path


def _finite_map_variant(
    repository: WorkspaceRepository,
    *,
    label: str,
    color_hz: float,
    depth: float,
) -> str:
    """素材ごとに軽い変調を加えたRawRender済みVariantを登録する(tests/conftest.pyと同型)。"""
    state = repository.state()
    project = state.project.project
    assert project is not None
    mapping: dict[str, JSONValue] = {}
    audios: list[AudioObject] = []
    for material_id in project.material_ids:
        material = state.compare.materials[material_id]
        source = state.compare.audio[material.source_audio_id]
        if depth == 0.0:
            audio = source
        else:
            decoded = decode_wav_bytes(repository.objects.read(source.object_id))
            time = np.arange(decoded.frames, dtype=np.float32) / decoded.sample_rate
            changed = decoded.pcm + depth * np.sin(2.0 * np.pi * color_hz * time).reshape(-1, 1)
            audio = import_canonical_wav_bytes(
                encode_float32_wav(changed.astype(np.float32), decoded.sample_rate),
                objects=repository.objects,
            )
        audios.append(audio)
        mapping[material_id] = {
            "audio_object_id": audio.id,
            "audio_sha": audio.pcm_sha,
            "sample_rate": audio.sample_rate,
            "channel_layout": audio.channel_layout,
            "frames": audio.frames,
        }
    key = commands.operation_key()
    with repository.events.transaction(causation_id=key) as tx:
        for index, audio in enumerate(audios):
            tx.append(
                draft(
                    "audio.imported",
                    {
                        "audio_id": audio.id,
                        "object_id": audio.object_id,
                        "pcm_sha": audio.pcm_sha,
                        "sample_rate": audio.sample_rate,
                        "channel_layout": audio.channel_layout,
                        "frames": audio.frames,
                        "provenance_kind": "dev_seed",
                    },
                    idempotency_key=child_key(key, index),
                )
            )
    archive = repository.objects.put(f"dev-seed:{label}".encode())
    manifest: dict[str, JSONValue] = {
        "schema_version": 1,
        "source_archive": {
            "object_id": archive.object_id,
            "sha": f"sha256:{archive.sha256}",
        },
        "renderer": {
            "kind": "finite_map",
            "context_policy": "full_material",
            "timeline_policy": "source_aligned_exact_v1",
            "command": None,
            "finite_map": mapping,
        },
        "input_contract": {"audio": "canonical_wav", "params": "canonical_json"},
        "output_contract": {
            "container": "wav",
            "sample_rates": "source",
            "channel_layouts": ["mono"],
        },
    }
    return commands.add_variant(repository, manifest, label=label)


def _answer_all(
    repository: WorkspaceRepository,
    core_session_id: str,
    preferences: list[int],
    *,
    blocker_slot: str | None = None,
) -> None:
    state = repository.state()
    deliveries = sorted(
        (item for item in state.compare.deliveries.values() if item.session_id == core_session_id),
        key=lambda item: item.sequence_index,
    )
    for index, delivery in enumerate(deliveries):
        preference = preferences[index % len(preferences)]
        commands.record_judgment(
            repository,
            delivery.id,
            preference=preference,  # type: ignore[arg-type]
            blocker_a=None
            if blocker_slot != "a"
            else BlockerInput(selected=True, note="アタックが鈍い"),
            blocker_b=None
            if blocker_slot != "b"
            else BlockerInput(selected=True, note="アタックが鈍い"),
            comment="dev seed answer" if index == 0 else None,
            telemetry=Telemetry({"a": 9_000, "b": 8_400}, 3, 21_000),
        )


def _answer_for_variant(
    repository: WorkspaceRepository,
    core_session_id: str,
    favored_variant_id: str,
) -> None:
    state = repository.state()
    deliveries = sorted(
        (item for item in state.compare.deliveries.values() if item.session_id == core_session_id),
        key=lambda item: item.sequence_index,
    )
    for delivery in deliveries:
        comparison = state.compare.comparisons[delivery.comparison_id]
        variant_by_key = {
            item.input_key: str(item.provenance_ref.get("variant_ref", "source"))
            for item in comparison.pair
        }
        favored_slot = next(
            slot
            for slot, input_key in delivery.slot_assignment.items()
            if variant_by_key[input_key] == favored_variant_id
        )
        commands.record_judgment(
            repository,
            delivery.id,
            preference=1 if favored_slot == "A" else 5,
            telemetry=Telemetry({"a": 9_000, "b": 8_400}, 3, 21_000),
        )


def _answer_observation_with_checks(
    repository: WorkspaceRepository,
    project_session_id: str,
    favored_variant_id: str,
) -> None:
    state = repository.state()
    project_session = state.research.project_sessions[project_session_id]
    deliveries = sorted(
        (
            item
            for item in state.compare.deliveries.values()
            if item.session_id == project_session.core_session_id
        ),
        key=lambda item: item.sequence_index,
    )
    for delivery in deliveries:
        if delivery.session_item_id == project_session.same_check_item_id:
            preference = 1
        elif delivery.session_item_id == project_session.repeat_check_item_id:
            preference = 3
        elif delivery.session_item_id == project_session.repeat_of_item_id:
            comparison = state.compare.comparisons[delivery.comparison_id]
            variant_by_key = {
                item.input_key: str(item.provenance_ref.get("variant_ref", "source"))
                for item in comparison.pair
            }
            favored_slot = next(
                slot
                for slot, input_key in delivery.slot_assignment.items()
                if variant_by_key[input_key] == favored_variant_id
            )
            preference = 1 if favored_slot == "A" else 5
        else:
            preference = 3
        commands.record_judgment(
            repository,
            delivery.id,
            preference=preference,
            telemetry=Telemetry({"a": 9_000, "b": 8_400}, 3, 21_000),
        )


def seed(
    workspace: Path,
    *,
    project_name: str = "Xifa",
    brief: str = "Increase density without losing attack or air",
) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        tmpdir = Path(tmp)
        materials = [
            _write_wav(tmpdir, "pad_intro.wav", _tone(220.0, harmonics=0.35)),
            _write_wav(tmpdir, "pad_sustain.wav", _tone(330.0, vibrato=0.4)),
            _write_wav(tmpdir, "pad_release.wav", _tone(147.0, harmonics=0.15)),
        ]
        repository = WorkspaceRepository.open(workspace)
        try:
            commands.init_project(
                repository,
                name=project_name,
                brief=brief,
                material_paths=tuple(materials),
                current_best="source",
            )
            state = repository.state()
            project = state.project.project
            assert project is not None
            for material_id in project.material_ids:
                commands.add_clip(
                    repository,
                    material_id,
                    start_seconds=0.5,
                    duration_seconds=6.0,
                    role="body",
                )
            variant_warm = _finite_map_variant(
                repository, label="warm-eq-v1", color_hz=660.0, depth=0.012
            )
            variant_dense = _finite_map_variant(
                repository, label="dense-chorus-v2", color_hz=880.0, depth=0.03
            )

            # 完了した現在最良チェック: warmをCurrent Bestにする。
            best_done_id = commands.create_best_update_session(
                repository,
                proposed_variant=variant_warm,
                actor_id="human",
                actor_type="human",
            )
            state = repository.state()
            best_done_core = state.research.project_sessions[best_done_id].core_session_id
            commands.start_session(repository, best_done_core, allocation_seed=7)
            _answer_for_variant(repository, best_done_core, variant_warm)

            # 完了した観察を2件用意し、v5の履歴テーブルを確認できるようにする。
            for index, focus in enumerate(
                (
                    "リバーブテイルの濁り",
                    "サチュレーション量の当たり",
                )
            ):
                done_id = commands.create_observation_session(
                    repository,
                    first_variant="source",
                    second_variant=variant_dense,
                    focus=focus,
                    size="standard" if index == 0 else "short",
                    same_check=index == 0,
                    repeat_check=index == 0,
                    actor_id="human",
                    actor_type="human",
                )
                state = repository.state()
                done_core = state.research.project_sessions[done_id].core_session_id
                commands.start_session(repository, done_core, allocation_seed=index + 20)
                if index == 0:
                    _answer_observation_with_checks(repository, done_id, variant_dense)
                else:
                    _answer_all(repository, done_core, preferences=[3])

            # 進行中Session: 現在最良チェック(3比較、1問だけ回答済み)
            check_id = commands.create_best_update_session(
                repository,
                proposed_variant=variant_dense,
                actor_id="human",
                actor_type="human",
            )
            state = repository.state()
            check_core = state.research.project_sessions[check_id].core_session_id
            commands.start_session(repository, check_core)
            state = repository.state()
            first_delivery = min(
                (
                    item
                    for item in state.compare.deliveries.values()
                    if item.session_id == check_core
                ),
                key=lambda item: item.sequence_index,
            )
            commands.record_judgment(
                repository,
                first_delivery.id,
                preference=2,
                telemetry=Telemetry({"a": 12_000, "b": 11_000}, 4, 30_000),
            )

            # 準備済みSession
            commands.create_observation_session(
                repository,
                first_variant=variant_warm,
                second_variant=variant_dense,
                focus="warm-eq と dense-chorus の性格差を聴き分ける",
                size="short",
                actor_id="human",
                actor_type="human",
            )

            # Indicator + 現在最良の値。guardには外部producerの判定も付ける。
            definition = tmpdir / "indicator.txt"
            definition.write_text("dev seed indicator definition", encoding="utf-8")
            state = repository.state()
            subject_audio = next(
                operand.audio_id
                for comparison in state.compare.comparisons.values()
                for operand in comparison.pair
                if operand.provenance_ref.get("variant_ref") == variant_warm
            )
            indicators = (
                (
                    "ind_density_v1",
                    "DENSITY",
                    "音像を潰さず、知覚上の密度を高める",
                    "target",
                    0.62,
                    None,
                ),
                (
                    "ind_punch_v1",
                    "PUNCH",
                    "アタックの明瞭さと前方への押し出しを保つ",
                    "target",
                    0.48,
                    None,
                ),
                (
                    "ind_attack_v1",
                    "ATTACK LOSS",
                    "トランジェントの輪郭を失っていないか",
                    "guard",
                    0.9,
                    "pass",
                ),
                (
                    "ind_air_v1",
                    "AIR LOSS",
                    "高域の抜けや空気感を失っていないか",
                    "guard",
                    0.97,
                    "pass",
                ),
            )
            for indicator_id, label, description, role, value, guard_result in indicators:
                commands.register_indicator(
                    repository,
                    indicator_id=indicator_id,
                    label=label,
                    description=description,
                    definition_path=definition,
                    subject_kind="audio",
                    unit="ratio",
                    role=role,  # type: ignore[arg-type]
                    actor_id="agent:dev-seed",
                )
                commands.record_indicator_value(
                    repository,
                    indicator_id=indicator_id,
                    subject_id=subject_audio,
                    variant_id=variant_warm,
                    value=value,
                    guard_result=guard_result,  # type: ignore[arg-type]
                    actor=Actor("agent:dev-seed", "agent"),
                )

            commands.write_note(
                repository,
                "\n".join(
                    [
                        "## 現在の仮説",
                        "- 密度は 2k-4k の持ち上げで感じやすい",
                        "- こもりの苦情は release 素材で出やすい",
                        "",
                        "次: dense-chorus が現在最良を超えるか確認する",
                    ]
                ),
                actor_id="human",
            )
        finally:
            repository.close()


def _materials(directory: Path) -> tuple[Path, ...]:
    return (
        _write_wav(directory, "pad_intro.wav", _tone(220.0, harmonics=0.35)),
        _write_wav(directory, "pad_sustain.wav", _tone(330.0, vibrato=0.4)),
        _write_wav(directory, "pad_release.wav", _tone(147.0, harmonics=0.15)),
    )


def _start_project(
    repository: WorkspaceRepository, directory: Path, *, name: str, brief: str
) -> tuple[str, ...]:
    """Projectを作り、素材ごとにClipを1件足す。素材IDを返す。"""
    commands.init_project(repository, name=name, brief=brief, material_paths=_materials(directory))
    project = repository.state().project.project
    assert project is not None
    for material_id in project.material_ids:
        commands.add_clip(
            repository, material_id, start_seconds=0.5, duration_seconds=6.0, role="body"
        )
    return project.material_ids


def _core_session(repository: WorkspaceRepository, project_session_id: str) -> str:
    return repository.state().research.project_sessions[project_session_id].core_session_id


def _promote(repository: WorkspaceRepository, variant_id: str) -> None:
    """現在最良チェックを作り、提案版を全問支持して現在最良を更新する。"""
    session_id = commands.create_best_update_session(
        repository, proposed_variant=variant_id, actor_id="agent:dev-seed"
    )
    core = _core_session(repository, session_id)
    commands.start_session(repository, core, allocation_seed=7)
    _answer_for_variant(repository, core, variant_id)


def seed_fresh(workspace: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        repository = WorkspaceRepository.open(workspace)
        try:
            _start_project(
                repository,
                Path(tmp),
                name="初回: Fresh",
                brief="Make the pad warmer without masking the vocal",
            )
            warm = _finite_map_variant(repository, label="warm-v1", color_hz=660.0, depth=0.012)
            commands.create_best_update_session(
                repository, proposed_variant=warm, actor_id="agent:dev-seed"
            )
            commands.create_observation_session(
                repository,
                first_variant="source",
                second_variant=warm,
                focus="高域の丸さを聴き分けられるか",
                size="short",
                actor_id="agent:dev-seed",
            )
        finally:
            repository.close()


def seed_all_done(workspace: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        repository = WorkspaceRepository.open(workspace)
        try:
            _start_project(
                repository,
                Path(tmp),
                name="完了済み: Quiet",
                brief="Reduce harshness while keeping presence",
            )
            soft = _finite_map_variant(repository, label="soft-v1", color_hz=520.0, depth=0.015)
            _promote(repository, soft)
            observed = commands.create_observation_session(
                repository,
                first_variant="source",
                second_variant=soft,
                focus="歯擦音の刺さり",
                size="short",
                actor_id="agent:dev-seed",
            )
            core = _core_session(repository, observed)
            commands.start_session(repository, core, allocation_seed=3)
            _answer_all(repository, core, preferences=[4])
        finally:
            repository.close()


def seed_quick_listen(workspace: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        directory = Path(tmp)
        repository = WorkspaceRepository.open(workspace)
        try:
            _start_project(
                repository,
                directory,
                name="Quick Listen: Echo",
                brief="Check a one-off bounce against the reference",
            )
            reference = _write_wav(directory, "reference.wav", _tone(261.6, harmonics=0.3))
            bounce = _write_wav(directory, "bounce.wav", _tone(261.6, vibrato=0.25, harmonics=0.4))
            session_id = commands.create_quick_listen(
                repository, str(reference), str(bounce), presentation="blind"
            )
            commands.start_session(repository, session_id)
        finally:
            repository.close()


def seed_simplification(workspace: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        repository = WorkspaceRepository.open(workspace)
        try:
            _start_project(
                repository,
                Path(tmp),
                name="簡素化確認: Lite",
                brief="Keep the sound while simplifying the chain",
            )
            full = _finite_map_variant(repository, label="full-chain", color_hz=660.0, depth=0.02)
            _promote(repository, full)
            # 同じ音を出す別Variant(処理を減らした版という想定)。
            lite = _finite_map_variant(repository, label="lite-chain", color_hz=660.0, depth=0.02)
            state = repository.state()
            project = state.project.project
            assert project is not None
            scope = tuple(
                clip_id
                for material_id in project.material_ids
                for clip_id in state.compare.materials[material_id].clip_ids
            )
            commands.create_simplification(
                repository,
                simple_variant_id=lite,
                reason="EQ段を1つ外しても出力が変わらない",
                scope_clip_ids=scope,
            )
        finally:
            repository.close()


def seed_blocked(workspace: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        repository = WorkspaceRepository.open(workspace)
        try:
            _start_project(
                repository,
                Path(tmp),
                name="開始不可: Broken",
                brief="Show why a Session could not start",
            )
            broken = _finite_map_variant(repository, label="broken-v1", color_hz=700.0, depth=0.02)
            session_id = commands.create_observation_session(
                repository,
                first_variant="source",
                second_variant=broken,
                focus="音声が欠けたSession",
                size="short",
                actor_id="agent:dev-seed",
            )
            core = _core_session(repository, session_id)
            state = repository.state()
            comparison = state.compare.comparisons[
                state.compare.sessions[core].items[0].comparison_id
            ]
            pair = state.compare.prepared_pairs[comparison.prepared_pair_id]
            missing = state.compare.audio[pair.output_audio_by_input_key["p2"]]
            _delete_object(repository, missing.object_id)
            # 開始はsession.blockedを記録して拒否される。それが表示したい状態。
            with contextlib.suppress(commands.CommandError):
                commands.start_session(repository, core)
        finally:
            repository.close()


def seed_degraded(workspace: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        repository = WorkspaceRepository.open(workspace)
        try:
            _start_project(
                repository,
                Path(tmp),
                name="停止: Degraded",
                brief="Show the recovery guidance",
            )
            project = repository.state().project.project
            assert project is not None
            # reducerが拒否する権威eventを直接追記し、replayを止める(開発用の再現)。
            repository.events.append(
                draft(
                    "project.brief.changed",
                    {
                        "project_id": project.id,
                        "revision": project.brief_revision + 5,
                        "text": "skipped revisions",
                        "human_quote": "skipped revisions",
                        "actor_id": "human",
                    },
                    idempotency_key=commands.operation_key(),
                )
            )
        finally:
            repository.close()


def seed_no_project(workspace: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="abar-seed-") as tmp:
        repository = WorkspaceRepository.open(workspace)
        try:
            commands.import_audio(repository, _write_wav(Path(tmp), "loose.wav", _tone(200.0)))
        finally:
            repository.close()


def _delete_object(repository: WorkspaceRepository, object_id: str) -> None:
    digest = ImmutableObjectStore._parse_object_id(object_id)  # pyright: ignore[reportPrivateUsage]
    path = repository.objects._path_for_digest(digest)  # pyright: ignore[reportPrivateUsage]
    path.chmod(0o600)
    path.unlink()


SCENARIOS: dict[str, Callable[[Path], None]] = {
    "standard": lambda workspace: seed(workspace, project_name="標準: Xifa"),
    "fresh": seed_fresh,
    "all-done": seed_all_done,
    "quick-listen": seed_quick_listen,
    "simplification": seed_simplification,
    "blocked": seed_blocked,
    "degraded": seed_degraded,
    "no-project": seed_no_project,
}
DEFAULT_ROOT = Path(".dev-workspaces")


def seed_scenarios(
    root: Path, names: tuple[str, ...] = tuple(SCENARIOS), *, reset: bool = False
) -> tuple[Path, ...]:
    """指定シナリオを `root/<name>` へ投入する。既存のものは reset しない限り残す。"""
    created: list[Path] = []
    for name in names:
        workspace = root / name
        if reset and workspace.exists():
            shutil.rmtree(workspace)
        if workspace.exists() and any(workspace.iterdir()):
            continue
        SCENARIOS[name](workspace)
        created.append(workspace)
    return tuple(created)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--scenario",
        action="append",
        choices=tuple(SCENARIOS),
        help="投入するシナリオ(複数指定可)。省略時は全シナリオ",
    )
    parser.add_argument("--reset", action="store_true", help="対象シナリオを削除して作り直す")
    args = parser.parse_args()
    root: Path = args.root.expanduser()
    names = tuple(args.scenario or SCENARIOS)
    created = seed_scenarios(root, names, reset=args.reset)
    for workspace in created:
        print(f"投入しました: {workspace}")
    skipped = [name for name in names if root / name not in created]
    if skipped:
        print(f"既存のため省略: {', '.join(skipped)}(作り直すなら --reset)")
    print("起動: uv run python scripts/dev.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
