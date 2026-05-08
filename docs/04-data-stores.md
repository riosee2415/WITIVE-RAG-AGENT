# 04 — Data Stores

본 서버가 사용하는 4개 외부 저장소(Pinecone, Neo4j, S3, Redis)의 명명 규칙·스키마·접근 패턴·격리 정책을 한 곳에 정의한다.
검색 정책은 `02-query-pipeline.md`, 색인 정책은 `03-document-pipeline.md`, 권한 필터 구성은 `07-multitenancy-and-access.md`.

---

## 1. Pinecone

### 1.1 Index 명명 및 사양

| 항목 | 값 | 비고 |
|---|---|---|
| 명명 규칙 | `witive-{tenant_id}` | 테넌트별 물리 격리 (namespace 미사용) |
| Spec | Serverless, AWS, ap-northeast-2 | INFRA §5 |
| dimension | 1536 | Bedrock Titan Embeddings v2 |
| metric | `cosine` | |
| filterable schema | `tenant_id`, `access_level`, `is_current`, `version`, `doc_id`, `effective_date_unix`, `allowed_departments`, `allowed_levels`, `min_level_rank`, `allowed_user_ids`, `index_state`, `archived` | 명시적 schema 선언으로 인덱스 비용 절감 |

테넌트 Index의 생성·삭제는 본 서버 책임이 아니다 (`00-scope.md` §2.3). 본 서버는 존재하는 Index를 조회·upsert만 한다.

### 1.2 클라이언트

Pinecone 공식 SDK의 `PineconeAsyncio` / `IndexAsyncio`를 사용해 네이티브 async I/O. `asyncio.to_thread` 래핑은 사용하지 않는다.

```python
from pinecone import PineconeAsyncio

async with PineconeAsyncio(api_key=PINECONE_API_KEY) as pc:
    async with pc.IndexAsyncio(host=tenant_index_host) as idx:
        results = await idx.query(
            vector=embedding,
            top_k=10,
            filter={...},
            include_metadata=True,
        )
```

`tenant_index_host` 매핑은 본 서버 시작 시 또는 첫 요청 시 lazy 캐시 (`meta:tenant:{tenant_id}` Redis 키, §4.1). 매핑 source는 Next.js가 보유한 테넌트 메타 또는 별도 admin endpoint (`10-config-and-secrets.md` §외부 의존성 부트스트랩).

SDK 메이저 버전(예: `pinecone>=6.0,<7.0`)은 `10-config-and-secrets.md`에 핀.

### 1.3 메타 스키마 (벡터당)

```json
{
  "chunk_id": "uuid7",
  "doc_id": "uuid",
  "doc_name": "취업규칙",
  "version": "2.1",
  "is_current": true,
  "effective_date_unix": 1704067200,
  "section": "3장 2조",
  "page": 12,
  "access_level": "COMPANY_WIDE",
  "allowed_departments": [],
  "allowed_levels": [],
  "min_level_rank": null,
  "allowed_user_ids": [],
  "tenant_id": "tenant-uuid",
  "chunk_index": 5,
  "total_chunks": 42,
  "checksum": "sha256:...",
  "index_state": "live",
  "archived": false
}
```

규칙:

- `tenant_id`는 메타에 박지만 **권한 필터에는 사용하지 않는다**. tenant 격리는 Index 단위 물리 격리에 의존하고, 메타의 `tenant_id`는 감사·사고 조사용
- `effective_date`는 ISO date string 대신 unix timestamp 저장 (Pinecone metadata 범위 비교 가능)
- `access_level`이 `COMPANY_WIDE`일 때 `allowed_*` 배열은 빈 배열 (null 금지 — Pinecone filter `$in` 안정성)
- `min_level_rank`는 `access_level=LEVEL`일 때만 정수 값 (예: `4` = 과장 이상). 그 외는 `null`. 산출: `min(LEVEL_RANK[lv] for lv in allowed_levels)` — 색인 시 1회 계산 (`03-document-pipeline.md` §3.6 Stage A 직전). LEVEL access의 1차 필터에 사용 (`07-multitenancy-and-access.md` §3.1)
- `index_state`: `"staging"` (색인 중) 또는 `"live"` (검색 노출). 검색은 항상 `live`만 본다 (`03-document-pipeline.md` §3.6)
- **청크 텍스트 본문은 메타에 넣지 않는다** (Pinecone metadata size 한계 + 비용). 본문은 Neo4j Chunk 노드와 S3 chunks.jsonl에 보관. 답변 생성 직전 일괄 fetch (`02-query-pipeline.md` §5.6)

### 1.4 검색 패턴 (Stage 2)

```python
filter = {
    "$and": [
        {"index_state": "live"},
        {"archived": False},
        # access_level 분기 (07-multitenancy-and-access.md)
        {"$or": [
            {"access_level": "COMPANY_WIDE"},
            {"$and": [
                {"access_level": "DEPARTMENT"},
                {"allowed_departments": {"$in": ctx.departments}},
            ]},
            # ... LEVEL/EXECUTIVE 케이스 (07 참조; EXECUTIVE는 1차 필터 후 응답 직전 post-filter)
        ]},
    ]
}
if version_filter:
    filter["$and"].append({"version": {"$eq": version_filter}})
else:
    filter["$and"].append({"is_current": {"$eq": True}})
```

자세한 access_level 분기는 `07-multitenancy-and-access.md`. 1차 검색에서 `is_current=true`로 결과가 부족(0건 또는 임계 미달)하면 2차로 `is_current` 필터를 제거하고 `effective_date_unix` 기준 최신 우선으로 다시 (`02-query-pipeline.md` §5.2).

### 1.5 upsert·delete 패턴

- 정상 vector_id: `{doc_id}:{version}:{chunk_index}` (멱등)
- staging vector_id: `stg:{job_id}:{chunk_index}` (Stage A 동안 임시; `job_id`로 동시 색인 충돌 회피)
- 신버전 색인은 두 단계 (`03-document-pipeline.md` §3.6):
  - **Stage A**: 임시 vector_id `stg:{job_id}:{chunk_index}` + 메타 `index_state="staging"`로 upsert (batch 100). 검색은 `index_state="live"` 필터로 자연 제외
  - **Stage B (atomic-ish swap)**: 같은 청크를 정상 vector_id + `index_state="live"`로 다시 upsert (batch 100), 그 다음 staging vector ID 리스트 일괄 delete (batch 100). 두 호출 사이 짧은 race window는 staging 메타로 격리되므로 검색 노출 없음
- 새 버전 추가 시 **구버전 벡터는 삭제하지 않는다** (PRD §4.2 모든 버전 보존). 구버전의 `is_current=false` 메타 갱신은 Stage B 후 비동기 후처리(`Index.update()` 단건; 실패 시 다음 색인에서 자연 보정)
- 소프트 삭제: 해당 doc_id의 모든 vector를 `archived=true` 메타로 갱신. 검색 시 `archived=false` 필터로 제외
- 하드 삭제 (테넌트 해지): Next.js/admin tool이 Index 자체를 삭제. 본 서버는 호출하지 않음

#### Pinecone update_metadata 한계 (전략 결정 근거)

Pinecone Python SDK의 `Index.update()`는 **단일 vector 단위만** 지원 (배치 update API 없음). 따라서 staging→live 전환을 메타 update로 하면 N건 청크에 N회 호출 발생 → throttling·시간 폭증.
위 전략은 **upsert + delete 조합**으로 swap을 구성해 호출 수를 N/100 수준으로 유지한다. 단점은 vector 데이터 재전송이지만, 1536차원 × 4byte × 100 = ~600KB/배치 → 무시 가능 수준.
구버전 `is_current=false` 갱신만 단건 update 사용 (실패해도 안전 — 검색은 새 버전 우선).

### 1.6 timeout·재시도

| 작업 | timeout | 재시도 |
|---|---|---|
| query | 500ms | 0회 (실패 시 Neo4j 단독 fallback) |
| upsert (배치 100) | 2s | 3회 exponential (250ms/500ms/1s) |
| update_metadata (구버전 `is_current=false` 후처리, 단건) | 1s | 3회 (실패 무시 OK, 다음 색인이 자연 보정) |
| delete | 1s | 3회 |

서킷 브레이커 임계는 `08-resilience.md`.

---

## 2. Neo4j

### 2.1 인스턴스·DB 명명

| 환경 | 형태 |
|---|---|
| dev | 사용 안 함 |
| staging / prod | Enterprise EC2 단일 인스턴스 + 테넌트별 logical Database |

| 항목 | 값 |
|---|---|
| Database 명명 | `tenant_{tenant_id_hex}` (대시 제거. 예: `tenant_abc123def456...`) |
| 식별자 시작 | 영문(`tenant_`) prefix로 Neo4j 식별자 규칙(시작 문자 영문) 충족 |
| 식별자 길이 | UUID hex 32자 + prefix 7자 = 39자, Neo4j Database 이름 한도 63자 이내 |
| 시스템 DB | `system` (DB 생성 시에만 사용, 본 서버는 호출 안 함) |
| 클라이언트 | `neo4j` 공식 async driver (`AsyncGraphDatabase.driver`) |
| 연결 풀 | driver 1개 (인스턴스당) + 요청마다 `AsyncSession(database=db_name)` |

DB 생성·삭제는 본 서버 책임이 아니다. 본 서버는 존재하는 DB에 read·write만.

### 2.2 노드·관계 스키마

```
(:Document {
  doc_id: uuid,
  doc_name: string,
  tenant_id: uuid,
  access_level: string,
  allowed_departments: [string],
  allowed_levels: [string],
  min_level_rank: int | null,    // access_level=LEVEL일 때만. 색인 시 LEVEL_RANK 기준 산출 (07 §3.1)
  allowed_user_ids: [uuid],
  archived: bool,
  created_at: datetime
})

(:Version {
  version_id: uuid,
  version: string,           // "2.1"
  is_current: bool,
  effective_date: date,
  uploaded_at: datetime
})

(:Chunk {
  chunk_id: uuid,
  text: string,              // 본문 보관 (Pinecone에는 없음)
  section: string,
  section_number: string,    // "제3조"
  page: int,
  chunk_index: int,
  embedding_id: string,      // Pinecone vector_id 동기화용
  staging: bool              // 색인 중 표기, 검색 시 staging=true 제외. ON CREATE/ON MATCH 모두 명시 (default 없음 → 색인 단계마다 명시 SET)
})

(:Department { name: string, tenant_id: uuid })
```

관계:

```
(Document)-[:HAS_VERSION]->(Version)
(Version)-[:HAS_CHUNK]->(Chunk)
(Version)-[:SUPERSEDES]->(Version)         // 개정 관계, 단방향 (newer → older)
(Version)-[:CONFLICTS_WITH]->(Version)     // 양방향 의미상이지만 1방향 저장 + 쿼리에서 양방향 탐색
(Document)-[:APPLIES_TO]->(Department)
(Document)-[:RELATED_TO]->(Document)
(Document)-[:REFERENCES]->(Document)       // 본문 인용 관계
```

### 2.3 인덱스·제약

```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (v:Version) REQUIRE v.version_id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE;

CREATE INDEX IF NOT EXISTS FOR (d:Document) ON (d.access_level);
CREATE INDEX IF NOT EXISTS FOR (v:Version) ON (v.is_current);
CREATE INDEX IF NOT EXISTS FOR (c:Chunk) ON (c.staging);

// 한국어 검색 품질을 위해 CJK 분석기 명시 (Lucene CJKAnalyzer)
// 'cjk'는 Neo4j 5.x 내장. admin tool이 DB 생성 시 listAvailableAnalyzers()로 가용성 검증.
CREATE FULLTEXT INDEX chunk_text_idx IF NOT EXISTS
FOR (c:Chunk) ON EACH [c.text]
OPTIONS {
  indexConfig: {
    `fulltext.analyzer`: 'cjk',
    `fulltext.eventually_consistent`: false
  }
};
```

각 테넌트 DB 생성 시 함께 적용 (admin tool이 적용. 본 서버는 첫 사용 시 인덱스 존재 여부만 확인, 없으면 경고 로그 + 알람).

#### Analyzer 검증 + 한국어 품질 보강 (H-5)

Lucene CJKAnalyzer는 일본어·중국어에 최적화돼 있고 한국어에서는 char-bigram 기반으로 동작한다. "연차휴가"는 검색 가능하지만 조사가 붙은 "연차의"가 "연차" 단독 검색과 매칭되지 않을 수 있다.

본 서버 정책:

1. **테넌트 DB 생성 시 검증 (admin tool 책임)**: `CALL db.index.fulltext.listAvailableAnalyzers() YIELD analyzer WHERE analyzer = 'cjk' RETURN count(*)`. 0이면 색인 진입 전 차단 + 알람
2. **한국어 recall 측정 (`11-testing.md`)**: 골든셋에 "fulltext recall ≥ 0.7" 케이스 추가. 임계 미달이면 옵션 3로 전환
3. **품질 부족 시 옵션 (Phase 2 후 평가)**: 청킹 단계에서 `Chunk.text_tokens`(공백 분리된 한국어 형태소 결과)를 별도 컬럼으로 보관 + fulltext index를 `text_tokens`에 걸어 standard analyzer 사용. 환경 변수 `NEO4J_USE_TOKENIZED_FIELD=true`로 분기. 03 §3.3 청킹 출력에 형태소 토큰 필드 추가

### 2.4 검색 패턴 (Stage 2)

```cypher
CALL db.index.fulltext.queryNodes('chunk_text_idx', $query_keywords)
YIELD node AS c, score
WHERE c.staging = false
MATCH (v:Version)-[:HAS_CHUNK]->(c)
MATCH (d:Document)-[:HAS_VERSION]->(v)
WHERE d.archived = false
  AND d.access_level IN $allowed_levels
  AND ($version_filter IS NULL AND v.is_current = true OR v.version = $version_filter)
  // department 교집합 (APOC 없이)
  AND (
    d.access_level <> 'DEPARTMENT'
    OR any(dept IN $user_departments WHERE dept IN d.allowed_departments)
  )
  // ... LEVEL/EXECUTIVE 분기는 07 참조
OPTIONAL MATCH (v)-[:CONFLICTS_WITH]-(conflict:Version)   // 방향 미명시 = 양방향 탐색 (Cypher 5.x)
OPTIONAL MATCH (d)-[:RELATED_TO]->(related:Document)
RETURN c, d, v,
       collect(DISTINCT conflict.version) AS conflicts,
       collect(DISTINCT related.doc_name) AS related_docs,
       score
ORDER BY score DESC
LIMIT 10
```

**APOC 의존 제거**: 위 Cypher는 list 교집합을 표준 Cypher의 `any()` + `IN`으로 처리해 APOC 없이 동작한다. APOC 설치 여부는 INFRA(EC2 setup) 책임이며, 본 서버는 APOC 부재를 가정한다. APOC 가용 환경에서 성능 이득이 있다면 별도 환경 변수 `NEO4J_USE_APOC=true`로 분기.

`$query_keywords`는 재작성된 질문에서 stop word 제거 + Lucene 특수문자 escape.

### 2.5 쓰기 패턴 (색인 시)

`MERGE`로 멱등 보장:

```cypher
MERGE (d:Document {doc_id: $doc_id})
ON CREATE SET d += $document_props
ON MATCH SET d.doc_name = $document_props.doc_name, d.access_level = $document_props.access_level

MERGE (v:Version {version_id: $version_id})
ON CREATE SET v += $version_props, v.is_current = false   // staging 단계는 항상 false
ON MATCH  SET v.is_current = false                         // 재시도/재색인 시도에서도 staging 동안 false 유지
MERGE (d)-[:HAS_VERSION]->(v)

// SUPERSEDES 관계: 같은 doc의 이전 current 버전을 식별해 단방향 연결 (재실행 시 멱등)
WITH d, v
OPTIONAL MATCH (d)-[:HAS_VERSION]->(prev:Version {is_current: true})
WHERE prev.version_id <> v.version_id
FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END |
  MERGE (v)-[:SUPERSEDES]->(prev)
)

WITH d, v
UNWIND $chunks AS chunk
MERGE (c:Chunk {chunk_id: chunk.chunk_id})
ON CREATE SET c = chunk.props, c.chunk_id = chunk.chunk_id, c.staging = true
ON MATCH  SET c += chunk.props, c.staging = true       // 재색인 시 명시 props만 갱신, staging=true 강제
MERGE (v)-[:HAS_CHUNK]->(c)
```

Stage B (swap to live):

```cypher
MATCH (v:Version {version_id: $version_id})-[:HAS_CHUNK]->(c:Chunk)
SET c.staging = false
WITH v
SET v.is_current = true
WITH v
MATCH (d:Document)-[:HAS_VERSION]->(v)
MATCH (d)-[:HAS_VERSION]->(prev:Version)
WHERE prev.version_id <> v.version_id AND prev.is_current = true
SET prev.is_current = false
```

전체를 단일 `AsyncTransaction`으로 묶어 `MAX_TRANSACTION_RETRY_TIME=5s`로 자동 재시도.

### 2.6 timeout·재시도

| 작업 | timeout | 재시도 |
|---|---|---|
| 검색 query | 1000ms | 0회 (실패 시 Pinecone 단독 fallback) |
| chunk text 단일 query (`MATCH (c:Chunk) WHERE c.chunk_id IN $ids`) | 100ms | 1회 (S3 chunks.jsonl fallback) |
| 색인 transaction | 5s | TransientError 시 driver 자동 재시도 |
| 시스템 DB 작업 | 본 서버 사용 안 함 | — |

---

## 3. S3

### 3.1 버킷·prefix

| prefix | 용도 |
|---|---|
| `s3://witive-docs/{tenant_id}/documents/{doc_id}/{version}/original.{ext}` | 원본 파일 (정상) |
| `s3://witive-docs/{tenant_id}/documents/{doc_id}/{version}/chunks.jsonl` | 청크 본문 + 메타 (본문 fetch fallback 출처) |
| `s3://witive-docs/{tenant_id}/documents/{doc_id}/metadata.json` | 문서 버전 이력 + current_version + chunk byte offset 인덱스 |
| `s3://witive-docs/{tenant_id}/jobs/{job_id}.json` | 파이프라인 작업 상태 (진실 출처) |
| `s3://witive-docs/{tenant_id}/failed-parse/{doc_id}/...` | 파싱 실패 격리 |
| `s3://witive-docs/{tenant_id}/failed-sqs/{doc_id}/...` | SQS 발행 실패 격리 |
| `s3://witive-docs/{tenant_id}/quarantine/{doc_id}/...` | 보안 격리 |
| `s3://witive-docs/{tenant_id}/archived/{doc_id}/...` | 소프트 삭제 |

### 3.2 암호화 / 접근 제어

| 항목 | 값 |
|---|---|
| SSE | `aws:kms` |
| KMS Key | `alias/witive-tenant-{tenant_id}` (테넌트별 CMK) |
| Bucket Policy | `s3:prefix` 조건으로 cross-tenant prefix 차단 (관리자 책임, 본 서버는 호출만) |
| ECS Task Role | put/get만 가능, 버킷 정책·KMS 키 변경 불가 |

KMS 키는 테넌트 생성 시 Next.js/admin tool이 만든다 (`00-scope.md`).

### 3.3 metadata.json 스키마

```json
{
  "schema_version": 1,
  "doc_id": "uuid",
  "doc_name": "취업규칙",
  "current_version": "2.1",
  "tenant_id": "tenant-uuid",
  "access_level": "COMPANY_WIDE",
  "allowed_departments": [],
  "allowed_levels": [],
  "allowed_user_ids": [],
  "versions": [
    {
      "version": "1.0",
      "effective_date": "2022-01-01",
      "is_current": false,
      "uploaded_at": "2022-01-01T09:00:00Z",
      "uploaded_by": "user-uuid",
      "chunk_count": 38,
      "sha256": "...",
      "chunks_jsonl_size": 84321,
      "chunks_offset": [
        // byte_start, byte_end는 inclusive (HTTP Range 헤더 호환). LF 포함 — 라인 전체.
        {"chunk_id": "...", "byte_start": 0, "byte_end": 412},
        {"chunk_id": "...", "byte_start": 413, "byte_end": 1024}
      ]
    },
    {
      "version": "2.1",
      "...": "..."
    }
  ]
}
```

`schema_version` 필드 도입으로 향후 마이그레이션 안전성 확보.
`chunks_offset`는 본문 fetch 시 byte-range request 용도 (`02-query-pipeline.md` §5.6).

쓰기는 ETag 기반 conditional write (`If-Match`)로 lost-update 방지.

### 3.4 chunks.jsonl

청크당 한 줄 (NDJSON):
```
{"chunk_id":"...","text":"...","section":"...","section_number":"...","page":12,"chunk_index":5,"char_range":[1234,1789]}
```

용도:
- 재색인 시 파싱·청킹을 다시 안 하고 임베딩부터 시작
- **Stage 2 답변 생성 시 chunk 본문 fetch fallback 출처** (`02-query-pipeline.md` §5.6)

본문 fetch:
- metadata.json의 `chunks_offset`을 먼저 GET (캐시 가능, `meta:doc:*` 5분 TTL)
- 청크별 `Range: bytes={byte_start}-{byte_end}` (inclusive) 단일 GET, LF 포함 라인 전체 반환
- S3 SDK는 단일 Range 헤더만 지원 — 5청크 fetch는 **5회 GET (asyncio.gather 병렬)** 또는 청크들의 byte_range를 묶은 단일 큰 range GET 후 클라이언트에서 라인 split. 본 서버는 병렬 5회를 기본 (구현 단순)

### 3.5 jobs/{job_id}.json

`03-document-pipeline.md` §2.3 참조. 본 서버 안에서의 진실 출처. Redis는 단순 5s TTL 캐시.

### 3.6 timeout·재시도

| 작업 | timeout | 재시도 |
|---|---|---|
| GetObject (small) | 2s | 3회 |
| GetObject byte-range (chunks.jsonl) | 500ms | 1회 |
| PutObject (멀티파트, ≤100MB) | 60s | 멀티파트 단계는 SDK 자체 재시도 |
| metadata.json conditional write | 2s | 3회 (ETag conflict는 재읽기 후 재시도) |
| jobs/*.json conditional write | 2s | 3회 |

---

## 4. Redis (ElastiCache)

### 4.1 키 명명 규약

모든 키는 prefix를 가지며 colon으로 구분.

| 키 패턴 | 용도 | TTL |
|---|---|---|
| `epoch:{tenant_id}` | 테넌트 캐시 무효화 카운터 | 무 TTL (영속) |
| `rag:q1:{tenant_id}:{epoch}:{access_sig}:{sha256}` | 1차 캐시 (원본 정규화) | 60s/300s (`02-query-pipeline.md` §3.4) |
| `rag:q2:{tenant_id}:{epoch}:{access_sig}:{sha256}` | 2차 캐시 (재작성 정규화) | 동일 |
| `dup:{user_id}:{sha256}` | 동일 질문 반복 카운터 | 60s |
| `meta:doc:{tenant_id}:{doc_id}` | 문서 메타 캐시 | 300s |
| `meta:tenant:{tenant_id}` | 테넌트 메타 캐시 (Pinecone host 등) | 600s |
| `meta:user:{user_id}` | 사용자 프로필 캐시 (필요 시) | 600s |
| `job:{job_id}` | 파이프라인 작업 상태 캐시 (S3 진실 출처의 5s TTL 캐시) | 5s |

### 4.2 값 형식

| 키 | 값 | 직렬화 |
|---|---|---|
| `epoch:*` | 정수 (INCR) | 기본 |
| `rag:q1`, `rag:q2` | SSE 이벤트 시퀀스 | MessagePack 또는 JSON gzip (응답 보통 < 4KB) |
| `dup:*` | INCR 카운터 (정수) | 기본 |
| `meta:*` | dict | JSON |
| `job:*` | dict | JSON |

### 4.3 무효화 트리거

| 트리거 | 삭제·갱신 대상 |
|---|---|
| 문서 업로드/수정/삭제 완료 (Worker §3.6 마지막) | `INCR epoch:{tenant_id}` (단일 명령). `meta:doc:{tenant_id}:{doc_id}`도 삭제 |
| 사용자 권한 변경 (Next.js 호출) | `meta:user:{user_id}` 삭제. epoch 건드리지 않음 (access_sig 변화로 자연 새 키) |
| 테넌트 메타 변경 (Next.js 호출) | `meta:tenant:{tenant_id}` 삭제 |
| 파이프라인 상태 변경 | `job:{job_id}` 5s TTL 자연 만료 + 다음 GET에서 S3 재캐싱 |

**SCAN/KEYS 사용 금지** — 모든 무효화는 `INCR epoch:{tenant_id}` 또는 단일 키 DEL/UNLINK로 충족된다. 운영 중 SCAN이 보이면 코드 리뷰에서 차단.

### 4.4 캐시 hit/miss 메트릭

`09-observability.md`에서 단일 진실 출처:
- `query_cache_hit_total{stage="q1"|"q2"}`
- `query_cache_miss_total{stage="q1"|"q2"}`
- `meta_cache_hit_ratio`
- `epoch_invalidation_total{tenant_id}` (per-tenant 화이트리스트)

### 4.5 timeout·재시도

| 작업 | timeout | 재시도 |
|---|---|---|
| GET / SET / INCR / DEL | 100ms | 1회 |

Redis 장애 시: 캐시 미스로 폴백 (서비스 가용성 유지). epoch GET 실패 시 캐시 조회를 생략하고 정상 흐름 진행. 미스 폭주에 의한 Bedrock 비용 증가는 알람으로 감지.

---

## 5. Cross-store 일관성

### 5.1 색인 시 일관성 (Pinecone ↔ Neo4j)

`03-document-pipeline.md` §3.6: staging → live 두 단계.
- **Stage A (staging)** 부분 실패 → 검색 노출 안 됨, 자연 stale 잔존, admin cleanup
- **Stage B (swap)** 부분 실패 → 단계별 보상 트랜잭션 (§3.6 표)

### 5.2 검색 시 일관성

검색은 두 저장소를 병렬 query하되, 한쪽이 다른 쪽보다 늦게 색인된 상태가 있을 수 있다. 본 서버는 이를 받아들이고 두 결과를 합쳐 재랭킹한다 (`02-query-pipeline.md` §5.1·§5.3). `index_state="live"` 필터로 staging 청크는 제외.

### 5.3 메타 일관성 (S3 metadata.json ↔ Neo4j Version.is_current ↔ Pinecone is_current)

같은 `is_current` 정보가 세 곳에 있다.

**Stage B 단계 순서는 `03-document-pipeline.md` §3.6이 단일 진실 출처**다 (6단계: Pinecone live upsert → Pinecone staging delete → Neo4j swap → S3 metadata → Redis epoch INCR → 비동기 후처리). 본 절은 시점만 요약:

- **Neo4j swap**(staging→live)이 metadata.json보다 먼저 끝나야 한다 — 외부(Next.js)는 metadata.json을 진실 출처로 보므로, metadata.json 갱신 후 검색이 들어오면 Neo4j·Pinecone이 이미 정합 상태여야 한다
- **구버전 Pinecone `is_current=false`** 갱신은 Stage B 마지막 비동기 후처리(단건 update; Pinecone batch 한계 §1.5). 실패해도 안전 — 검색 결과가 신·구 버전 모두 노출될 수 있으나 재랭킹 + 신버전 우선 정책으로 영향 최소

### 5.4 chunk 본문 일관성 (Neo4j Chunk.text ↔ S3 chunks.jsonl)

같은 본문이 두 곳에 보관되어 답변 생성 시 본문 fetch의 fallback path를 보장한다.
- 정상: Neo4j MATCH 1회로 5개 청크 본문 일괄 fetch (100ms)
- Neo4j 단독 장애 / dev 환경: S3 chunks.jsonl byte-range fetch (500ms)
- 둘 다 실패: `error: SERVICE_DEGRADED`로 생성 생략, sources만 노출

청킹 알고리즘 변경 시 두 곳 모두 재작성됨 (멱등 보장).

### 5.5 캐시-데이터 일관성

문서 변경 후 epoch INCR 실패 → TTL이 짧아 자연 만료까지 최대 60s(prod 업무시간) 동안 구버전 캐시 노출. 안전성보다 가용성을 택한 설계 (`02-query-pipeline.md` §3.6).

---

## 6. 변경 시 영향 범위

- Pinecone 메타 스키마 추가 → filterable schema 갱신 (Index 재생성 필요할 수 있음, admin tool 책임). 본 서버 색인 코드의 메타 building과 검색 필터 동시 수정
- Pinecone Index 명명 규칙 변경 → 모든 테넌트 마이그레이션 필요. 매우 비싼 변경
- Pinecone async SDK 메이저 버전 업 → `IndexAsyncio` 시그니처 변경 가능. `10-config-and-secrets.md` 버전 핀 + 통합 테스트
- Neo4j fulltext analyzer 변경 → 인덱스 재생성. 검색 결과 품질 평가 필요 (`11-testing.md`)
- Neo4j 노드/관계 추가 → Cypher 패턴 갱신, 인덱스 추가 권고
- S3 prefix 구조 변경 → 기존 데이터 마이그레이션. metadata.json `schema_version` 활용
- chunks.jsonl 포맷·byte offset 구조 변경 → `02-query-pipeline.md` §5.6 fetch 코드와 동기화
- Redis 키 prefix 변경 → 운영 중 변경 시 dual-write·dual-read로 점진 전환
- epoch 카운터를 다른 무효화 패턴으로 교체 → `02-query-pipeline.md` §3, `03-document-pipeline.md` §3.6과 동시 변경
