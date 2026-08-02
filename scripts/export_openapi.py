import argparse
import json
import tempfile
from pathlib import Path

from abar.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="abar-openapi-") as temporary:
        application = create_app(
            Path(temporary),
            automation_token="build-time-automation-token",
            interaction_token="build-time-interaction-token",
            allowed_origins=frozenset({"http://127.0.0.1:8765"}),
        )
        arguments.output.write_text(
            json.dumps(application.openapi(), separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
