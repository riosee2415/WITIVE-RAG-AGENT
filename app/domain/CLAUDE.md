# app/domain — 도메인 모델

## 책임

- 도메인 모델·값 객체·enum (`TenantContext`, `Chunk`, `Question`, `RagError`, `ErrorCode`, ...)
- 외부 의존성 0 — stdlib만 import 허용 (PostToolUse hook이 차단)
- `frozen=True` immutable dataclass 또는 검증 필요 시 pydantic

## 금지 (절대)

- `boto3`, `pinecone`, `neo4j`, `redis`, `httpx`, `fastapi` 등 외부 라이브러리 import
- `app.api`, `app.pipeline`, `app.infra` 어떤 모듈도 import
- I/O (파일·네트워크·DB)

## 표준 패턴

```python
# domain/tenant_context.py
from dataclasses import dataclass
from uuid import UUID
from datetime import date

@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user_id: UUID
    role: "Role"
    departments: tuple[str, ...]
    level: "Level | None"
    hire_date: date | None
    request_id: str

    @property
    def is_system_cron(self) -> bool:
        return str(self.user_id) == "00000000-0000-0000-0000-000000000001"
```

## 파일 분리

| 파일 | 책임 |
|---|---|
| `tenant_context.py` | `TenantContext`, `Role`, `Level`, `AccessLevel` |
| `question.py` | `Question`, `RewrittenQuestion` |
| `chunk.py` | `Chunk`, `ChunkMetadata`, `Source` |
| `document.py` | `Document`, `Version` |
| `errors.py` | `RagError`, `ErrorCode` (StrEnum) |
| `events.py` | SSE 이벤트 도메인 객체 (`SseEvent`, `SourceEvent`, ...) |

## 참조

- `@docs/07-multitenancy-and-access.md` §1 — `TenantContext` 정의
- `@docs/12-coding-conventions.md` §5·§7 — 에러 모델·타입 힌트

## work_rule

@work_rule.md
