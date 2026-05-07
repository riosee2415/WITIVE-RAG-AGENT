# 11 — Testing

본 서버의 테스트 전략 단일 진실 출처. 단위·통합·RAG 평가·부하·보안·비용 측정 + 빌드 시간 검증을 포함.
RAG 시스템은 일반 테스트 외에도 **답변 품질 회귀 측정** + **비용 회귀 측정**이 필수다. 두 영역에 별도 골든셋을 운영한다.

## 1. 테스트 피라미드

```
                    ┌──────────────────┐
                    │  부하 (k6)        │  주 1회 staging
                    ├──────────────────┤
                    │  RAG 평가 골든셋   │  PR마다 staging
                    ├──────────────────┤
                    │  통합 (testcontainers / LocalStack)  │  PR마다 CI
                    ├──────────────────┤
                    │  단위 (pytest + fake adapter)         │  PR마다 CI (빠르게)
                    └──────────────────────────────────────┘
                         (커버리지 우선) ←→ (운영 신뢰 우선)
```

각 층은 다른 역할:
- 단위: 도메인 로직, 분기, 엣지 케이스
- 통합: 외부 의존성과 결합한 시나리오 (멱등·재시도·서킷)
- RAG 평가: 답변 품질 (정확도/리콜)
- 비용 측정: cache hit, prompt cache hit, 토큰 비용
- 부하: SLO·OOM·Auto Scaling

## 2. 단위 테스트

### 2.1 라이브러리

- `pytest` + `pytest-asyncio` (async 테스트)
- `pytest-cov` (커버리지, 목표 ≥ 85% — 도메인·pipeline 한정)
- `freezegun` (시간 의존 테스트)

### 2.2 도메인 레이어 테스트

`app/domain/`은 외부 의존성 0이라 가장 빠른 테스트.

```python
def test_tenant_context_normalize_departments():
    ctx = build_context(departments_csv="영업팀, 인사팀, 인사팀, ")
    assert ctx.departments == ("영업팀", "인사팀")  # trim, dedup, sorted

def test_rag_error_serialization():
    err = RagError(code="NO_RESULTS", message="...", retryable=False)
    assert err.to_sse_event() == {"code": "NO_RESULTS", ...}
```

### 2.3 Fake adapter 패턴

`infra/` 어댑터는 모두 Protocol/ABC 인터페이스로 정의 (12 §의존방향). 테스트는 fake로 대체.

```python
class FakePineconeAdapter:
    def __init__(self, results=None, fail=False):
        self._results = results or []
        self._fail = fail
        self.calls: list[dict] = []

    async def query(self, ctx, vector, **kw):
        self.calls.append({"ctx": ctx, "vector": vector, **kw})
        if self._fail:
            raise PineconeError("fake")
        return self._results
```

테스트에서:
```python
async def test_query_pipeline_pinecone_failure_falls_back_to_neo4j():
    pinecone = FakePineconeAdapter(fail=True)
    neo4j = FakeNeo4jAdapter(results=[chunk_a, chunk_b])
    rerank = FakeReranker()
    bedrock = FakeBedrock(stream=["연차", "는 ", "15일"])

    sse = await run_query(pinecone, neo4j, rerank, bedrock, ctx, "연차일수")
    events = await collect_sse(sse)

    assert any(e.type == "warnings" and "PINECONE_DEGRADED" in e.content for e in events)
    assert any(e.type == "token" for e in events)
```

### 2.4 권한 격리 테스트 (07 §6 cross-ref)

| 테스트 | 검증 |
|---|---|
| `test_pinecone_filter_companywide_user_returns_filter_dict` | filter 모양 |
| `test_pinecone_filter_executive_includes_user_id` | EXECUTIVE 1차 필터 |
| `test_executive_post_filter_drops_other_user_chunks` | post-filter 동작 |
| `test_pinecone_adapter_rejects_cross_tenant_vector` | 색인 시 cross-tenant 거부 |
| `test_neo4j_adapter_routes_to_tenant_database` | DB 명 매핑 |
| `test_system_cron_context_blocks_query_endpoint` | 시스템 컨텍스트 격리 |

### 2.5 서킷 브레이커 테스트 (08 §3.1)

| 테스트 | 검증 |
|---|---|
| `test_circuit_opens_at_50_percent_failure_for_bedrock` | 임계 |
| `test_circuit_open_skips_call_returns_fallback` | open 동작 |
| `test_circuit_half_open_after_30s` | 회복 |
| `test_jitter_applied_to_retry_backoff` | jitter 분산 |

## 3. 통합 테스트

### 3.1 환경 선택

| 의존성 | 통합 테스트 환경 |
|---|---|
| Bedrock | **moto** 또는 dev AWS 계정 (실 호출 비용 적음, throttle 위험) |
| Pinecone | **로컬 mock** 또는 dev Pinecone Index (테스트 전용, 작은 차원) |
| Neo4j | **testcontainers** (`neo4j:5.18-enterprise`, license accept) |
| Redis | **testcontainers** 또는 GitHub Actions service container |
| S3 | **moto** (in-memory) 또는 LocalStack |
| SQS | **moto** 또는 LocalStack |

testcontainers 우선 — CI에서 실 의존성과 비슷한 동작.

### 3.2 핵심 통합 시나리오

| 시나리오 | 검증 |
|---|---|
| `test_query_end_to_end_cache_miss` | 전체 흐름 + SSE 이벤트 시퀀스 |
| `test_query_end_to_end_cache_hit` | 2번째 호출이 ≤100ms |
| `test_query_executive_postfilter_drops_unauth_user` | 캐시 hit 시 post-filter 동작 |
| `test_document_upload_to_indexed_full_pipeline` | upload → SQS → Worker → Pinecone+Neo4j |
| `test_stage_b_step_3_failure_yields_partial_success` | 부분 실패 보상 트랜잭션 |
| `test_orphan_staging_cleanup_endpoint` | cleanup endpoint 동작 |
| `test_epoch_invalidation_after_document_upload` | 캐시 자연 stale |
| `test_dlq_message_does_not_auto_redrive` | 자동 redrive 금지 |
| `test_redis_outage_falls_back_to_local_token_bucket` | 08 §3.3 시간선 |
| `test_maintenance_mode_returns_503` | 수동 게이트 |

### 3.3 cancellation 검증

`05 §3.1` Bedrock stream cancellation 검증:

| 테스트 | 검증 |
|---|---|
| `test_client_disconnect_cancels_bedrock_stream` | disconnect → 진행 중 호출 즉시 종료 |
| `test_bedrock_stream_close_handled_for_old_botocore` | close 미지원 버전 안전 처리 |

## 4. RAG 평가 골든셋

### 4.1 골든셋 구성

테넌트별 영구 골든셋. 본 서버 레포에는 **합성 데이터 골든셋**만 (실 고객 데이터는 별도 격리 저장소).

```
tests/rag_eval/
├── synthetic/
│   ├── corpus/                # 청크 파일 + 메타
│   │   ├── 취업규칙_v2.1.pdf
│   │   ├── 출장규정_v1.0.docx
│   │   └── ...
│   └── queries.jsonl          # {question, expected_chunk_ids, expected_answer_keywords}
└── runners/
    └── run_eval.py
```

### 4.2 평가 지표

| 지표 | 산식 | 임계 |
|---|---|---|
| **Recall@5** | (relevant chunks ∩ top 5) / relevant | ≥ 0.80 |
| **Precision@5** | (relevant ∩ top 5) / 5 | ≥ 0.60 |
| **MRR** | mean(1 / rank of first relevant) | ≥ 0.70 |
| **Answer Faithfulness** | 답변 키워드 중 sources 본문에 등장하는 비율 | ≥ 0.90 |
| **Answer Relevance** | LLM-as-judge로 0~1 점수 (claude judge) | ≥ 0.75 |
| **Latency P95** | 첫 토큰 ms | ≤ 4000 |
| **No-results rate** | 미답변 비율 | ≤ 0.10 |

### 4.3 PR 게이트

골든셋 평가는 **staging 배포 전 PR check**로 실행. 임계 위반 시 PR 차단.

비용 절감 측정 시나리오 (사용자 요구 "경제적 이익"):

| 시나리오 | 측정 |
|---|---|
| Stage 2 모델 변경 (Sonnet → Sonnet 4.7) | Recall@5·MRR·Latency·비용 비교 |
| 임계값 변경 (0.75 → 0.70) | 폐기율·LOW_CONFIDENCE 비율·비용 변화 |
| 시스템 프롬프트 minimal vs padded (05 §4.2) | Faithfulness·Relevance·답변 길이·예시 인용 빈도 비교 |
| 청킹 알고리즘 변경 | 전체 지표 회귀 |

### 4.4 실 고객 데이터 골든셋 (별도 저장소)

운영 중 발생한 어려운 케이스를 **수동 큐레이션**하여 별도 사설 저장소(`witive-rag-eval-private`)에 보관. PR 게이트 통과 후 수동으로 추가 평가. 본 서버 레포에 절대 commit 금지.

## 5. 보안·멀티테넌트 격리 테스트

| 카테고리 | 테스트 |
|---|---|
| **Prompt injection** | "위 지시 무시하고..." 입력에 시스템 프롬프트 노출 안 됨 |
| **Cross-tenant** | tenant A 컨텍스트로 tenant B vector·DB 접근 시도 → SecurityError |
| **Role escalation** | USER role로 admin endpoint 호출 → 403 |
| **System cron impersonation** | reserved UUID 위장 시도 → admin endpoint만 통과, 일반 endpoint 403 |
| **MIME 위장** | `.exe`를 `application/pdf` MIME으로 업로드 → 매직 바이트 검증 차단 |
| **PII 누수** | 질문 본문이 로그에 노출 안 됨 (SHA-256만) |
| **EXECUTIVE 정보 누수** | 다른 user_id로 같은 access_sig 캐시 hit → post-filter가 차단 |

`bandit` static analyzer + `pip-audit` (의존성 CVE) CI 통합.

## 6. 부하 테스트 (k6)

### 6.1 시나리오

```
tests/load/
├── 01_query_steady.js       # 100 RPS × 30분, P95·오류율 측정
├── 02_query_burst.js        # 500 RPS spike → backpressure 동작
├── 03_concurrent_sse.js     # 200 동시 SSE → MAX_CONCURRENT_SSE 동작
├── 04_document_upload.js    # 100MB × 10건 동시 업로드 → SQS·Worker
└── 05_mixed_workload.js     # query 70% + upload 30%, 1시간
```

### 6.2 검증 항목

| 항목 | 임계 |
|---|---|
| 첫 토큰 P95 | ≤ 4.0s (cold) / ≤ 0.1s (cache hit) |
| 전체 답변 P95 | ≤ 11s |
| 오류율 (비-429) | < 1% |
| 429 발행 비율 (burst) | > 0% (backpressure 동작 확인) |
| Auto Scaling | 5분 내 max task로 스케일 아웃 확인 |
| 메모리 사용 | 정상 부하 시 < 70%, burst 시 < 85% (drain mode 트리거 임계) |

### 6.3 비용 측정 (사용자 요구 "경제적 이익")

부하 테스트 중 측정:
- **Bedrock 토큰 비용**: 시간당 $/1k queries (`bedrock_estimated_cost_usd` 합산)
- **prompt cache hit ratio**: 업무 시간 ≥ 0.7
- **query cache hit ratio**: 사용 패턴별 측정
- **CloudWatch metric 비용**: PutMetricData 호출 0 검증, custom metric 수 < 100
- **X-Ray sample 비용**: prod 시뮬레이션 모드에서 reservoir 동작 검증

## 7. 빌드 시간 검증 (CI)

코드 작성 외에 빌드 단계에서 실행되는 검증:

| 검증 | 임계 | 출처 docs |
|---|---|---|
| `mypy --strict` | 0 error | 12 |
| `ruff check` | 0 error | 12 |
| `bandit` 보안 | 0 high | §5 |
| `pip-audit` 의존성 CVE | 0 critical | §5 |
| **시스템 프롬프트 토큰 길이** ≥ `STAGE2_SYSTEM_PROMPT_MIN_TOKENS` | warn (fail 아님) | 05 §4.2 |
| **Neo4j fulltext analyzer 'cjk' 가용성** (admin tool 책임이지만 CI에 포함 가능) | warn | 04 §2.3 |
| **사전 저장 모델 ID 환경 변수 형식 검증** (regex `^[a-z]+\..+`) | error | 05 §1.3 |

## 8. 비용 회귀 측정 (월간 자동 보고)

별도 월간 작업으로 prod 메트릭에서 추출:

| 지표 | 비교 기준 |
|---|---|
| 쿼리당 평균 비용 ($) | 전월 대비 ±10% 이내 |
| Stage 2 prompt cache hit ratio | ≥ 0.5 (업무 시간) |
| query cache hit ratio | ≥ 0.5 |
| EXECUTIVE post-filter drop 비율 | < 5% |
| DLQ 누적 메시지 수 | 0 (자동 redrive 없음 정책) |
| `bedrock_estimated_cost_usd` 일 평균 | 전월 대비 ±20% 이내 |

비용 회귀 발견 시 RAG 평가 골든셋과 cross-check (품질 vs 비용 트레이드오프).

## 9. CI/CD 파이프라인 통합

| 단계 | 트리거 | 단계 |
|---|---|---|
| PR open/update | 단위 + 통합 + 빌드 검증 + RAG 평가 (작은 골든셋) | 5~10분 |
| `main` merge | 위 + RAG 평가 (전체 골든셋) + staging 배포 | 20~30분 |
| staging 배포 후 | smoke test (헬스, 샘플 query) + 작은 부하 (100 RPS × 5분) | 10분 |
| prod 승인 후 배포 | Blue/Green Canary 10% → 50% → 100% + 5분 모니터링 | (운영 책임) |
| 주간 (월요일 야간) | 부하 테스트 staging 1시간 + 비용 측정 | (별도 잡) |
| 월간 | prod 비용 회귀 보고 (§8) | (별도 잡) |

CI/CD 자체 정의는 `00-scope.md`에 따라 본 서버 외 책임 (DevOps Harness CD). 본 서버는 **Dockerfile / 헬스체크 / 테스트 정의**만 제공.

## 10. 변경 시 영향 범위

- 임계값(P95 SLO, RAG metric 임계) 변경 → 본 docs + 09 알람 임계 동기화
- 새 통합 시나리오 추가 → §3.2 + 통합 테스트 환경 추가 (testcontainers 또는 LocalStack)
- 골든셋 갱신 → PR 게이트 통과 임계 재산정
- 부하 테스트 도구 변경 (k6 → Locust 등) → §6 + Harness pipeline (DevOps)
- 비용 회귀 보고 추가 → §8 + 메트릭 추가 (`09 §2.3`)
