# 08 — Resilience

본 서버의 모든 외부 의존성에 대한 fallback / 서킷 브레이커 / 재시도 / timeout 정책을 단일 진실 출처로 정리한다.
이 docs의 첫째 목적은 안정성 — 둘째 목적은 **운영 비용 폭증 방어**. 외부 장애 시 무한 재시도가 Bedrock·Pinecone 비용을 분 단위로 폭증시키므로, 서킷 브레이커는 상품 가격 모델과 직결된 1차 방어선이다.

## 1. 핵심 원칙

1. **Fail fast over hang** — 사용자 대기 시간 P95 4초 안에서 실패는 명시적으로 종료. 클라이언트는 retryable 여부를 알고 재시도 정책 결정
2. **No-retry by default for client errors** — 4xx 에러는 retry 안 함 (입력 변경 없이는 같은 결과)
3. **Bounded retry** — 모든 retry는 횟수·시간 상한 (외부 장애 시 무한 호출로 비용·throughput quota 폭증 방지)
4. **Circuit breaker first, retry second** — 서킷 오픈 상태에서 재시도 안 함. 서킷이 닫힌 상태에서만 짧은 backoff
5. **Fallback over error** — 부분 결과라도 사용자 가치가 있으면 fallback (예: Pinecone 단독, Neo4j 단독, sources만 노출)
6. **DLQ는 수동 처리** — 자동 redrive 금지 (`03 §4.3`). 같은 메시지 무한 재처리 비용 차단

## 2. 의존성별 fallback 매트릭스

`02-query-pipeline.md` §8 + `03-document-pipeline.md` §4 + `04-data-stores.md`의 timeout/재시도를 한 곳에 통합.

| 의존성 | 단독 장애 fallback | 비용 폭증 방어 |
|---|---|---|
| AWS Bedrock Claude (Stage 1) | 원본 질문 사용, Stage 2 직진 | Stage 1 throttle 시 backoff 후 fallback — 무한 재시도 안 함 |
| AWS Bedrock Claude (Stage 2 답변) | 검색 결과 원문 반환 (sources만, GENERATION_DEGRADED) | 답변 생성 실패가 quota 소진 안 되게 fail fast |
| AWS Bedrock Titan (임베딩, query) | Pinecone 검색 불가 → Neo4j 단독 결과 | 글로벌 token bucket(`05 §5.2`)이 호출량 자체를 제한 |
| AWS Bedrock Titan (임베딩, 색인) | 청크 단위 격리 → `PARTIAL_SUCCESS` job 상태 (다른 청크 색인 진행, 06 §4.2 enum과 통합) | DLQ 도달 후 수동 처리. 자동 retry 폭주 차단 |
| Pinecone query | Neo4j 단독 결과로 진행 (`PINECONE_DEGRADED` 경고) | 서킷 오픈 시 query 자체를 skip — 호출량 0 |
| Pinecone upsert (색인) | Stage A 단계라 검색 노출 없음 → 다음 SQS attempt 또는 cleanup | 청크 폐기 후 다른 청크 진행 |
| Neo4j query | Pinecone 단독 결과 + S3 chunks.jsonl 본문 fetch (`NEO4J_DEGRADED`) | 서킷 오픈 시 fallback path만 실행 |
| Neo4j 색인 (Stage A·B) | Stage A 실패는 staging 잔존 + cleanup, Stage B 단계별 보상 (`03 §3.6`) | bounded retry (3회 + Stage B deadline 60s) |
| AWS S3 GetObject (chunks.jsonl) | 본문 fetch 실패 → `SERVICE_DEGRADED` (sources만) | 짧은 timeout(500ms) 후 폐기 |
| AWS S3 PutObject (원본 업로드) | 동기 5xx 반환, SQS 발행 안 함 | 부분 성공 없음 — 보상 트랜잭션 0 |
| AWS SQS | 동기 처리 fallback (소용량만) 또는 동기 5xx | 일시 장애만 가정 — 장기 장애 시 색인 보류 |
| ElastiCache (Redis) | 캐시 미스로 폴백, epoch GET 실패 시 캐시 조회 생략 | **미스 폭주 → Bedrock 비용 ↑ 위험**. 알람 임계 §5 |
| AWS Textract | OCR confidence 낮음·실패 → 라인 폐기 + warning | bounded retry (3회) |
| Cross-encoder (재랭킹) | Pinecone score 순으로 fallback (`RERANK_DEGRADED`) | timeout 1.5s 후 fallback — Sonnet TTFT 예산 보호 |

## 3. 서킷 브레이커

각 의존성에 별도 서킷 브레이커 (라이브러리: `pybreaker` 또는 자체 구현 `platform/circuit_breaker.py`).

### 3.1 임계 정책

| 의존성 | 실패율 임계 | 윈도 | Open 상태 유지 | Half-Open 테스트 |
|---|---|---|---|---|
| Bedrock Claude (Stage 1·2) | > 50% | 10s | 30s | 30초 후 단일 요청 |
| Bedrock Titan (임베딩) | > 50% | 10s | 30s | 동일 |
| Pinecone | > 30% | 10s | 30s | 동일 |
| Neo4j | > 30% | 10s | 30s | 동일 |
| S3 GetObject | > 50% | 10s | 60s | 동일 |
| Redis | > 50% | 5s | 10s | 동일 (회복 빠름) |
| Cross-encoder | > 50% | 10s | 30s | 동일 |

실패 정의: 4xx 제외, 5xx + timeout + connection error만 카운트 (4xx는 우리 잘못이라 retry 안 함).

### 3.2 Open 상태 동작

| 의존성 | Open 상태에서 호출 시 |
|---|---|
| Bedrock Claude Stage 1 | 즉시 fallback (원본 질문) |
| Bedrock Claude Stage 2 | 즉시 fallback (sources만, GENERATION_DEGRADED) |
| Bedrock Titan (query) | Pinecone 호출 skip → Neo4j 단독 |
| Pinecone | Neo4j 단독 |
| Neo4j | Pinecone 단독 + S3 chunks.jsonl |
| Redis | 캐시 사용 안 함 (모든 요청이 Bedrock 도달) ⚠️ |
| Cross-encoder | score 순 fallback |
| S3 (본문 fetch) | `SERVICE_DEGRADED` 종료 |

### 3.3 Redis 서킷 오픈 시 단일 시간선 (M-7 정합)

Redis 서킷 오픈 = 모든 요청이 캐시 미스 = 모든 요청이 Bedrock 호출 = 평균 비용 ~5배. 30초 Open 상태로 5,000 RPM 트래픽이면 Bedrock 추가 비용 수십 달러/분.

본 서버는 다음 단일 시간선으로 응답한다 (`05-llm-bedrock.md` §5.2 Redis 장애 fallback과 통합):

| 시점 | 동작 |
|---|---|
| t=0s (Redis Open 감지) | 글로벌 token bucket → **로컬 Task 단위 token bucket 자동 fallback** (`05 §5.2`). 캐시 lookup 생략(요청별로 자연 미스). Critical 알람 발행 (`09 §4.1`) |
| t=0~30s | 트래픽 정상 처리. 단 Bedrock 호출 비율 ↑ → `bedrock_estimated_cost_usd` 분당 알람이 1차 감시 |
| t=30s (서킷 Half-Open) | 단일 ping. 성공 시 Closed → 글로벌 token bucket 모드 복귀 |
| t=5min (지속 Open) | **`MAINTENANCE_MODE=true` 자동 전환** + Critical 알람 강화. 모든 query는 `503 SERVICE_UNAVAILABLE` + `Retry-After: 60`. 운영팀이 Redis 복구 후 환경 변수 수동 해제 |

이 시간선은 token bucket 정책(`05`)과 backpressure 정책(`08 §6`) 사이 중복을 제거하기 위한 단일 진실 출처. 어느 docs를 변경하더라도 이 표 함께 갱신.

## 4. 재시도 정책 표

`03·04`에 흩어진 retry 정책을 한 곳에 통합.

| 작업 | 재시도 횟수 | backoff | 비고 |
|---|---|---|---|
| Bedrock Claude (Stage 1·2) | 3회 | 250ms / 500ms / 1s + jitter ±20% | throttling/5xx만 |
| Bedrock Titan (query 임베딩) | 0회 | — | 사용자 대기 시간 안 — 실패 즉시 fallback |
| Bedrock Titan (색인 임베딩) | 3회 | 1s / 2s / 4s + jitter | throttling/5xx만 |
| Pinecone query | 0회 | — | 실패 즉시 fallback |
| Pinecone upsert | 3회 | 250ms / 500ms / 1s | 5xx만, 4xx는 즉시 실패 |
| Pinecone delete | 3회 | 250ms / 500ms / 1s | |
| Neo4j query | 0회 | — | 실패 즉시 fallback |
| Neo4j 색인 transaction | driver 자동 (TransientError) | 자동 backoff | `MAX_TRANSACTION_RETRY_TIME=5s` |
| S3 GetObject | 3회 | 250ms / 500ms / 1s | 5xx + timeout만 |
| S3 PutObject | SDK 자체 (멀티파트) | 기본 | |
| Textract | 3회 | 1s / 2s / 4s | throttling/5xx만 |
| SQS receive/send | SDK 기본 | 기본 | |
| Redis | 1회 | 50ms | 회복 빠름 |
| Stage B 단계별 (`03 §3.6`) | 3회 (`STAGE_B_STEP_RETRIES`) | 250ms / 500ms / 1s | 단계별 + Stage B 전체 deadline 60s |

**jitter 필수** — 동시에 다중 Worker가 동시 실패하면 재시도 동기화로 호출 폭주 (thundering herd). 모든 backoff에 ±20% jitter.

## 5. Timeout 한 곳

`02·03·04·05`에 흩어진 timeout 정리.

### 5.1 사용자 대기 경로 (질의)

| 구간 | timeout |
|---|---|
| Stage 1 Bedrock 전체 | 3.0s |
| Bedrock Titan 임베딩 (query) | 300ms |
| Pinecone query | 500ms |
| Neo4j query | 1000ms |
| Cross-encoder 재랭킹 | 1500ms |
| Neo4j chunk 본문 fetch | 100ms |
| S3 chunks.jsonl byte-range fetch (5청크) | 500ms |
| Bedrock Sonnet 전체 생성 (스트림) | 30s |
| Redis GET / SET / INCR | 100ms |

전체 사용자 대기 deadline: 60s (asyncio top-level wait_for). 초과 시 진행 중 Bedrock cancel + `error: TIMEOUT`.

### 5.2 색인 경로 (Worker)

| 구간 | timeout |
|---|---|
| Bedrock Titan 임베딩 (배치당) | 5s |
| Pinecone upsert (배치 100) | 2s |
| Pinecone delete (배치 100) | 2s |
| Neo4j transaction (Stage A·B) | 5s |
| Stage B 전체 | 60s (`STAGE_B_DEADLINE_S`) |
| S3 PutObject (멀티파트, ≤100MB) | 60s |
| S3 metadata.json conditional write | 2s |
| SQS Visibility | 300s |

### 5.3 Admin·Health

| 구간 | timeout |
|---|---|
| `/internal/admin/cleanup/orphan-staging` (테넌트당) | 600s (다수 청크 처리) |
| `/internal/admin/reindex` (트리거만) | 30s |
| `/internal/health` | 1s (자체 ping은 무비용 마지막 호출 시간 비교) |

## 6. Backpressure (글로벌 보호)

본 서버는 외부 의존성 quota를 보호하기 위해 자체 backpressure를 발행한다.

| 트리거 | 응답 | 효과 |
|---|---|---|
| Bedrock 글로벌 token bucket 한도 초과 | 429 + `Retry-After: <seconds>` + `X-Backpressure-Reason: bedrock_titan_global_bucket` | Bedrock throttling exception 회피, Next.js·클라이언트가 자연 throttle |
| **동시 SSE connection 상한 도달 (`MAX_CONCURRENT_SSE_CONNECTIONS`, 기본 200/Task)** | 429 + `Retry-After: 5` + `X-Backpressure-Reason: max_concurrent_sse` | Stage 2 30s timeout 워스트 케이스 OOM 1차 방어선. Auto Scaling 60s 쿨다운보다 빠른 보호 |
| **`/internal/cache/invalidate` tenant당 분당 60회 초과** | 429 + `Retry-After: 60` + `X-Backpressure-Reason: cache_invalidate` | Next.js 버그·악성 호출로부터 Redis CPU와 캐시 hit ratio 보호 |
| **ECS Task 메모리 사용률 > 85% (1분 평균)** | 신규 query는 429 발행 + **ALB drain mode (헬스 체크 unhealthy 일시 마킹)**. 진행 중 SSE는 graceful 완료 | OOM 직전 갑작스런 connection 드롭 회피 (in-flight SSE 보호). 90%로 임계 상향했던 이전 결정은 사고 직전이라 위험 — 85%로 보수적 조정 |
| Redis 서킷 오픈 즉시 | `08 §3.3` 시간선 따름 (로컬 token bucket → 5분 후 MAINTENANCE_MODE 자동 전환) | 비용 폭증 방어 |
| Redis 서킷 오픈 + 5분 지속 | 503 `MAINTENANCE_MODE` 자동 + Critical 알람 강화 | 캐시 0 상태로 풀 트래픽 보호 |

## 7. DLQ 처리 정책

`03 §4.3` 기준:

- DLQ 메시지 1건 이상 → CloudWatch 알람 (Critical, 즉시 운영팀 호출 — `09`)
- **자동 redrive 금지**. 본 서버에서 redrive 코드 없음
- 운영팀 수동 절차:
  1. DLQ 메시지 검사 (메시지 본문 + S3 jobs/*.json 상태)
  2. 원인 분석 (파서 버그, 외부 의존성 장애, 잘못된 데이터)
  3. 코드 수정 또는 데이터 정정
  4. admin tool로 SQS redrive (DLQ → 원본 큐) — admin tool은 본 서버 외 책임

자동 redrive 금지의 비용 근거: 100MB 파일 1건 색인 비용 ~$0.01. 무한 retry로 1,000회 도달 시 $10 + Bedrock·Pinecone API 호출 quota 소진 위험. 수동 게이트가 안전.

## 8. 비용 폭증 방어 시나리오

운영 중 발생 가능한 "비용 사고" 패턴과 본 서버 방어선:

| 사고 패턴 | 방어선 | 결과 |
|---|---|---|
| Bedrock 일시 장애 → 본 서버가 무한 retry | 서킷 브레이커 + bounded retry (3회) | 분당 호출 수 한계, fallback 경로 |
| 사용자가 DDoS 패턴으로 query 폭주 | 글로벌 token bucket → 429 BACKPRESSURE | Bedrock 한도 도달 전 throttle |
| Redis 다운 → 캐시 미스 폭주 → Bedrock 비용 5배 | Redis 서킷 오픈 + MAINTENANCE_MODE 수동 게이트 | 운영팀 결정 필수 (자동 503으로 일시 전환) |
| 잘못된 색인 메시지가 DLQ 무한 redrive | 자동 redrive 금지 정책 | 한 번 실패하면 수동 검토까지 정지 |
| 청킹 알고리즘 버그로 청크당 토큰 폭증 | 청크 후 임베딩 호출 전 토큰 길이 검증 (`03 §3.3`) | 호출 전 차단 |
| 시스템 프롬프트 변경으로 캐시 미형성 → 입력 토큰 비용 5배 | `bedrock_cache_read_tokens_total = 0 for 24h` Critical 알람 | 즉시 감지 + 롤백 |
| EXECUTIVE post-filter로 5개 모두 폐기 → 재요청 폭주 | `error: NO_ACCESSIBLE_RESULTS` (retryable=false) | 클라이언트 재시도 안 함 |
| 본문 fetch 실패 → SERVICE_DEGRADED → 사용자 재요청 | retryable=false (`06 §1.4`) | 무한 재요청 차단 |
| **Stage 1 Haiku 장기 장애 → 원본 질문 fallback → 검색 품질 저하 → 사용자 재질문 → Sonnet 호출 비율 ↑** | **자동 방어 부재**. `query.stage1.fallback_total / queries_total > 20% for 30min` 알람(High) + `bedrock_estimated_cost_usd` 시간 평균 2배 알람(Critical) → 운영팀 신속 복구 | 알람 기반 운영 대응 (자동 방어 없음 명시) |
| **동시 SSE connection burst** (`MAX_CONCURRENT_SSE_CONNECTIONS` 도달) | 429 BACKPRESSURE 즉시 발행 + Auto Scaling trigger | Auto Scaling 60s 쿨다운보다 빠른 OOM 방어 |
| **Next.js 버그로 cache/invalidate 폭주** | tenant당 60/min rate limit + 429 | Redis CPU + 캐시 hit ratio 보호 |

이 표가 **"경제적 이익을 최대한"** 가치의 핵심 가드레일이다. 새 fallback 경로 추가 시 본 표에 행 추가 + 비용 영향 설명 필수.

## 9. 환경 변수 한 곳

| 항목 | 기본값 | 환경 변수 |
|---|---|---|
| 서킷 임계 (Bedrock) | 50% / 10s / 30s open | `CB_BEDROCK_FAIL_THRESHOLD` / `CB_BEDROCK_WINDOW_S` / `CB_BEDROCK_OPEN_S` |
| 서킷 임계 (Pinecone/Neo4j) | 30% / 10s / 30s | `CB_PINECONE_*` / `CB_NEO4J_*` |
| 서킷 임계 (Redis) | 50% / 5s / 10s | `CB_REDIS_*` |
| 글로벌 token bucket (Bedrock Titan) | 30 RPS | `BEDROCK_TITAN_RPS_LIMIT` (`05 §5.2`) |
| Stage B deadline | 60s | `STAGE_B_DEADLINE_S` |
| Stage B 단계별 retry | 3회 | `STAGE_B_STEP_RETRIES` |
| MAINTENANCE_MODE | false | `MAINTENANCE_MODE` (수동 전환) |
| 사용자 대기 deadline (질의) | 60s | `QUERY_REQUEST_DEADLINE_S` |
| Worker 메시지 처리 deadline | 270s (SQS visibility 300s 안에 안전 마진) | `WORKER_MESSAGE_DEADLINE_S` |

## 10. 검증 (`11-testing.md`)

자동화 테스트로 확인:

- [ ] Bedrock fake가 50% 실패 반환 → 서킷 Open → 다음 호출은 즉시 fallback (호출 카운트 0)
- [ ] Pinecone 5xx 응답 → 3회 retry + jitter 시간차 검증
- [ ] Pinecone fake가 모두 fail → Neo4j 단독으로 답변 생성 (PINECONE_DEGRADED 경고)
- [ ] DLQ 메시지가 자동 redrive되지 않음 (자동 처리 없음 검증)
- [ ] MAINTENANCE_MODE=true로 부팅 → 모든 query 503
- [ ] 글로벌 token bucket 초과 시 429 + Retry-After

## 11. 변경 시 영향 범위

- 새 의존성 추가 → §2 fallback 행 + §3 서킷 임계 + §4 retry + §5 timeout + §8 비용 사고 시나리오
- 서킷 임계 변경 → 운영 메트릭(`09`) 알람 임계 동기화
- 새 fallback 경로 → §2 + §8 + 02 §8 매트릭스 동시 갱신
- DLQ 자동 처리 도입 검토 → 이 docs §1 원칙 6 변경 + 비용 추정 재산정 필수
