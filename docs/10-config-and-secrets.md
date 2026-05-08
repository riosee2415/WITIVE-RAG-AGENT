# 10 — Config & Secrets

본 서버의 모든 환경 변수와 시크릿의 단일 진실 출처. 다른 docs(02·03·05·06·07·08·09)에서 정의된 변수를 한 곳에 모으고, 환경별(dev/staging/prod) 차이와 시크릿 관리 정책을 명시한다.

## 1. 설정 라이브러리

`pydantic-settings` 사용. 모든 설정을 `Settings(BaseSettings)` 단일 클래스로 관리. 환경 변수 → 검증 → 타입 안전 컨텍스트로 주입.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid",                   # 모르는 env 변수 거부 (오타 방지)
    )
    ...
```

설정 누락·형식 오류는 **앱 시작 시 즉시 fail**. 런타임 도중 None 분기 회피.

## 2. 환경 변수 카탈로그

### 2.1 서버·런타임

| 변수 | 기본값 (prod) | 출처 docs | 설명 |
|---|---|---|---|
| `ENV` | `prod` | — | `dev` / `staging` / `prod` |
| `LOG_LEVEL` | `INFO` | 09 §1.4 | DEBUG / INFO / WARNING / ERROR |
| `MAX_EXPECTED_TASKS` | `20` | 05 §5.2 | ECS Auto Scaling max — Redis 장애 fallback 산정 |
| `MAINTENANCE_MODE` | `false` | 08 §3.3 | true 시 모든 query 503 |

### 2.2 인증·헤더

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `INTERNAL_AUTH_SECRET_PRIMARY` | (Secrets Manager) | 00 §3.1 | dual-key 회전 — 신규 |
| `INTERNAL_AUTH_SECRET_SECONDARY` | (Secrets Manager) | 00 §3.1 | dual-key 회전 — 구 |
| `LEVEL_RANK_JSON` | `{"사원":1,"주임":2,...}` | 07 §1.4 | 직급 → 정수 매핑 |
| `SYSTEM_CRON_USER_ID` | `00000000-0000-0000-0000-000000000001` | 00 §3.2 | 시스템 호출 reserved |

### 2.3 Bedrock·LLM

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `BEDROCK_REGION` | `ap-northeast-2` | 05 §1.3 | |
| `BEDROCK_MODEL_STAGE1` | `anthropic.claude-haiku-4-5-v1:0` | 05 §1.3 | 모델 ID 또는 inference profile ARN |
| `BEDROCK_MODEL_STAGE2` | `anthropic.claude-sonnet-4-6-v1:0` (dev: Haiku) | 05 §1.3 | |
| `BEDROCK_MODEL_EMBEDDING` | `amazon.titan-embed-text-v2:0` | 05 §1.3 | |
| `STAGE1_TIMEOUT_S` | `3.0` | 02 §4.1 | |
| `STAGE2_GEN_TIMEOUT_S` | `30` | 02 §5.7 | 전체 생성 |
| `STAGE1_MAX_TOKENS` | `300` | 02 §4.1 | |
| `STAGE2_MAX_TOKENS` | `1024` | 02 §5.7 | |
| `STAGE1_TEMP` | `0.1` | 02 §4.1 | |
| `STAGE2_TEMP` | `0.3` | 02 §5.7 | |
| `STAGE1_TOP_P` | `1.0` | 05 §6 | |
| `STAGE2_TOP_P` | `0.9` | 05 §6 | |
| `STAGE2_SYSTEM_PROMPT_TARGET_TOKENS` | `1200` | 05 §4.2 | prompt cache 형성 목표 |
| `STAGE2_SYSTEM_PROMPT_MIN_TOKENS` | `1024` | 05 §4.2 | 빌드 warn 임계 |
| `BEDROCK_TITAN_RPS_LIMIT` | `30` | 05 §5.2 | 글로벌 RPS 한도 |
| `BEDROCK_TITAN_BURST` | `60` | 05 §5.2 | token bucket capacity |
| `EMBED_BATCH_SIZE` | `20` | 05 §5.2 / 03 §3.5 | 동시 호출 |
| `MAX_CONCURRENT_EMBED_BATCHES` | `4` | 05 §5.2 / 03 §3.5 | 동시 배치 |
| `EMBED_QUERY_TIMEOUT_MS` | `300` | 02 §5.1 | 검색용 임베딩 |

#### 비용 단가 (09 §2.4)

| 변수 | 단위 | 비고 |
|---|---|---|
| `BEDROCK_PRICE_INPUT_HAIKU_USD_PER_1M` | USD | 백만 토큰당 |
| `BEDROCK_PRICE_OUTPUT_HAIKU_USD_PER_1M` | USD | |
| `BEDROCK_PRICE_CACHE_READ_HAIKU_USD_PER_1M` | USD | prompt cache hit |
| `BEDROCK_PRICE_INPUT_SONNET_USD_PER_1M` | USD | |
| `BEDROCK_PRICE_OUTPUT_SONNET_USD_PER_1M` | USD | |
| `BEDROCK_PRICE_CACHE_READ_SONNET_USD_PER_1M` | USD | |
| `BEDROCK_PRICE_INPUT_TITAN_USD_PER_1M` | USD | |

운영팀이 AWS 가격 변경 시 환경 변수만 갱신. 코드 변경 없음.

### 2.4 Pinecone

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `PINECONE_API_KEY` | (Secrets Manager) | 04 §1.2 | |
| `PINECONE_TOP_K` | `10` | 02 §5.1 | |
| `PINECONE_TIMEOUT_MS` | `500` | 02 §5.1 | |
| `PINECONE_UPSERT_BATCH` | `100` | 03 §3.6 | |
| `SIM_THRESHOLD_HIGH` | `0.75` | 02 §5.2 | |
| `SIM_THRESHOLD_LOW` | `0.60` | 02 §5.2 | |
| `SIM_THRESHOLD_FALLBACK` | `0.55` | 02 §5.2 | |

### 2.5 Neo4j

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `NEO4J_URI` | (Secrets Manager) | 04 §2.1 | `bolt://...` |
| `NEO4J_USER` | (Secrets Manager) | 04 §2.1 | |
| `NEO4J_PASSWORD` | (Secrets Manager) | 04 §2.1 | |
| `NEO4J_LIMIT` | `10` | 02 §5.1 | query LIMIT |
| `NEO4J_TIMEOUT_MS` | `1000` | 02 §5.1 | query timeout |
| `NEO4J_USE_APOC` | `false` | 04 §2.4 | APOC 사용 분기 |
| `NEO4J_USE_TOKENIZED_FIELD` | `false` | 04 §2.3 | 한국어 형태소 토큰 컬럼 사용 |
| `CHUNK_TEXT_NEO4J_TIMEOUT_MS` | `100` | 02 §5.6 | 본문 fetch |
| `NEO4J_MAX_TRANSACTION_RETRY_TIME_S` | `5` | 04 §2.5 | driver 자동 retry 시간 한도 (TransientError) |

dev 환경은 Neo4j 미사용 — 위 변수 모두 빈 값 허용.

### 2.6 S3·KMS

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `S3_BUCKET_DOCS` | `witive-docs` | 04 §3.1 | |
| `S3_REGION` | `ap-northeast-2` | — | |
| `KMS_KEY_ALIAS_PREFIX` | `alias/witive-tenant-` | 04 §3.2 | + tenant_id |
| `MAX_UPLOAD_BYTES` | `104857600` (100MB) | 03 §2.1 | |
| `ALLOWED_MIME_TYPES` | (csv) | 03 §2.1 | |
| `CHUNK_TEXT_S3_TIMEOUT_MS` | `500` | 02 §5.6 | byte-range fetch |

### 2.7 Redis (ElastiCache)

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `REDIS_URL` | (Secrets Manager) | 04 §4 | `rediss://...` (TLS) |
| `REDIS_AUTH_TOKEN` | (Secrets Manager) | 04 §4 | |
| `QUERY_CACHE_TTL_BUSINESS_S` | `60` | 02 §3.4 | 업무시간 |
| `QUERY_CACHE_TTL_OFF_S` | `300` | 02 §3.4 | 그 외 |
| `CACHE_REPLAY_CHUNK_CHARS` | `32` | 02 §3.5 | hit 재생 chunk 크기 |
| `JOB_CACHE_TTL_S` | `5` | 03 §2.3 / 04 §4.1 | jobs 캐시 |
| `DUP_QUERY_WINDOW_S` | `60` | 02 §2.3 | 동일 질문 카운터 윈도 |
| `DUP_QUERY_THRESHOLD` | `3` | 02 §2.3 | 강제 캐시 임계 |
| `CACHE_INVALIDATE_RATE_PER_MIN` | `60` | 06 §3.2 / 08 §6 | tenant당 |

### 2.8 SQS·Worker

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `SQS_QUEUE_URL` | (env별 다름) | 03 §4.2 | |
| `SQS_DLQ_URL` | (env별 다름) | 03 §4.3 | |
| `SQS_VISIBILITY_TIMEOUT_S` | `300` | 03 §3.1 | |
| `MAX_CONCURRENT_DOCS` | `4` | 01 §5 / 03 §3.1 | Worker 동시 처리 |
| `WORKER_MESSAGE_DEADLINE_S` | `270` | 08 §5.2 | visibility 안 안전 마진 |

### 2.9 색인·청킹

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `CHUNK_SIZE_TOKENS` | `512` | 03 §3.3 | |
| `CHUNK_OVERLAP_TOKENS` | `50` | 03 §3.3 | |
| `CHUNK_MIN_TOKENS` | `50` | 03 §3.3 | |
| `CHUNK_MAX_TOKENS` | `1024` | 03 §3.3 | |
| `OCR_FALLBACK_CHAR_PER_PAGE` | `100` | 03 §3.2 | |
| `OCR_MIN_CONFIDENCE` | `0.70` | 03 §3.2 | |
| `CONFLICT_SIMILARITY_THRESHOLD` | `0.92` | 03 §3.7 | |
| `STAGE_B_STEP_RETRIES` | `3` | 03 §3.6 | |
| `STAGE_B_DEADLINE_S` | `60` | 03 §3.6 | |

### 2.10 입력 검증

| 변수 | 기본값 | 출처 docs | 설명 |
|---|---|---|---|
| `QUERY_MIN_LEN` | `1` | 02 §2.2 | |
| `QUERY_MAX_LEN` | `2000` | 02 §2.2 | |
| `RERANK_TOP_K` | `5` | 02 §5.3 | |
| `RERANK_TIMEOUT_MS` | `1500` | 02 §5.3 | |
| `MAX_CONCURRENT_SSE_CONNECTIONS` | `200` | 06 §1.7 / 08 §6 | Task당 |
| `QUERY_REQUEST_DEADLINE_S` | `60` | 08 §5.1 | top-level wait_for |
| `SLO_FIRST_TOKEN_P95_MS` | `4000` | 02 §7 / 09 §4.2 | 메트릭 알람 임계 (cold 첫 토큰) |

### 2.11 서킷 브레이커 (08 §3.1)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `CB_BEDROCK_FAIL_THRESHOLD` | `0.50` | |
| `CB_BEDROCK_WINDOW_S` | `10` | |
| `CB_BEDROCK_OPEN_S` | `30` | |
| `CB_PINECONE_FAIL_THRESHOLD` | `0.30` | |
| `CB_PINECONE_WINDOW_S` | `10` | |
| `CB_PINECONE_OPEN_S` | `30` | |
| `CB_NEO4J_FAIL_THRESHOLD` | `0.30` | |
| `CB_NEO4J_WINDOW_S` | `10` | |
| `CB_NEO4J_OPEN_S` | `30` | |
| `CB_REDIS_FAIL_THRESHOLD` | `0.50` | |
| `CB_REDIS_WINDOW_S` | `5` | |
| `CB_REDIS_OPEN_S` | `10` | |

### 2.12 관찰가능성 (09)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `XRAY_ENABLED` | `true` | |
| `EMF_NAMESPACE` | `WitiveRagAi` | 09 §2.2 |
| `EMF_NAMESPACE_PER_TENANT` | `WitiveRagAi/PerTenant` | |
| `PER_TENANT_METRIC_TENANT_IDS` | (empty) | csv 화이트리스트 ≤ 50 |
| `LOG_LLM_RESPONSE_BODY` | `false` | DEBUG 게이트 |

---

## 3. AWS Secrets Manager

### 3.1 경로 규칙

```
witive/{env}/{category}/{name}
```

| 경로 | 용도 |
|---|---|
| `witive/{env}/internal-auth-primary` | dual-key PRIMARY |
| `witive/{env}/internal-auth-secondary` | dual-key SECONDARY |
| `witive/{env}/pinecone-api-key` | |
| `witive/{env}/neo4j-credentials` | uri / user / password JSON |
| `witive/{env}/redis-credentials` | url / auth-token JSON |
| `witive/{env}/external/{tenant_id}/{integration_id}` | URL/API 등록 외부 토큰 (03 §5) |

### 3.2 ECS Task에서 시크릿 주입

`ecs.task_definition.containerDefinitions[].secrets[]`에 valueFrom으로 주입 → 컨테이너 시작 시 환경 변수로 들어감 (Pydantic settings가 자동 검증).

```json
{
  "name": "INTERNAL_AUTH_SECRET_PRIMARY",
  "valueFrom": "arn:aws:secretsmanager:ap-northeast-2:ACCOUNT:secret:witive/prod/internal-auth-primary"
}
```

본 서버 코드는 Secrets Manager API를 직접 호출하지 않는다. 인프라(Terraform/Harness)가 ARN을 task definition에 박는 것만으로 끝.

### 3.3 시크릿 회전 정책

| 시크릿 | 회전 주기 | 절차 |
|---|---|---|
| `internal-auth-primary/secondary` | 90일 | 00 §3.1 dual-key 절차 |
| `pinecone-api-key` | 1년 (Pinecone 콘솔에서 새 키 생성 후 교체) | 무중단: 새 키를 staging에 먼저 배포 후 prod 스왑 |
| `neo4j-credentials` | 90일 | Neo4j Enterprise admin password 변경 + Secrets Manager 업데이트 + ECS 재배포 |
| `redis-auth-token` | 90일 | ElastiCache rotation API + ECS 재배포 |
| `external/*` | 외부 시스템 정책 따름 | 만료 임박 알람 (CloudWatch metric on TTL) |

회전은 **운영팀(DevOps) 책임** — 본 서버 코드는 환경 변수 변경만 따라가면 됨.

---

## 4. 환경별 차이 매트릭스

| 항목 | dev | staging | prod |
|---|---|---|---|
| `ENV` | dev | staging | prod |
| `LOG_LEVEL` | DEBUG | INFO | INFO |
| Stage 1 모델 | Haiku | Haiku | Haiku |
| Stage 2 모델 | Haiku | Sonnet | Sonnet |
| Neo4j | 미사용 (env 비움) | Enterprise EC2 | Enterprise EC2 |
| Redis | t3.micro 단일 | t3.micro 단일 | t3.small Multi-AZ |
| `QUERY_CACHE_TTL_BUSINESS_S` | 300 | 60 | 60 |
| `QUERY_CACHE_TTL_OFF_S` | 300 | 60 | 300 (적응형) |
| `MAX_CONCURRENT_DOCS` | 1 | 2 | 4 |
| `MAX_EXPECTED_TASKS` | 2 | 5 | 20 |
| `MAX_CONCURRENT_SSE_CONNECTIONS` | 50 | 100 | 200 |
| `XRAY_ENABLED` | true | true | true |
| X-Ray sampling rule | 100% | 50% (+ 5xx 강제) | 10% (+ reservoir 100/min) |
| 로그 retention | 7일 | 30일 | 90일 (+ S3 WORM 275일) |
| `BEDROCK_TITAN_RPS_LIMIT` | 10 | 20 | 30 |
| `MAINTENANCE_MODE` | false | false | false (수동 전환) |

---

## 5. 부트스트랩 (앱 시작 시)

### 5.1 시작 시퀀스

```
1. Settings 로드 + 검증 (실패 시 fail fast)
2. structlog 초기화 (09 §1)
3. X-Ray patch (boto3, redis, httpx)
4. Bedrock client 풀 생성 (aioboto3, region)
5. Pinecone client 생성 (PineconeAsyncio, lazy index resolution)
6. Neo4j driver 1개 생성 (env이 비어 있으면 skip — dev)
7. Redis client 풀 생성
8. 서킷 브레이커 인스턴스 생성 (의존성당 1개)
9. 글로벌 token bucket 초기화 (Redis 또는 로컬)
10. SQS consumer 시작 (Worker entry point만)
11. FastAPI app start (uvicorn)
12. /health 응답 시작
```

5번 Pinecone host 매핑은 **lazy** — 첫 query 시 Next.js의 tenant 메타 endpoint 호출 또는 admin endpoint로 가져온 후 Redis `meta:tenant:{tenant_id}`에 캐시. 시작 시점에 모든 테넌트 host를 미리 가져오지 않음 (테넌트 수가 많으면 시작 시간 부담).

### 5.2 외부 의존성 부트스트랩 contract

Next.js 또는 admin tool이 보유한 정보를 본 서버가 가져오는 방법:

| 정보 | 출처 | 캐시 |
|---|---|---|
| 테넌트 → Pinecone Index host 매핑 | Next.js `GET /admin/tenants/{tenant_id}/pinecone` (Next.js API) 또는 본 서버 `meta:tenant` Redis 캐시 | 600s |
| 테넌트 → Neo4j Database 명 | 명명 규칙 `tenant_{hex}` (04 §2.1) — API 호출 불필요 | — |
| 테넌트 → KMS key alias | 명명 규칙 `alias/witive-tenant-{tenant_id}` (04 §3.2) — 호출 불필요 | — |

Next.js API endpoint(`/admin/tenants/...`)는 Next.js contract — 본 docs 외 결정.

---

## 6. .env 파일 (로컬 개발)

```bash
# .env (로컬 개발용. 실제 prod는 ECS Task Definition + Secrets Manager)
ENV=dev
LOG_LEVEL=DEBUG

INTERNAL_AUTH_SECRET_PRIMARY=local-dev-secret-1
INTERNAL_AUTH_SECRET_SECONDARY=

BEDROCK_REGION=ap-northeast-2
BEDROCK_MODEL_STAGE1=anthropic.claude-haiku-4-5-v1:0
BEDROCK_MODEL_STAGE2=anthropic.claude-haiku-4-5-v1:0
BEDROCK_MODEL_EMBEDDING=amazon.titan-embed-text-v2:0
# AWS credentials는 ~/.aws/credentials 또는 환경 변수로 (AWS_PROFILE)

PINECONE_API_KEY=pc-...
# Neo4j 미사용
REDIS_URL=redis://localhost:6379/0

S3_BUCKET_DOCS=witive-docs-dev
SQS_QUEUE_URL=...
SQS_DLQ_URL=...

# 비용 단가 (24년 기준 대략, 실제는 AWS 콘솔 확인)
BEDROCK_PRICE_INPUT_HAIKU_USD_PER_1M=0.25
BEDROCK_PRICE_OUTPUT_HAIKU_USD_PER_1M=1.25
# ...
```

`.env`는 git ignore. `.env.example`만 커밋.

---

## 7. 라이브러리 버전 핀 (`pyproject.toml`)

### 7.1 런타임 의존성

| 라이브러리 | 핀 | 비고 |
|---|---|---|
| Python | `>=3.12,<3.14` | README 명시 |
| FastAPI | `>=0.110,<0.130` | (06 §3.1) |
| **sse-starlette** | `>=2.1,<3.0` | `EventSourceResponse`, 15s ping (02 §6.2, 06 §3.1) — FastAPI 공식 패키지에 SSE 모듈 없음 |
| pydantic / pydantic-settings | `>=2.5,<3.0` | 10 §1 |
| aioboto3 | `>=12.0,<14.0` | Bedrock converse_stream 안정 (05 §3.1) |
| pinecone | `>=6.0,<7.0` | PineconeAsyncio (04 §1.2) |
| neo4j | `>=5.18,<6.0` | async driver |
| redis | `>=5.0,<6.0` | async client |
| structlog | `>=24.0,<26.0` | 09 §1 |
| aws-xray-sdk | `>=2.14,<3.0` | 09 §3 |
| **aws-embedded-metrics** | `>=3.2,<4.0` | EMF 메트릭 발행 (09 §2.1) |
| **aiolimiter** | `>=1.1,<2.0` | Bedrock token bucket Redis 장애 fallback (05 §5.2) |
| sentence-transformers | `>=3.0,<4.0` | cross-encoder (02 §5.3) |
| pymupdf | `>=1.24,<2.0` | 03 §3.2 |
| python-docx | `>=1.1,<2.0` | 03 §3.2 |
| openpyxl | `>=3.1,<4.0` | 03 §3.2 |
| selectolax + httpx | latest minor | URL 파싱 (03 §3.2) |
| playwright | `>=1.45,<2.0` | JS 렌더링 (03 §3.2) |
| pybreaker (or 자체) | `>=1.2,<2.0` | 서킷 브레이커 (08 §3) |

### 7.2 dev 의존성

| 라이브러리 | 핀 | 용도 |
|---|---|---|
| pytest | `>=8.0,<9.0` | 단위·통합 테스트 (11 §2·§3) |
| pytest-asyncio | `>=0.24,<1.0` | async 테스트 |
| pytest-cov | `>=5.0,<6.0` | 커버리지 (목표 ≥ 85%) |
| freezegun | `>=1.5,<2.0` | 시간 의존 테스트 |
| moto | `>=5.0,<6.0` | AWS 서비스 mock (Bedrock·S3·SQS) |
| testcontainers | `>=4.0,<5.0` | Neo4j·Redis 통합 테스트 |
| mypy | `>=1.10,<2.0` | strict 타입 체크 (12 §2) |
| ruff | `>=0.5,<1.0` | linter + formatter (12 §2) |
| bandit | `>=1.7,<2.0` | 정적 보안 분석 (11 §5) |
| pip-audit | `>=2.7,<3.0` | 의존성 CVE (11 §5) |
| import-linter (또는 tach) | `>=2.0,<3.0` (또는 `>=0.13,<1.0`) | 의존 방향 강제 (12 §3.2) |
| pre-commit | `>=3.7,<4.0` | git hook (12 §2) |

**SDK 메이저 버전 업그레이드는 통합 테스트(`11-testing.md`) 통과 필수**. 특히 Pinecone/Neo4j/Bedrock SDK는 시그니처 변경 위험 큼.

---

## 8. 변경 시 영향 범위

- 환경 변수 추가 → 본 docs §2 + 출처 docs(02·03·05·07·08 등) 동시 갱신, `Settings` 클래스 추가
- Secrets Manager 경로 변경 → ECS task definition + Terraform + 본 docs §3.1 동기화
- 환경별 차이 갱신 → §4 + INFRA.md
- 라이브러리 버전 업 → §7 + `11-testing.md` 통합 테스트 통과 후 적용
- 새 외부 의존성 추가 → §5.2 부트스트랩 contract + 본 docs §2 환경 변수 + 06 cache/invalidate 영향 검토
