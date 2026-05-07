# app/api — FastAPI router

## 책임

- HTTP/SSE endpoint 정의 (`@docs/06-api.md` 단일 진실 출처)
- request 검증 (pydantic models)
- error → HTTP/SSE 매핑 (`RagError` → 응답)
- 미들웨어 (인증, request_id, structlog contextvars)

## 금지 (PostToolUse hook이 차단)

- `app/infra/` 직접 import — 반드시 `app/pipeline/`을 거쳐
- 도메인 로직 (단순 변환만, 비즈니스 규칙은 `app/pipeline/`)
- `boto3`/`pinecone`/`neo4j`/`redis` 직접 호출
- raw `HTTPException(500)` 사용 — `RagError` 도메인 클래스 사용

## 표준 패턴 (예시)

```python
from sse_starlette.sse import EventSourceResponse
from app.pipeline.query.orchestrator import handle_query
from app.platform.auth import require_tenant_context

@router.post("/internal/query")
async def query(req: QueryRequest, ctx = Depends(require_tenant_context)):
    return EventSourceResponse(handle_query(ctx, req), ping_interval=15)
```

## 파일 분리

| 파일 | endpoint |
|---|---|
| `query.py` | POST /internal/query (SSE) |
| `documents.py` | upload + jobs |
| `admin.py` | cleanup, reindex, cache/invalidate |
| `health.py` | GET /internal/health |
| `_middleware.py` | 인증·context·request_id |
| `_error_handlers.py` | `RagError` → HTTP/SSE |

## 참조

- `@docs/06-api.md` — endpoint 명세 + retryable 매핑 + payload schema
- `@docs/02-query-pipeline.md` §6 — SSE 이벤트 시퀀스
- `@docs/12-coding-conventions.md` §5 — `RagError` 모델
- `@docs/operations/adr/0005-sse-starlette-not-fastapi-native.md`

## work_rule

@work_rule.md
