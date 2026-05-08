"""변경 파일에 가까운 work_rule.md를 찾아 자동 활동 로그 append.

C qa-tester가 관리하는 "## 일반 규칙" / "## 금지 규칙" 영역은 건드리지 않고,
별도 "## 자동 활동 로그 (hooks 자동 갱신)" 섹션에만 행 추가.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

ACTIVITY_HEADER = "## 자동 활동 로그 (hooks 자동 갱신)"
ACTIVITY_TABLE_HEADER = "| 일자 | 작업 요약 | 변경 파일 | 비고 |\n|---|---|---|---|"
MAX_ROWS = 200  # 너무 길어지면 head 200줄만 유지


def find_nearest_work_rule(file_path: Path, root: Path) -> Path:
    cur = file_path.resolve()
    if cur.is_file():
        cur = cur.parent
    try:
        cur.relative_to(root)
    except ValueError:
        return root / "work_rule.md"
    while True:
        candidate = cur / "work_rule.md"
        if candidate.exists():
            return candidate
        if cur == root or cur.parent == cur:
            return root / "work_rule.md"
        cur = cur.parent


def _ensure_section(text: str) -> str:
    if ACTIVITY_HEADER in text:
        return text
    return text.rstrip() + f"\n\n{ACTIVITY_HEADER}\n\n{ACTIVITY_TABLE_HEADER}\n"


def _trim_activity_rows(text: str) -> str:
    if ACTIVITY_HEADER not in text:
        return text
    head, tail = text.split(ACTIVITY_HEADER, 1)
    lines = tail.splitlines()
    body_lines = []
    table_lines = []
    in_table = False
    for ln in lines:
        if ln.startswith("|"):
            in_table = True
            table_lines.append(ln)
        elif in_table and ln.strip() == "":
            break
        else:
            body_lines.append(ln)
    if len(table_lines) > MAX_ROWS + 2:
        table_lines = table_lines[:2] + table_lines[-MAX_ROWS:]
    rebuilt = head + ACTIVITY_HEADER + "\n" + "\n".join(body_lines).rstrip() + "\n\n" + "\n".join(table_lines) + "\n"
    return rebuilt


def append_activity_log(changes: list[str], prompts: list[str], root: Path) -> list[Path]:
    targets: dict[Path, list[str]] = {}
    if changes:
        for c in changes:
            try:
                p = Path(c)
                wr = find_nearest_work_rule(p, root)
                targets.setdefault(wr, []).append(c)
            except Exception:
                continue
    if not targets:
        targets[root / "work_rule.md"] = []

    today = dt.date.today().isoformat()
    summary = (prompts[0] if prompts else "(자동 갱신)").replace("\n", " ").replace("|", "/")[:80] or "(자동 갱신)"

    written: list[Path] = []
    for wr, files in targets.items():
        if not wr.exists():
            wr.parent.mkdir(parents=True, exist_ok=True)
            wr.write_text(
                f"# work_rule\n\n자동 hook이 활동 로그를 누적한다. C qa-tester 영역은 분리.\n\n{ACTIVITY_HEADER}\n\n{ACTIVITY_TABLE_HEADER}\n",
                encoding="utf-8",
            )
        text = wr.read_text(encoding="utf-8")
        text = _ensure_section(text)
        files_str = ", ".join(Path(f).name for f in files[:5]) or "—"
        new_row = f"| {today} | {summary} | {files_str} | hook |"
        text = text.rstrip() + "\n" + new_row + "\n"
        text = _trim_activity_rows(text)
        wr.write_text(text, encoding="utf-8")
        written.append(wr)
    return written
