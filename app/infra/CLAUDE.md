# app/infra — 외부 의존성 어댑터

## 책임

- 외부 SDK 호출을 도메인 객체로 변환
- 외부 SDK 에러를 `RagError`로 변환 (`@docs/12-coding-conventions.md` §5.3)
- 의존성별 timeout·재시도·서킷 브레이커 적용 (`@docs/08-resilience.md`)

## 금지

- 다른 `app.infra.*` 모듈 직접 import (조합은 `pipeline/`에서)
- `app.api`, `app.pipeline` import
- 외부 SDK 에러를 그대로 raise — 반드시 `RagError`로 변환

## 디렉토리

```
infra/
├── bedrock/
│   ├── client.py                  # aioboto3 client 풀
│   ├── claude.py                  # Stage1/Stage2 converse_stream
│   ├── titan_embeddings.py
│   └── rate_limiter.py            # Redis 분산 token bucket (aiolimiter)
├── pinecone/                      # PineconeAsyncio (ADR-0001)
├── neo4j/                         # async driver
├── s3/                            # 멀티파트 업로드, byte-range
├── redis/                         # 쿼리/메타/사용자 캐시
├── sqs/                           # 문서 파이프라인 producer/consumer
└── reranker/                      # Cross-encoder (asyncio.to_thread)
```

## 표준 패턴 (외부 에러 변환)

```python
try:
    response = await client.converse_stream(...)
except botocore.exceptions.ClientError as e:
    code = e.response.get("Error", {}).get("Code", "")
    if code == "ThrottlingException":
        raise RagError(ErrorCode.BACKPRESSURE, str(e), retryable=True, retry_after_ms=1000)
    raise RagError(ErrorCode.BEDROCK_UPSTREAM_ERROR, str(e), retryable=True)
```

## 참조

- `@docs/04-data-stores.md` — Pinecone/Neo4j/S3/Redis 스키마·접근 패턴
- `@docs/05-llm-bedrock.md` — Bedrock 호출
- `@docs/08-resilience.md` — 서킷·재시도 임계
- `@docs/operations/adr/0001-pinecone-asyncio-client.md`

## work_rule

@work_rule.md
