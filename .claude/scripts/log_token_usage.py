"""Stop / SubagentStop hook — 토큰 사용량 누적 기록.

`kpi/token_usage.jsonl`에 한 줄씩 append. 4 agent별 비용 가시화 → /review-check가 이 데이터를 활용 가능.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KPI_DIR = ROOT / "kpi"
LOG_FILE = KPI_DIR / "token_usage.jsonl"


def main() -> None:
    payload = sys.stdin.read()
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {}

    KPI_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "event": data.get("hook_event_name", "stop"),
        "agent": data.get("subagent_type") or os.environ.get("CLAUDE_SUBAGENT_TYPE", "main"),
        "session_id": data.get("session_id"),
        "stop_reason": data.get("stop_reason"),
        "transcript_path": data.get("transcript_path"),
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
