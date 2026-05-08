# 06 — API Contract

본 서버가 노출하는 HTTP/SSE 엔드포인트의 단일 진실 출처. Next.js↔FastAPI 사이 contract.
다른 docs(`02-query-pipeline.md` 등)에 임시로 적힌 SSE schema와 충돌하면 본 문서가 우선.

## 1. 공통 사항

### 1.1 Base URL과 prefix

```
http://<vpc-internal>/internal/...
```

모든 endpoint는 `/internal/` prefix. ALB·SG에서 외부 접근 차단을 전제 (`00-scope.md` §1).
versioning은 path prefix(`/internal/v1/...` 등)를 도입하지 않는다 — 본 서버는 Next.js와 1:1 internal contract라 Next.js 배포와 동시에 갱신. 외부 공개 API는 Next.js가 별도로 versioning한다.

### 1.2 인증 헤더

`00-scope.md` §3.2 / §3.2.시스템 호출 reserved 컨텍스트 준수.

| 헤더 | 누락 시 |
|---|---|
| `X-Internal-Auth` | 401 `UNAUTHORIZED` |
| `X-Tenant-Id`, `X-User-Id`, `X-Role` | 500 `TENANT_CONTEXT_INVALID` (Next.js contract 위반은 internal 에러 취급) |
| 시스템 호출(cleanup 등)에서 reserved UUID·`SYSTEM_CRON` 미사용 | 403 `INVALID_SYSTEM_CONTEXT` |

### 1.3 응답 공통 형식 (HTTP/JSON)

```json
{
  "data": { ... },
  "error": null,
  "meta": { "request_id": "...", "epoch": 42 }
}
```

에러:

```json
{
  "data": null,
  "error": { "code": "...", "message": "...", "retryable": true, "retry_after_ms": 1500 },
  "meta": { "request_id": "...", "epoch": 42 }
}
```

`request_id`: `X-Request-Id` 헤더 echo. 없으면 본 서버 생성 (uuid7).

### 1.4 에러 코드 + retryable 매핑

| HTTP | code | retryable | 발생 |
|---|---|---|---|
| 400 | `QUESTION_EMPTY` / `QUESTION_NO_CONTENT` / `INVALID_REQUEST` | false | 입력 검증 실패 |
| 401 | `UNAUTHORIZED` | false | `X-Internal-Auth` 검증 실패 |
| 403 | `FORBIDDEN` / `INVALID_SYSTEM_CONTEXT` | false | role 부족, 시스템 호출 컨텍스트 위반 |
| 404 | `NOT_FOUND` | false | 존재하지 않는 job_id 등 |
| 409 | `DUPLICATE_FILE` / `DUPLICATE_VERSION` | false | 동일 SHA-256 (DUPLICATE_FILE) 또는 동일 (doc_id, version) (DUPLICATE_VERSION) |
| 413 | `PAYLOAD_TOO_LARGE` | false | 파일 > 100MB |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | false | MIME 화이트리스트 외 |
| 429 | `BACKPRESSURE` | true | 본 서버 글로벌 token bucket 한도 / 동시 SSE 상한 / cache_invalidate rate 초과 (`X-Backpressure-Reason` 헤더로 구분) → `Retry-After` 헤더 포함 |
| 500 | `TENANT_CONTEXT_INVALID` / `INTERNAL_ERROR` | false | Next.js contract 위반 또는 본 서버 결함 |
| 502 | `BEDROCK_UPSTREAM_ERROR` | true | Bedrock 5xx 또는 시간 초과 (HTTP 응답 시. SSE 도중 발생 시 §3.1 SSE error 이벤트로) |
| 503 | `SERVICE_UNAVAILABLE` | true | Pinecone+Neo4j 동시 장애, 서킷 오픈, MAINTENANCE_MODE (`08-resilience.md`) |

**SSE 도중 Bedrock 장애 처리** (HTTP는 200으로 시작되어 도중 status 변경 불가):
- 검색 결과 원문이 있으면: `warnings: GENERATION_DEGRADED` + token 대신 원문 chunk 발행 + `done(meta.fallback_used=["bedrock_stage2_failed"])` (정상 종료)
- 그조차 불가하면: `error` 이벤트 (`code: BEDROCK_UPSTREAM_ERROR`, `retryable: true`, `retry_after_ms: 5000`) 후 SSE 종료. 클라이언트는 새 query로 재시도

`retryable=true`이면 `Retry-After` 헤더(초) 또는 응답 body의 `error.retry_after_ms`로 재시도 시간 제안.

### 1.5 Rate limit 응답 (429)

본 서버는 **글로벌 Bedrock token bucket 한도**(`05 §5.2`)로 429를 발행. 사용자별 rate limit는 Next.js 책임이지만, 본 서버는 비정상 부하 감지 시 `429` + `Retry-After`로 보호. 헤더:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 2
X-Backpressure-Reason: bedrock_titan_global_bucket
```

### 1.6 압축

- 응답 body가 1KB 이상이면 gzip 적용 (FastAPI `GZipMiddleware`, `minimum_size=1024`)
- SSE는 압축 안 함 (이벤트별 chunk가 작고 streaming의 즉시성 우선)

### 1.7 동시 SSE connection 상한 (자원·비용 보호) — H-2

ECS Task당 동시 SSE connection 상한을 환경 변수로 강제. 초과 시 `429 BACKPRESSURE`.

| 환경 변수 | 기본값 | 비고 |
|---|---|---|
| `MAX_CONCURRENT_SSE_CONNECTIONS` | 200 (Task당) | Stage 2 워스트 30s timeout 동안 200 conn × ~1MB context ≈ 200MB. ECS Task 메모리(prod 2048MB) 안전 마진. **카운트 범위**: 모든 SSE endpoint (현재는 `/internal/query`만, 향후 추가 시 동일 카운터 공유) |

상한 도달 시 응답:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 5
X-Backpressure-Reason: max_concurrent_sse
```

**Auto Scaling 상호작용**: ECS Auto Scaling 스케일 아웃 쿨다운 60s. 동시 connection 상한이 메모리 임계 알람보다 빠른 1차 방어선 — Auto Scaling이 따라오기 전 OOM 회피. 상한 도달 빈도가 잦으면 (`backpressure_triggered_total{reason="max_concurrent_sse"} > 10/min` for 10min) Auto Scaling 임계 또는 Task당 상한 자체를 운영팀이 조정.

---

## 2. 엔드포인트 목록

| Method | Path | 인증 | 책임 |
|---|---|---|---|
| POST | `/internal/query` | 일반 (X-User-Id) | 질의 → SSE 답변 |
| POST | `/internal/documents/upload` | role ∈ {ADMIN, MANAGER} | 문서 업로드 |
| GET | `/internal/documents/jobs/{job_id}` | 일반 | 파이프라인 작업 상태 |
| POST | `/internal/admin/cleanup/orphan-staging` | role=SUPER_ADMIN + `SYSTEM_CRON` user_id 허용 | orphan staging 청소 |
| POST | `/internal/admin/reindex` (Phase 2+) | role=SUPER_ADMIN | 테넌트 재색인 트리거 |
| POST | `/internal/cache/invalidate` | role ∈ {SUPER_ADMIN, ADMIN} (Next.js 호출) | tenant epoch INCR |
| GET | `/internal/health` | 인증 면제 | 서비스 헬스 |

---

## 3. 질의 API

### 3.1 POST /internal/query

```http
POST /internal/query
Accept: text/event-stream
Content-Type: application/json
X-Internal-Auth: ...
X-Tenant-Id: ...
X-User-Id: ...
X-Role: COMPANY_USER
X-Department: 인사팀
X-Level: 사원
X-Hire-Date: 2024-03-01
X-Request-Id: req-uuid

{
  "question": "연차휴가는 며칠인가요?",
  "conversation_id": "conv-uuid",        // optional, 본 서버는 로깅·추적 컨텍스트로만 사용 (아래 노트)
  "version_filter": "2024"               // optional, "v2.1" 또는 "2024" 형식
}
```

**`conversation_id` 처리**: 본 서버는 현재 `conversation_id`를 **로깅·추적 컨텍스트로만** 사용한다 (request_id와 동급 추적 키). 답변 생성에 대화 이력은 반영하지 않는다 (Stateless single-turn). 다중 턴 대화 컨텍스트 도입은 ROADMAP §Phase 3+ Stage 1 ContextPlugin 확장으로 별도 결정.

**`conversation_id` 검증·PII 정책**: uuid7 형식만 허용 (정규식 검증). 비-uuid 형식·과도한 길이는 400 `INVALID_REQUEST`로 거부 — Next.js 측 누수로 conversation 텍스트가 들어와 PII 로그에 박히는 것을 방지. PII 분류는 `09-observability.md` §1.3 참조 (uuid는 PII 아님으로 분류).

응답: `text/event-stream` (`sse-starlette`의 `EventSourceResponse`).

#### SSE 구현 contract

본 서버는 [`sse-starlette`](https://pypi.org/project/sse-starlette/)의 `EventSourceResponse` (`from sse_starlette.sse import EventSourceResponse`)를 사용한다. **`fastapi.sse` 모듈은 FastAPI 공식 패키지에 없음** — `sse-starlette`은 FastAPI 생태계의 사실상 표준 SSE 라이브러리. `sse-starlette`이 자동 처리:

- **15초 간격 keep-alive ping** (HTML5 SSE 표준 comment line, `EventSourceResponse(ping_interval=15)` 기본값). 별도 heartbeat task 발행 금지
- `Cache-Control: no-cache` 자동 설정
- `X-Accel-Buffering: no` 자동 설정 (Nginx 등 reverse proxy 버퍼링 차단)
- 클라이언트 reconnection 시 `Last-Event-ID` 헤더로 resumption (단, **본 서버는 query 결과를 resumable하게 저장하지 않음** — Last-Event-ID 헤더는 받지만 무시. 클라이언트는 reconnection 시 새 query로 요청해야 함. resumable이 필요해지면 별도 결정)

#### 이벤트 시퀀스 (정상 경로)

`02-query-pipeline.md` §6.1과 동일. 본 절은 형식 단일 진실 출처.

```
event: rewritten_query
data: {"content": "연차휴가 일수는?", "meta": {"fallback": false}}

event: sources
data: {"content": [{"chunk_id":"...", "doc_id":"...", "doc_name":"취업규칙", "version":"2.1", "is_current":true, "effective_date":"2024-01-01", "section":"3장 2조", "page":12, "excerpt":"...", "similarity_score":0.92}]}

event: warnings
data: {"content": [{"type":"OUTDATED_VERSION", "severity":"medium", "message":"v1.8 (2023년 기준)이 결과에 포함되었습니다.", "current_version":"2.1"}]}

event: token
data: {"content": "연차"}

event: token
data: {"content": "휴가는 1년 이상 ..."}

event: done
data: {"meta": {"latency_ms": 4250, "tokens_used": {"input": 1820, "output": 312, "cache_read": 1024}, "cache_hit": false, "fallback_used": [], "epoch": 42}}
```

#### Event field 명세 (각 event당 `data` 안의 JSON 객체)

| event type | required keys | optional keys |
|---|---|---|
| `rewritten_query` | `content: str`, `meta: { fallback: bool }` | — |
| `sources` | `content: [Source]` | — |
| `warnings` | `content: [Warning]` | — |
| `token` | `content: str` | — |
| `done` | `meta: DoneMeta` | — |
| `error` | `code: str`, `message: str`, `retryable: bool` | `retry_after_ms: int` |

#### Source 객체

```ts
{
  chunk_id: string,
  doc_id: string,
  doc_name: string,
  version: string,
  is_current: boolean,              // Pinecone 메타의 is_current를 1차 출처로 사용. PARTIAL_SUCCESS 상태(03 §3.6 Stage B step 3 실패)에서 Neo4j Version과 일시 불일치 시 Pinecone 우선 — sources 표시 일관성 유지
  effective_date: string,           // ISO date
  section: string | null,
  page: number | null,
  excerpt: string,                  // 청크 본문 앞 ~200자
  similarity_score: number,         // 0.0 ~ 1.0
  warning?: string                  // "현재 미적용 버전입니다" 등
}
```

#### Warning 객체

```ts
{
  type: "VERSION_CONFLICT" | "OUTDATED_VERSION" | "LOW_CONFIDENCE"
      | "RERANK_DEGRADED" | "PINECONE_DEGRADED" | "NEO4J_DEGRADED"
      | "GENERATION_DEGRADED" | "ANSWER_TRUNCATED" | "QUESTION_TRUNCATED"
      | "OCR_FALLBACK" | "OCR_LOW_CONFIDENCE",
  severity: "high" | "medium" | "low",
  message: string,
  // type별 추가 필드 (예: VERSION_CONFLICT는 conflicting_docs)
  ...
}
```

#### DoneMeta

```ts
{
  latency_ms: number,
  tokens_used: {
    input: number,        // Stage 1 + Stage 2 합산
    output: number,
    cache_read: number    // Bedrock prompt cache hit 토큰 수 (비용 절감 가시화)
  },
  cache_hit: boolean,     // Redis 쿼리 캐시 hit 여부
  fallback_used: string[],  // ["stage1_timeout", "rerank_degraded", ...]
  epoch: number
}
```

#### 에러 종료 케이스

```
event: error
data: {"code": "NO_RESULTS", "message": "관련 문서를 찾을 수 없습니다.", "retryable": false}
```

`error` 이벤트 후 SSE는 종료 (done 미발행). 단, **검색은 성공했으나 본문 fetch 1·2차 모두 실패** 케이스는 다르다 (`02 §5.6` SERVICE_DEGRADED): `error` 미발행, `sources` + `warnings:GENERATION_DEGRADED` + `done(meta.fallback_used=["chunk_text_fetch_failed"])`로 정상 종료.

### 3.2 POST /internal/cache/invalidate

Next.js가 사용자 권한 변경 또는 테넌트 메타 변경 시 호출.

```json
{
  "scope": "tenant_epoch" | "user" | "tenant_meta",
  "tenant_id": "...",        // tenant_epoch / tenant_meta 일 때
  "user_id": "..."           // user 일 때
}
```

응답:
```json
{ "data": { "invalidated": true, "new_epoch": 43 }, "meta": { ... } }
```

`scope=tenant_epoch`이면 `INCR epoch:{tenant_id}` (Stage B의 마지막 단계가 자동으로 호출하지만, Next.js가 명시적으로 호출 가능 — 어드민 강제 새로고침).

**Rate limit (M-4 Redis 보호)**: tenant_id 단위 분당 호출 상한 `CACHE_INVALIDATE_RATE_PER_MIN` (기본 60). 초과 시 `429 BACKPRESSURE` + `X-Backpressure-Reason: cache_invalidate` + `Retry-After: 60`. Next.js 버그·악성 호출로부터 ElastiCache CPU와 캐시 hit ratio를 보호 (무한 INCR → 모든 캐시 무효화 → Bedrock 비용 5배).

`new_epoch` 필드 사용처: Next.js가 epoch를 보유하면 다음 invalidate 호출 시 If-Match 조건부 처리 가능(현재 미구현). 현재는 Next.js가 받아서 무시해도 무방한 정보 필드.

---

## 4. 문서 파이프라인 API

### 4.1 POST /internal/documents/upload

```http
POST /internal/documents/upload
Content-Type: multipart/form-data
X-Internal-Auth: ...
X-Tenant-Id: ...
X-Role: COMPANY_ADMIN
```

multipart fields:

| field | 필수 | 설명 |
|---|---|---|
| `file` | ✅ | 파일 바이너리 |
| `doc_name` | ✅ | 1~256자 |
| `version` | ✅ | semver-like ("2.1"). **Next.js가 채번** — 같은 doc_id의 다음 version 결정 규칙은 Next.js 책임. 본 서버는 받은 그대로 저장 |
| `effective_date` | ✅ | ISO date. Next.js가 결정 |
| `access_level` | ✅ | `COMPANY_WIDE` / `DEPARTMENT` / `LEVEL` / `EXECUTIVE` |
| `allowed_departments[]` | conditional | `access_level=DEPARTMENT`일 때 필수 |
| `allowed_levels[]` | conditional | `access_level=LEVEL`일 때 필수 |
| `allowed_user_ids[]` | conditional | `access_level=EXECUTIVE`일 때 필수 |
| `overwrite_if_duplicate` | ❌ | bool, 기본 false. 동일 SHA-256 시 덮어쓰기 의사 |

**version·effective_date 채번 책임**: Next.js가 채번해 본 서버에 보낸다. 본 서버는 `(doc_id, version)` 조합 unique를 보장 — 동일 조합 재업로드는 `409 DUPLICATE_VERSION`. 같은 파일 SHA-256 재업로드(다른 version 시도)는 `409 DUPLICATE_FILE`과 별개. 같은 doc_id의 version 채번 규칙(예: semver 자동 증가, 사용자 입력)은 Next.js 책임.

응답 `202 Accepted`:
```json
{
  "data": {
    "job_id": "...",
    "doc_id": "...",
    "version": "2.1",
    "status": "QUEUED",
    "estimated_seconds": 30
  },
  "meta": { ... }
}
```

에러 매핑은 §1.4. URL/API 등록 endpoint는 Phase 2+에 명세.

### 4.2 GET /internal/documents/jobs/{job_id}

```json
{
  "data": {
    "job_id": "...",
    "doc_id": "...",
    "tenant_id": "...",
    "version": "2.1",
    "status": "QUEUED" | "PARSING" | "CHUNKING" | "EMBEDDING" | "INDEXING_STAGE_A" | "INDEXING_STAGE_B" | "COMPLETED" | "PARTIAL_SUCCESS" | "FAILED_STAGE_A" | "FAILED_STAGE_B" | "FAILED_RETRY" | "CLEANED_UP",
    "stages": {
      "parsing": "COMPLETED",
      "chunking": "COMPLETED",
      "embedding": "COMPLETED",
      "indexing_stage_a": "COMPLETED",
      "indexing_stage_b": "IN_PROGRESS",
      "indexing_stage_b_step": 3
    },
    "chunk_count": 42,
    "attempts": 0,
    "error": null,
    "created_at": "...",
    "completed_at": null
  },
  "meta": { ... }
}
```

---

## 5. Admin API

### 5.1 POST /internal/admin/cleanup/orphan-staging

`03-document-pipeline.md` §4.4 동작.

Query params:
- `tenant_id` (required)
- `older_than_hours` (default 24)

헤더:
- `X-Role: WITIVE_SUPER_ADMIN`
- `X-User-Id: 00000000-0000-0000-0000-000000000001` (SYSTEM_CRON reserved)

응답 `200 OK`:
```json
{
  "data": {
    "tenant_id": "...",
    "scanned_jobs": 12,
    "cleaned_jobs": 8,
    "deleted_pinecone_vectors": 432,
    "deleted_neo4j_chunks": 432,
    "errors": []
  },
  "meta": { ... }
}
```

### 5.2 POST /internal/admin/reindex (Phase 2+)

테넌트 단위 재색인 트리거. 청킹 알고리즘·임베딩 모델 변경 후 사용.
Next.js/admin tool이 호출. 본 서버는 SQS에 모든 활성 doc 재색인 메시지 발행.

```json
{
  "data": {
    "tenant_id": "...",
    "queued_jobs": 128,
    "estimated_completion_seconds": 7200
  },
  "meta": { ... }
}
```

---

## 6. 헬스체크

### 6.1 GET /internal/health

인증 면제. ECS Task health check + ALB target group용.

```json
{
  "status": "healthy" | "degraded" | "unhealthy",
  "dependencies": {
    "bedrock": "healthy",
    "pinecone": "healthy",
    "neo4j": "healthy" | "n/a (dev)",
    "redis": "healthy",
    "sqs": "healthy",
    "s3": "healthy"
  },
  "timestamp": "2026-05-07T09:00:00Z",
  "version": "git-sha"
}
```

- `healthy`: 모든 의존성 정상
- `degraded`: 일부 의존성 장애지만 fallback 동작 중 (예: Neo4j 다운 → Pinecone 단독 모드). HTTP 200 유지 (ECS Task는 살아있음)
- `unhealthy`: 다음 중 하나
  - Bedrock 또는 Pinecone 동시 장애 → HTTP 503 → ALB target group이 instance 제외
  - **ECS Task 메모리 사용률 > 85%** (08 §6 ALB drain mode 트리거) → HTTP 503 일시 마킹 → ALB가 다른 Task로 라우팅 → 진행 중 SSE는 graceful 완료, 새 트래픽 차단. 메모리 회복 후 healthy 자동 복귀
  - `MAINTENANCE_MODE=true` (08 §3.3 Redis 5분 지속 Open 자동 전환)

각 의존성 ping은 가벼운 ping. 본 서버는 `last_success_ts:{dependency}` **in-process 메모리(asyncio task-local)**에 마지막 성공 호출 timestamp를 보관하고, `/health` 호출 시 이 값과 현재 시각의 diff(임계 60s)로 판정. Bedrock·Pinecone·Neo4j 같은 큰 의존성은 별도 ping 호출 안 함 (헬스 체크 자체가 비용 발생하지 않게 함). Redis 자체는 짧은 `PING` 명령으로 직접 확인 (자기 의존 paradox 회피, 호출 비용 무시 가능). S3·SQS는 boto3 SDK의 last successful 호출 timestamp 사용. 다수 ECS Task가 각자 in-process 상태를 가지므로 health 응답은 Task별로 다를 수 있다 — ALB target group이 N개 Task 중 unhealthy를 자동 격리.

---

## 7. 비용·운영 가드레일 (경제성)

본 API contract가 비용에 미치는 영향 정리:

| 결정 | 비용 영향 |
|---|---|
| SSE keep-alive 15s (FastAPI 기본) | 1초 heartbeat 대비 트래픽 ~94% 감소 |
| ALB idle_timeout 120s 권장 | SSE connection 안정성 ↑, 끊김 재요청으로 인한 Bedrock 비용 폭증 방지 |
| 응답 gzip (≥1KB) | Next.js↔FastAPI VPC 트래픽 비용 미미하나, Next.js→Client 외부 트래픽 ~70% 감소 (Next.js 측 적용 가정) |
| `429 + Retry-After` 발행 | 클라이언트 재시도 폭주 방지. Next.js 측이 retry-after 존중 필수 |
| `done.meta.tokens_used.cache_read` 노출 | Next.js·운영팀이 prompt cache hit 비용 절감 가시화 가능 |
| `done.meta.epoch` 노출 | 클라이언트가 새 epoch 감지 시 캐시 갱신 트리거 가능 |
| `Last-Event-ID` 무시 결정 | resumable 저장 비용(Redis 쓰기 +N×payload) 회피. 필요해지면 별도 결정 |
| `/health` 가벼운 ping | Bedrock 호출 없이 헬스 체크. 1분당 60회 × ECS Task N대 × Bedrock $0.0008 = 회피된 월 비용 수십~수백 달러 |
| `/admin/reindex` SQS 발행만, 동기 색인 없음 | 단일 호출로 대규모 작업 트리거, API timeout 위험 회피 |

## 8. Next.js contract 변경 절차

본 API의 schema·status code·event 형식 변경은 Next.js 코드와 1:1로 묶여 있다. 변경 절차:

1. 본 docs PR 단계에서 Next.js 팀 리뷰
2. 변경이 backward incompatible이면 dual-deploy: 본 서버가 신/구 schema 모두 지원하는 transition 기간 (1주 권장) → Next.js 전환 → 구 schema 제거
3. Next.js↔FastAPI 통합 테스트가 변경 PR과 같이 통과해야 함 (`11-testing.md`)

## 9. 변경 시 영향 범위

- 이벤트 형식 변경 → Next.js 프록시 코드 + 클라이언트 EventSource handler
- 헤더 contract 변경 → `00-scope.md` §3.2 동시 갱신
- 새 endpoint 추가 → ALB routing rule + IAM policy + `09-observability.md` 메트릭 라벨
- payload 필드 추가 → backward compatible로 기본 (필드 추가만), 제거는 위 §8 절차
