# ADR — Architecture Decision Records

본 폴더는 본 서버 설계의 **결정 근거**를 영구 기록한다.
ADR은 한 번 작성하면 변경하지 않는다. 결정이 바뀌면 새 ADR을 작성하고 기존 ADR의 status를 `Superseded by ADR-XXXX`로 갱신한다.

## ADR 템플릿

새 ADR 파일은 `NNNN-short-title.md` 명명. NNNN은 4자리 정수, 1번부터 순차.

```markdown
# ADR-NNNN: 한 줄 결정 제목

- 상태: Proposed | Accepted | Deprecated | Superseded by ADR-XXXX
- 일자: YYYY-MM-DD
- 결정자: 본 서버 설계팀
- 관련 docs: `00-scope.md`, `04-data-stores.md` 등

## Context (배경)

이 결정이 나오게 된 문제·제약·요구사항. ref docs 또는 검수 라운드에서 발견된 이슈 인용.

## Decision (결정)

채택한 옵션을 명확하게. 한 문단.

## Alternatives (대안)

검토했지만 거부한 옵션들. 각각 거부 사유 명시.

## Consequences (영향)

- 긍정적: 무엇을 얻는가
- 부정적: 어떤 비용·복잡도를 감수하는가
- 후속 작업: 이 결정으로 발생하는 추가 작업

## References

- 14 docs cross-link
- 외부 자료
- 검수 라운드 이슈 ID (예: 검수 4차 H-1)
```

## ADR 인덱스

| ID | 제목 | 상태 | 일자 |
|---|---|---|---|
| [0001](./0001-pinecone-asyncio-client.md) | Pinecone async 클라이언트로 PineconeAsyncio 채택 | Accepted | 2026-05-07 |
| [0002](./0002-staging-vector-id-prefix-swap.md) | 색인 staging→live swap을 vector_id prefix + batch upsert/delete로 구성 | Accepted | 2026-05-07 |
| [0003](./0003-epoch-invalidation.md) | 캐시 무효화에 SCAN 대신 epoch INCR 채택 | Accepted | 2026-05-07 |
| [0004](./0004-executive-post-filter.md) | EXECUTIVE만 응답 직전 post-filter, access_sig는 user_id 미포함 | Accepted | 2026-05-07 |
| [0005](./0005-sse-starlette-not-fastapi-native.md) | SSE 응답에 sse-starlette 라이브러리 채택 (fastapi.sse 모듈 없음) | Accepted | 2026-05-07 |
| [0006](./0006-bootstrap-dependencies.md) | 1차 부트스트랩에서 AWS·Pinecone·Neo4j·Redis 라이브러리 제외 | Accepted | 2026-05-08 |
| [0007](./0007-uuid7-for-request-id.md) | request_id 생성에 uuid7 채택 (K-Sortable, CloudWatch 호환) | Accepted | 2026-05-08 |

## 주의

- ADR은 **단일 결정 단위**. 여러 결정이 묶여 있으면 분리
- 본 14 docs와 cross-link해 docs와 ADR의 단일 진실 출처 충돌 회피 (docs는 "무엇/어떻게", ADR은 "왜")
- 본 1차 5개는 검수 6라운드에서 가장 큰 결정들. 추가 ADR은 운영 진입 직전 또는 새 결정 시 점진 작성
