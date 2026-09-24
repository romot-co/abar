"""ABARの開発環境を一つのコマンドで起動する。

ダミーデータ(scripts/dev_seed.py のシナリオ)を必要な分だけ投入し、UIサーバーを起動する。
UIのProject切替で、状態ごとのWorkspace(標準・初回・完了済み・Quick Listen・簡素化確認・
開始不可・停止)を行き来できる。

    uv run python scripts/dev.py                    # ビルド済みUIで起動 → ブラウザを開く
    uv run python scripts/dev.py --hot              # Viteのホットリロードで ui/src を確認
    uv run python scripts/dev.py --agent            # 模擬エージェントがSessionを補充し続ける
    uv run python scripts/dev.py --primary fresh    # 最初に開くシナリオを選ぶ
    uv run python scripts/dev.py --reset            # ダミーデータを作り直す

開発用Workspaceは固定token(`abar-dev`)を使うため、URLは再起動しても変わらない。
ローカルのダミーデータ専用であり、実データのWorkspaceには使わない。
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

try:  # `python scripts/dev.py` と `import scripts.dev`(テスト)の両方で読めるようにする
    from dev_seed import DEFAULT_ROOT, SCENARIOS, seed_scenarios
except ModuleNotFoundError:
    from scripts.dev_seed import DEFAULT_ROOT, SCENARIOS, seed_scenarios

REPOSITORY = Path(__file__).resolve().parent.parent
DEV_TOKEN = "abar-dev"
VITE_PORT = 5173


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=REPOSITORY / DEFAULT_ROOT)
    parser.add_argument("--primary", choices=tuple(SCENARIOS), default="standard")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8765")),
        help="UIサーバーのport(使用中なら次の空きportを使う。既定は$PORTまたは8765)",
    )
    parser.add_argument("--hot", action="store_true", help="Vite dev server(ホットリロード)も起動")
    parser.add_argument("--agent", action="store_true", help="模擬エージェントも起動")
    parser.add_argument("--reset", action="store_true", help="全シナリオを作り直す")
    parser.add_argument("--no-open", dest="open", action="store_false", help="ブラウザを開かない")
    args = parser.parse_args()

    root: Path = args.root.expanduser().resolve()
    created = seed_scenarios(root, reset=args.reset)
    if created:
        print(f"ダミーデータを投入: {', '.join(path.name for path in created)}")
    primary = root / args.primary
    (primary / ".ui-secret").write_text(DEV_TOKEN, encoding="utf-8")

    port = _free_port(args.port)
    backend = f"http://127.0.0.1:{port}"
    children: list[subprocess.Popen[bytes]] = []
    try:
        children.append(
            _spawn(
                [
                    *(sys.executable, "-m", "abar", "--workspace", str(primary)),
                    *("ui", "--no-open", "--port", str(port)),
                ]
            )
        )
        _wait_until_up(backend, children[0])
        url = f"{backend}/#token={DEV_TOKEN}"
        if args.hot:
            npm = shutil.which("npm")
            if npm is None or not (REPOSITORY / "ui" / "node_modules").is_dir():
                print("--hot には Node と `cd ui && npm ci` が必要です", file=sys.stderr)
                return 1
            vite_port = _free_port(VITE_PORT)
            children.append(
                _spawn(
                    [npm, "run", "dev", "--", "--port", str(vite_port), "--strictPort"],
                    cwd=REPOSITORY / "ui",
                    env={**os.environ, "ABAR_API": backend},
                )
            )
            url = f"http://localhost:{vite_port}/#token={DEV_TOKEN}"
            _wait_until_up(f"http://localhost:{vite_port}", children[-1])
        if args.agent:
            children.append(
                _spawn(
                    [
                        *(sys.executable, str(REPOSITORY / "scripts" / "dev_agent.py")),
                        *("--workspace", str(primary)),
                    ]
                )
            )
        _print_summary(url, root, args)
        if args.open:
            webbrowser.open(url)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        stopped = next(child for child in children if child.poll() is not None)
        print(f"停止したため終了します: {' '.join(map(str, stopped.args))}", file=sys.stderr)  # type: ignore[arg-type]
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()


def _free_port(preferred: int) -> int:
    """preferredから順に、localhost(IPv4/IPv6)で誰も待ち受けていないportを返す。"""
    for port in range(preferred, preferred + 50):
        try:
            with socket.create_connection(("localhost", port), timeout=0.2):
                continue  # 他のサーバーが使用中
        except OSError:
            if port != preferred:
                print(f"port {preferred} は使用中のため {port} を使います")
            return port
    raise SystemExit(f"port {preferred}〜{preferred + 49} に空きがありません")


def _spawn(
    argv: list[str], *, cwd: Path = REPOSITORY, env: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(argv, cwd=cwd, env=env)


def _wait_until_up(url: str, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"起動に失敗しました: {' '.join(map(str, process.args))}")  # type: ignore[arg-type]
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except urllib.error.HTTPError:
            return  # 応答があれば起動済み
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise SystemExit(f"{url} が {timeout:.0f} 秒以内に起動しませんでした")


def _print_summary(url: str, root: Path, args: argparse.Namespace) -> None:
    lines = [
        "",
        f"ABAR dev: {url}",
        f"  データ: {root}(Project切替で各シナリオへ移動)",
        f"  主Workspace: {args.primary}"
        + (
            "(Project一覧に出ないため主Workspaceでだけ表示)" if args.primary == "no-project" else ""
        ),
    ]
    if args.hot:
        lines.append("  ui/src の変更はホットリロードされます")
    else:
        lines.append("  ビルド済みUIを表示中。ui/src を編集するなら --hot で起動")
    if args.agent:
        lines.append("  模擬エージェント: 回答するとSessionが補充されます([agent] ログ)")
    lines.append("  停止: Ctrl+C")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    sys.exit(main())
