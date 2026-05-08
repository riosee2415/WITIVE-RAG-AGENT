# Runbook: DLQ 메시지 발생

- 심각도: Critical
- 알람 트리거: `dlq_messages_visible > 0` (`docs/09-observability.md` §4.1)
- SLO 영향: 색인 처리량 (사용자 가시성 낮음, 운영 누수 위험 높음)
- 평균 복구 시간 목표: 1시간 (수동 처리 필수)

## 0. 핵심 (DLQ 처리의 특수성)

본 서버는 **DLQ 자동 redrive 금지** 정책 (`08 §7`, ADR 검토 권장). 자동 redrive 시 같은 잘못된 메시지가 무한 반복 → Bedrock·Pinecone API 호출 quota·비용 폭증.

따라서 DLQ는 **항상 수동 게이트** — 알람이 떴다는 건 누군가 들어가서 봐야 한다는 신호.

## 1. 1차 대응 (5분 안)

### 1.1 DLQ 메시지 수 확인

```bash
aws sqs get-queue-attributes \
  --queue-url $SQS_DLQ_URL \
  --attribute-names ApproximateNumberOfMessages
```

1~2건이면 일시적 외부 장애 가능성. 10건+ 또는 단일 시간에 폭주면 본 서버·외부 시스템 결함.

### 1.2 SQS 콘솔에서 메시지 본문 샘플 확인

각 메시지에는 `{job_id, doc_id, tenant_id, version, s3_path, attempt}` 들어 있음. attempt=3은 3회 재시도 후 도달.

### 1.3 같은 시각에 다른 알람 동반?

Bedrock outage 동반이면 임베딩 실패가 원인일 가능성. Bedrock runbook 먼저 진행.

## 2. 진단

### 2.1 메시지별 S3 jobs/{job_id}.json 확인

```bash
aws s3 cp s3://witive-docs/{tenant_id}/jobs/{job_id}.json -
```

`status`, `error`, `stages` 필드로 어느 단계에서 실패했는지 추적.

| 실패 단계 | 가능 원인 |
|---|---|
| `parsing` | 손상 파일, 인코딩 오류, OCR 실패 |
| `chunking` | 매우 드뭄. 메모리 부족 또는 토크나이저 버그 |
| `embedding` | Bedrock Titan throttling/장애 |
| `indexing_stage_a` | Pinecone/Neo4j 일시 장애 |
| `indexing_stage_b` | Stage B 단계 보상 트랜잭션 실패 (`03 §3.6`) |

### 2.2 같은 doc_id의 이전 시도와 비교

```bash
aws s3 ls s3://witive-docs/{tenant_id}/jobs/ | grep {doc_id}
```

같은 파일을 여러 번 시도했는지 확인. 결정론적 실패면 자동 retry 무의미.

### 2.3 같은 테넌트의 다른 메시지들도 영향?

```
fields @timestamp, tenant_id, error.code
| filter event = "document.worker.process" and level in ["ERROR"]
| stats count(*) by tenant_id, error.code
```

## 3. 완화

### 3.1 일시적 외부 장애 (Bedrock·Pinecone outage)

- 외부 서비스 회복 확인 후
- admin tool로 redrive: `POST /admin/sqs/redrive --queue dlq --target main` (admin tool은 본 서버 외 책임)
- 또는 AWS SQS 콘솔에서 수동 메시지 이동 (1건씩, 또는 batch)

### 3.2 결정론적 실패 (손상 파일, 잘못된 데이터)

- 재시도해도 실패. 메시지를 DLQ에 그대로 두고 별도 처리:
  - 사용자(테넌트 ADMIN)에게 Next.js를 통해 알림 — "파일 N이 처리 실패했습니다"
  - 사용자가 파일 수정 후 재업로드
  - DLQ의 메시지는 14일 retention 후 자동 만료 또는 운영팀이 수동 삭제

### 3.3 본 서버 결함 (코드 버그)

- 메시지 본문 + S3 jobs/*.json + 로그를 보존
- 코드 수정 → 배포 → 원본 SQS로 redrive
- DLQ에 있던 메시지는 새 코드로 재처리

### 3.4 staging artifact 정리

DLQ에 들어간 메시지가 Stage A 도중 실패라면 staging vector·Neo4j Chunk가 잔존할 수 있음. cleanup endpoint 호출:
```bash
curl -X POST "$INTERNAL_URL/internal/admin/cleanup/orphan-staging?tenant_id={tenant_id}&older_than_hours=0" \
  -H "X-Internal-Auth: ..." -H "X-User-Id: 00000000-0000-0000-0000-000000000001" -H "X-Role: WITIVE_SUPER_ADMIN"
```

(평소엔 EventBridge cron 1일 1회로 자동, 긴급 시 즉시 호출)

## 4. 근본 원인 해결

| 원인 | 해결 |
|---|---|
| 일시 외부 장애 | 외부 회복 후 redrive. 본 서버 변경 없음 |
| 결정론적 파일 결함 | 사용자에게 알림 + 사용자 측 파일 수정 |
| 본 서버 코드 버그 | 코드 수정 + 배포 + redrive + 14 docs/ADR 갱신 |
| 외부 시스템 contract 변경 (예: Pinecone API 변경) | SDK 버전 핀 갱신 + 통합 테스트 |
| 부하 burst로 일시 throttling | Auto Scaling 임계 조정 또는 Provisioned Throughput |

## 5. 사후

### 5.1 기록

- DLQ 진입 메시지 수
- 원인 카테고리 분포
- redrive 후 성공률
- 각 메시지별 lifecycle (생성 → DLQ 도달 → 처리 시각)

### 5.2 false alarm 패턴 추적

DLQ 알람이 자주 false-positive(일시 장애로 1~2건)면 임계 조정 검토 — 단 자동 redrive는 절대 도입 금지 (ADR 정책). 임계만 "1건" → "5건/시간"으로 완화 가능.

### 5.3 예방 조치 결정 트리

```
원인 카테고리 분포가...
  외부 장애 위주 → 외부 시스템 SLA·circuit breaker 임계 검토
  본 서버 버그 위주 → 통합 테스트 강화 + 코드 리뷰 강화
  파일 결함 위주 → 업로드 단계 검증 강화 (03 §2.1 MIME·시그니처·hash)
```

### 5.4 docs 갱신

이 runbook 자체 보강 + 필요 시 14 docs (`03 §4`) 갱신.
