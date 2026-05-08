---
description: spec.md 파일을 받아 planner(A)에게 전달. /spec <path> 형식. 완료 시 specs/_done/로 자동 이동.
argument-hint: <spec 파일 경로>
---

# /spec — spec 파일 기반 하네스 진입점

## 사용법

```
/spec specs/2026-05-08-fix-redis-cache.md
/spec specs/2026-05-09-add-bedrock-converse-stream.md
```

## 동작

다음 단계를 정확히 실행하세요:

1. `$ARGUMENTS`가 비어 있거나 `.md` 파일 경로가 아니면 사용자에게 안내 후 종료.
2. `Read` tool로 해당 파일을 읽는다. 존재하지 않으면 "파일 없음" 보고 후 종료.
3. **YAML frontmatter 파싱**: 파일 시작 `---` ~ `---` 사이에서 다음 5필드 추출:
   - `target_dir` (string)
   - `category` (`bug` | `fix` | `add` | `refactor`)
   - `refs` (list of `"@docs/..."` 또는 `"@docs/operations/..."`)
   - `accept` (list)
   - `reject` (list)
4. **헤더 검증**:
   - `refs`가 비어 있으면 → 사용자에게 "refs 누락 — 처리 거부. specs/README.md 참조" 안내 후 종료.
   - `target_dir`/`category`/`accept` 누락은 경고만, 기본값 적용 (각각 root / `misc` / 본문에서 추출).
5. `Agent` tool을 `subagent_type="planner"`로 호출. prompt 내용:
   - **모드**: spec 모드
   - **spec 파일 경로**: `<인자>`
   - **target_dir**: `<파싱값>`
   - **category**: `<파싱값>`
   - **refs (planner가 읽을 docs)**: `<리스트>` — "이 외 docs는 절대 Read 금지. 정보 부족 시 사용자에게 회신"
   - **accept (C qa-tester로 전달)**: `<리스트>`
   - **reject (B implementer prompt에 강제)**: `<리스트>`
   - **본문**: `<spec 본문 그대로>`
   - **지시**: ".claude/agents/planner.md의 spec 모드 절차에 따라 작업 분해 → implementer → qa-tester → kpi-tester. tdd-runner는 Stop hook이 자동 호출. 모든 단위 완료 후 사용자에게 변경 파일·검수·KPI 보고서 경로 요약 보고."
6. planner 응답 받음 → 사용자에게 짧게 요약 전달.
7. **자동 이동은 Stop hook이 처리** — 본 명령어 본문에서는 직접 mv 하지 않는다 (`post_stop_orchestrator.py`가 transcript에서 본 명령 호출을 감지해 처리).

## 사전 조건

- spec 파일이 `specs/README.md` 양식을 따라야 한다 (특히 `refs` 필수)
- planner agent 정의에 spec 모드 절이 있어야 한다 (`.claude/agents/planner.md`)
- `specs/_done/` 디렉토리는 없으면 hook이 자동 생성

## 참조

- `specs/README.md` — 양식 명세
- `.claude/agents/planner.md` — A 정체성, spec 모드 절차
- `.claude/scripts/post_stop_orchestrator.py` — 자동 이동 로직
