# app/pipeline — 유즈케이스

## 책임

- 도메인 + infra 어댑터를 조합해 비즈니스 흐름 구현
- Stage 1·2 query 처리 (`pipeline/query/`)
- 문서 색인 처리 (`pipeline/document/`)
- 도메인 레벨 검증 + 비즈니스 규칙

## 금지

- `app.api` import (반대 방향)
- 외부 SDK 직접 호출 — 반드시 `app.infra` adapter 통과
- HTTP/SSE 직접 응답 (반환은 도메인 객체 또는 async iterator)

## 디렉토리

```
pipeline/
├── query/
│   ├── stage1_rewriter.py
│   ├── stage2_retrieve.py        # Pinecone + Neo4j 병렬
│   ├── stage2_rerank.py          # Cross-encoder
│   ├── stage2_generate.py        # Bedrock Sonnet streaming
│   └── orchestrator.py           # Stage1 + Stage2 + 캐시 + SSE 합성
└── document/
    ├── parsers/                   # pdf, docx, xlsx, url, ocr
    ├── chunker.py
    ├── embedder.py
    ├── indexer.py                 # Stage A/B (03 §3.6)
    └── orchestrator.py
```

## 표준 패턴

```python
async def handle_query(ctx: TenantContext, req: QueryRequest):
    if cached := await query_cache.get_q1(ctx, req):
        async for evt in replay_sse(cached): yield evt; return
    rewritten = await stage1_rewrite_with_fallback(ctx, req)
    yield SseEvent("rewritten_query", rewritten)
    chunks = await stage2_retrieve(ctx, rewritten)
    chunks = await rerank(ctx, chunks)
    chunks = enforce_access_filter(ctx, chunks)
    yield SseEvent("sources", chunks)
    async for token in stage2_generate(ctx, rewritten, chunks):
        yield SseEvent("token", token)
    yield SseEvent("done", meta=...)
```

## 참조

- `@docs/02-query-pipeline.md` — Stage 1·2 처리 흐름
- `@docs/03-document-pipeline.md` — 색인 흐름 + Stage A/B
- `@docs/05-llm-bedrock.md` — Bedrock 호출 패턴
- `@docs/08-resilience.md` — fallback·서킷·재시도

## work_rule

@work_rule.md
