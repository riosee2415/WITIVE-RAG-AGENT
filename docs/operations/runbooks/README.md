# Runbooks — 사고 대응 절차

본 폴더는 CloudWatch Critical/High 알람과 1:1 매핑되는 사고 대응 절차다.
온콜 엔지니어가 알람을 받으면 해당 runbook을 열고 단계별로 따라간다.

## Runbook 명명·위치

알람 이름과 가까운 파일명. 예:
- `bedrock-outage.md` — Bedrock 장애
- `redis-outage.md` — Redis 장애 (비용 폭증 위험 높음)
- `dlq-message-handling.md` — DLQ 메시지 발생

## 표준 형식

각 runbook은 다음 구조:

```markdown
# Runbook: <사고 명>

- 심각도: Critical | High | Medium
- 알람 트리거: <CloudWatch 알람 이름·임계>
- SLO 영향: <어떤 SLO 위반인지>
- 평균 복구 시간(MTTR 목표): N분

## 1. 1차 대응 (5분 안)

가장 먼저 확인할 것·즉시 조치. 결정 트리.

## 2. 진단

원인 파악 절차. 명령·쿼리·로그 검색.

## 3. 완화 (Mitigation)

서비스 복구 — 근본 원인 해결 전 사용자 영향 최소화.

## 4. 근본 원인 해결

영구 수정.

## 5. 사후 (Post-mortem)

- 알람 발생 시점·복구 시점 기록
- 근본 원인 카테고리
- 향후 예방 조치 (ADR 또는 docs 갱신)
```

## Runbook 인덱스

| 파일 | 알람 | 심각도 |
|---|---|---|
| [`bedrock-outage.md`](./bedrock-outage.md) | `circuit_state{dependency=bedrock} = 2 for 5m` | Critical |
| [`redis-outage.md`](./redis-outage.md) | `circuit_state{dependency=redis} = 2 for 5m` | Critical |
| [`dlq-message-handling.md`](./dlq-message-handling.md) | `dlq_messages_visible > 0` | Critical |

## 추가 작성 예정

본 1차에 포함되지 않은 runbook (운영 진입 전·중 작성):

- `pinecone-outage.md` — Pinecone 장애 → Neo4j 단독 fallback 모니터링
- `neo4j-outage.md` — Neo4j 장애 → Pinecone + S3 본문 fetch fallback
- `cost-spike.md` — `bedrock_estimated_cost_usd` 시간 평균 2배 알람
- `prompt-cache-miss.md` — `bedrock_cache_read_tokens_total = 0 for 24h`
- `partial-success-recovery.md` — Stage B step 3 실패 후 Neo4j 수동 토글
- `orphan-staging-accumulated.md` — staging vector 누적 비정상
- `slo-violation.md` — `query_latency_first_token_ms` P95 > 5s
- `low-cache-hit-ratio.md` — `query_cache_hit_ratio < 0.3`
- `executive-postfilter-spike.md` — post-filter 폐기 비율 비정상

각 runbook은 알람이 처음 발생한 시점에 작성·보강하는 것이 가장 정확하다 (실제 사고 데이터 활용).
