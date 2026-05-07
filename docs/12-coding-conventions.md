# 12 — Coding Conventions

본 서버 코드의 스타일·구조·async·에러·로깅 규칙. 하네스가 코드 작성 시 일관성 있게 따라가도록.
다른 docs(01·09·11)와 cross-link.

## 1. Python 환경

| 항목 | 값 |
|---|---|
| Python 버전 | 3.12+ (`pyproject.toml`에 `>=3.12,<3.14` 핀) |
| 패키지 매니저 | `uv` (lock 파일 `uv.lock` 커밋) |
| 프로젝트 형식 | `src layout` (`src/app/...`) |
| 가상환경 | `uv venv` (CI 동일) |

## 2. Linting / Formatting / Type checking

| 도구 | 설정 |
|---|---|
| `ruff` | linter + formatter 통합. line length 100. `pyproject.toml`에 ruleset 명시 |
| `mypy --strict` | 모든 함수에 타입 힌트 의무. `Any` 사용은 보고 + 리뷰 사유 필요 |
| `pre-commit` | ruff + mypy + bandit + pip-audit 모두 자동 |

`pyproject.toml` 예시:
```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "S", "C4", "ASYNC", "SIM", "ARG"]
ignore = ["E501"]  # ruff format이 처리

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
disallow_any_generics = true
plugins = ["pydantic.mypy"]
```

## 3. 모듈 구조와 의존 방향 (강제)

`01-architecture.md` §3 6계층 (`api / domain / pipeline / infra / platform / workers`)을 코드로 강제한다.

### 3.1 디렉토리

```
src/app/
├── api/             # FastAPI router
├── domain/          # 도메인 모델·값 객체 (외부 라이브러리 의존 0)
├── pipeline/        # 유즈케이스 (도메인 + infra adapter 조합)
├── infra/           # 외부 의존성 어댑터
├── platform/        # 횡단 관심사 (config, logging, tracing, retry, auth, metrics)
└── workers/         # SQS 소비자 entry point
```

### 3.2 의존 방향 강제

```
api ──→ pipeline ──→ infra
              ↓
            domain ←── infra
```

규칙:

- `domain`은 **stdlib만** import 허용. 외부 라이브러리·다른 app 모듈 import 금지
- `pipeline`은 `domain`·`infra` import 가능. `api` import 금지
- `api`는 `pipeline`·`platform` import 가능. `infra` 직접 import 금지
- `infra`끼리 직접 import 금지 (필요 시 `pipeline`에서 조합)
- `platform`은 누구나 사용 가능

CI에 `import-linter` 또는 `tach` 같은 도구로 의존 방향 자동 검증.

### 3.3 모듈 안 파일 분리

| 모듈 | 파일 분리 기준 |
|---|---|
| `api/` | endpoint별 1파일 (query.py, documents.py, admin.py, health.py) |
| `domain/` | 도메인 개념별 1파일 (tenant_context.py, chunk.py, errors.py) |
| `pipeline/query/` | 단계별 1파일 (stage1_rewriter.py, stage2_retrieve.py, ...) |
| `infra/<dependency>/` | 모듈 디렉토리. 내부에 client.py + 책임별 파일 |

함수 1개당 ~50줄 안. 초과 시 분리 검토.

## 4. async 규칙

### 4.1 핵심 원칙

- 모든 I/O는 async. 동기 I/O 금지 (`requests`, `boto3` 직접, blocking redis 등)
- CPU 바인드는 `asyncio.to_thread` 또는 별도 thread pool로 격리
- 동기 함수에서 async 호출은 `asyncio.run()` 금지 (Worker entry point만 예외)

### 4.2 패턴

```python
# ✅ 올바른 병렬
pinecone_hits, neo4j_hits = await asyncio.gather(
    pinecone.query(ctx, embedding),
    neo4j.search(ctx, keywords),
    return_exceptions=True,
)

# ✅ CPU 바인드 격리
reranked = await asyncio.to_thread(cross_encoder.rerank, query, chunks)

# ❌ 잘못 — async 함수 안에서 동기 I/O
def get_secret_sync():
    return boto3.client("secretsmanager").get_secret_value(...)["SecretString"]

async def handler():
    return get_secret_sync()  # event loop 블록!

# ✅ 올바른 — async 클라이언트
async def handler():
    async with session.client("secretsmanager") as sm:
        return (await sm.get_secret_value(...))["SecretString"]
```

### 4.3 cancellation

`asyncio.CancelledError`는 **잡고 swallow 금지**. 항상 re-raise.

```python
# ✅ 올바른 cleanup
try:
    async for token in bedrock.stream(...):
        yield token
except asyncio.CancelledError:
    await bedrock_client.close()
    raise   # 반드시 re-raise
```

`05 §3.1` Bedrock stream close 패턴 동일.

### 4.4 timeout

`asyncio.wait_for` 또는 `asyncio.timeout` (3.11+) 사용. 직접 sleep+race 패턴 금지.

```python
async with asyncio.timeout(STAGE1_TIMEOUT_S):
    return await bedrock.invoke(...)
```

## 5. 에러 모델

### 5.1 도메인 에러 클래스

```python
# domain/errors.py
@dataclass(frozen=True)
class RagError(Exception):
    code: ErrorCode
    message: str
    retryable: bool = False
    retry_after_ms: int | None = None
    fallback_used: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

class ErrorCode(StrEnum):
    QUESTION_EMPTY = "QUESTION_EMPTY"
    QUESTION_NO_CONTENT = "QUESTION_NO_CONTENT"
    NO_RESULTS = "NO_RESULTS"
    NO_ACCESSIBLE_RESULTS = "NO_ACCESSIBLE_RESULTS"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    SERVICE_DEGRADED = "SERVICE_DEGRADED"
    BEDROCK_UPSTREAM_ERROR = "BEDROCK_UPSTREAM_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_SYSTEM_CONTEXT = "INVALID_SYSTEM_CONTEXT"
    TENANT_CONTEXT_INVALID = "TENANT_CONTEXT_INVALID"
    BACKPRESSURE = "BACKPRESSURE"
    DUPLICATE_FILE = "DUPLICATE_FILE"
    DUPLICATE_VERSION = "DUPLICATE_VERSION"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"
```

### 5.2 HTTP/SSE 매핑

`api/` 레이어에서 `RagError` → HTTP/SSE 변환. 직접 `HTTPException` 던지기는 검증 단계만 (예: pydantic validation).

```python
# api/_error_handlers.py
@app.exception_handler(RagError)
async def handle_rag_error(req, exc: RagError):
    status = ERROR_CODE_TO_HTTP[exc.code]
    return JSONResponse(
        status_code=status,
        content={
            "data": None,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "retry_after_ms": exc.retry_after_ms,
            },
            "meta": {"request_id": req.state.request_id},
        },
    )
```

### 5.3 외부 SDK 에러 → 도메인 에러 변환

`infra/` 어댑터가 외부 SDK 에러를 잡아 `RagError`로 변환. `pipeline`·`api`는 외부 SDK 에러 타입을 모름.

```python
# infra/bedrock/claude.py
try:
    response = await client.converse_stream(...)
except botocore.exceptions.ClientError as e:
    code = e.response.get("Error", {}).get("Code", "")
    if code == "ThrottlingException":
        raise RagError(ErrorCode.BACKPRESSURE, "...", retryable=True, retry_after_ms=1000)
    raise RagError(ErrorCode.BEDROCK_UPSTREAM_ERROR, str(e), retryable=True)
```

## 6. 로깅 (structlog)

### 6.1 표준 사용

`09 §1.6` event 코드 enum 사용. free-form 문자열 금지.

```python
# platform/logging.py
class LogEvent(StrEnum):
    QUERY_RECEIVED = "query.received"
    QUERY_CACHE_HIT = "query.cache.hit"
    QUERY_STAGE1_COMPLETED = "query.stage1.completed"
    QUERY_STAGE1_FALLBACK = "query.stage1.fallback"
    # ...

# 사용
logger.info(
    LogEvent.QUERY_STAGE1_COMPLETED,
    duration_ms=duration,
    fallback_used=False,
)
```

### 6.2 PII 정책 (09 §1.3)

| 입력 | 로그 |
|---|---|
| `question` | `question_hash=sha256(text)`만 |
| 답변 본문 | `output_tokens=N`만 |
| `user_id` (uuid) | OK |

`structlog` processor에 PII filter 강제. 도메인 모델에 `__str__`/`__repr__` override해서 민감 필드 마스킹.

### 6.3 컨텍스트 자동 주입

`request_id`·`tenant_id`·`user_id`는 미들웨어에서 `structlog.contextvars`에 박아 모든 로그에 자동 포함.

```python
# api/_middleware.py
async def context_middleware(request, call_next):
    structlog.contextvars.bind_contextvars(
        request_id=request.state.request_id,
        tenant_id=request.state.ctx.tenant_id,
        user_id=request.state.ctx.user_id,
    )
    try:
        return await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
```

## 7. 타입 힌트 규칙

### 7.1 도메인 모델은 frozen dataclass 또는 pydantic

```python
@dataclass(frozen=True)
class Chunk:
    chunk_id: UUID
    text: str
    section: str | None
    page: int | None
    chunk_index: int

# 또는 pydantic (검증 필요한 외부 입력)
class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None
    version_filter: str | None = None
```

### 7.2 Protocol로 인터페이스 정의

`infra/` 어댑터 인터페이스는 Protocol — 테스트의 fake 구현을 명시적 상속 없이 substitution.

```python
class PineconeAdapter(Protocol):
    async def query(self, ctx: TenantContext, vector: list[float], **kw) -> list[Chunk]: ...
    async def upsert(self, ctx: TenantContext, vectors: list[Vector]) -> None: ...
```

### 7.3 enum 우선

문자열 상수 대신 `StrEnum` (Python 3.11+).

```python
class AccessLevel(StrEnum):
    COMPANY_WIDE = "COMPANY_WIDE"
    DEPARTMENT = "DEPARTMENT"
    LEVEL = "LEVEL"
    EXECUTIVE = "EXECUTIVE"
```

### 7.4 Optional 표기

`Optional[X]` 대신 `X | None` (3.10+).

## 8. 테스트 컨벤션 (11 cross-ref)

### 8.1 fixture 위치

```
tests/
├── conftest.py             # 공통 fixture (settings, logger, fake adapter factory)
├── unit/                   # 단위 테스트
├── integration/            # 통합 테스트 (testcontainers)
├── rag_eval/               # RAG 평가 (§4)
├── load/                   # k6 스크립트
└── security/               # 보안 시나리오
```

### 8.2 테스트 명명

```python
def test_<주체>_<상황>_<기대결과>():
    # ex: test_query_pipeline_pinecone_failure_falls_back_to_neo4j
```

### 8.3 fixture 패턴

```python
@pytest.fixture
def fake_pinecone():
    return FakePineconeAdapter()

@pytest.fixture
def ctx_user():
    return build_test_context(role="COMPANY_USER")

@pytest.fixture
def ctx_executive():
    return build_test_context(role="COMPANY_USER", user_id="...")
```

`build_test_context` 같은 helper는 `tests/_factories.py`에.

## 9. Git / PR 컨벤션

### 9.1 브랜치

- `main` (배포용)
- `feat/<short-desc>`, `fix/<short-desc>`, `chore/<short-desc>`

### 9.2 커밋 메시지

Conventional Commits:
```
feat(pipeline): add EXECUTIVE post-filter to query orchestrator

- 06-api.md sources EXECUTIVE 청크 누수 방어
- access_sig는 user_id 미포함, 응답 직전 폐기
```

### 9.3 PR 템플릿

```
## What
- 한 줄 요약

## Why  
- 문제·동기

## How
- 구현 요약

## docs 갱신
- [ ] 02 / 03 / ... 의 어느 절을 갱신했는지 명시
- [ ] 또는 docs 갱신 불필요 사유

## Test
- [ ] 단위
- [ ] 통합
- [ ] (필요 시) RAG 평가 골든셋

## Cost / Resilience 영향
- (필요 시) 새 fallback 경로, 비용 함정 분석
```

**docs 갱신 필수**: 코드 변경이 docs와 어긋나면 PR 거부. 본 서버는 docs-first.

## 10. 변경 시 영향 범위

- 새 도메인 개념 → `domain/` 새 파일 + `13-glossary.md` 갱신
- 새 외부 의존성 → `infra/<name>/` + `01 §2` 의존성 매트릭스 + `08 §2` fallback + `10 §2` 환경 변수
- 새 에러 코드 → `domain/errors.py` ErrorCode + `06 §1.4` HTTP 매핑 + `02 §8` 매트릭스
- 새 log event → `platform/logging.py` LogEvent + `09 §1.6` 카탈로그
- 의존 방향 위반 → CI 자동 차단
