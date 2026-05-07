"""PostToolUse(Edit|Write) hook.

변경된 파일에 대해 빠른 검증을 자동 실행하고, 위반이 있으면
Claude 컨텍스트에 system reminder로 주입한다.

Claude Code hook stdout convention: 출력 텍스트가 컨텍스트에 추가됨.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    payload = sys.stdin.read()
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {}

    file_paths = data.get("tool_input", {}).get("file_path") or os.environ.get(
        "CLAUDE_FILE_PATHS", ""
    )
    if isinstance(file_paths, str):
        files = [f for f in file_paths.split(":") if f.strip()]
    else:
        files = list(file_paths)

    py_files = [f for f in files if f.endswith(".py") and "src/app" in f.replace("\\", "/")]
    if not py_files:
        return

    issues: list[str] = []

    # ruff (빠름, 1초 안)
    try:
        r = subprocess.run(
            ["ruff", "check", "--quiet", *py_files],
            capture_output=True, text=True, timeout=15, cwd=ROOT,
        )
        if r.returncode != 0:
            issues.append(f"[ruff] {r.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # mypy 빠른 모드는 비용 큼 — 생략 (CI에서 검증)

    if issues:
        print("[hook:post_edit_check] 다음 이슈가 발견되었다. 다음 응답 전에 수정을 검토하라:")
        for i in issues:
            print(f"  - {i}")


if __name__ == "__main__":
    main()
