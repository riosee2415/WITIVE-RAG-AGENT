# 01 — Architecture

본 서버 안에서 한 요청이 어떻게 흐르고, 외부와 어떻게 연결되며, 코드를 어떻게 배치하는지 정의한다.
이 문서는 골격만 잡는다. 각 단계의 알고리즘 디테일은 02·03이, 외부 SDK 호출 디테일은 04·05가 다룬다.

## 1. 두 가지 요청 흐름

본 서버가 받는 요청은 두 종류다.

### 1.1 질의 흐름 (동기 SSE)

```
Next.js → POST /internal/query
   │
   ▼
[Stage 1] Bedrock Claude Haiku 4.5로 질문 재작성
   │
   ▼
[Stage 2 검색] Pinecone + Neo4j 병렬 호출
   │
   ▼
[Stage 2 후처리] Cross-encoder 재랭킹 → 권한·버전 필터링
   │
   ▼
[Stage 2 생성] Bedrock Claude Sonnet 4.6 스트리밍
   │
   ▼
SSE 이벤트: rewritten_query → token… → sources → warnings → done
```

캐시 hit 시 Stage 1·2를 모두 생략하고 Redis에 저장된 결과를 동일한 SSE 이벤트로 그대로 흘린다.

상세는 `02-query-pipeline.md`.

### 1.2 문서 흐름 (동기 검증 + 비동기 Worker)

```
Next.js → POST /internal/documents/upload
   │
   ▼
[검증] MIME·크기·해시 중복 (동기, 빠르게 202 반환)
   │
   ▼
[S3 저장] 원본 파일을 KMS 암호화로 저장
   │
   ▼
[SQS 발행] doc_id, tenant_id, version, s3_path
                                              ┌── 이 시점에 Next.js에 202 반환
                                              │
[ECS Worker가 SQS 소비] ────────────────────────┘
   │
   ▼
파싱 → 청킹 → 임베딩 → Pinecone + Neo4j 색인 → 상태 갱신
```

Next.js는 `GET /internal/documents/jobs/{job_id}`로 상태를 폴링한다.

상세는 `03-document-pipeline.md`.

### 1.3 두 흐름의 결정 근거

| 작업 | 처리 형태 | 이유 |
|---|---|---|
| 질문 → 답변 | 동기 SSE | 사용자 체감 응답성이 최우선. 첫 토큰 P95 ≤ 3s |
| 캐시 hit | 동기 SSE (동일 인터페이스) | Next.js·클라이언트 입장에서 캐시 hit 여부를 몰라도 됨 |
| 문서 업로드 | 검증·S3 저장은 동기, 파싱·임베딩·색인은 SQS Worker | 100MB 파일도 빠르게 202 반환, 무거운 단계는 재시도·DLQ가 필요 |
| 작업 상태 조회 | 동기 GET | Next.js 폴링 |

## 2. 외부 의존성

| 의존성 | 용도 | 라이브러리 | 동기/비동기 |
|---|---|---|---|
| AWS Bedrock | Claude Haiku/Sonnet 호출, Titan Embeddings v2 | `aioboto3` | async |
| Pinecone | 벡터 upsert·검색 | `pinecone` 공식 SDK의 `PineconeAsyncio` / `IndexAsyncio` | async (네이티브) |
| Neo4j | 그래프 노드/관계 저장·검색 | `neo4j` async driver | async |
| AWS S3 | 원본 문서 read/write | `aioboto3` | async |
| AWS SQS | 문서 파이프라인 큐 | `aioboto3` | async |
| ElastiCache (Redis) | 쿼리·메타·사용자 캐시 | `redis` async client | async |
| AWS Textract | 스캔 PDF OCR | `aioboto3` | async |
| Cross-encoder | 재랭킹 (CPU/GPU 추론) | `sentence-transformers` | sync→async wrap |

본 서버는 위 의존성을 **호출만 한다**. 인프라 리소스(Index 생성, DB 생성, IAM 정책, KMS 키) 자체를 만드는 코드는 본 서버에 없다 (`00-scope.md` §2.3).

각 의존성의 단독 장애 시 fallback 정책은 `08-resilience.md`. 데이터 스키마와 접근 패턴은 `04-data-stores.md`.

## 3. 코드 레이어

```
app/
├── api/         FastAPI router (HTTP/SSE 엔드포인트)
├── domain/      도메인 모델·값 객체 (외부 라이브러리 의존 0)
├── pipeline/    유즈케이스 (도메인 + infra 어댑터 조합)
├── infra/       외부 의존성 어댑터 (도메인 ↔ 외부 SDK 변환)
├── platform/    횡단 관심사 (config, logging, tracing, retry, auth, metrics)
└── workers/     SQS 소비자 entry point
```

### 3.1 의존 방향

```
api ──→ pipeline ──→ infra
              ↓
            domain
              ↑
            infra
```

- `domain`은 어디에도 의존하지 않는다 (외부 라이브러리도 금지)
- `pipeline`은 `domain`과 `infra`를 조합한다. 외부 SDK를 직접 부르지 않는다
- `api`는 `pipeline`만 호출한다. 외부 SDK를 직접 부르지 않는다
- `infra`끼리 직접 의존하지 않는다 (필요하면 `pipeline`에서 조합)
- `platform`은 누구나 사용 가능

### 3.2 이 분리의 효과

- Bedrock 모델이나 SDK가 바뀌어도 `infra/bedrock`만 수정하면 된다 — 도메인·유즈케이스 영향 없음
- 단위 테스트에서 `infra`를 fake로 갈아끼우면 도메인·유즈케이스만 검증 가능 (`11-testing.md`)
- 새 외부 의존성 추가 시 패턴이 강제됨 (`infra/<name>` 모듈 추가)

각 레이어 안의 모듈 이름·파일 분리 규칙은 `12-coding-conventions.md` §모듈에서 다룬다. 본 1단계에서는 더 깊게 들어가지 않는다.

## 4. 처리 시간 예산 (P95)

ARC §4.1을 본 서버 관점에서 재정렬:

```
[Stage 1] ≤ 1.5s
  헤더 → TenantContext 변환:        50ms
  Bedrock Claude Haiku 호출:     1,300ms
  결과 검증 + fallback 판단:        150ms

[Stage 2 검색·생성] ≤ 8.5s
  Bedrock Titan v2 임베딩:         300ms   (Stage 1 직후, Pinecone에 필요)
  Pinecone + Neo4j 병렬 검색:    1,000ms   (Neo4j timeout 기준 max)
  Cross-encoder 재랭킹:            300ms
  버전·권한 필터:                    50ms
  chunk 본문 일괄 로드:            100ms   (Neo4j MATCH 또는 S3 chunks.jsonl, 04 §5)
  Bedrock Sonnet TTFT:             800ms
  Bedrock Sonnet 전체 생성(스트림): 6,000~7,000ms

본 서버 내부 합산 (P95)
  첫 토큰 출력까지: 1.5 + 0.3 + 1.0 + 0.3 + 0.05 + 0.1 + 0.8 ≈ 4.05s
  전체 완료까지:    위 + 6.0~7.0 ≈ 10.0~11.0s
```

Next.js 프록시·네트워크 오버헤드(약 0.5s)는 본 서버 예산 밖이다. **본 서버 내부 첫 토큰 P95 SLO = 4.0s**로 갱신한다 (cold 요청 기준). 클라이언트 체감 첫 토큰 P95는 4.5s.

**PRD §6의 클라이언트 체감 P95 ≤ 3s는 본 서버 단독으로는 달성 불가능 — SLA 재합의 필요**:

P95 percentile 정의상 hit/miss 비율이 r:(1-r)일 때 P95(혼합) ≈ cold_p95 (단, 1-r > 0.05일 때) / cache_p95 (1-r ≤ 0.05일 때). 즉 P95 자체를 cache_p95로 끌어내리려면 **r ≥ 0.95** 필요. r=0.5는 평균(P50)을 단축할 뿐 P95에는 영향 미미.

본 서버 docs의 명시적 SLO (PRD와 협의 갱신 트리거):

| 지표 | 본 서버 SLO | 비고 |
|---|---|---|
| 본 서버 내부 첫 토큰 P95 (cold) | **4.0s** | §1·§3 합산 산정 |
| 본 서버 내부 첫 토큰 P95 (cache hit) | **0.1s** | Redis lookup + SSE |
| 본 서버 내부 첫 토큰 **P50** | **≤ 2.5s** (r ≥ 0.5 가정) | 평균 체감 단축 |
| 클라이언트 체감 첫 토큰 P95 | **≤ 4.5s (cold)** / **≤ 3s (r ≥ 0.95일 때만)** | 네트워크 0.5s 합산 |

**PRD §6의 P95 ≤ 3s 달성 옵션** (택1 또는 조합):
- (a) cold cold_p95 자체를 ≤ 3s로 끌어내리는 추가 최적화 — Stage 1 + 임베딩 병렬, Neo4j timeout 단축, Bedrock Provisioned Throughput 등 (모두 비용·복잡도 증가)
- (b) PRD §6 SLA 자체를 **P95 → P50 또는 평균 ≤ 3s**로 변경하도록 ref와 협의 (가장 현실적 — 3s가 사용자 체감 평균이라면 P50/평균 metric이 더 적합)
- (c) 매우 높은 캐시 hit ratio(≥ 0.95) 가정 — 운영상 비현실적

`query_cache_hit_ratio` 메트릭은 평균 체감 단축에 여전히 중요. 알람: < 0.5 (15분) → Redis 용량/TTL 검토.

Bedrock prompt cache는 latency 영향 minor, **입력 토큰 비용 절감** 효과(`05-llm-bedrock.md` §4).

추가 단축 수단(미채택, 필요 시 검토): (a) embedding을 원본 질문으로 사전 시작하고 Stage 1 결과로 재계산 — 비용 2배. (b) Neo4j timeout 단축 또는 일부 케이스에서 Neo4j 우회. (c) cross-encoder 경량화·캐시.

## 5. 환경별 변동

| 항목 | dev | staging | prod |
|---|---|---|---|
| Stage 1 모델 | Haiku 4.5 | Haiku 4.5 | Haiku 4.5 |
| Stage 2 모델 | Haiku 4.5 (비용 절감) | Sonnet 4.6 | Sonnet 4.6 |
| Neo4j | 사용 안 함 (Pinecone 단독) | Enterprise EC2 | Enterprise EC2 |
| Redis | 단일 t3.micro | 단일 t3.micro | t3.small Multi-AZ |
| Redis TTL | 300s 고정 | 60s 고정 | 60s 적응형 |
| Worker 동시 처리 | 1 | 2 | 환경 변수로 가변 (기본 4) |
| 로그 레벨 | DEBUG | INFO | INFO |
| X-Ray 샘플링 | 100% | 50% | 10% (오류는 100%) |

상세 환경 변수 정의는 `10-config-and-secrets.md`.

## 6. 확장 포인트 (참고)

본 architecture는 다음 변경을 흡수할 수 있게 설계되었다:

- Bedrock 모델 추상화 (`infra/bedrock`에 `LLMAdapter` 도입)
- Stage 1 다중 플러그인 (의도 분류, 민감도 판단)
- 한국어 형태소 청킹 (`pipeline/document/chunker.py` 교체)
- Pinecone/Neo4j 색인 분리 이벤트화 (한쪽 실패가 다른 쪽 검색을 막지 않도록)

위 변경은 모두 `pipeline` 또는 `infra` 안에서 끝나야 한다. `domain` 변경이 동반된다면 본 docs `01`·`13` 동시 갱신.
