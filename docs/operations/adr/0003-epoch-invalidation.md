# ADR-0003: 캐시 무효화에 SCAN 대신 epoch INCR 채택

- 상태: Accepted
- 일자: 2026-05-07
- 결정자: 본 서버 설계팀
- 관련 docs: `02-query-pipeline.md` §3, `04-data-stores.md` §4.3

## Context

쿼리 캐시(`rag:q1:*` / `rag:q2:*`)는 테넌트 단위로 무효화돼야 한다 — 문서 업로드/수정/삭제 시 테넌트의 모든 캐시가 stale 처리되어야 정확한 답변 보장.

1차 시안은 색인 완료 시 `SCAN MATCH rag:q1:{tenant_id}:*` + `UNLINK`로 일괄 삭제였다. 검수 2차 라운드에서 다음 비용 문제가 발견됐다:
- 한 테넌트당 활성 캐시 키 수: 사용자 다양성 × 질문 다양성 → 수만~수십만 키
- 색인마다 SCAN을 수십~수백 회 돌리는 비용
- ElastiCache CPU 부하 + Worker 색인 throughput 감소
- SCAN cursor가 다른 테넌트 키도 훑으므로 keyspace 전체 비용

## Decision

테넌트당 단일 카운터 `epoch:{tenant_id}` 도입. 캐시 키에 epoch를 포함:
```
rag:q1:{tenant_id}:{epoch}:{access_sig}:{sha256(question_norm)}
rag:q2:{tenant_id}:{epoch}:{access_sig}:{sha256(rewritten_norm)}
```

색인 완료 시 `INCR epoch:{tenant_id}` 1회로 무효화 완료. 기존 키는 자연 만료 (TTL 60~300s).

매 요청 시 epoch GET 1회 추가 — Redis O(1) + 100ms timeout 안에 끝남.

## Alternatives

| 대안 | 거부 사유 |
|---|---|
| `SCAN` + `UNLINK` (1차 시안) | 위 비용 문제. 색인 throughput 깎음 |
| `KEYS pattern` | 블로킹 명령 — Redis 운영 모범사례에서 금지 |
| Redis pubsub으로 무효화 신호 | 모든 reader가 구독해야 함. 본 서버 ECS Task N개 동기화 복잡 |
| 캐시 자체를 짧은 TTL만 (무효화 트리거 없음) | TTL 60s 동안 stale 답변 가능. 문서 업데이트 직후 사용자 경험 저하 |

## Consequences

긍정적:
- 무효화 비용 O(1) — INCR 1회
- ElastiCache CPU 부하 0
- Worker 색인 throughput 영향 없음
- 매 요청 epoch GET 1회는 Redis 100ms 안에 끝남 (총 latency 영향 무시 가능)

부정적:
- 캐시 키 길이 증가 (epoch 정수 추가) — 무시 가능
- Redis 메모리에 stale 키가 잠시 남음 (TTL까지) — 메모리 비용 무시 가능
- INCR 실패 (Redis 일시 장애) 시 잠시 stale 노출 — TTL 60~300s 만료까지

후속 작업:
- `06 §3.2` `/internal/cache/invalidate` endpoint를 Next.js가 권한 변경 시 명시 호출 가능하게
- 같은 endpoint에 tenant당 분당 60회 rate limit (검수 4차 M-4)
- `09 §2.3` `epoch_invalidation_total{tenant_id}` 메트릭 발행 (per-tenant 화이트리스트 적용 시)

## References

- `docs/02-query-pipeline.md` §3 (캐시 정책)
- `docs/04-data-stores.md` §4.3 (Redis 무효화 트리거)
- `docs/03-document-pipeline.md` §3.6 Stage B step 5
- 검수 2차 라운드 H-5 (SCAN 비용 문제 발견)
- Redis 운영 모범사례 — KEYS/SCAN 무효화 안티패턴
