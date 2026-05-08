# specs/ — 작업 명세 파일

`/spec <path>` 명령어가 처리하는 task spec 파일을 보관한다.

## 위치 정책

- `specs/YYYY-MM-DD-<slug>.md` — 활성 spec
- `specs/_done/YYYY-MM-DD-<slug>.md` — `/spec` 처리 완료 후 Stop hook이 자동 이동

## git tracking

- 본 README만 git tracked
- spec `.md` 파일과 `_done/` 전체는 `.gitignore`로 제외됨 (사용자 결정 — 임시 백로그 용도)
- 따라서 spec은 PR review 대상이 아니며, 로컬 작업 메모리로만 사용

## 양식 (YAML frontmatter + 본문)

```markdown
---
target_dir: app/api/                                # planner cwd 힌트
category: bug | fix | add | refactor                # 분류
refs:                                               # planner가 읽을 docs/ADR만 명시 (전체 scan 금지)
  - "@docs/06-api.md §3.1"
  - "@docs/operations/adr/0005-sse-starlette-not-fastapi-native.md"
accept:                                             # 작업 완료 판정 기준 (C qa-tester로 전달)
  - "/internal/query SSE keep-alive 15s 유지"
  - "기존 pytest 통과"
reject:                                             # 절대 하지 말 것 (B implementer prompt에 강제)
  - "FastAPI 공식 sse 모듈 사용 시도"
  - "백워드 호환 깨짐"
---

# 본문 (자유 양식)

## 문제 / 의도

(현재 동작과 기대 동작, 재현 단계, 영향 범위 등 자유 서술)

## 메모 (선택)

(planner·implementer가 참고할 추가 컨텍스트)
```

## 명령어

| 명령 | 동작 |
|---|---|
| `/spec-new <slug>` | `specs/YYYY-MM-DD-<slug>.md` 빈 템플릿 생성 |
| `/spec <path>` | 해당 spec을 planner에 전달 → 4-agent 워크플로우 → 완료 시 `_done/`로 자동 이동 |

## 워크플로우

```
1. /spec-new fix-redis-cache       → specs/2026-05-08-fix-redis-cache.md 생성
2. (사용자가 헤더 + 본문 채움)
3. /spec specs/2026-05-08-fix-redis-cache.md
4. planner가 refs만 읽고 작업 분해
5. implementer → qa-tester → kpi-tester → tdd-runner (Stop hook 자동)
6. spec → specs/_done/ 자동 이동 (post_stop_orchestrator hook)
7. reports/YYYY-MM-DD-<slug>.html 자동 발행
```

## 헤더 필드 검증

`/spec` 명령은 헤더 5개 필드를 요구한다:

| 필드 | 누락 시 |
|---|---|
| `target_dir` | 경고 (root cwd로 진행) |
| `category` | 경고 (`misc`로 진행) |
| `refs` | **거부** — planner는 docs scan 회피가 목적이므로 refs 없으면 spec 의미 없음 |
| `accept` | 경고 (qa-tester가 spec 본문에서 추출 시도) |
| `reject` | 무시 OK (없을 수 있음) |

## 작성 가이드

- **refs는 §까지 명시** (예: `@docs/06-api.md §3.1`) — planner가 해당 절만 검색하므로 토큰 절감 ↑
- **accept는 검증 가능하게** — "잘 동작" X, "pytest tests/test_x.py 통과" O
- **본문 ≤ 200줄 권장** — 길면 핵심 의도가 묻힘. 외부 문서 링크로 대체

## 비교: `/spec` vs `/harness`

| 진입점 | 적합 상황 |
|---|---|
| `/harness <자연어>` | 즉흥, 탐색적 작업, "이게 가능한가?" |
| `/spec <file>` | 사전 정리된 버그·수정·추가, 동일 작업 재실행, 백로그 처리 |

토큰 비용:
- `/harness` → planner가 docs 27개 후보 중 관련 N개를 Grep·Read로 식별 (~50K)
- `/spec` → planner가 spec.refs 명시 docs만 Read (~5–10K)

같은 작업이면 spec 모드가 5–10배 효율.
