# Runbook: Bedrock 장애

- 심각도: Critical
- 알람 트리거: `circuit_state{dependency=bedrock} = 2 for 5m` (`docs/09-observability.md` §4.1)
- SLO 영향: 첫 토큰 P95 / 답변 완료 / no_results_rate
- 평균 복구 시간 목표: 30분 (Bedrock 측 회복 의존)

## 1. 1차 대응 (5분 안)

### 1.1 알람 확인

```
- 어느 stage가 영향? Stage 1 / Stage 2 (답변 생성) / Titan (임베딩)
- 어느 모델? Haiku / Sonnet / Titan-v2
- 어느 region? ap-northeast-2
```

CloudWatch Logs Insights:
```
fields @timestamp, level, event, error.code, error.type
| filter event like /bedrock/ and level in ["ERROR", "CRITICAL"]
| stats count(*) by error.code
| sort count desc
```

### 1.2 AWS Health Dashboard 확인

```
https://health.aws.amazon.com/health/home → Bedrock service for ap-northeast-2
```

AWS 측 광범위 장애면 본 서버는 fallback 동작 중 — 4번으로 직행.
계정 단위 issue(quota·throttling)면 2·3번 진행.

### 1.3 본 서버 fallback 동작 확인

알람 발생해도 본 서버는 자동 fallback 중이어야 함:
- Stage 1 장애 → 원본 질문 fallback (`02 §4.3`)
- Stage 2 답변 생성 장애 → 검색 결과 원문 반환 (`02 §5.7`, GENERATION_DEGRADED)
- Titan 임베딩 장애 → Pinecone 검색 불가 → Neo4j 단독 (`02 §5.1`)

`query_no_results_rate` 메트릭으로 사용자 영향 추정. 30%+이면 사용자 통보 검토.

## 2. 진단

### 2.1 throttling 확인

```
fields @timestamp, error.code
| filter event like /bedrock/ and error.code = "ThrottlingException"
| stats count(*) by bin(1m)
```

throttling이라면 quota 부족 — AWS Bedrock Service Quotas 콘솔에서 현재 할당량 확인.

### 2.2 5xx vs timeout 분포

```
fields error.code, error.type
| filter event like /bedrock/
| stats count(*) by error.code, error.type
```

- 5xx 다수: AWS 측 장애. 4번 완화 후 회복 대기
- timeout 다수: 네트워크 또는 모델 지연. VPC Endpoint 상태 확인

### 2.3 VPC Endpoint 상태

```bash
aws ec2 describe-vpc-endpoints --filters "Name=service-name,Values=com.amazonaws.ap-northeast-2.bedrock-runtime"
```

`State=available` 아니면 인프라 문제 — DevOps 호출.

## 3. 완화

### 3.1 throttling이면 — Provisioned Throughput 임시 증설 검토

Bedrock 콘솔 → Provisioned Throughput → 모델별 단위 확인. 비용 발생하므로 사용자 영향 큰 경우만.

### 3.2 광범위 장애면 — 사용자 영향 통제

- 본 서버는 자동 fallback 중. Next.js·운영팀에 상황 공유
- 필요 시 `MAINTENANCE_MODE=true` 수동 전환 (`08 §6`) — 비용 폭증 방지가 더 중요한 경우
- 단, MAINTENANCE_MODE는 모든 query 503이라 사용자 경험 0. 보통은 fallback 유지가 낫다

### 3.3 prompt cache 미형성으로 비용 증가 시

`bedrock_cache_read_tokens_total = 0 for 24h` 알람도 함께 발생할 수 있음 — `prompt-cache-miss.md` runbook 참조.

## 4. 근본 원인 해결

| 원인 | 해결 |
|---|---|
| AWS 측 일시 장애 | 회복 대기. 별도 조치 없음 |
| 계정 quota 부족 | AWS Support 티켓 → quota 증설 (보통 24~48h) 또는 Provisioned Throughput |
| inference profile ARN 잘못된 region | `BEDROCK_REGION`·`BEDROCK_MODEL_*` 환경 변수 점검 |
| VPC Endpoint 장애 | DevOps + Terraform 점검 |
| 모델 ID 변경 (예: deprecated) | 환경 변수 갱신 + ECS 재배포. 사전에 새 모델 호환성 검증 (`11 §4.3`) |

## 5. 사후

### 5.1 기록

- 알람 발생 시각
- 자동 복구 vs 수동 개입 여부
- 영향 받은 사용자 수 (대략)
- `bedrock_estimated_cost_usd` 사고 동안 누적 비용
- 회복 시각

### 5.2 예방 조치 결정 트리

```
사고가 자동 fallback으로 충분히 보호됐는가?
  YES → docs/runbook 갱신 정도로 종료
  NO  → 어느 fallback이 부족했는가?
    ├─ Stage 2 fallback이 본문 fetch 실패로 SERVICE_DEGRADED → 본문 fetch 정책 보강 (`02 §5.6`)
    ├─ 비용 폭증 (cache 미형성) → prompt cache 정책 보강 (`05 §4.2`)
    └─ 너무 많은 fallback 발생 → 새 ADR로 fallback 정책 변경 검토
```

### 5.3 docs 갱신

이 runbook 자체에 새로 발견된 진단 명령·완화 옵션 추가. 근본 원인이 본 서버 결함이면 14 docs 또는 새 ADR로 반영.
