# 02 — Query Pipeline

`POST /internal/query` 한 요청이 어떻게 처리되어 SSE 답변이 되는지 정의한다.
이 문서는 Stage 1 / Stage 2의 단계, 데이터 변환, 임계값, 에러·엣지 케이스를 다룬다.
모델별 호출 디테일은 `05-llm-bedrock.md`, 데이터 저장소 접근은 `04-data-stores.md`, fallback·서킷 정책은 `08-resilience.md`.

## 1. 한 요청의 전체 흐름

```
[입력 검증] → [1차 캐시 조회 (원본 정규화 + epoch)]
                       │ miss
                       ▼
              [Stage 1: 재작성]  ─→ SSE: rewritten_query
                       │
                       ▼
              [2차 캐시 조회 (재작성 정규화 + epoch)]
                       │ miss
                       ▼
              [임베딩 → Stage 2 검색]  Pinecone || Neo4j  (asyncio.gather)
                       │
                       ▼
              [임계값 정책]  0.75 / 0.60 / 0.55
                       │
                       ▼
              [재랭킹]  Cross-encoder, top 5
                       │
                       ▼
              [권한·버전 재검증 + EXECUTIVE post-filter]
                       │
                       ▼
              [Chunk 본문 일괄 로드]  Neo4j → S3 chunks.jsonl fallback
                       │
                       ▼
              SSE: sources → warnings(있으면) → token… → done
                       │
                       ▼
              [캐시 저장] 1차·2차 키 모두 (현재 epoch 기준)
```

캐시 hit 시: Stage 1·2 전부 생략하고 저장된 SSE 이벤트 시퀀스를 즉시 재생 (≤ 100ms). SSE connection은 `sse-starlette` 15초 keep-alive ping으로 자동 유지 (§6.2).

## 2. 입력 검증

### 2.1 헤더 → TenantContext

`X-Internal-Auth` dual-key 검증 후, X-* 헤더를 정규화 규약(`00-scope.md` §3.2)대로 `TenantContext`로 변환. 누락·형식 오류는 401 또는 500으로 즉시 종료. SSE 스트림 시작 전이므로 일반 HTTP 응답.

### 2.2 질문 본문 검증

| 검증 | 규칙 | 위반 시 |
|---|---|---|
| 길이 | 1 ≤ len ≤ 2000 | < 1: `QUESTION_EMPTY` (HTTP 400). > 2000: 앞 2000자만 사용 + `QUESTION_TRUNCATED` 경고 |
| 공백만 | trim 후 길이 0 | `QUESTION_EMPTY` |
| 의미 문자 부재 | 한글·영문·숫자 모두 0 | `QUESTION_NO_CONTENT` |

PRD §4.1 엣지 케이스 반영. 길이 외에는 SSE 시작 전 HTTP 400으로 종료.

### 2.3 동일 질문 반복 감지

PRD §4.1: 동일 사용자가 1분 내 동일 질문을 3회 이상 보낼 경우 강제 캐시 hit. Redis에 `dup:{user_id}:{sha256(question_norm)}` 카운터를 INCR + EXPIRE 60s.

## 3. 캐시 정책

ARC §8 기준 + 본 서버 결정. **표준 invalidation 패턴(epoch INCR)**을 채택해 SCAN 비용을 회피한다.

### 3.1 두 단계 캐시 키 + epoch invalidation

테넌트당 단일 `epoch:{tenant_id}` 카운터를 둔다. 키에 epoch를 포함시키면 INCR 1회로 모든 활성 캐시가 자연 stale이 되며, 실제 키 삭제는 TTL 만료에 위임 → SCAN/UNLINK 비용 0.

| 단계 | 키 |
|---|---|
| 1차 | `rag:q1:{tenant_id}:{epoch}:{access_sig}:{sha256(question_norm)}` |
| 2차 | `rag:q2:{tenant_id}:{epoch}:{access_sig}:{sha256(rewritten_norm)}` |
| epoch | `epoch:{tenant_id}` (INCR로 무효화, 무 TTL) |

요청 처리 시 항상 현재 epoch를 GET → 키 조립 → 조회. epoch GET은 매 요청마다 발생하지만 Redis O(1) + 100ms timeout 안에 끝남.

### 3.2 access_sig — EXECUTIVE는 post-filter

`access_sig = sha256(role + sorted(department_normalized) + level)`.

**EXECUTIVE 사용자별 user_id는 캐시 키에 포함하지 않는다**. 그 대신 SSE 응답 직전 EXECUTIVE 청크에 한해 user_id 화이트리스트로 post-filter (§5.4). 이 분리로 캐시는 권한 클래스 단위로 공유되고, 노출은 user 단위로 차단된다.

ARC §8 "권한 단위" 의도와 일치. EXECUTIVE 사용자 N명의 hit율 0% 문제 해소.

### 3.3 정규화 규칙

| 항목 | 규칙 |
|---|---|
| `question_norm` | NFC 유니코드 → trim → 연속 공백 1칸 → 영문 소문자 |
| `rewritten_norm` | 동일 |
| `department_normalized` | `00-scope.md` §3.2 contract — 콤마 구분 trim, NFC, 영문 소문자, 빈 항목 제거, 정렬 |

### 3.4 TTL (환경별)

| 환경 | TTL |
|---|---|
| dev | 300s 고정 |
| staging | 60s 고정 |
| prod | 60s (08:00~22:00) / 300s (그 외) — ARC §11.4 적응형 |

### 3.5 저장 형식 + 재생

캐시 값은 SSE 이벤트 시퀀스 그대로 직렬화: `[rewritten_query, sources, warnings?, full_answer_text, done_meta]`.
재생 시 `full_answer_text`를 N자(기본 32자, `CACHE_REPLAY_CHUNK_CHARS`) chunk로 잘라 `token` 이벤트로 흘려 보내 사용자 체감을 일관되게 한다. keep-alive는 `sse-starlette` 자동 처리 (§6.2).

### 3.6 무효화 트리거

| 트리거 | 동작 |
|---|---|
| 해당 tenant 문서 업로드/삭제/버전 변경 완료 (Worker가 `03-document-pipeline.md` §3.6 Stage B 마지막 단계) | `INCR epoch:{tenant_id}` 1회 |
| 사용자 권한 변경 (Next.js 호출) | 본 서버는 `meta:user:{user_id}` 삭제만. 캐시 epoch는 건드리지 않음 (권한 변경은 access_sig 변화로 자연스레 새 키) |
| 테넌트 마이그레이션 (Index 재생성 등) | admin tool이 `INCR epoch:{tenant_id}` |

epoch INCR 실패 (Redis 일시 장애) → 잠시 stale 노출 가능 (TTL 60~300s). 다음 INCR 시 정상화.

**Stage 1 fallback 시 2차 캐시 SET 생략**: fallback이면 `question_norm == rewritten_norm`이라 1차/2차 키가 같음. 같은 값을 두 번 SET하지 않고 1차만 저장 — Redis 메모리 절약.

**user 단위 제한 정책**: EXECUTIVE 외에 user 단위 접근 제어가 도입되면 캐시 hit 정보 누수 위험. **본 서버 정책상 user 단위 제한은 EXECUTIVE access_level의 `allowed_user_ids` 한 곳에만 존재하며**, 그것은 §5.4 응답 직전 post-filter로 처리된다. 다른 곳에서 user 단위 제한을 도입하려면 `07-multitenancy-and-access.md`와 본 절 동시 갱신 + access_sig에 user_id 포함 또는 epoch 무효화 트리거 추가 결정 필요.

## 4. Stage 1 — Query Rewriter

### 4.1 호출 사양

| 항목 | 값 |
|---|---|
| 모델 | Claude Haiku 4.5 (`05-llm-bedrock.md`) |
| temperature | 0.1 |
| max_tokens | 300 |
| timeout | 3.0s |
| 시스템 프롬프트 | 한국어 재작성 + TenantContext 주입 (`05` §2.1) |

### 4.2 출력 검증

| 검증 | 위반 시 |
|---|---|
| 빈 문자열 또는 공백만 | 원본 질문 fallback |
| 길이 > 2000 | 앞 2000자만 사용 |
| 의미 문자 0개 | 원본 질문 fallback |

### 4.3 fallback

| 조건 | 처리 |
|---|---|
| Bedrock timeout (>3s) | 원본 질문, `meta.fallback_used += "stage1_timeout"` |
| Bedrock throttling (`ThrottlingException`) | 250ms → 500ms → 1s exponential backoff (3회), 최종 실패 시 원본 |
| Bedrock 5xx | 원본 질문 |
| 빈/무효 결과 | 원본 질문 |
| 서킷 오픈 (`08-resilience.md`) | 원본 질문, Stage 2로 직진 |

fallback인 경우에도 `rewritten_query` 이벤트는 발송한다 (원본 그대로 + `meta.fallback: true` — payload schema는 §6.3).

## 5. Stage 2 — Hybrid RAG

### 5.1 임베딩 + 검색

쿼리 임베딩(Pinecone용)은 Bedrock Titan v2 호출 1회. Stage 1과 직렬, 그 다음 Pinecone+Neo4j 병렬.

| 단계 | timeout |
|---|---|
| Bedrock Titan v2 임베딩 | 300ms |
| Pinecone query | 500ms |
| Neo4j query | 1000ms |

```python
embedding = await bedrock.embed(rewritten.text)
pinecone_hits, neo4j_hits = await asyncio.gather(
    pinecone.query(embedding, filter=...),
    neo4j.fulltext_search(rewritten.text, ctx),    # dev 환경은 noop
    return_exceptions=True,
)
```

dev 환경은 Neo4j 호출하지 않음. 본문 로드 경로(§5.6)도 dev는 S3 chunks.jsonl로 직행.

#### Pinecone 필터

`04-data-stores.md` §1.4 + 권한 분기 `07-multitenancy-and-access.md`. **`index_state == "live"` 필터를 항상 포함**해 색인 진행 중인 staging 청크가 검색에 노출되지 않게 한다 (`03-document-pipeline.md` §3.5).

### 5.2 임계값 정책 (Pinecone 기준)

| 1차 검색 결과 최대 score | 처리 |
|---|---|
| ≥ 0.75 | 정상 |
| 0.60 ~ 0.75 | `LOW_CONFIDENCE` 경고 + 정상 단계 진행 |
| < 0.60 또는 0건 | 임계값 0.55로 1회 재검색 |
| 재검색도 0.55 미만 / 0건 | 미답변 처리 (`error: NO_RESULTS`) |

Neo4j 결과는 점수 개념이 아니므로 위 임계값과 별개로 합쳐 재랭킹 단계에 넘긴다.

### 5.3 재랭킹

- 모델: Cross-encoder (한국어 지원 모델 우선)
- 입력: Pinecone + Neo4j 청크 합친 후 `chunk_id` 중복 제거
- 출력: 상위 5개
- 실행: `asyncio.to_thread`로 격리 (CPU 바인드)
- timeout: 1500ms
- fallback: 실패·timeout·서킷 오픈 시 → Pinecone score 내림차순 상위 5개. `warnings: RERANK_DEGRADED`

### 5.4 권한·버전 재검증 + EXECUTIVE post-filter

Pinecone에서는 filter로 1차 보장, Neo4j 결과는 별도 검증.

추가로, 캐시 키에 user_id가 빠진 결과로 EXECUTIVE 청크는 응답 직전 한 번 더 화이트리스트 검증한다:

```
for each chunk in top_5:
    if chunk.access_level == "EXECUTIVE":
        if ctx.user_id not in chunk.allowed_user_ids:
            drop(chunk)
```

폐기 후 0개면 `error: NO_ACCESSIBLE_RESULTS`.

자세한 정책 함수는 `07-multitenancy-and-access.md`.

### 5.5 충돌 감지

Neo4j Cypher의 `OPTIONAL MATCH (v)-[:CONFLICTS_WITH]->(conflict:Version)` 결과가 비어 있지 않으면 `warnings`에 `VERSION_CONFLICT`. 상위 5개 청크 중 `is_current=false`가 1개 이상이면 `warnings`에 `OUTDATED_VERSION`.

### 5.6 Chunk 본문 일괄 로드 (생성 직전, 필수 단계)

Pinecone 메타에는 chunk 본문이 없다 (`04-data-stores.md` §1.3). 답변 생성 전 본문을 일괄 조회한다. "Pinecone 단독 장애"는 query 실패와 임베딩 실패 양쪽을 포괄한다 (어느 쪽이든 Pinecone 결과 0건 처리).

| 환경 / 상태 | 1차 출처 | 2차 fallback | 둘 다 실패 시 |
|---|---|---|---|
| dev (Neo4j 미사용) | S3 `chunks.jsonl` byte-range | — | `SERVICE_DEGRADED` 종료 (아래) |
| staging/prod 정상 | Neo4j `MATCH (c:Chunk) WHERE c.chunk_id IN $ids RETURN c.chunk_id, c.text` (단일 query) | S3 `chunks.jsonl` byte-range | `SERVICE_DEGRADED` 종료 |
| Neo4j 단독 장애 (서킷 오픈) | S3 `chunks.jsonl` byte-range | — | `SERVICE_DEGRADED` 종료 |
| Pinecone 단독 장애 (query 또는 임베딩 실패) | Neo4j 결과 + Neo4j Chunk.text (이미 본문 있음) | — | (Neo4j도 실패면 §8 `SERVICE_UNAVAILABLE`) |

S3 chunks.jsonl은 색인 단계에서 청크별 byte offset을 metadata.json에 기록 (`04-data-stores.md` §3.4). offset 기반 byte-range GET 5회 병렬 (`asyncio.gather`). offset이 없으면 전체 jsonl GET 후 메모리 필터.

| 항목 | 값 |
|---|---|
| 본문 fetch timeout (5청크) | 100ms (Neo4j) / 500ms (S3) |
| 본문 fetch 실패한 청크 | 폐기 |
| 폐기 후 0개 | `error: NO_RESULTS` |

#### `SERVICE_DEGRADED` 종료 케이스 (sources만, token 0개)

검색·재랭킹은 성공했으나 본문 fetch 1차·2차 모두 실패 → SSE 시퀀스: `rewritten_query → sources → warnings:GENERATION_DEGRADED → done(meta.fallback_used=["chunk_text_fetch_failed"])`. **token 이벤트 0개, error 이벤트 미발행** (검색은 정상 → 사용자에게 sources를 보여주는 게 가치).

### 5.7 답변 생성 (스트리밍)

| 항목 | 값 |
|---|---|
| 모델 | Claude Sonnet 4.6 (dev: Haiku 4.5) |
| temperature | 0.3 |
| max_tokens | 1024 |
| 시스템 프롬프트 캐싱 | 활성 (`05-llm-bedrock.md` §4) |
| 호출 형태 | Bedrock `converse_stream` async iterator |
| timeout (전체 생성) | 30s |

스트리밍 도중 클라이언트 disconnect → `asyncio.CancelledError` 전파 → `05` §3.1의 try/finally로 stream close 호출 → Bedrock 호출 종료.

## 6. SSE 이벤트 명세

### 6.1 시퀀스

```
1. rewritten_query   (Stage 1 직후, fallback이어도 발행)
2. sources           (Stage 2 검색·재랭킹·필터·본문로드 후, token 시작 전)
3. warnings          (있으면, sources 직후. token 도중 발생 시 token 사이에)
4. token …           (생성 중 0~N개)
5. done              (meta: latency_ms, tokens_used, cache_hit, fallback_used[], epoch)
```

에러 경로:
- `rewritten_query` 발행 후 미답변 결정 시 → `error` 이벤트로 종료 (token·done 없음)
- 검색은 성공했으나 본문 fetch 1·2차 모두 실패 → `sources → warnings:GENERATION_DEGRADED → done` (§5.6 `SERVICE_DEGRADED` 종료, token 0개, error 미발행)
- 검증 실패는 SSE 시작 전 HTTP 400/401/500

`error` 이벤트의 `retryable: bool` 매핑: throttling/Bedrock 5xx/Redis 일시 장애 = `true`. `QUESTION_EMPTY`/`QUESTION_NO_CONTENT`/`NO_RESULTS`/`NO_ACCESSIBLE_RESULTS` = `false`. 자세한 매핑은 `08-resilience.md`.

### 6.2 Heartbeat (sse-starlette)

본 서버는 [`sse-starlette`](https://pypi.org/project/sse-starlette/) 라이브러리의 `EventSourceResponse` (`from sse_starlette.sse import EventSourceResponse`)를 사용한다. **FastAPI 공식 패키지에는 SSE 모듈이 없다** — `sse-starlette`은 FastAPI 생태계에서 사실상 표준 SSE 라이브러리. 이 응답은 다음을 자동 처리:

- **15초 간격 keep-alive ping comment** (HTML5 SSE 표준 + 프록시 idle 방지). `EventSourceResponse(ping_interval=15)` 기본값
- `Cache-Control: no-cache`, `X-Accel-Buffering: no` 응답 헤더 자동 설정 (Nginx 등 reverse proxy 버퍼링 차단)
- `Last-Event-ID` 헤더로 클라이언트 reconnection 시 resumption 지원

운영 가정 idle timeout (모두 15s 초과 안전):
- Next.js SSE 프록시 idle timeout: ≥ 60s 권장 (Next.js 측 설정 책임)
- AWS ALB idle_timeout: 기본 60s — **120s로 상향 권장** (대용량 답변 시 token 사이 간격 안전 마진)
- API Gateway: HTTP API는 30s 고정, REST API 29s — SSE에는 부적합. 본 서버는 ALB→ECS 직접 경로 가정

**별도 1초 heartbeat 발행 금지** — FastAPI 15초 ping이 표준. `SSE_HEARTBEAT_MS` 환경 변수는 폐기. 이전 docs의 "1초 heartbeat"는 잘못된 결정 (트래픽 낭비, 비용 증가).

상세 구현 계약은 `06-api.md` §SSE.

### 6.3 이벤트 payload schema

`06-api.md`가 단일 진실 출처. `06` 작성 전에도 하네스가 코드를 짤 수 있도록 본 절에 명시. `06` 작성 후 충돌 시 `06`이 우선.

| event type | payload (JSON) | 비고 |
|---|---|---|
| `:heartbeat` (comment) | (없음) | connection 유지, 클라이언트 무시 |
| `rewritten_query` | `{"content": str, "meta": {"fallback": bool}}` | Stage 1 결과 또는 fallback 원본 |
| `sources` | `{"content": [{"chunk_id", "doc_id", "doc_name", "version", "is_current", "effective_date", "section", "page", "excerpt", "similarity_score", "warning"?}]}` | 상위 5개 청크. `chunk_id`는 Next.js·클라이언트 피드백/추적용 |
| `warnings` | `{"content": [{"type", "severity", "message", "...추가 필드"}]}` | 종류는 §8 매트릭스 |
| `token` | `{"content": str}` | 답변 토큰 chunk |
| `done` | `{"meta": {"latency_ms": int, "tokens_used": {"input", "output", "cache_read"}, "cache_hit": bool, "fallback_used": [str], "epoch": int}}` | 종료 |
| `error` | `{"code": str, "message": str, "retryable": bool}` | 에러 종료 |

## 7. 임계값·설정 한 곳

모든 임계값은 코드에 하드코딩하지 않고 환경 변수로 받는다 (`10-config-and-secrets.md`).

| 항목 | 기본값 | 환경 변수 |
|---|---|---|
| 질문 길이 min/max | 1 / 2000 | `QUERY_MIN_LEN` / `QUERY_MAX_LEN` |
| 동일 질문 강제 캐시 임계 | 1분 / 3회 | `DUP_QUERY_WINDOW_S` / `DUP_QUERY_THRESHOLD` |
| 캐시 TTL (업무 시간 / 외) | 60s / 300s | `QUERY_CACHE_TTL_BUSINESS_S` / `QUERY_CACHE_TTL_OFF_S` |
| 캐시 재생 chunk 크기 | 32자 | `CACHE_REPLAY_CHUNK_CHARS` |
| 임베딩 timeout | 300ms | `EMBED_QUERY_TIMEOUT_MS` |
| Pinecone top_k | 10 | `PINECONE_TOP_K` |
| Pinecone 임계 high/low/fallback | 0.75 / 0.60 / 0.55 | `SIM_THRESHOLD_HIGH` / `LOW` / `FALLBACK` |
| Pinecone / Neo4j / 재랭킹 timeout | 500ms / 1000ms / 1500ms | `PINECONE_TIMEOUT_MS` / `NEO4J_TIMEOUT_MS` / `RERANK_TIMEOUT_MS` |
| Neo4j LIMIT | 10 | `NEO4J_LIMIT` |
| 재랭킹 결과 수 | 5 | `RERANK_TOP_K` |
| 본문 fetch timeout (Neo4j / S3) | 100ms / 500ms | `CHUNK_TEXT_NEO4J_TIMEOUT_MS` / `CHUNK_TEXT_S3_TIMEOUT_MS` |
| Stage 1 timeout | 3s | `STAGE1_TIMEOUT_S` |
| Stage 2 생성 timeout | 30s | `STAGE2_GEN_TIMEOUT_S` |
| Stage 1/2 max_tokens | 300 / 1024 | `STAGE1_MAX_TOKENS` / `STAGE2_MAX_TOKENS` |
| Stage 1/2 temperature | 0.1 / 0.3 | `STAGE1_TEMP` / `STAGE2_TEMP` |
| SSE keep-alive | 15s (`sse-starlette` 자동) | (설정 불필요, `EventSourceResponse(ping_interval=15)` 기본값) |
| 첫 토큰 SLO (본 서버 내부) | 4.0s P95 | `SLO_FIRST_TOKEN_P95_MS` (메트릭 임계) |

## 8. 에러·엣지 케이스 매트릭스

| 상황 | 처리 | 클라이언트가 받는 것 |
|---|---|---|
| 질문 길이 0 / 공백만 / 의미 문자 0 | 거부 | HTTP 400 `QUESTION_EMPTY` / `QUESTION_NO_CONTENT` |
| 질문 길이 > 2000 | 앞 2000자만 처리 | 정상 SSE + `warnings: QUESTION_TRUNCATED` |
| 1분 내 동일 질문 3회+ | 강제 캐시 사용 | 정상 SSE + `done.meta.cache_hit=true` |
| 캐시 hit | 즉시 SSE 재생 (`sse-starlette` keep-alive 자동) | 정상 SSE + `done.meta.cache_hit=true` |
| Stage 1 실패 | 원본 질문 fallback, Stage 2 진행 | 정상 SSE + `done.meta.fallback_used` |
| 임베딩 실패 (Pinecone 검색 불가) | Neo4j 단독 검색 (있으면) | 정상 SSE + `warnings: PINECONE_DEGRADED` |
| Pinecone 단독 장애 | Neo4j 단독 결과로 진행, 본문은 Neo4j Chunk.text | 정상 SSE + `warnings: PINECONE_DEGRADED` |
| Neo4j 단독 장애 | Pinecone 단독 결과로 진행, 본문은 S3 chunks.jsonl | 정상 SSE + `warnings: NEO4J_DEGRADED` |
| Pinecone+Neo4j 동시 장애 | 미답변 | `error: SERVICE_UNAVAILABLE` |
| 검색 결과 0건 또는 0.55 미만 | 미답변 + 미답변 로그 | `error: NO_RESULTS` |
| 0.60~0.75 | 정상 답변 + 경고 | 정상 SSE + `warnings: LOW_CONFIDENCE` |
| 모든 결과가 구버전 | 정상 답변 + 경고 | 정상 SSE + `warnings: OUTDATED_VERSION` |
| 충돌 버전 동시 검색 | 정상 답변 + 충돌 명시 | 정상 SSE + `warnings: VERSION_CONFLICT` |
| EXECUTIVE post-filter로 5개 모두 폐기 | 미답변 + 안내 | `error: NO_ACCESSIBLE_RESULTS` |
| 권한 없는 문서만 매칭 (1차 필터에서 0개) | 미답변 + 안내 | `error: NO_ACCESSIBLE_RESULTS` |
| 재랭킹 실패 | score 순 fallback | 정상 SSE + `warnings: RERANK_DEGRADED` |
| 본문 fetch 0개 (검색 결과 자체 부재) | 미답변 | `error: NO_RESULTS` |
| 본문 fetch 부분 실패 (일부 청크) | 실패 청크 폐기 후 진행 | 정상 SSE + 짧은 sources |
| 본문 fetch 1·2차 모두 실패 (검색은 성공) | sources만 노출, token 생략 | 정상 SSE + `warnings: GENERATION_DEGRADED` + `done(meta.fallback_used=["chunk_text_fetch_failed"])` (§5.6 SERVICE_DEGRADED 케이스, error 미발행) |
| Bedrock Sonnet 장애 | 검색 결과 원문 반환 (생성 생략) | 정상 SSE + `warnings: GENERATION_DEGRADED` (token 대신 원문 chunk) |
| Bedrock max_tokens 도달 | 자연스럽게 마무리 + 안내 | 정상 SSE + `warnings: ANSWER_TRUNCATED` |
| 클라이언트 disconnect | 진행 중 Bedrock 호출 즉시 중단 (`sse-starlette` keep-alive task 자동 종료) | (스트림 종료) |
| 인증 실패 (X-Internal-Auth) | HTTP 401 | `UNAUTHORIZED` |
| TenantContext 불완전 | HTTP 500 + 알람 | `TENANT_CONTEXT_INVALID` |
| epoch GET 실패 | 캐시 조회 생략, 정상 흐름 진행 | (사용자 영향 없음, warn 로그) |

## 9. 변경 시 영향 범위

- 임계값(0.75/0.60/0.55) 변경 → RAG 평가 골든셋 (`11-testing.md`) 재실행
- 재랭킹 모델 교체 → P95 예산 측정, 골든셋 재실행
- Stage 1 모델 변경 → 1차 캐시 hit 비율 영향 평가 (`05-llm-bedrock.md`)
- 캐시 키 구조 변경 (epoch 포함, access_sig 정의 등) → `04-data-stores.md` §4.1과 동기화 필수
- 첫 토큰 SLO 변경 → `09-observability.md` 메트릭 임계, `11-testing.md` P95 측정 임계 동기화
- chunk 본문 로드 경로 변경 → `03-document-pipeline.md` (chunks.jsonl 포맷·byte offset) + `04-data-stores.md` §3.4 동기화
- SSE 이벤트 형식·payload 스키마 변경 → `06-api.md` 갱신 + Next.js 프록시 contract 조율 필수 (keep-alive는 FastAPI 위임이라 본 서버 변경 사항 아님)
