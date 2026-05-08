# WITIVE Knowledge AI — Harness root

LLM·RAG·AI 전담 FastAPI 마이크로서비스. Next.js 백엔드(Supabase Auth 검증 후)의 internal 호출만 받음.

## 절대 규칙 (시스템 레벨, hook 강제)

1. **`@docs/`가 단일 진실 출처** — 코드 변경이 docs와 어긋나면 거부 (`docs-sync` Skill 자동 검증)
2. **`@docs/00-scope.md` 책임 경계 위반 금지** — Supabase Auth 직접 호출, 사용자 식별자 생성, 인프라 프로비저닝, Next.js 책임 영역 호출 모두 거부
3. **모든 데이터 접근은 `tenant_id` 필터 강제** — 누락된 코드는 `import-linter`/QA가 자동 차단 (`@docs/07-multitenancy-and-access.md`)
4. **외부 의존성 호출은 `app/infra/`만** — `pipeline`·`api`·`domain` 직접 호출 금지 (`@docs/12-coding-conventions.md` §3)
5. **비용 영향 결정은 ADR 작성** — `@docs/operations/adr/`

## 작업 진입점 (slash 명령어)

| 명령 | 동작 |
|---|---|
| `/harness <feature>` | 자유 자연어 진입점 — 4-agent 워크플로 (즉흥 작업) |
| `/spec-new <slug>` | `specs/YYYY-MM-DD-<slug>.md` 빈 템플릿 생성 |
| `/spec <path>` | spec.md 파일 기반 진입점 — planner가 spec.refs만 읽음 (토큰 5–10배 효율). 종료 시 `specs/_done/`로 자동 이동 |
| `/review-check` | 안정성 KPI 측정 → upustream@gmail.com 이메일 |
| `/rubric` | 바이브코딩 정량 평가 → upustream@gmail.com 이메일 |

**spec 모드 워크플로우** — 버그·수정·추가 사항을 사전에 정리해두고 처리. 양식은 `specs/README.md`. spec 파일은 `.gitignore`로 제외(임시 백로그).

## 멀티 에이전트 (5개)

`/harness` 실행 시 A → B → C → D 순환. hooks로 시스템 강제.

- **A** `.claude/agents/planner.md` — docs 게이트키퍼·오케스트레이터 (model: opus)
- **B** `.claude/agents/implementer.md` — 코드 구현 (model: sonnet)
- **C** `.claude/agents/qa-tester.md` — QA + work_rule.md 갱신 (model: sonnet)
- **D** `.claude/agents/kpi-tester.md` — 골든셋 비교 + `kpi/<datetime>_<feature>.html` (model: sonnet)
- **TDD** `.claude/agents/tdd-runner.md` — 모든 작업 종료 직전 Stop hook이 자동 호출 (model: sonnet)

## 자동 작업 종료 프로토콜 (시스템 강제)

매 작업 종료 시 hooks가 자동으로 다음을 수행한다 (사용자 요청 불필요):

1. **TDD 강제** — 코드/문서 변경이 있으면 `Stop` hook이 `decision:block`을 반환해 `tdd-runner` 서브에이전트 실행을 강제
2. **work_rule 갱신** — 변경 파일에 가까운 `work_rule.md`의 `## 자동 활동 로그` 섹션에 행 append (C qa-tester 영역과 분리)
3. **보고서 발행** — `reports/YYYY-MM-DD-<slug>.html`에 사용자 프롬프트·도구 호출·에러·토큰 사용량 자동 기록

훅 구현: `.claude/scripts/{inject_completion_directive,post_stop_orchestrator,update_work_rule,generate_report}.py`

## 토큰 효율 정책

- 작업 디렉토리에 가까운 `CLAUDE.md` + `work_rule.md`만 로드 (전체 트리 X — `UserPromptSubmit` hook이 nearest 자동 주입)
- 도큐먼트 인용은 `@docs/<file>.md` 또는 `@docs/<file>.md §<절>` 형식 (전체 로드 X)
- 한 작업 단위 = 한 agent 위임 (4 agent 동시 호출 X, 명시적 Agent tool로 호출)
- B·C·D 결과는 요약만 메인 메모리에 보존

## 디렉토리별 세부 규칙

| 위치 | 책임 |
|---|---|
| `app/CLAUDE.md` | 6 레이어 의존 방향 강제 |
| `app/api/CLAUDE.md` | FastAPI router |
| `app/domain/CLAUDE.md` | 도메인 모델 (외부 라이브러리 의존 0) |
| `app/pipeline/CLAUDE.md` | 유즈케이스 (도메인 + infra 조합) |
| `app/infra/CLAUDE.md` | 외부 의존성 어댑터 |
| `app/platform/CLAUDE.md` | 횡단 관심사 |
| `app/workers/CLAUDE.md` | SQS 소비자 |

## 참조

- 14 docs: `@docs/`
- ADR: `@docs/operations/adr/`
- Runbook: `@docs/operations/runbooks/`
- SOP: `@docs/operations/sop/`
- 4-agent contract: `.claude/agents/*.md`
- hook 설정: `.claude/settings.json`

## work_rule

@work_rule.md
