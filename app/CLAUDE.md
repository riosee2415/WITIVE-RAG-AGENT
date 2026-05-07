# app — 6 레이어 의존 방향

`@docs/01-architecture.md` §3 의존 방향이 코드 레벨에서 강제됨.

## 6 레이어

| 레이어 | 책임 | 외부 라이브러리 |
|---|---|---|
| `api/` | FastAPI router (HTTP/SSE) | FastAPI, sse-starlette |
| `domain/` | 도메인 모델·값 객체 | **stdlib only** |
| `pipeline/` | 유즈케이스 (도메인 + infra 조합) | (조합만) |
| `infra/` | 외부 의존성 어댑터 | aioboto3, pinecone, neo4j, redis |
| `platform/` | 횡단 관심사 | structlog, pydantic-settings |
| `workers/` | SQS 소비자 entry point | (조합) |

## 의존 방향 (CI 자동 검증 — `import-linter` 또는 `tach`)

```
api ──→ pipeline ──→ infra
              ↓
            domain ←── infra
```

규칙:
- `domain`은 어디에도 의존 X (외부 라이브러리도)
- `pipeline`은 `domain`+`infra` 조합. `api` import X
- `api`는 `pipeline`+`platform`만. `infra` 직접 import X
- `infra`끼리 직접 import X (조합은 `pipeline`)
- `platform`은 누구나 사용 가능

위반 시 PostToolUse hook이 차단.

## src layout

```
src/app/
├── api/
├── domain/
├── pipeline/
├── infra/
├── platform/
└── workers/
```

`pyproject.toml` 의 `[tool.setuptools.packages.find]` 또는 `uv` workspace 설정으로 src layout 명시.

## 디렉토리별 세부

각 sub 디렉토리에 `CLAUDE.md` + `work_rule.md` 별도. 작업 시 가장 가까운 것 자동 로드.

## 참조

- `@docs/01-architecture.md` — 모듈 구성
- `@docs/12-coding-conventions.md` — 의존 방향 강제·async 규칙
- `@CLAUDE.md` — 절대 규칙

## work_rule

@work_rule.md
