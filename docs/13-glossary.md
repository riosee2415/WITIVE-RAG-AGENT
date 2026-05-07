# 13 — Glossary

본 프로젝트 docs와 코드에서 사용하는 용어 단일 진실 출처. 같은 용어가 여러 docs에 다르게 쓰이지 않도록 통일.
한국어 용어는 가능한 영어 병기. 외부 시스템 명은 원문 그대로.

---

## 1. 본 프로젝트 고유 용어

| 용어                      | 영어             | 정의                                                                                                                                                   |
| ------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **2-Stage Query Chain**   | —                | 사용자 질문을 Stage 1(재작성)과 Stage 2(검색·생성)로 처리하는 본 서버의 핵심 흐름 (`02-query-pipeline.md`)                                             |
| **Stage 1**               | Query Rewriter   | 사용자 질문을 검색에 적합한 형태로 재작성. Claude Haiku 4.5 사용                                                                                       |
| **Stage 2**               | Hybrid RAG       | Pinecone(벡터) + Neo4j(그래프) 병렬 검색 → 재랭킹 → 권한 필터 → Claude Sonnet 4.6 답변 생성                                                            |
| **Stage A**               | staging upsert   | 색인 1단계. 청크를 staging 메타로 Pinecone·Neo4j에 적재 (검색 노출 안 됨, `03 §3.6`)                                                                   |
| **Stage B**               | swap to live     | 색인 2단계. staging → live 전환. 6단계 atomic-ish swap (Pinecone live upsert → staging delete → Neo4j swap → S3 metadata → epoch INCR → 비동기 후처리) |
| **TenantContext**         | —                | NestJS가 보낸 X-\* 헤더로부터 build된 immutable dataclass. 모든 use case의 첫 인자 (`07 §1.1`)                                                         |
| **access_sig**            | access signature | 캐시 키에 들어가는 권한 클래스 해시. `sha256(role + departments + level)`. EXECUTIVE 사용자 user_id는 미포함 (`02 §3.2`)                               |
| **epoch invalidation**    | —                | 테넌트 캐시 무효화 패턴. `INCR epoch:{tenant_id}` 1회로 모든 캐시 자연 stale (`02 §3.1`)                                                               |
| **EXECUTIVE post-filter** | —                | EXECUTIVE access_level 청크를 응답 직전 user_id 화이트리스트로 폐기 (`02 §5.4`)                                                                        |
| **MAINTENANCE_MODE**      | —                | 503 모드. 모든 query 차단. **자동**(Redis 5분 이상 Open 지속, 08 §3.3) 또는 **수동**(`MAINTENANCE_MODE=true` 환경 변수, 운영팀 강제 전환)              |
| **glossary**              | (이 문서)        | 본 docs 13                                                                                                                                             |
| **하네스**                | harness          | 자동화 에이전트 (Claude Code 등). 본 docs를 참조해 코드 생성                                                                                           |
| **dual-key 회전**         | —                | `INTERNAL_AUTH_SECRET_PRIMARY`/`SECONDARY` 두 값 동시 검증으로 무중단 시크릿 회전 (`00 §3.1`)                                                          |
| **fail-closed**           | —                | 매핑 미정의·검증 실패 시 안전 측(거부)으로 동작. 본 서버 보안 기본값 (`07 §1.4`)                                                                       |
| **min_level_rank**        | —                | LEVEL access의 1차 필터에 사용되는 사전 계산 정수. `min(LEVEL_RANK[lv] for lv in allowed_levels)` (`07 §1.4`, `04 §1.3`, `03 §3.6`)                    |
| **GENERATION_DEGRADED**   | —                | Bedrock Stage 2 장애 또는 본문 fetch 실패 시 sources만 노출하고 token 생략하는 SSE warning                                                             |
| **SERVICE_DEGRADED**      | —                | 검색은 성공했으나 본문 fetch 1·2차 모두 실패해 token 0개로 정상 종료하는 SSE 종료 케이스 (`02 §5.6`)                                                   |
| **PARTIAL_SUCCESS**       | —                | 색인 Job의 Stage B 부분 실패 상태. Pinecone live + Neo4j staging 같은 일시 불일치 (`03 §3.6`)                                                          |

---

## 2. RAG 도메인 용어

| 용어                 | 영어                                 | 정의                                                                                       |
| -------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------ |
| **검색 증강 생성**   | RAG (Retrieval-Augmented Generation) | 외부 문서에서 근거를 검색해 LLM 답변을 생성하는 패턴                                       |
| **재작성**           | Query Rewriting                      | 사용자 질문을 검색에 적합한 형태로 재구성                                                  |
| **시맨틱 검색**      | Semantic search                      | 의미 기반 벡터 검색 (vs 키워드 검색)                                                       |
| **하이브리드 검색**  | Hybrid search                        | 시맨틱 + 키워드/그래프 검색 병행                                                           |
| **재랭킹**           | Reranking                            | 검색 1차 결과를 cross-encoder로 다시 점수화                                                |
| **임베딩**           | Embedding                            | 텍스트를 고차원 벡터로 변환                                                                |
| **청킹**             | Chunking                             | 문서를 작은 단위로 분할 (본 서버 512 토큰 / 50 overlap)                                    |
| **청크**             | Chunk                                | 청킹 결과 단위                                                                             |
| **Cross-encoder**    | —                                    | (질문, 청크) 쌍을 함께 입력받아 점수를 내는 모델. 재랭킹용                                 |
| **TTFT**             | Time To First Token                  | 답변 첫 토큰까지 걸린 시간                                                                 |
| **prompt caching**   | —                                    | LLM API의 시스템 prefix 캐시. 본 서버는 Bedrock ephemeral cache 사용 (`05 §4`)             |
| **few-shot**         | —                                    | 시스템 프롬프트에 답변 예시를 포함시키는 기법. 본 서버는 의도적으로 사용 안 함 (`05 §4.2`) |
| **golden set**       | 골든셋                               | 평가용 정답 데이터셋 (질문·기대 답변·기대 청크)                                            |
| **Recall@K**         | —                                    | 검색 결과 상위 K개 안에 정답 청크가 포함된 비율                                            |
| **MRR**              | Mean Reciprocal Rank                 | 정답이 처음 나타난 순위의 역수 평균                                                        |
| **Faithfulness**     | —                                    | 답변이 sources 본문에 근거해 있는지 측정                                                   |
| **prompt injection** | —                                    | 사용자 입력으로 시스템 프롬프트를 우회·조작하려는 공격                                     |
| **LLM-as-judge**     | —                                    | 다른 LLM이 답변 품질을 평가하는 방법                                                       |

---

## 3. 멀티테넌트 / 권한

| 용어            | 영어                                | 정의                                                                                                      |
| --------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **테넌트**      | Tenant                              | B2B SaaS의 한 고객사 (PRD §3)                                                                             |
| **테넌트 격리** | Tenant Isolation                    | 테넌트 간 데이터·자원 분리. 본 서버는 Pinecone Index/Neo4j Database 물리 격리 + S3 prefix 논리 격리       |
| **Role**        | —                                   | 사용자 역할. WITIVE_SUPER_ADMIN / COMPANY_ADMIN / COMPANY_MANAGER / COMPANY_USER (`07 §1.2`)              |
| **AccessLevel** | —                                   | 문서 접근 레벨. COMPANY_WIDE / DEPARTMENT / LEVEL / EXECUTIVE (`07 §1.3`)                                 |
| **RBAC**        | Role-Based Access Control           | 역할 기반 접근 제어                                                                                       |
| **PII**         | Personally Identifiable Information | 개인 식별 정보                                                                                            |
| **STRIDE**      | —                                   | 위협 모델링 프레임워크 (Spoofing/Tampering/Repudiation/Information Disclosure/DoS/Elevation of Privilege) |
| **Zero Trust**  | —                                   | "내부 네트워크라도 검증" 보안 원칙                                                                        |

---

## 4. 운영·resilience

| 용어                  | 영어                    | 정의                                                                                          |
| --------------------- | ----------------------- | --------------------------------------------------------------------------------------------- |
| **서킷 브레이커**     | Circuit Breaker         | 외부 의존성 실패율이 임계 초과 시 호출을 차단하는 패턴 (`08 §3`)                              |
| **Half-Open**         | —                       | 서킷이 일정 시간 후 단일 테스트 호출을 허용하는 상태                                          |
| **fallback**          | —                       | 1차 경로 실패 시 부분 결과·대체 경로로 진행                                                   |
| **bounded retry**     | —                       | 횟수·시간 상한이 있는 재시도. 비용 폭증 방어 (`08 §1`)                                        |
| **jitter**            | —                       | 재시도 간격에 ±20% 랜덤 분산. 동시 재시도 동기화(thundering herd) 방어                        |
| **backpressure**      | —                       | 부하 한계 초과 시 클라이언트에 throttle 신호(429) 발행 (`08 §6`)                              |
| **DLQ**               | Dead Letter Queue       | SQS 처리 실패 메시지가 이동하는 큐. 본 서버는 자동 redrive 금지 (`08 §7`)                     |
| **SLO**               | Service Level Objective | 서비스 수준 목표                                                                              |
| **SLA**               | Service Level Agreement | 외부 약속 수준                                                                                |
| **Auto Scaling**      | —                       | 부하에 따라 ECS Task 수를 자동 조정                                                           |
| **drain mode**        | —                       | ALB 헬스 체크 unhealthy 마킹으로 새 트래픽 차단, 진행 중 connection은 graceful 완료 (`08 §6`) |
| **graceful shutdown** | —                       | 진행 중 작업 완료 후 종료                                                                     |

---

## 5. 관찰가능성

| 용어           | 영어                   | 정의                                                                      |
| -------------- | ---------------------- | ------------------------------------------------------------------------- |
| **EMF**        | Embedded Metric Format | CloudWatch 메트릭을 로그 라인에 박는 형식. PutMetricData 호출 0 (`09 §2`) |
| **structlog**  | —                      | 구조 로깅 Python 라이브러리                                               |
| **request_id** | —                      | 한 요청 추적용 uuid7. 모든 로그·trace에 포함                              |
| **trace**      | —                      | 분산 추적 단위 (X-Ray Segment)                                            |
| **span**       | —                      | trace 안의 한 작업 단위                                                   |
| **reservoir**  | —                      | X-Ray sampling rule의 분당 보장 샘플 수                                   |
| **fixedRate**  | —                      | reservoir 초과분에 적용되는 고정 비율                                     |
| **카디널리티** | Cardinality            | 메트릭 라벨 조합의 가짓수. 높으면 비용 폭발                               |
| **알람**       | Alarm                  | CloudWatch에서 임계 위반 시 알림 발행                                     |
| **PagerDuty**  | —                      | 알람 → 운영팀 호출 도구 (운영팀 책임)                                     |

---

## 6. AWS·외부 시스템

| 용어                                          | 영어                       | 정의                                                                                                                   |
| --------------------------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Bedrock**                                   | AWS Bedrock                | 매니지드 LLM 서비스 (Claude, Titan 등)                                                                                 |
| **Claude Haiku 4.5**                          | —                          | Anthropic의 빠른 모델. 본 서버 Stage 1                                                                                 |
| **Claude Sonnet 4.6**                         | —                          | Anthropic의 균형 모델. 본 서버 Stage 2                                                                                 |
| **Titan Embeddings v2**                       | —                          | AWS의 임베딩 모델. 1536차원                                                                                            |
| **Converse API**                              | —                          | Bedrock의 통합 LLM 호출 API                                                                                            |
| **converse_stream**                           | —                          | Bedrock Converse API의 스트리밍 변형                                                                                   |
| **cachePoint**                                | —                          | Bedrock Converse API의 prompt caching 마커                                                                             |
| **inference profile**                         | —                          | Bedrock 모델의 cross-region 가용성 ARN                                                                                 |
| **Pinecone**                                  | —                          | 벡터 검색 SaaS. 본 서버는 Serverless 사용                                                                              |
| **PineconeAsyncio**                           | —                          | Pinecone Python SDK의 async 클라이언트 (`04 §1.2`)                                                                     |
| **Neo4j Enterprise**                          | —                          | 그래프 DB. EC2 자체 호스팅 + 테넌트별 logical Database                                                                 |
| **Cypher**                                    | —                          | Neo4j 쿼리 언어                                                                                                        |
| **APOC**                                      | —                          | Neo4j 확장 procedure 라이브러리. 본 서버는 의존 회피 (`04 §2.4`)                                                       |
| **CJKAnalyzer**                               | —                          | Lucene의 한·중·일 텍스트 분석기. 본 서버 fulltext index `'cjk'`                                                        |
| **AWS S3**                                    | —                          | Object storage. 본 서버는 원본·청크·jobs 보관                                                                          |
| **KMS**                                       | AWS Key Management Service | 암호화 키 관리. 테넌트별 CMK                                                                                           |
| **CMK**                                       | Customer Master Key        | KMS의 고객 마스터 키                                                                                                   |
| **WORM**                                      | Write Once Read Many       | S3 Object Lock — 변경 불가 보존                                                                                        |
| **ElastiCache**                               | AWS ElastiCache            | 매니지드 Redis                                                                                                         |
| **SQS**                                       | AWS Simple Queue Service   | 메시지 큐. 본 서버 문서 파이프라인용                                                                                   |
| **SES**                                       | AWS Simple Email Service   | 이메일 발송 (NestJS 책임)                                                                                              |
| **Cognito**                                   | AWS Cognito                | 사용자 인증 (NestJS 책임)                                                                                              |
| **ECS Fargate**                               | —                          | AWS의 서버리스 컨테이너                                                                                                |
| **ALB**                                       | Application Load Balancer  | AWS의 L7 로드 밸런서                                                                                                   |
| **API Gateway**                               | AWS API Gateway            | API 관리. 본 서버는 ALB 직접 사용 (SSE 호환성)                                                                         |
| **CloudWatch**                                | AWS CloudWatch             | 모니터링·로그·메트릭·알람                                                                                              |
| **CloudWatch Logs Insights**                  | —                          | CloudWatch Logs 쿼리 도구                                                                                              |
| **X-Ray**                                     | AWS X-Ray                  | 분산 추적                                                                                                              |
| **Textract**                                  | AWS Textract               | OCR 서비스                                                                                                             |
| **EventBridge**                               | AWS EventBridge            | cron 스케줄러                                                                                                          |
| **moto**                                      | —                          | AWS 서비스 in-memory mock (테스트용)                                                                                   |
| **LocalStack**                                | —                          | AWS 서비스 로컬 시뮬레이터                                                                                             |
| **testcontainers**                            | —                          | Docker 기반 테스트 의존성 도구                                                                                         |
| **Harness CD**                                | —                          | CI/CD 도구. 본 서버 외 (DevOps)                                                                                        |
| **NestJS**                                    | —                          | TypeScript 기반 백엔드 프레임워크. 본 서버를 호출하는 상위 백엔드                                                      |
| **sse-starlette**                             | —                          | FastAPI 생태계의 SSE 라이브러리. `EventSourceResponse` 제공 (FastAPI 공식 패키지에 SSE 모듈 없음). `02 §6.2 / 06 §3.1` |
| **aws-embedded-metrics**                      | —                          | EMF 형식으로 CloudWatch 메트릭을 로그에 박는 라이브러리 (PutMetricData 호출 0). `09 §2`                                |
| **aiolimiter**                                | —                          | async token bucket rate limiter. Bedrock RPS 글로벌 제한 (Redis 장애 시 로컬 fallback). `05 §5.2`                      |
| **import-linter** / **tach**                  | —                          | Python 모듈 의존 방향을 CI에서 자동 검증하는 도구. `12 §3.2`                                                           |
| **pydantic-settings**                         | —                          | 환경 변수 → typed Settings 자동 변환. `10 §1`                                                                          |
| **uv**                                        | —                          | Python 패키지 매니저 (pip+venv 통합, lock 파일). `12 §1`                                                               |
| **ruff** / **mypy** / **bandit** / **pytest** | —                          | dev 표준 도구 (linter+formatter / strict 타입 / 정적 보안 / 테스트). `12·11`                                           |
| **moto** / **testcontainers**                 | —                          | AWS in-memory mock / Docker 기반 의존성 컨테이너 (테스트). `11 §3.1`                                                   |

---

## 7. 자주 혼동되는 용어 구분

| 비교                                                    | 차이                                                                                                                                           |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **degraded** vs **unhealthy**                           | degraded = 일부 의존성 장애지만 fallback 동작 중(HTTP 200 유지). unhealthy = 핵심 의존성 동시 장애·메모리 임계 초과·MAINTENANCE_MODE(HTTP 503) |
| **NO_RESULTS** vs **NO_ACCESSIBLE_RESULTS**             | NO_RESULTS = 검색 결과 자체가 없음. NO_ACCESSIBLE_RESULTS = 검색은 됐으나 권한으로 모두 폐기                                                   |
| **NO_RESULTS** vs **SERVICE_DEGRADED**                  | NO_RESULTS = 검색 0건 (error 종료). SERVICE_DEGRADED = 검색 성공 + 본문 fetch 실패 (token 0개로 정상 종료)                                     |
| **PARTIAL_SUCCESS** vs **FAILED_STAGE_B**               | PARTIAL_SUCCESS = Stage B 일부 단계 실패하지만 검색·답변 정상. FAILED_STAGE_B = Stage B 전체 실패, cleanup 대상                                |
| **DUPLICATE_FILE** vs **DUPLICATE_VERSION**             | DUPLICATE_FILE = 동일 SHA-256 재업로드. DUPLICATE_VERSION = 같은 (doc_id, version) 재업로드 (다른 파일이라도)                                  |
| **GENERATION_DEGRADED** vs **SERVICE_DEGRADED**         | GENERATION_DEGRADED = warnings 항목명. SERVICE_DEGRADED = SSE 종료 케이스명. 같은 사고 시 둘 다 등장 가능                                      |
| **fallback** vs **retry**                               | fallback = 다른 경로 사용. retry = 같은 경로 재시도                                                                                            |
| **backpressure** vs **circuit open**                    | backpressure = 부하 한계로 본 서버가 클라이언트에 throttle. circuit open = 외부 의존성 장애로 본 서버가 호출 차단                              |
| **cache_hit** (Redis) vs **prompt cache hit** (Bedrock) | Redis = 같은 질문 답변 재사용. Bedrock = 시스템 프롬프트 입력 토큰 비용 절감                                                                   |

---

## 8. 약어 사전 (자주 쓰이는 것만)

| 약어      | 풀이                                      |
| --------- | ----------------------------------------- |
| RAG       | Retrieval-Augmented Generation            |
| LLM       | Large Language Model                      |
| SSE       | Server-Sent Events                        |
| SDK       | Software Development Kit                  |
| API       | Application Programming Interface         |
| RBAC      | Role-Based Access Control                 |
| PII       | Personally Identifiable Information       |
| TTFT      | Time To First Token                       |
| MRR       | Mean Reciprocal Rank                      |
| EMF       | Embedded Metric Format                    |
| WORM      | Write Once Read Many                      |
| DLQ       | Dead Letter Queue                         |
| KMS       | Key Management Service                    |
| CMK       | Customer Master Key                       |
| SLO       | Service Level Objective                   |
| SLA       | Service Level Agreement                   |
| MTTR      | Mean Time To Recovery                     |
| OOM       | Out Of Memory                             |
| CSV       | Comma-Separated Values                    |
| NFC       | Normalization Form Composed (Unicode)     |
| TPS       | Transactions Per Second                   |
| RPS       | Requests Per Second                       |
| RPM       | Requests Per Minute                       |
| CJK       | Chinese·Japanese·Korean                   |
| OCR       | Optical Character Recognition             |
| HMAC      | Hash-based Message Authentication Code    |
| CSP       | Content Security Policy                   |
| MFA       | Multi-Factor Authentication               |
| VPC       | Virtual Private Cloud                     |
| SG        | Security Group                            |
| ECS       | Elastic Container Service                 |
| ALB       | Application Load Balancer                 |
| CDN       | Content Delivery Network                  |
| WAF       | Web Application Firewall                  |
| SOC2      | Service Organization Control 2            |
| ISO 27001 | 정보보안 국제 표준                        |
| GDPR      | General Data Protection Regulation (참고) |
| MTEB      | Massive Text Embedding Benchmark          |

---

## 9. 변경 시 영향 범위

- 새 용어 도입 → 본 docs 추가 + 사용 docs cross-link
- 기존 용어 의미 변경 → 본 docs + 모든 사용 docs 일괄 수정
- 외부 시스템 변경 (예: Pinecone → Weaviate) → §6 + 04·05·08·10 cross-link 갱신
