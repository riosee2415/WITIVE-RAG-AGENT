"""UserPromptSubmit hook — 토큰 효율을 위해 가장 가까운 work_rule.md만 컨텍스트 주입.

작업 디렉토리 또는 사용자 프롬프트에서 추정한 디렉토리로부터 가장 가까운 work_rule.md를 찾아 stdout으로 주입. 전체 트리 로드 회피.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def find_nearest_work_rule(start: Path) -> Path | None:
    cur = start.resolve()
    while True:
        candidate = cur / "work_rule.md"
        if candidate.exists():
            return candidate
        if cur == ROOT or cur.parent == cur:
            return None
        cur = cur.parent


def main() -> None:
    payload = sys.stdin.read()
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {}

    cwd = Path(data.get("cwd", ROOT))
    nearest = find_nearest_work_rule(cwd) or (ROOT / "work_rule.md")
    if not nearest.exists():
        return

    rel = nearest.relative_to(ROOT).as_posix()
    text = nearest.read_text(encoding="utf-8").strip()
    if len(text) < 200 and "등록된 규칙 없음" in text:
        # 빈 상태는 컨텍스트 낭비 — 주입하지 않음
        return

    print(f"<work_rule path=\"{rel}\">")
    print(text)
    print("</work_rule>")


if __name__ == "__main__":
    main()
