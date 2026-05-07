# ADR-0001: Pinecone async 클라이언트로 PineconeAsyncio 채택

- 상태: Accepted
- 일자: 2026-05-07
- 결정자: 본 서버 설계팀
- 관련 docs: `01-architecture.md` §2, `04-data-stores.md` §1.2

## Context

본 서버는 FastAPI + asyncio 기반 마이크로서비스. 모든 I/O는 async여야 event loop 블록 회피 가능. Pinecone 호출은 query·upsert·delete 모두 빈번하며 사용자 대기 경로(Stage 2 검색)에 들어 있다.

설계 1차 시안은 "Pinecone 공식 SDK + `asyncio.to_thread`로 sync→async wrap"였다. 검수 1차 라운드에서 Pinecone 공식 Python SDK v6+에 **`PineconeAsyncio` / `IndexAsyncio` 네이티브 async 클라이언트**가 있다는 사실이 발견됐다.

## Decision

Pinecone Python SDK v6+ 의 `PineconeAsyncio` 컨텍스트 매니저와 `IndexAsyncio`를 사용한다.
`asyncio.to_thread` 래핑은 사용하지 않는다.

```python
async with PineconeAsyncio(api_key=PINECONE_API_KEY) as pc:
    async with pc.IndexAsyncio(host=tenant_index_host) as idx:
        results = await idx.query(...)
```

SDK 메이저 버전 핀: `pinecone>=6.0,<7.0` (`docs/10-config-and-secrets.md` §7.1).

## Alternatives

| 대안 | 거부 사유 |
|---|---|
| sync SDK + `asyncio.to_thread` | thread pool 압박 + 진짜 비동기 아님. 동시 query 100건 시 thread starvation |
| `httpx`로 Pinecone REST 직접 호출 | SDK 구현 복잡도 + 인증·재시도·페일오버 다 자체 구현 부담 |
| Pinecone TypeScript 클라이언트 (NestJS에서 호출) | 본 서버가 RAG 책임이라 Pinecone 결합도가 본 서버에 있어야 함 — NestJS는 호출만 |

## Consequences

긍정적:
- 진짜 async I/O. event loop 블록 0
- 공식 SDK라 인증·재시도·페일오버 무료
- 코드 단순화

부정적:
- SDK v6+ 버전 핀 의존. v7로 메이저 업그레이드 시 시그니처 변경 가능 → 통합 테스트 필수 (`docs/11-testing.md` §3)
- `IndexAsyncio` 컨텍스트 매니저 lifecycle 관리 필요 — 매 요청마다 enter/exit는 비효율, host당 캐시 결정 (`docs/04-data-stores.md` §1.2)

후속 작업:
- 통합 테스트에 PineconeAsyncio 시그니처 검증 추가
- SDK 메이저 업그레이드 시 본 ADR 업데이트 또는 새 ADR

## References

- `docs/04-data-stores.md` §1.2 (사용 패턴)
- `docs/01-architecture.md` §2 (외부 의존성 매트릭스)
- 검수 1차 라운드 C-1 (1차 시안의 모순 발견)
- Pinecone 공식 Python SDK docs: https://docs.pinecone.io/reference/python-sdk
