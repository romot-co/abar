"""開発用ダミーデータ投入スクリプト。

UIの確認・手元テスト用に、各状態を網羅したWorkspaceを作る:
素材3件(+Clip)、Variant2件、完了Session、進行中Session、準備済みSession、
Indicator、ノート。

使い方:
    uv run python scripts/dev_seed.py                # ./.dev-workspace に投入
    uv run python scripts/dev_seed.py --reset        # 作り直し
    uv run python scripts/dev_seed.py --workspace /tmp/abar-dev

投入後:
    uv run abar --workspace .dev-workspace ui
UI開発(Viteホットリロード)なら:
    uv run abar --workspace .dev-workspace ui --no-open   # tokenをメモ
    cd ui && npm run dev
    → http://localhost:5173/#token=<上のtoken> を開く
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
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
                    size="short",
                    actor_id="human",
                    actor_type="human",
                )
                state = repository.state()
                done_core = state.research.project_sessions[done_id].core_session_id
                commands.start_session(repository, done_core, allocation_seed=index + 20)
                _answer_all(
                    repository,
                    done_core,
                    preferences=[4 if index == 0 else 3],
                    blocker_slot="a" if index == 0 else None,
                )

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workspace", type=Path, default=Path(".dev-workspace"))
    parser.add_argument("--reset", action="store_true", help="既存のworkspaceを削除して作り直す")
    args = parser.parse_args()
    workspace: Path = args.workspace.expanduser()
    secondary = workspace.with_name(f"{workspace.name}-noct")
    targets = (workspace, secondary)
    if args.reset:
        for target in targets:
            if target.exists():
                shutil.rmtree(target)
    occupied = next(
        (target for target in targets if target.exists() and any(target.iterdir())), None
    )
    if occupied is not None:
        print(f"{occupied} は空ではありません。--reset を付けるか別のパスを指定してください。")
        return 1
    seed(workspace)
    seed(
        secondary,
        project_name="Noct",
        brief="Tighter low end, keep the vocal forward",
    )
    print(f"ダミーデータを投入しました: {workspace}, {secondary}")
    print(f"  uv run abar --workspace {workspace} ui")
    print("UI開発(ホットリロード)なら `abar ui --no-open` + `cd ui && npm run dev`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
