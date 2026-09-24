"""開発用の模擬エージェント。

実際のエージェントの代わりに、試聴の受信箱が空にならないよう候補とSessionを補充する。
人間の回答は一切生成しない(ABARの権限境界どおり、回答はUIから人間が行う)。

一回の巡回で行うこと:
    - 完了したSessionを読み、結果をログとProject noteへ記録する
    - 現在最良が変わっていれば、新しい現在最良へ指標値を記録する
    - 準備済みSessionが --keep-ready 件未満なら、新しいVariantを作ってSessionを足す
      (奇数世代は現在最良チェック、偶数世代は観察Session)

使い方:
    uv run python scripts/dev_agent.py --workspace .dev-workspaces/standard
    uv run python scripts/dev_agent.py --workspace ... --once        # 一回だけ巡回
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from abar.app import commands
from abar.app.actors import Actor
from abar.app.queries import session_result
from abar.app.repository import WorkspaceDegraded, WorkspaceRepository
from abar.app.state import ABARState

try:  # `python scripts/dev_agent.py` と `import scripts.dev_agent`(テスト)の両方で読めるようにする
    from dev_seed import _finite_map_variant  # pyright: ignore[reportPrivateUsage]
except ModuleNotFoundError:
    from scripts.dev_seed import _finite_map_variant  # pyright: ignore[reportPrivateUsage]

ACTOR_ID = "agent:dev-agent"
FOCUSES = (
    "アタックの輪郭が保たれているか",
    "高域の空気感が減っていないか",
    "低域の膨らみで濁っていないか",
    "密度が上がったと感じるか",
)
INDICATORS = (
    ("ind_dev_density_v1", "DENSITY", "音像を潰さず、知覚上の密度を高める", "target"),
    ("ind_dev_attack_v1", "ATTACK LOSS", "トランジェントの輪郭を失っていないか", "guard"),
)


@dataclass(slots=True)
class MockAgent:
    workspace: Path
    keep_ready: int = 2
    seen_ended: set[str] = field(default_factory=set[str])
    started: bool = False

    def tick(self) -> list[str]:
        repository = WorkspaceRepository.open(self.workspace)
        try:
            try:
                state = repository.state()
            except WorkspaceDegraded:
                return ["Workspaceがdegradedのため何もしません"]
            if state.project.project is None:
                return ["Projectがないため何もしません"]
            if not self.started:
                # 起動前に完了していたSessionは報告済みとみなす。
                self.seen_ended = _ended_sessions(state)
                self.started = True
            try:
                log = self._report_finished(repository, state)
                log.extend(self._refill(repository))
            except commands.CommandError as error:
                # 実エージェントと同じく、拒否は記録して次の巡回で続ける。
                return [f"操作が拒否されました({error.code}): {error}"]
            return log
        finally:
            repository.close()

    def _report_finished(self, repository: WorkspaceRepository, state: ABARState) -> list[str]:
        log: list[str] = []
        for project_session_id in sorted(_ended_sessions(state) - self.seen_ended):
            self.seen_ended.add(project_session_id)
            project_session = state.research.project_sessions[project_session_id]
            result = session_result(repository, project_session_id)
            line = (
                f"「{project_session.focus}」が完了: "
                f"優勢={result.favored_variant_label or 'なし'}"
                + (" / 現在最良を更新" if result.current_best_updated else "")
            )
            log.append(line)
            commands.write_note(repository, _append_note(repository, line), actor_id=ACTOR_ID)
            if result.current_best_updated:
                log.extend(self._measure_current_best(repository))
        return log

    def _measure_current_best(self, repository: WorkspaceRepository) -> list[str]:
        state = repository.state()
        project = state.project.project
        assert project is not None
        variant_id = project.current_best_variant_id
        subject = next(
            (
                operand.audio_id
                for comparison in state.compare.comparisons.values()
                for operand in comparison.pair
                if operand.provenance_ref.get("variant_ref") == variant_id
            ),
            None,
        )
        if subject is None:
            return []
        with tempfile.TemporaryDirectory(prefix="abar-agent-") as tmp:
            definition = Path(tmp) / "definition.txt"
            definition.write_text("dev agent indicator definition", encoding="utf-8")
            for indicator_id, label, description, role in INDICATORS:
                if indicator_id not in state.research.indicators:
                    commands.register_indicator(
                        repository,
                        indicator_id=indicator_id,
                        label=label,
                        description=description,
                        definition_path=definition,
                        subject_kind="audio",
                        unit="ratio",
                        role=role,  # type: ignore[arg-type]
                        actor_id=ACTOR_ID,
                    )
        score = _unit(variant_id)
        for indicator_id, _label, _description, role in INDICATORS:
            commands.record_indicator_value(
                repository,
                indicator_id=indicator_id,
                subject_id=subject,
                variant_id=variant_id,
                value=round(0.5 + 0.4 * score, 3) if role == "target" else round(score, 3),
                guard_result=None if role == "target" else ("fail" if score < 0.2 else "pass"),
                actor=Actor(ACTOR_ID, "agent"),
            )
        return ["新しい現在最良へ指標値を記録"]

    def _refill(self, repository: WorkspaceRepository) -> list[str]:
        log: list[str] = []
        while _ready_count(repository.state()) < self.keep_ready:
            generation = _next_generation(repository.state())
            color = 400.0 + 900.0 * _unit(f"color-{generation}")
            depth = 0.008 + 0.03 * _unit(f"depth-{generation}")
            label = f"agent-v{generation}"
            variant = _finite_map_variant(repository, label=label, color_hz=color, depth=depth)
            project = repository.state().project.project
            assert project is not None
            try:
                if generation % 2 == 1:
                    commands.create_best_update_session(
                        repository, proposed_variant=variant, actor_id=ACTOR_ID
                    )
                    log.append(f"{label} で現在最良チェックを準備")
                else:
                    focus = FOCUSES[(generation // 2) % len(FOCUSES)]
                    commands.create_observation_session(
                        repository,
                        first_variant=project.current_best_variant_id,
                        second_variant=variant,
                        focus=focus,
                        size="short" if generation % 4 == 2 else "standard",
                        same_check=generation % 4 == 0,
                        repeat_check=generation % 4 == 0,
                        actor_id=ACTOR_ID,
                    )
                    log.append(f"{label} で観察Session「{focus}」を準備")
            except commands.CommandError as error:
                log.append(f"Sessionを準備できません: {error}")
                break
        return log


def _append_note(repository: WorkspaceRepository, line: str) -> str:
    notes = repository.state().research.notes
    current = notes[-1].markdown if notes else ""
    stamp = datetime.now().strftime("%H:%M")
    entry = f"- {stamp} {line}"
    return (
        f"{current.rstrip()}\n{entry}\n"
        if current.strip()
        else f"## 模擬エージェントの記録\n{entry}\n"
    )


def _ended_sessions(state: ABARState) -> set[str]:
    return {
        project_session.id
        for project_session in state.research.project_sessions.values()
        if state.compare.session_runtime[project_session.core_session_id].status == "ended"
    }


def _ready_count(state: ABARState) -> int:
    return sum(
        state.compare.session_runtime[item.core_session_id].status == "ready"
        for item in state.research.project_sessions.values()
    )


def _next_generation(state: ABARState) -> int:
    labels = {variant.label for variant in state.compare.variants.values()}
    generation = 1
    while f"agent-v{generation}" in labels:
        generation += 1
    return generation


def _unit(seed: str) -> float:
    """seedから決まる [0, 1) の値。実行ごとに同じ候補列を作る。"""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=3.0, help="巡回間隔(秒)")
    parser.add_argument("--keep-ready", type=int, default=2, help="維持する準備済みSession数")
    parser.add_argument("--once", action="store_true", help="一回だけ巡回して終了する")
    args = parser.parse_args()
    agent = MockAgent(args.workspace.expanduser().resolve(), keep_ready=args.keep_ready)
    print(f"[agent] 監視を開始: {agent.workspace}", flush=True)
    try:
        while True:
            for line in agent.tick():
                print(f"[agent] {datetime.now():%H:%M:%S} {line}", flush=True)
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
