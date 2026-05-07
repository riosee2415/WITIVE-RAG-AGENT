# Runbook: Redis (ElastiCache) 장애

- 심각도: Critical
- 알람 트리거: `circuit_state{dependency=redis} = 2 for 5m` (`docs/09-observability.md` §4.1)
- SLO 영향: **비용 5배 폭증** (캐시 미스 → Bedrock 호출 비율 ↑)
- 평균 복구 시간 목표: 15분 (자동 MAINTENANCE_MODE 전환 5분 + 운영팀 대응)

## 0. 핵심 (Redis 장애의 특수성)

Redis 장애는 다른 의존성 장애와 달리 **사용자 가용성보다 비용 폭증이 더 큰 위험**이다.
- 캐시 미스 100% → 모든 query가 Bedrock 호출 → 평균 비용 ~5배
- 5,000 RPM 트래픽이 30초만 풀 미스해도 비용 수십 달러/분
- 본 서버 자동 시간선(`08 §3.3`)을 따라가되, **5분 내 복구 안 되면 자동 MAINTENANCE_MODE 진입**으로 비용 차단

## 1. 1차 대응 (5분 안)

### 1.1 알람 + 본 서버 시간선 위치 확인

`08 §3.3` 시간선:
- t=0~30s: 로컬 token bucket fallback. 비용 정상보다 ~5배
- t=30s 시점: Half-Open 시도
- t=5min: **자동 MAINTENANCE_MODE 전환** (모든 query 503)

CloudWatch:
```
fields @timestamp, event
| filter event = "circuit.open" and dependency = "redis"
| sort @timestamp desc
| limit 5
```

알람 시각 = circuit Open 시각. 5분 카운트다운 시작.

### 1.2 ElastiCache 상태 확인

```bash
aws elasticache describe-replication-groups \
  --replication-group-id witive-prod \
  --query 'ReplicationGroups[0].{Status:Status,Members:MemberClusters}'
```

Status가 `available` 아니면 ElastiCache 측 issue.

### 1.3 비용 모니터링 즉시 확인

`bedrock_estimated_cost_usd` 분당 합산이 평소의 3배 이상이면 사고 진행 중. 5분 안에 복구 안 되면 MAINTENANCE_MODE가 자동 보호.

## 2. 진단

### 2.1 cluster failover 발생?

```bash
aws elasticache describe-events \
  --source-identifier witive-prod \
  --source-type replication-group \
  --duration 30
```

failover 이벤트가 있으면 일시 장애. 보통 1~2분 안에 자동 회복.

### 2.2 메모리 압박?

CloudWatch Metric `AWS/ElastiCache/DatabaseMemoryUsagePercentage` (replication-group 단위) > 90%면 OOM 위험. evict policy 확인.

### 2.3 connection 한계?

`AWS/ElastiCache/CurrConnections` > maxclients 임계 → ECS Task 수 × Redis pool size × N tenants 합산 부담.

### 2.4 네트워크 문제?

VPC route, SG 변경 사항 확인 (DevOps 협의).

## 3. 완화

### 3.1 5분 안에 복구되면

- 본 서버 자동 Half-Open → Closed 복귀 (`08 §3.3`)
- MAINTENANCE_MODE 진입 안 함
- post-mortem만 진행

### 3.2 5분 미회복 → 자동 MAINTENANCE_MODE 진입 시

- **사용자에게 503 + Retry-After: 60 응답**. NestJS·클라이언트는 자연 throttle
- ElastiCache 복구 완료까지 대기
- 복구 후 환경 변수 `MAINTENANCE_MODE=false` 수동 해제 + ECS 재배포 (또는 Parameter Store 변경 + 핫 리로드)
- Redis 재연결 확인 후 정상 트래픽 회복

### 3.3 ElastiCache 자체가 회복 안 될 때 (장기 장애)

- AWS Support 티켓 (Critical priority)
- Multi-AZ failover 강제 (`aws elasticache test-failover --replication-group-id witive-prod --node-group-id ...`)
- 최후 수단: 새 ElastiCache 클러스터 프로비저닝 (Terraform) + 환경 변수 `REDIS_URL` 갱신 + ECS 재배포. 캐시는 0에서 재형성

### 3.4 비용 폭증 추가 방어

MAINTENANCE_MODE 진입 전 30s~5min 동안 발생한 추가 Bedrock 비용 추정:
```
extra_cost = (실 호출 수 - 기대 호출 수) × 평균 호출 비용
            ≈ (5min × RPM × (1 - normal_cache_hit_ratio)) × $0.020
```

5,000 RPM × 5min × 0.5 hit ratio × $0.020 ≈ $250 추가 비용 가능. 회복 후 `bedrock_estimated_cost_usd` 메트릭으로 실제 비용 확인.

## 4. 근본 원인 해결

| 원인 | 해결 |
|---|---|
| ElastiCache failover | 정상. Multi-AZ 동작. 별도 조치 없음 |
| 메모리 OOM | 노드 타입 증설 (t3.small → t3.medium 등) + Terraform |
| connection 한계 초과 | maxclients 증설 또는 Redis pool size 조정 (10 §2.7) |
| 네트워크/SG | DevOps + Terraform |
| ElastiCache 측 광범위 장애 | AWS Support 회복 대기 |

## 5. 사후

### 5.1 기록

- 알람 발생 시각
- t=5min MAINTENANCE_MODE 진입 여부
- ElastiCache 회복 시각
- 사용자 503 받은 시간 (MAINTENANCE_MODE 동안)
- `bedrock_estimated_cost_usd` 사고 동안 추가 비용

### 5.2 비용 사고 보고

비용이 평소의 3배 이상이면 별도 보고서:
- 비용 차이 ($)
- 원인 (Redis 장애 + cache 미스)
- 방어선 작동 여부 (MAINTENANCE_MODE 자동 진입했는가)
- 향후 임계 조정 검토 (예: 5min → 3min)

### 5.3 예방 조치

```
ElastiCache failover 빈도가 잦다 → Multi-AZ를 더 안정한 노드 타입으로
  연 1~2회 → 정상 (운영 가이드만 보강)
  월 1회+ → ADR로 노드 타입·DR 전략 변경 결정

5분 임계가 너무 길어 비용 폭증이 심하다 → 임계 단축 ADR
  prod cache hit ratio가 매우 높다면 (95%+) 1~2분으로 단축 가능
  hit ratio가 낮다면 5분 유지 (잦은 MAINTENANCE_MODE는 사용자 경험 ↓)
```

### 5.4 docs 갱신

이 runbook 자체 + 필요 시 `08 §3.3` Redis 시간선 임계 조정 ADR.
