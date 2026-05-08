# work_rule (root)

C QA 테스터가 작업 중 발견한 **전역** 규칙을 누적. C만 수정 권한.

## 일반 규칙

- [2026-05-08] `pytest --cov` 전체 커버리지 기준은 새 레이어 테스트 누락분이 분모를 키운다 — `--cov=src/app` 범위는 전체 모듈을 측정하므로, 특정 레이어(domain)만 추가한 경우 기존 미테스트 파일(api/_middleware, main, platform/logging 등)이 총 커버리지를 끌어내린다. B가 특정 레이어 코드만 추가할 경우 커버리지 미달은 예상된 결과이며, TASK 완료 기준으로 "해당 레이어 100%"를 우선 체크해야 한다. (`@docs/11-testing.md`, TASK-3 domain 검수)
- [2026-05-08] `StrEnum`, `datetime.UTC`는 Python 3.11+ API이다 — `pyproject.toml requires-python >=3.12`이지만 환경에 Python 3.12가 없으면 3.10/3.11로 실행된다. CI 및 로컬 개발 환경에 Python 3.12를 명시적으로 pinning해야 한다. `py -3.12` 또는 가상환경 기반 `.python-version` 파일로 강제. (TASK-3 domain 검수 — `StrEnum` import error on 3.10)
- [2026-05-08] `.importlinter`에 `unmatched_ignore_imports_alerting = none` 필수: import-linter 2.x는 `ignore_imports` 패턴이 실제 import와 매칭되지 않으면 기본적으로 ERROR를 발생시킨다. 빈 부트스트랩 단계에서 wildcard 패턴(`** -> app.platform` 등)이 오류를 일으키므로 contract 섹션에 `unmatched_ignore_imports_alerting = none`을 추가해야 한다. (`@docs/12-coding-conventions.md §3.2`, import-linter 2.11 LayersContract 소스)
- [2026-05-08] `lint-imports` 및 `pytest` 실행 시 `PYTHONPATH=src` 환경변수 필수: src layout 채택 프로젝트에서 import-linter 2.11은 패키지 루트를 `src/`로 인식하지 못하므로 `PYTHONPATH=src lint-imports`로 실행해야 한다. Makefile 및 CI 파이프라인에 동일 환경변수를 명시해야 한다. (TASK-1 부트스트랩 재검수, B 보고)
- [2026-05-08] `pyproject.toml`의 ruff ruleset은 `docs/12-coding-conventions.md §2`와 정확히 일치해야 한다: 문서 명세(`E, F, W, I, N, UP, B, S, C4, ASYNC, SIM, ARG`)와 실제 설정(`E, F, I, B, UP, SIM, RUF`)이 불일치할 경우 FAIL. (`@docs/12-coding-conventions.md §2`)
- [2026-05-08] `pyproject.toml`의 `requires-python`은 `docs/12-coding-conventions.md §1`의 `>=3.12,<3.14` 형식으로 상한 핀 포함 필수: 상한 없이 `>=3.12`만 명시하면 문서와 불일치. (`@docs/12-coding-conventions.md §1`)
- [2026-05-08] CLAUDE.md의 레이어 참조 경로는 실제 코드 경로와 일치해야 한다: `src layout` 채택 시 `app/CLAUDE.md`(구 경로)가 아닌 `src/app/`을 기준으로 CLAUDE.md 및 work_rule.md가 위치해야 한다. (`@docs/12-coding-conventions.md §3.1`)
- [2026-05-08] Fake adapter의 cross-tenant 차단은 Protocol 수준 단위 테스트로 검증해야 한다: Pinecone/S3는 테넌트 prefix·metadata 비교 전에 전체 batch 검증 후 first mismatch에서 abort해야 하며 (`fail-fast, all-or-nothing` 패턴), 하나라도 실패하면 정상 레코드도 저장하지 않아야 한다. (`@docs/07-multitenancy-and-access.md §2.2`, TASK-5 QA 검수)
- [2026-05-08] FakeEmbeddings NaN 회피 패턴: `struct.unpack`으로 임의 바이너리를 IEEE 754 float으로 해석하면 NaN/Inf가 발생한다. 대신 각 바이트를 정수로 읽어 `[0,255]` → `[-0.5, 0.5]` 스케일 후 L2 정규화하는 패턴이 안전하다. 동일 패턴을 모든 결정론적 임베딩 생성 코드에 적용. (`@docs/03-document-pipeline.md §3.5`, TASK-5 QA 검수)
- [2026-05-08] Redis fake에서 key format validation은 큐잉(pipeline.set/delete/incr)과 실행(execute) 사이가 아닌 큐잉 시점에 즉시 검증해야 한다: 잘못된 키가 execute 이후 무결성을 오염시키지 않도록 early-fail 필수. (`@docs/04-data-stores.md §4.1`, TASK-5 QA 검수)

## 금지 규칙

- [2026-05-08] ruff 검사 대상에 `.claude/scripts/`를 포함하는 전역 `ruff check .` 실행 금지: hook 스크립트는 한국어 주석 등으로 line-length 초과가 구조적으로 발생한다. `ruff check src/ tests/`로 범위를 한정해야 한다.
- [2026-05-08] `request_id` 서버 자체 생성 시 `uuid.uuid4()` 사용 금지: `@docs/06-api.md §1.3` 및 `@docs/13-glossary.md`에서 `request_id`는 uuid7로 명시한다. `python-uuid7` 또는 `uuid6` 패키지의 `uuid7()` 사용 필수.
- [2026-05-08] 타입 스텁 미제공 순수 Python 패키지(`uuid_extensions` 등) import 시 `# type: ignore[import-untyped]`를 해당 import 줄 한 줄에만 인라인 적용 필수: mypy `--strict`는 타입 스텁 없는 패키지를 기본 차단한다. `mypy.ini`나 `pyproject.toml`의 `[[tool.mypy.overrides]]` 전역 suppress보다 인라인 주석이 영향 범위를 최소화한다. 동일 패턴: `from uuid_extensions import uuid7  # type: ignore[import-untyped]`. (TASK-2 재검수 ADR-0007 패턴 확인)
- [2026-05-08] 파일 docstring 직후 `from __future__ import annotations` 앞에 빈 줄 삽입 필수: ruff formatter(PEP 257 스타일)가 module docstring 끝 `"""` 다음 줄 바로 `from __future__`가 오면 빈 줄을 삽입하도록 강제한다. B가 새 파일 작성 시 미리 빈 줄을 추가해야 `ruff format --check` 통과. (TASK-2 검수 발견)
- [2026-05-08] structlog processor protocol-required-but-unused 인자 처리 표준: `_ = (logger, method)` 패턴을 `# structlog processor protocol — params are required` 주석과 함께 사용한다. ARG001(unused-argument)을 noqa 없이 해소하면서 의도를 명시. 동일 패턴: protocol 인자가 있지만 현재 구현에서 미사용인 다른 processor 함수에도 적용. (`src/app/platform/logging.py` `_redact_pii`, TASK-2 위생 항목 검수)

## 변경 이력

| 일자 | 추가/수정 | 사유 | 담당 |
|---|---|---|---|
| 2026-05-07 | 초기 생성 | 하네스 셋업 | (system) |
| 2026-05-08 | 규칙 4건 추가 (import-linter wildcard, ruff ruleset, requires-python 상한, src layout 경로), 금지 1건 추가 | TASK-1 부트스트랩 검수 | C |
| 2026-05-08 | 규칙 1건 추가 (PYTHONPATH=src 환경변수 필수) | TASK-1 부트스트랩 재검수 — B 추가 발견 | C |
| 2026-05-08 | 금지 2건 추가 (uuid4 사용 금지, docstring 후 빈 줄 누락 금지) | TASK-2 FastAPI 앱 검수 발견 | C |
| 2026-05-08 | 금지 1건 추가 (import-untyped 인라인 적용 패턴) | TASK-2 재검수 ADR-0007 uuid_extensions 패턴 확인 | C |
| 2026-05-08 | 일반 규칙 1건 추가 (structlog protocol-required-but-unused 인자 처리 패턴), docs 정합성 관찰 1건 기록 (NOT_FOUND vs NO_RESULTS) | TASK-2 위생 항목 검수 (C 2/3) | C |
| 2026-05-08 | 일반 규칙 2건 추가 (coverage 범위 한정, Python 3.12 필수 API 사용 시 CI 환경 명시) | TASK-3 도메인 모델 검수 | C |
| 2026-05-08 | 구조 검수: src/app/...로 이동 PASS. TASK-4 infra Protocol 검수 PASS (41 tests, mypy strict 0 errors, ruff PASS, interrogate 98.2%) — vulture Protocol 스텁 오탐 패턴 기록, pyproject.toml [tool.vulture] 억제 필요 | TASK-4 infra protocol 검수 | C |
| 2026-05-08 | TASK-5 in-memory fake infra + cross-tenant 차단 검수 PASS (287 tests passed, cov 98.66%, ruff PASS, mypy strict PASS, import-linter 1 kept 0 broken, vulture 0건) | TASK-5 fake adapters 검수 | C |

## 자동 활동 로그 (hooks 자동 갱신)


| 일자 | 작업 요약 | 변경 파일 | 비고 |
|---|---|---|---|
| 2026-05-08 | (자동 갱신) | — | hook |
| 2026-05-08 | @docs\ 안에 기획을 변경해야 해. Nest.JS + NestJS 구성이었는데, Next.JS + Supabase 구성으로 변경했어. @do | CLAUDE.md, README.md, .env.example, 00-scope.md, 01-architecture.md | hook |
| 2026-05-08 | @docs\ 안에 기획을 변경해야 해. Nest.JS + NestJS 구성이었는데, Next.JS + Supabase 구성으로 변경했어. @do | CLAUDE.md, README.md, .env.example, 00-scope.md, 01-architecture.md | hook |
| 2026-05-08 | @docs\ 안에 기획을 변경해야 해. Nest.JS + NestJS 구성이었는데, Next.JS + Supabase 구성으로 변경했어. @do | CLAUDE.md, README.md, .env.example, 00-scope.md, 01-architecture.md | hook |
| 2026-05-08 | @docs\ 안에 기획을 변경해야 해. Nest.JS + NestJS 구성이었는데, Next.JS + Supabase 구성으로 변경했어. @do | CLAUDE.md, README.md, .env.example, 00-scope.md, 01-architecture.md | hook |
| 2026-05-08 | @docs\ 안에 기획을 변경해야 해. Nest.JS + NestJS 구성이었는데, Next.JS + Supabase 구성으로 변경했어. @do | CLAUDE.md, README.md, .env.example, 00-scope.md, 01-architecture.md | hook |
| 2026-05-08 | @docs\ 안에 기획을 변경해야 해. Nest.JS + NestJS 구성이었는데, Next.JS + Supabase 구성으로 변경했어. @do | CLAUDE.md, README.md, .env.example, 00-scope.md, 01-architecture.md | hook |
| 2026-05-08 | # /harness — 멀티 에이전트 코드 생성  ## 사용법  ``` /harness POST /internal/query SSE endpoi | — | hook |
| 2026-05-08 | # /harness — 멀티 에이전트 코드 생성  ## 사용법  ``` /harness POST /internal/query SSE endpoi | — | hook |
