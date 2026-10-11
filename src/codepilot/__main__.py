"""入口：`uv run codepilot` 或 `python -m codepilot`。"""

from __future__ import annotations

from codepilot.ui.app import run


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
