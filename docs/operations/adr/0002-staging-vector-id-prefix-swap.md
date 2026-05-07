# ADR-0002: 색인 staging→live swap을 vector_id prefix + batch upsert/delete로 구성

- 상태: Accepted
- 일자: 2026-05-07
- 결정자: 본 서버 설계팀
- 관련 docs: `03-document-pipeline.md` §3.6, `04-data-stores.md` §1.5

## Context

문서 색인이 진행 중일 때 검색 트래픽이 신버전 일부만 본 채 답변하는 race를 피하기 위해 색인을 **두 단계(Stage A staging → Stage B live swap)**로 나누기로 했다.

1차 시안은 Stage B에서 Pinecone 메타 update로 `index_state="staging" → "live"` swap이었다. 검수 2차 라운드에서 **Pinecone Python SDK의 `Index.update()`는 단일 vector만 지원**(배치 update API 없음)이 발견됐다. 500 청크 짜리 PDF의 swap에 500회 호출 → throttling + 시간 폭증.

## Decision

Stage A에서 vector_id에 `stg:{job_id}:{chunk_index}` prefix를 박고, Stage B에서:
1. 같은 청크를 정상 vector_id `{doc_id}:{version}:{chunk_index}` + 메타 `index_state="live"`로 batch upsert (100건)
2. Stage A의 staging vector ID 리스트를 batch delete (100건)

호출 수 N/100 수준 유지. 호출 사이 짧은 race window는 staging 메타로 격리되므로 검색 노출 없음.

## Alternatives

| 대안 | 거부 사유 |
|---|---|
| `Index.update()` 단건 N회 | 호출 폭증. 500 청크 색인이 throttling으로 분 단위 지연 |
| Append-only (staging 단계 없이 즉시 live, 구버전 별도 정리) | 색인 진행 중 신·구 버전 동시 검색 가능. 답변 정확도 회귀 위험 |
| Pinecone Index 자체를 staging/live 두 개 운영 | 인덱스 비용 2배. 테넌트 수 N → 2N 인덱스. 매우 비쌈 |

## Consequences

긍정적:
- 색인 진행 중 검색 격리 완전 보장 (`index_state="live"` 필터)
- batch API 사용으로 호출 수 1/100 수준
- vector 데이터 재전송 비용은 1536차원 × 4byte × 100 = 600KB/배치 → 무시 가능

부정적:
- 구현 복잡도 증가 (vector_id 두 가지 형식, 단계별 보상 트랜잭션)
- Stage A 실패 시 staging vector 잔존 → cleanup endpoint 필요 (`03 §4.4`)
- Stage B 부분 실패 시 단계별 보상 (`03 §3.6` 표)

후속 작업:
- `03 §3.6` 단계별 보상 트랜잭션 6행 표 명세
- `03 §4.4` cleanup endpoint (`POST /internal/admin/cleanup/orphan-staging`)
- EventBridge cron 일 1회 호출 (admin tool 책임)
- 운영 진입 후 staging 잔존 누적 비율 모니터링

## References

- `docs/03-document-pipeline.md` §3.6 (Stage A·B 흐름)
- `docs/04-data-stores.md` §1.5 (vector_id 명명)
- `docs/operations/runbooks/orphan-staging-accumulated.md` (운영 시 작성 예정)
- 검수 2차 라운드 H-1 (Pinecone update_metadata 한계 발견)
- Pinecone Python SDK `Index.update()` 시그니처: 단건만
