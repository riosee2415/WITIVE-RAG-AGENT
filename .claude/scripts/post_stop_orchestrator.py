"""Stop hook — 작업 종료 강제 절차.

흐름:
1. transcript_path를 파싱해 변경 파일·도구 호출·tdd-runner 호출 여부·토큰 사용량 추출
2. 코드/문서 변경이 있는데 tdd-runner 미호출 + stop_hook_active=False
   → JSON {decision: block, reason: "..."} 반환 → Claude가 자동으로 tdd-runner 호출
3. 그 외 (TDD 완료 / 변경 없음 / 이미 한 번 block된 상태)
   → work_rule.md 활동 로그 갱신
   → /spec 호출 감지 시 spec.md를 specs/_done/로 자동 이동
   → reports/YYYY-MM-DD-<slug>.html 발행 후 통과
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / ".claude" / "scripts"
STATE_DIR = ROOT / ".claude" / "state"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def parse_transcript(path: str) -> dict:
    p = Path(path) if path else None
    info: dict = {
        "changes": [],
        "tools": [],
        "user_prompts": [],
        "subagents_called": [],
        "tdd_called": False,
        "errors": [],
        "usage": {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0},
    }
    if not p or not p.exists():
        return info

    seen_changes: set[str] = set()
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                mtype = msg.get("type")
                if mtype == "user":
                    content = msg.get("message", {}).get("content")
                    if isinstance(content, str) and not content.startswith("<"):
                        info["user_prompts"].append(content[:600])
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                t = c.get("text", "")
                                if t and not t.startswith("<"):
                                    info["user_prompts"].append(t[:600])
                            elif isinstance(c, dict) and c.get("type") == "tool_result":
                                if c.get("is_error"):
                                    info["errors"].append(str(c.get("content", ""))[:400])
                elif mtype == "assistant":
                    m = msg.get("message", {})
                    u = m.get("usage", {}) or {}
                    info["usage"]["input"] += int(u.get("input_tokens", 0) or 0)
                    info["usage"]["output"] += int(u.get("output_tokens", 0) or 0)
                    info["usage"]["cache_read"] += int(u.get("cache_read_input_tokens", 0) or 0)
                    info["usage"]["cache_create"] += int(u.get("cache_creation_input_tokens", 0) or 0)
                    for c in m.get("content", []) or []:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "tool_use":
                            name = c.get("name", "")
                            inp = c.get("input", {}) or {}
                            info["tools"].append({"name": name, "input": inp})
                            if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                                fp = inp.get("file_path", "")
                                if fp and fp not in seen_changes:
                                    seen_changes.add(fp)
                                    info["changes"].append(fp)
                            elif name in ("Agent", "Task"):
                                sub = inp.get("subagent_type", "")
                                if sub:
                                    info["subagents_called"].append(sub)
                                if sub == "tdd-runner":
                                    info["tdd_called"] = True
    except OSError:
        pass

    return info


_SPEC_CMD_RE = re.compile(r"/spec\s+([^\s\n]+\.md)", re.IGNORECASE)


def detect_spec_paths(prompts: list[str]) -> list[str]:
    out: list[str] = []
    for p in prompts or []:
        for m in _SPEC_CMD_RE.finditer(p or ""):
            path = m.group(1).strip().strip('"\'').replace("\\", "/")
            if path and path not in out:
                out.append(path)
    return out


def move_specs_to_done(spec_paths: list[str], root: Path) -> list[Path]:
    moved: list[Path] = []
    if not spec_paths:
        return moved
    done_dir = root / "specs" / "_done"
    done_dir.mkdir(parents=True, exist_ok=True)
    done_resolved = done_dir.resolve()
    for sp in spec_paths:
        try:
            src = (root / sp).resolve() if not Path(sp).is_absolute() else Path(sp).resolve()
        except OSError:
            continue
        if not src.exists() or not src.is_file():
            continue
        try:
            src.relative_to(done_resolved)
            continue
        except ValueError:
            pass
        dst = done_dir / src.name
        if dst.exists():
            ts = dt.datetime.now().strftime("%H%M%S")
            dst = done_dir / f"{src.stem}-{ts}{src.suffix}"
        try:
            src.rename(dst)
            moved.append(dst)
        except OSError as e:
            print(f"[hook:post_stop_orchestrator] spec 이동 실패 {src}: {e}", file=sys.stderr)
    return moved


def needs_tdd(changes: list[str]) -> bool:
    for c in changes:
        cl = c.lower().replace("\\", "/")
        if cl.endswith(".py"):
            return True
        parts = set(cl.split("/"))
        if cl.endswith(".md") and (parts & {"docs", "app"}):
            return True
        if parts & {"app", "tests"}:
            return True
    return False


def main() -> None:
    payload = sys.stdin.read()
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        data = {}

    transcript_path = data.get("transcript_path", "") or ""
    session_id = (data.get("session_id") or "default").replace("/", "_").replace("\\", "_")
    stop_hook_active = bool(data.get("stop_hook_active", False))

    info = parse_transcript(transcript_path)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{session_id}.json"
    state: dict = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}

    tdd_done = bool(state.get("tdd_done") or info["tdd_called"])
    must_tdd = needs_tdd(info["changes"])

    if must_tdd and not tdd_done and not stop_hook_active:
        first_changes = info["changes"][:5]
        out = {
            "decision": "block",
            "reason": (
                "[hook:post_stop_orchestrator] 변경된 코드/문서에 대한 TDD/lint 검증이 누락됐다. "
                "다음 응답에서 반드시 Agent tool을 subagent_type=\"tdd-runner\"로 호출해 검증을 수행하라. "
                f"변경 파일(샘플): {first_changes}. "
                "tdd-runner 결과를 받은 뒤 사용자에게 결과를 짧게 요약 보고하면 본 hook이 통과시킨다."
            ),
        }
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
        return

    state["tdd_done"] = tdd_done
    state["last_changes"] = info["changes"]
    state["last_tools_count"] = len(info["tools"])
    try:
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        print(f"[hook:post_stop_orchestrator] state 기록 실패: {e}", file=sys.stderr)

    try:
        from update_work_rule import append_activity_log
        append_activity_log(info["changes"], info["user_prompts"], ROOT)
    except Exception as e:
        print(f"[hook:post_stop_orchestrator] work_rule 갱신 실패: {e}", file=sys.stderr)

    try:
        spec_paths = detect_spec_paths(info["user_prompts"])
        moved = move_specs_to_done(spec_paths, ROOT)
        if moved:
            info["spec_moved"] = [str(p.relative_to(ROOT)) for p in moved]
    except Exception as e:
        print(f"[hook:post_stop_orchestrator] spec 이동 실패: {e}", file=sys.stderr)

    try:
        from generate_report import write_html_report
        write_html_report(info, ROOT, session_id)
    except Exception as e:
        print(f"[hook:post_stop_orchestrator] report 생성 실패: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
