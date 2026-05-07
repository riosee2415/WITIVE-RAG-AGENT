# SOP: 신규 테넌트 온보딩

- 주기: 신규 테넌트 추가 시
- 책임자: DevOps + Backend (NestJS) — 본 서버는 호출 받기만
- 소요 시간: 30분 (자동 스크립트 권장)
- 사전 조건:
  - AWS 권한 (Pinecone Index 생성, KMS CMK 생성, Neo4j 접근)
  - NestJS 측 테넌트 메타 등록 endpoint 권한

## 0. 책임 구분 (`docs/00-scope.md` §2.3)

| 작업 | 책임 |
|---|---|
| Pinecone Index 생성 | 본 서버 외 (admin tool 또는 NestJS) |
| Neo4j Database 생성 + 인덱스·analyzer 설정 | 본 서버 외 (admin tool) |
| KMS CMK 생성 + alias | 본 서버 외 (admin tool 또는 Terraform) |
| S3 prefix는 자동 생성 (KMS 정책에서 prefix 허용만) | 본 서버 외 |
| Cognito 사용자 그룹·custom attribute | NestJS |
| 본 서버에 테넌트 메타 등록 (Pinecone host 등) | NestJS — 본 서버는 lazy fetch |

본 서버에는 "테넌트 생성" endpoint가 없다. **본 SOP는 외부 책임 작업이지만 본 서버와의 contract 부분을 명세**.

## 1. 사전 점검

- 신규 tenant_id (UUID) 결정 — NestJS의 테넌트 DB에서 생성
- 테넌트 메타 (회사명, 티어, 한도) NestJS에 등록 완료
- KMS CMK quota 여유 (계정당 한도 확인)
- Pinecone Index quota 여유 (Pinecone 콘솔)
- Neo4j EC2 메모리·DB 수 한도 (보통 EC2당 100+ DB 가능)

## 2. 인프라 프로비저닝 (admin tool 또는 Terraform)

### 2.1 KMS CMK 생성

```python
import boto3
kms = boto3.client("kms", region_name="ap-northeast-2")
key = kms.create_key(
    Description=f"WITIVE tenant {tenant_id} CMK",
    KeyUsage="ENCRYPT_DECRYPT",
    KeySpec="SYMMETRIC_DEFAULT",
    Tags=[{"TagKey": "tenant_id", "TagValue": tenant_id}],
)
kms.create_alias(
    AliasName=f"alias/witive-tenant-{tenant_id}",
    TargetKeyId=key["KeyMetadata"]["KeyId"],
)
kms.enable_key_rotation(KeyId=key["KeyMetadata"]["KeyId"])
```

### 2.2 Pinecone Index 생성

```python
from pinecone import Pinecone, ServerlessSpec, CloudProvider, AwsRegion, Metric
pc = Pinecone(api_key=PINECONE_API_KEY)
pc.create_index(
    name=f"witive-{tenant_id}",
    dimension=1536,
    metric=Metric.COSINE,
    spec=ServerlessSpec(cloud=CloudProvider.AWS, region=AwsRegion.AP_NORTHEAST_2),
    tags={"tenant_id": tenant_id, "env": "prod"},
)
```

생성 직후 host URL을 NestJS 테넌트 메타에 저장.

### 2.3 Neo4j Database 생성 + 인덱스

EC2 SSM:
```bash
aws ssm start-session --target i-xxxxxxxxxxxxxxxxx
```

Cypher (system DB):
```cypher
CREATE DATABASE tenant_${TENANT_HEX} IF NOT EXISTS;
```

대상 DB로 전환 후:
```cypher
:USE tenant_${TENANT_HEX}

CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (v:Version) REQUIRE v.version_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE;

CREATE INDEX IF NOT EXISTS FOR (d:Document) ON (d.access_level);
CREATE INDEX IF NOT EXISTS FOR (v:Version) ON (v.is_current);
CREATE INDEX IF NOT EXISTS FOR (c:Chunk) ON (c.staging);

CREATE FULLTEXT INDEX chunk_text_idx IF NOT EXISTS
FOR (c:Chunk) ON EACH [c.text]
OPTIONS {
  indexConfig: {
    `fulltext.analyzer`: 'cjk',
    `fulltext.eventually_consistent`: false
  }
};
```

분석기 가용성 검증:
```cypher
CALL db.index.fulltext.listAvailableAnalyzers() YIELD analyzer 
WHERE analyzer = 'cjk' RETURN count(*) AS available;
```

`available = 1` 아니면 중단 — Neo4j Enterprise 5.x 버전 점검.

### 2.4 NestJS 테넌트 메타 등록

NestJS 내부 DB에 다음 저장:
- `tenant_id`
- `pinecone_index_host` (2.2에서 받은 URL)
- `neo4j_database_name` (`tenant_${TENANT_HEX}`)
- `kms_key_alias` (`alias/witive-tenant-{tenant_id}`)

본 서버는 NestJS API endpoint(예: `/admin/tenants/{tenant_id}`)를 lazy fetch해 위 정보 가져온다 (`docs/10-config-and-secrets.md` §5.2).

## 3. 본 서버 contract 검증 (smoke test)

본 서버는 자동 호출만 받음. 검증은 NestJS가 본 서버를 호출해서:

### 3.1 헬스 확인 (인증 없이)

```bash
curl $INTERNAL_URL/internal/health
```

본 서버 자체는 정상이어야 함 (테넌트 무관).

### 3.2 빈 query (테넌트 메타 lazy fetch 확인)

```bash
curl -X POST $INTERNAL_URL/internal/query \
  -H "X-Internal-Auth: ..." \
  -H "X-Tenant-Id: $NEW_TENANT_ID" \
  -H "X-User-Id: $TEST_USER_ID" \
  -H "X-Role: COMPANY_USER" \
  -H "Content-Type: application/json" \
  -d '{"question": "테스트 질의"}'
```

기대: `error: NO_RESULTS` (문서 0건이라 검색 결과 없음). 이게 나오면 본 서버가 NestJS 메타 fetch 성공 + Pinecone Index 접근 성공.

`error: SERVICE_UNAVAILABLE` 또는 500이면 메타 fetch·Pinecone 접근 실패 — NestJS 측 메타 또는 Pinecone host 점검.

### 3.3 샘플 문서 업로드 → query 검증

작은 PDF (10 페이지) 업로드 → SQS → Worker → 색인 완료 확인 후 → 관련 질문 query → 정상 답변.

전체 시나리오 5분 안에 끝나야 정상. 안 끝나면 Worker·DLQ 확인.

## 4. 사후 확인

- CloudWatch 신규 tenant_id 첫 호출 메트릭 발행 확인
- Per-tenant 메트릭 화이트리스트(`PER_TENANT_METRIC_TENANT_IDS`)에 추가할지 결정 (`09 §2.2`)
- 비용 메트릭에 신규 tenant 트래픽 추가 확인 (24h 후)

## 5. 롤백 (테넌트 제거)

신규 테넌트가 잘못 생성됐거나 즉시 폐기 필요 시:

### 5.1 트래픽 차단

NestJS에서 해당 tenant_id로의 호출 차단 (NestJS 책임).

### 5.2 본 서버는 자동 처리 없음

본 서버는 테넌트별 자원을 자체 정리하지 않는다. 외부 도구로 정리:

```bash
# Pinecone Index 삭제
pc.delete_index(f"witive-{tenant_id}")

# Neo4j Database 삭제 (system DB)
echo "DROP DATABASE tenant_${TENANT_HEX} IF EXISTS DESTROY DATA;" | cypher-shell -u neo4j -p $PWD

# S3 prefix 삭제 (또는 KMS 키 폐기로 복호화 불가)
aws s3 rm s3://witive-docs/{tenant_id}/ --recursive
aws kms schedule-key-deletion --key-id $KEY_ID --pending-window-in-days 30

# NestJS 테넌트 메타 삭제
```

### 5.3 캐시 정리 (자연 만료 또는 강제)

본 서버 Redis의 `epoch:{tenant_id}`·`meta:tenant:{tenant_id}` 등은 자연 만료. 강제 삭제도 안전:
```bash
redis-cli DEL epoch:{tenant_id} meta:tenant:{tenant_id}
```

## 6. 자동화 권장

위 절차는 admin tool 스크립트로 자동화 권장:
```
admin-tool tenant create --id $TENANT_ID --tier STANDARD
admin-tool tenant smoke-test --id $TENANT_ID
admin-tool tenant delete --id $TENANT_ID --confirm
```

admin tool은 본 서버 외 책임이지만 본 SOP가 contract 명세.
