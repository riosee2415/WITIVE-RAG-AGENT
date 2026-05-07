# WITIVE Knowledge AI — Harness root

LLM·RAG·AI 전담 FastAPI 마이크로서비스. NestJS 백엔드의 internal 호출만 받음.

## 절대 규칙 (시스템 레벨, hook 강제)

1. **`@docs/`가 단일 진실 출처** — 코드 변경이 docs와 어긋나면 거부 (`docs-sync` Skill 자동 검증)
2. **`@docs/00-scope.md` 책임 경계 위반 금지** — Cognito 직접 호출, 사용자 식별자 생성, 인프라 프로비저닝, NestJS 책임 영역 호출 모두 거부
3. **모든 데이터 접근은 `tenant_id` 필터 강제** — 누락된 코드는 `import-linter`/QA가 자동 차단 (`@docs/07-multitenancy-and-access.md`)
4. **외부 의존성 호출은 `app/infra/`만** — `pipeline`·`api`·`domain` 직접 호출 금지 (`@docs/12-coding-conventions.md` §3)
5. **비용 영향 결정은 ADR 작성** — `@docs/operations/adr/`

## 작업 진입점 (slash 명령어)

| 명령 | 동작 |
|---|---|
| `/harness <feature>` | A·B·C·D 4-agent 워크플로 시작 |
| `/review-check` | 안정성 KPI 측정 → upustream@gmail.com 이메일 |
| `/rubric` | 바이브코딩 정량 평가 → upustream@gmail.com 이메일 |

## 멀티 에이전트 (4개)

`/harness` 실행 시 A → B → C → D 순환. hooks로 시스템 강제.

- **A** `.claude/agents/planner.md` — docs 게이트키퍼·오케스트레이터 (model: opus)
- **B** `.claude/agents/implementer.md` — 코드 구현 (model: sonnet)
- **C** `.claude/agents/qa-tester.md` — QA + work_rule.md 갱신 (model: sonnet)
- **D** `.claude/agents/kpi-tester.md` — 골든셋 비교 + `kpi/<datetime>_<feature>.html` (model: sonnet)

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
