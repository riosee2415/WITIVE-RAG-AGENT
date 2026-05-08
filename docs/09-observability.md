# 09 — Observability

본 서버의 구조 로그·메트릭·분산 추적 단일 진실 출처. 알람·대시보드 정의의 기준.
이 docs도 둘째 목적은 **CloudWatch·X-Ray 비용 가드레일** — Custom metric 카디널리티, 로그 retention, X-Ray 샘플링은 모두 직접 비용을 발생시키므로 정책 결정이 운영비에 즉각 반영된다.

## 1. 로깅

### 1.1 라이브러리·포맷

- 라이브러리: `structlog` + `python-json-logger`
- 출력: JSON (CloudWatch Logs Insights 쿼리 친화)
- destination: stdout → ECS awslogs → CloudWatch Logs group `/ecs/witive-rag-{env}`

### 1.2 표준 필드 (모든 로그)

| key | 타입 | 의미 |
|---|---|---|
| `timestamp` | ISO 8601 | 자동 |
| `level` | enum | DEBUG / INFO / WARNING / ERROR / CRITICAL |
| `logger` | str | 모듈 경로 (예: `app.pipeline.query.orchestrator`) |
| `message` | str | 사람 가독 메시지 |
| `request_id` | str | TenantContext.request_id (요청 추적) |
| `tenant_id` | str | 테넌트 식별 (PII 아님) |
| `user_id` | str | uuid (PII이지만 감사 필요) |
| `event` | str | 머신 가독 이벤트 코드 (예: `query.stage1.completed`) |
| `duration_ms` | int (optional) | 단계 소요 시간 |
| `error.code`, `error.type`, `error.stack` | optional | 예외 시 |

`event` 코드는 enum으로 관리 (`platform/logging.py`의 `LogEvent` 상수). free-form 문자열 금지 — 로그 쿼리·알람 안정성.

### 1.3 PII·민감 정보 정책

| 데이터 | 로그 기록 |
|---|---|
| 사용자 질문 본문 | **로그 금지**. SHA-256 해시만 (`question_hash`) |
| 답변 본문 | **로그 금지**. 토큰 수만 |
| 사용자 이름·이메일 | 로그 금지 (Next.js 책임) |
| `user_id` (uuid) | 기록 OK (감사용) |
| `conversation_id` (uuid) | 기록 OK — 본 서버는 uuid7 형식만 허용 (06 §3.1 검증). 비-uuid 텍스트가 들어오면 400 거부 → 로그 노출 차단 |
| Pinecone vector 값 | **로그 금지** (배열 자체) |
| 시스템 프롬프트 | DEBUG 레벨에서만 (해시도 가능) |
| Bedrock 응답 본문 | DEBUG 레벨 + 환경 변수 게이트 (`LOG_LLM_RESPONSE_BODY=false` 기본) |

### 1.4 로그 레벨 정책 (환경별)

| 환경 | 레벨 | retention |
|---|---|---|
| dev | DEBUG | 7일 |
| staging | INFO | 30일 |
| prod | INFO | 90일 (CloudWatch) → S3 WORM 275일 (감사) |

DEBUG 레벨은 prod에서 끄기 — 분당 수만 라인이 CloudWatch Logs 비용($0.50/GB ingest + $0.03/GB stored) 폭증.

### 1.5 샘플링 (비용 가드레일)

| 로그 유형 | 샘플링 |
|---|---|
| INFO 이상 | 100% |
| DEBUG | dev 100% / staging 10% / prod 1% (조건부 — 특정 request_id에 대해서만 강제 100%) |
| 스팸 가능 이벤트 (`heartbeat`, `cache_hit_check`) | 1% 샘플 또는 비활성 |
| 에러 발생 request_id의 모든 로그 | 100% (debug 포함, 1시간 trace lookback) |

샘플링은 `structlog` processor로 구현. `request_id`별 결정적 샘플링 (hash mod) → 같은 요청의 모든 로그가 함께 보이거나 함께 누락.

### 1.6 핵심 이벤트 카탈로그

`event` 필드 표준 값. 변경 시 본 docs와 알람 룰 동시 수정.

| event | 발생 위치 | level |
|---|---|---|
| `query.received` | api/query.py | INFO |
| `query.cache.hit` / `miss` | pipeline/query/orchestrator | INFO |
| `query.stage1.completed` / `failed` / `fallback` | stage1_rewriter | INFO / WARN |
| `query.stage2.retrieval.completed` / `degraded` | stage2_retrieve | INFO / WARN |
| `query.stage2.rerank.completed` / `degraded` | stage2_rerank | INFO / WARN |
| `query.stage2.generation.completed` / `degraded` / `cancelled` | stage2_generate | INFO / WARN |
| `query.completed` / `failed` | orchestrator | INFO / ERROR |
| `document.upload.received` / `validated` / `s3_uploaded` / `sqs_published` | api/documents | INFO |
| `document.worker.message.received` / `locked` / `released` | worker | INFO |
| `document.worker.parse.completed` / `failed` | parsers | INFO / ERROR |
| `document.worker.embed.completed` / `partial_failed` | embedder | INFO / WARN |
| `document.worker.index.stage_a.completed` / `failed` | indexer | INFO / WARN |
| `document.worker.index.stage_b.completed` / `partial_success` / `failed` | indexer | INFO / WARN / ERROR |
| `circuit.open` / `half_open` / `closed` | platform/circuit_breaker | WARN / INFO |
| `backpressure.triggered` | platform/rate_limiter | WARN |
| `audit.cleanup.completed` | api/admin | INFO |

## 2. 메트릭

### 2.1 발행 방식

CloudWatch Embedded Metric Format (EMF) — 로그 라인에 메트릭 메타를 함께 박는 방식. 별도 PutMetricData 호출 없음 (네트워크 비용 0).

라이브러리: `aws-embedded-metrics-python` 또는 자체 구현 (`platform/metrics.py`).

### 2.2 namespace 정책 (비용 가드레일)

| namespace | 용도 | 카디널리티 정책 |
|---|---|---|
| `WitiveRagAi` | 기본 메트릭 (모델·stage·코드 dimension) | tenant_id 라벨 미발행 — 카디널리티 폭발 방지 |
| `WitiveRagAi/PerTenant` | per-tenant 추적 | `PER_TENANT_METRIC_TENANT_IDS` 화이트리스트 등록 테넌트만. 기본 0개 |

CloudWatch custom metric 비용: $0.30/metric/월. 메트릭 8종 × 테넌트 1,000개 = 월 $2,400 위험 → 화이트리스트 ≤ 50개로 운영 (≤ $120/월).

### 2.3 메트릭 카탈로그

#### 질의 (queries)

| metric | unit | dimensions | 의미 |
|---|---|---|---|
| `queries_total` | Count | `result` (success / no_results / error) | 분당 질의 수 |
| `query_latency_first_token_ms` | Milliseconds (Histogram) | `cache_hit` (true/false) | 첫 토큰까지 |
| `query_latency_total_ms` | Milliseconds (Histogram) | `cache_hit` | 완료까지 |
| `query_cache_hit_total` | Count | `stage` (q1 / q2) | 캐시 hit 수 |
| `query_cache_miss_total` | Count | `stage` | 캐시 miss 수 |
| `query_low_confidence_total` | Count | — | 0.60~0.75 |
| `query_no_results_total` | Count | — | 0건 또는 < 0.55 |
| `query_version_conflict_total` | Count | — | 충돌 감지 |
| `query_executive_postfilter_drop_total` | Count | — | post-filter 폐기 청크 수 |
| `query_stage1_fallback_total` | Count | `reason` (timeout/throttle/5xx/empty/circuit) | Stage 1 fallback 발생 — 08 §8 알람 산식 입력 (`/queries_total > 20% for 30min` High 알람) |

#### Bedrock (비용 직결)

| metric | unit | dimensions | 의미 |
|---|---|---|---|
| `bedrock_input_tokens_total` | Count | `model`, `stage` | 입력 토큰 |
| `bedrock_output_tokens_total` | Count | `model`, `stage` | 출력 토큰 |
| `bedrock_cache_read_tokens_total` | Count | `model`, `stage` | prompt cache hit (절감 효과 가시화) |
| `bedrock_cache_write_tokens_total` | Count | `model`, `stage` | prompt cache write |
| `bedrock_call_duration_ms` | Milliseconds | `model`, `stage` | 호출 latency |
| `bedrock_throttle_total` | Count | `model` | ThrottlingException |
| `bedrock_error_total` | Count | `model`, `code` | 5xx / timeout |
| `bedrock_estimated_cost_usd` | None — 호출당 dollar 값 1회 발행 | `model` | 환산 비용. CloudWatch에서 `Sum` statistic으로 분/시간/일 단위 집계 (`Gauge` metric type은 EMF에 없음) |

#### Pinecone / Neo4j / Redis / S3

| metric | unit | dimensions |
|---|---|---|
| `pinecone_query_duration_ms`, `pinecone_upsert_duration_ms`, `pinecone_delete_duration_ms` | Milliseconds | `operation` |
| `pinecone_error_total` | Count | `operation`, `code` |
| `neo4j_query_duration_ms`, `neo4j_transaction_duration_ms` | Milliseconds | `operation` |
| `neo4j_error_total` | Count | `code` |
| `redis_op_duration_ms` | Milliseconds | `op` (get/set/incr) |
| `redis_error_total` | Count | `code` |
| `s3_op_duration_ms` | Milliseconds | `op` (get/put/range) |

#### 색인 파이프라인

| metric | unit | dimensions |
|---|---|---|
| `documents_indexed_total` | Count | `result` (success / partial / failed) |
| `chunks_indexed_total` | Count | — |
| `parse_duration_seconds`, `embed_duration_seconds`, `index_duration_seconds` | Seconds (Histogram) | `format` (pdf/docx/xlsx/url/ocr) |
| `dlq_messages_visible` | Count | — (CloudWatch Auto, AWS/SQS namespace) |
| `staging_artifacts_count` | Count | — | cleanup endpoint가 발행 |

#### 서킷·backpressure

| metric | unit | dimensions |
|---|---|---|
| `circuit_state` | None (Gauge: 0=closed, 1=half_open, 2=open) | `dependency` |
| `circuit_transition_total` | Count | `dependency`, `to_state` |
| `backpressure_triggered_total` | Count | `reason` |

### 2.4 비용 메트릭 가시화

`bedrock_estimated_cost_usd`는 호출당 환산 비용을 metric value로 발행하고 CloudWatch에서 `Sum` statistic으로 분/시간/일 단위 집계해 운영팀에 노출한다 (EMF 표준 — Gauge 타입 아님).

산출 (호출 직후 1회 발행):
```
cost = (input_tokens × input_price + output_tokens × output_price + cache_read × cache_read_price) / 1_000_000
```

단가는 환경 변수로 주입 (`05 §1.3`의 모델 ID와 매핑):
- `BEDROCK_PRICE_INPUT_HAIKU_USD_PER_1M`
- `BEDROCK_PRICE_OUTPUT_HAIKU_USD_PER_1M`
- `BEDROCK_PRICE_CACHE_READ_HAIKU_USD_PER_1M` (caching 적용 시)
- (Sonnet, Titan 동일)

운영팀이 AWS 가격 변경 시 환경 변수만 갱신.

## 3. 분산 추적 (X-Ray)

### 3.1 라이브러리

`aws-xray-sdk-python` (또는 OpenTelemetry + AWS X-Ray exporter — Phase 4 검토). 1차는 X-Ray SDK 직접.

### 3.2 샘플링 정책 (비용 가드레일)

X-Ray 비용: $5 / 1M traces. 1,000 RPS 100% 샘플링이면 월 $13,000+.

| 환경 | 기본 샘플링 | 강제 100% (단, reservoir 상한) |
|---|---|---|
| dev | 100% | — |
| staging | 50% | 5xx 에러 |
| prod | **10%** | 5xx 에러, P95 SLO 위반(latency > 4s), backpressure 발생, 서킷 transition |

샘플링 결정은 X-Ray 콘솔의 sampling rule에 정의. 본 서버 코드에서는 `xray_recorder` 호출 시 자동 적용.

#### 강제 100%의 비용 상한 (reservoir + fixedRate, M-3)

광범위 사고(Bedrock 장기 장애로 모든 요청 5xx 등) 시 강제 100% 트리거가 X-Ray 비용을 평소의 10배로 끌어올릴 수 있다 — 사고 시점에 비용도 함께 폭증하는 안티패턴. AWS X-Ray sampling rule의 `reservoir + fixedRate` 조합으로 상한:

| 환경 | reservoir (분당 보장 샘플) | 초과분 fixedRate |
|---|---|---|
| dev | 무제한 | — |
| staging | 50/min | 20% |
| prod | **100/min** | **10%** (기본 샘플링과 동일) |

이 reservoir 상한은 X-Ray 콘솔 또는 IaC(Terraform `aws_xray_sampling_rule`)에서 관리. 본 docs는 정책 단일 진실 출처만 명시.

운영 효과: 정상 트래픽 1,000 RPS → trace 발행 = 100 RPS(reservoir) + 9,900 × 10% = 1,090 RPS. 사고 트래픽 1,000 RPS 100% 후보 → 100 RPS reservoir + 9,900 × 10% = 1,090 RPS (폭증 회피).

### 3.3 Span 명세

| span name | parent | attributes |
|---|---|---|
| `query.handle` | (root) | `request_id`, `tenant_id`, `cache_hit` |
| `query.cache.lookup` | query.handle | `key_class` (q1/q2), `result` |
| `query.stage1` | query.handle | `model`, `fallback_used` |
| `query.stage2.retrieve` | query.handle | (sub-spans) |
| `query.stage2.retrieve.pinecone` | retrieve | `top_k`, `result_count`, `max_score` |
| `query.stage2.retrieve.neo4j` | retrieve | `result_count` |
| `query.stage2.embed` | retrieve (sibling) | `model`, `dimension` |
| `query.stage2.rerank` | query.handle | `input_count`, `output_count`, `degraded` |
| `query.stage2.fetch_text` | query.handle | `source` (neo4j/s3), `count` |
| `query.stage2.generate` | query.handle | `model`, `tokens.input`, `tokens.output`, `tokens.cache_read` |
| `document.handle_upload` | (root) | `tenant_id`, `doc_id`, `file_size`, `mime` |
| `document.worker.process` | (root) | `job_id`, `attempt` |
| `document.worker.parse` | process | `format` |
| `document.worker.chunk` | process | `chunk_count` |
| `document.worker.embed` | process | `chunk_count`, `batch_count` |
| `document.worker.index.stage_a` | process | `pinecone_ok`, `neo4j_ok` |
| `document.worker.index.stage_b` | process | `step`, `step_retries` |

### 3.4 외부 호출 자동 추적

`aws-xray-sdk` patch:
- `boto3` → 모든 AWS 호출 (Bedrock, S3, SQS) 자동 sub-span
- `redis` → 자동 sub-span
- `httpx` (URL 파서) → 자동
- Pinecone·Neo4j는 SDK 자체 X-Ray 통합 없음 → 본 서버 어댑터에서 명시적 sub-span

## 4. 알람 (CloudWatch)

핵심 알람만 정리. SNS topic으로 PagerDuty/Slack 라우팅 (운영팀 책임).

### 4.1 Critical (즉시 호출, 24/7)

| 알람 | 임계 | 근거 |
|---|---|---|
| `dlq_messages_visible > 0` | 1건 (1분) | `08 §7` 자동 redrive 금지 — 즉시 수동 처리 |
| `bedrock_cache_read_tokens_total = 0 for 24h` (stage=2) | 24시간 | `05 §4.3` 캐시 미형성 의심 (비용 5배) |
| `circuit_state{dependency=bedrock} = 2 for 5m` | 5분 연속 Open | Bedrock 장기 장애 |
| `circuit_state{dependency=redis} = 2 for 5m` | 5분 | Redis 장기 장애 (비용 폭증 위험) |
| `bedrock_estimated_cost_usd` (1시간 합산) | 시간 평균의 2배 초과 | 비정상 트래픽 또는 prompt cache 미형성 |
| `query_no_results_rate > 30%` (1시간) | 30% | RAG 품질 회귀 |

### 4.2 High (1시간 이내 대응)

| 알람 | 임계 |
|---|---|
| `query_latency_first_token_ms` P95 > 5s (15분) | SLO(4s) 초과 |
| `bedrock_throttle_total > 100/min` (5분) | quota 부족 가능성 |
| `pinecone_error_total > 50/min` (5분) | Pinecone 장애 시작 |
| `neo4j_error_total > 50/min` (5분) | Neo4j 장애 시작 |
| `query_cache_hit_ratio < 0.3` (30분) | 캐시 효율 저하 |

### 4.3 Medium / Low

| 알람 | 임계 |
|---|---|
| `query_cache_hit_ratio < 0.5` (15분) | `01 §4` SLO 가정 위반 |
| `documents_indexed_total{result=failed} > 5/hour` | 색인 실패 누적 |
| `query_low_confidence_rate > 20%` (1시간) | 문서 공백 가능성 |
| `query_executive_postfilter_drop_total > 100/min` | EXECUTIVE 캐시 키 정책 재검토 신호 |

## 5. 대시보드 (CloudWatch Dashboard)

운영팀이 매일 보는 대시보드는 본 서버 docs 외 책임이지만, 본 서버 메트릭이 포함되어야 할 패널:

- 분당 질의 수 / 캐시 hit ratio / 첫 토큰 P50/P95
- Bedrock 분당 토큰 (입력/출력/cache_read) / 추정 시간당 비용
- 의존성별 서킷 상태 게이지
- DLQ 메시지 수 / 색인 처리량
- backpressure 발생 빈도

## 6. 구조 로그 검색 패턴 (운영 가이드)

CloudWatch Logs Insights 쿼리 예시:

```
# 특정 요청의 전체 흐름
fields @timestamp, level, event, duration_ms
| filter request_id = "req-..."
| sort @timestamp asc

# 어제 LOW_CONFIDENCE 발생 질의 패턴
fields tenant_id, count(*) as cnt
| filter event = "query.completed" and warnings like /LOW_CONFIDENCE/
| stats count(*) by tenant_id
| sort cnt desc

# Bedrock 비용 시간당
fields strftime(@timestamp, '%H') as hour, sum(bedrock_input_tokens + bedrock_output_tokens) as tokens
| filter event = "query.stage2.generation.completed"
| stats sum(tokens) by hour
```

## 7. 비용 요약 (경제성 가드레일 모음)

| 결정 | 절감 |
|---|---|
| EMF 메트릭 (PutMetricData 미사용) | 분당 PutMetricData 호출 비용 0 |
| `tenant_id` 라벨 화이트리스트 (≤ 50개) | 메트릭당 $0.30/월 × 미발행 950개 = 월 $285 절감/메트릭 |
| X-Ray prod 10% 샘플링 + 에러 강제 100% | 1,000 RPS 기준 월 $11,700 절감 ($13K → $1.3K) |
| DEBUG 로그 prod 1% 샘플링 | 로그 ingest 비용 99% 절감 |
| 로그 stdout → awslogs (kinesis 미사용) | kinesis stream 비용 회피 |
| `/health` 가벼운 ping | Bedrock 호출 회피 (`06 §6.1`) |
| `bedrock_estimated_cost_usd` 가시화 | 비용 사고 즉시 감지 → 평균 24h 단축으로 사고당 수십~수백 달러 절감 |

## 8. 변경 시 영향 범위

- 새 metric 추가 → §2.3 카탈로그 + 화이트리스트 정책(§2.2) + 알람 임계(§4)
- 새 log event 추가 → §1.6 카탈로그 + Logs Insights 쿼리 영향
- X-Ray span 추가 → §3.3 + 샘플링 비용 영향 평가
- 알람 임계 변경 → 본 docs §4 + SOP (운영팀)
- 가격 변동 (Bedrock) → 환경 변수만 (코드 변경 없음, `05 §1.3`)
