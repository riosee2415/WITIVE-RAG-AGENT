# SOP: 시크릿 회전

- 주기: 시크릿별 다름 (90일 권장 주기는 아래 표)
- 책임자: DevOps
- 소요 시간: 30분 (dual-key 시크릿) / 1시간 (외부 SaaS 시크릿)
- 사전 조건:
  - AWS Secrets Manager 쓰기 권한
  - ECS 재배포 권한 (Harness CD 또는 직접)
  - 본 서버·Next.js 배포 협업

## 시크릿 목록 + 회전 주기

| 시크릿 | 경로 | 주기 | 절차 |
|---|---|---|---|
| `INTERNAL_AUTH_SECRET_PRIMARY/SECONDARY` | `witive/{env}/internal-auth-primary/secondary` | 90일 | dual-key (§2) |
| `PINECONE_API_KEY` | `witive/{env}/pinecone-api-key` | 1년 | 외부 SaaS (§3) |
| `NEO4J_PASSWORD` | `witive/{env}/neo4j-credentials` | 90일 | EC2 admin (§4) |
| `REDIS_AUTH_TOKEN` | `witive/{env}/redis-credentials` | 90일 | ElastiCache rotation (§5) |
| `external/{tenant_id}/{integration_id}` | `witive/{env}/external/...` | 외부 시스템 정책 따름 | 외부 SaaS (§3) |

## 1. 사전 점검

- 회전 대상 시크릿 식별 (Secrets Manager의 `LastRotatedDate` 확인)
- 다음 점검 후 진행:
  - [ ] 본 서버·Next.js 양측 정상 동작
  - [ ] CloudWatch 알람 0건 (다른 사고 진행 중 회전 금지)
  - [ ] Harness CD 배포 파이프라인 정상

## 2. dual-key 시크릿 회전 (`INTERNAL_AUTH_SECRET_*`)

`docs/00-scope.md` §3.1 절차.

### 2.1 새 secret 생성 + SECONDARY로 추가

```bash
NEW_SECRET=$(openssl rand -base64 48)
aws secretsmanager update-secret \
  --secret-id witive/prod/internal-auth-secondary \
  --secret-string "$NEW_SECRET"
```

### 2.2 본 서버·Next.js 동시 재배포 (SECONDARY 인식 시작)

- Harness CD 배포 트리거 (본 서버 + Next.js 두 파이프라인)
- 양측이 SECONDARY로도 검증 가능 상태가 됨

### 2.3 Next.js가 새 secret으로 호출 전환

- Next.js 측 환경 변수 또는 코드에서 PRIMARY 호출 → SECONDARY 호출로 전환
- Next.js 재배포 (또는 핫 리로드)

### 2.4 PRIMARY를 새 secret으로 교체, SECONDARY 비움

```bash
aws secretsmanager update-secret \
  --secret-id witive/prod/internal-auth-primary \
  --secret-string "$NEW_SECRET"

aws secretsmanager update-secret \
  --secret-id witive/prod/internal-auth-secondary \
  --secret-string ""
```

### 2.5 본 서버·Next.js 재배포 (구 secret 인식 종료)

회전 완료. 다음 회전 90일 후.

### 2.6 사후 확인

- CloudWatch에서 401 UNAUTHORIZED 에러 0건 확인 (5분)
- `query.received` 이벤트 분당 카운트가 평소 수준 유지

## 3. 외부 SaaS 시크릿 회전 (Pinecone API key 등)

### 3.1 외부 콘솔에서 새 key 생성 (구 key는 유지)

Pinecone 콘솔 → API Keys → New key → 이름 `witive-prod-{date}`.

### 3.2 staging 환경부터 적용

```bash
aws secretsmanager update-secret \
  --secret-id witive/staging/pinecone-api-key \
  --secret-string "$NEW_KEY"
```

ECS 재배포 → staging 검증 (smoke test, 통합 테스트).

### 3.3 prod 적용

```bash
aws secretsmanager update-secret \
  --secret-id witive/prod/pinecone-api-key \
  --secret-string "$NEW_KEY"
```

Blue/Green 배포 — Canary 10% → 5분 모니터링 → 100%.

### 3.4 구 key 비활성화 (Pinecone 콘솔)

prod에서 신규 key가 정상 동작 확인 후 (24h 권장) 구 key revoke.

## 4. Neo4j password 회전

### 4.1 EC2 SSH/SSM으로 접속

```bash
aws ssm start-session --target i-xxxxxxxxxxxxxxxxx
```

### 4.2 Neo4j admin password 변경

```cypher
ALTER USER neo4j SET PASSWORD '$NEW_PASSWORD' CHANGE NOT REQUIRED;
```

### 4.3 Secrets Manager 갱신

```bash
aws secretsmanager update-secret \
  --secret-id witive/prod/neo4j-credentials \
  --secret-string '{"uri":"bolt://10.0.1.50:7687","user":"neo4j","password":"NEW_PASSWORD"}'
```

### 4.4 ECS 재배포 (롤링)

connection 풀이 새 password로 재연결.

### 4.5 사후 확인

- `neo4j_error_total{code=AUTHENTICATION_*}` 0건 (5분)
- Stage 2 검색 정상

## 5. Redis auth token 회전

ElastiCache는 Multi-Factor Auth (구·신 token 동시 인식 기간) 지원:

```bash
aws elasticache modify-replication-group \
  --replication-group-id witive-prod \
  --auth-token "$NEW_TOKEN" \
  --auth-token-update-strategy ROTATE \
  --apply-immediately
```

ROTATE 모드는 구 token도 일정 기간 인식 → 본 서버 재배포 후 SET 모드로 전환.

```bash
aws elasticache modify-replication-group \
  --replication-group-id witive-prod \
  --auth-token "$NEW_TOKEN" \
  --auth-token-update-strategy SET
```

ROTATE → SET 사이에 본 서버 재배포 (Secrets Manager 갱신 후).

## 6. 사후 확인 (공통)

- CloudWatch 5xx 알람 0건 30분
- `bedrock_estimated_cost_usd` 평소 수준 유지
- 헬스 체크 healthy 유지
- 회전 결과 변경 이력에 기록

## 7. 롤백

회전 도중 인증 실패 폭주 시:

| 단계 | 롤백 |
|---|---|
| dual-key 2.4까지 진행 | SECONDARY에 구 secret 다시 SET → 재배포 |
| 외부 SaaS 3.3까지 진행 | Secrets Manager에 구 key 다시 SET → 재배포 → 외부 콘솔에서 신규 key 비활성화 |
| Neo4j 4.2까지 진행 | EC2에서 구 password로 다시 ALTER USER |
| Redis 5번 SET 모드 진입 후 | 어렵음 — ROTATE 모드 다시 진입 시도, 안 되면 새 ElastiCache 클러스터 |

## 8. 변경 이력

| 일자 | 시크릿 | 담당자 | 결과 |
|---|---|---|---|
| (작성 예정) | | | |
