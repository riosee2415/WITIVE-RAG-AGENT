# 03 — Document Pipeline

`POST /internal/documents/upload` 한 번이 어떻게 검색 가능한 청크가 되는지 정의한다.
이 문서는 동기 단계(검증·S3·SQS)와 비동기 Worker 단계(파싱·청킹·임베딩·색인), 에러 처리·재시도·DLQ 정책을 다룬다.
저장 스키마는 `04-data-stores.md`, fallback·재시도 정책은 `08-resilience.md`.

## 1. 한 문서의 전체 흐름

```
[Next.js] ── multipart upload ──→ [동기 핸들러]
                                       │
                                       ▼
                              [검증]  MIME / 크기 / 해시 / 입력 헤더
                                       │
                                       ▼
                              [S3 저장]  KMS 암호화, 멀티파트
                                       │
                                       ▼
                              [Job 등록]  S3 jobs/{job_id}.json (진실 출처)
                                       │            + Redis 캐시 5s TTL (조회 가속)
                                       ▼
                              [SQS 발행]  doc_id, version, s3_path, tenant_id
                                       │
                                       └─→ HTTP 202 (job_id 반환)

──────────────────────── 비동기 경계 ────────────────────────

[ECS Worker]  SQS Long Polling
      │
      ▼
[잠금]  job 상태 = PARSING (조건부 갱신, 멱등)
      │
      ▼
[파싱]    포맷별 파서 → 정규화 텍스트 + 섹션 메타
      │
      ▼
[청킹]    512 토큰 / 50 overlap / 조항·문단 경계 우선
      │
      ▼
[chunks.jsonl 저장]  S3에 청크 본문 + byte offset 메타 저장 (본문 fetch fallback 출처)
      │
      ▼
[임베딩]  Bedrock Titan v2 (글로벌 rate limit 적용)
      │
      ▼
[색인 — staging]  Pinecone upsert (index_state="staging") + Neo4j MERGE  (둘 다 성공해야 다음 단계)
      │
      ▼
[색인 — swap to live]  Pinecone vector 메타 일괄 갱신 (staging → live), 구버전 vector는 is_current=false
      │
      ▼
[버전 메타 갱신]  S3 metadata.json conditional write, Neo4j Version.is_current 토글
      │
      ▼
[캐시 무효화]  INCR epoch:{tenant_id}  (단일 명령)
      │
      ▼
[완료]  job 상태 = COMPLETED, SQS 메시지 삭제
```

색인은 두 단계로 나뉜다 (staging → live). 검색 트래픽은 항상 `index_state="live"`만 보므로 색인 진행 중인 신버전이 노출되지 않는다 (`02-query-pipeline.md` §5.1, `04-data-stores.md` §1.3).

## 2. 동기 단계 (API 핸들러)

### 2.1 입력 검증

| 검증 | 규칙 | 위반 시 |
|---|---|---|
| 헤더 | `00-scope.md` §3.2의 X-* 필수 | 401/500 |
| 권한 | `X-Role ∈ {COMPANY_ADMIN, COMPANY_MANAGER}`. MANAGER는 `document_groups` 범위 검증 | 403 `FORBIDDEN` |
| MIME | `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `text/html` (URL 등록 시) | 415 `UNSUPPORTED_MEDIA_TYPE` |
| 파일 시그니처 | MIME과 매직 바이트 일치 (위장 차단) | 415 |
| 크기 | ≤ 100MB | 413 `PAYLOAD_TOO_LARGE` |
| SHA-256 해시 중복 | 동일 tenant 내 동일 해시 존재 | 409 `DUPLICATE_FILE` (덮어쓰기 의사 옵션 별도 파라미터로 명시 시 진행) |
| `doc_name` | 1~256자 | 400 |
| `access_level` 정합성 | DEPARTMENT면 `allowed_departments`, LEVEL이면 `allowed_levels`, EXECUTIVE면 `allowed_user_ids` 필수 | 400 |

검증 실패는 모두 동기 응답으로 즉시 종료. SQS·S3에 아무것도 남기지 않는다.

### 2.2 S3 저장

| 항목 | 값 |
|---|---|
| 버킷·prefix | `s3://witive-docs/{tenant_id}/documents/{doc_id}/{version}/original.{ext}` (`04-data-stores.md` §3.1) |
| 암호화 | SSE-KMS, 테넌트별 CMK alias `alias/witive-tenant-{tenant_id}` |
| 업로드 | 모든 파일을 S3 멀티파트 (5MB chunk) |
| 실패 처리 | 멀티파트 abort + 동기 5xx, SQS 발행 안 함 |

### 2.3 Job 등록과 SQS 발행

S3 저장 성공 후에만 다음을 수행 (순서 중요):

1. **Job 영속 등록 (진실 출처)**: `s3://witive-docs/{tenant_id}/jobs/{job_id}.json`에 PutObject. 내용:
   ```json
   {
     "job_id": "uuid7",
     "doc_id": "uuid",
     "tenant_id": "tenant-uuid",
     "version": "2.1",
     "status": "QUEUED",
     "created_at": "...",
     "s3_path": "s3://...",
     "stages": {"parsing":"PENDING","chunking":"PENDING","embedding":"PENDING","indexing":"PENDING"},
     "attempts": 0,
     "error": null,
     "completed_at": null
   }
   ```
2. **Redis 캐시 등록 (조회 가속)**: `job:{job_id}` 키로 동일 내용을 5s TTL로 SET. 진실 출처는 S3, Redis는 단순 캐시.
3. **SQS 발행**: 메시지 본문에 `{job_id, doc_id, tenant_id, version, s3_path, attempt: 0}`. `MessageDeduplicationId`는 `job_id` (FIFO 큐 아니어도 본 서버 dedup용).
4. 클라이언트에 `202 Accepted` + `{job_id, status: "QUEUED", estimated_seconds}` 반환.

S3 PutObject 또는 SQS 발행 실패 시: 동기 5xx. S3 원본 객체는 보존하되 `failed-sqs/` prefix로 격리하고 알람.

### 2.4 작업 상태 조회

`GET /internal/documents/jobs/{job_id}` →
1. Redis `job:{job_id}` 조회 (5s TTL, hit이면 반환)
2. miss 시 S3 `jobs/{job_id}.json` GET → 결과를 Redis에 5s TTL로 캐시 → 반환

상세 응답 스키마는 `06-api.md`.

## 3. Worker 단계

### 3.1 메시지 수신과 잠금

- Long Polling 20s, `VisibilityTimeout=300s` (파싱·임베딩·색인 최대 시간)
- 수신 즉시 S3 jobs/{job_id}.json 조건부 갱신 (`status=QUEUED` 또는 `FAILED_RETRY`일 때만 → `PARSING`). conditional write는 ETag(`If-Match`) 사용 — 멱등 보장
- `attempt > 3`이면 즉시 DLQ로 보냄 (재실행 폭주 방지)
- ETag 충돌(다른 Worker가 먼저 잠금) → 메시지 visibility 즉시 반환 + 다음 메시지로

### 3.2 파싱

| 포맷 | 파서 | 주의 |
|---|---|---|
| PDF (텍스트) | PyMuPDF (`pymupdf`) | 한국어 폰트 인코딩 fallback (cmap 깨질 시 byte 디코드 재시도) |
| PDF (스캔본) | AWS Textract (`DetectDocumentText` 또는 `AnalyzeDocument`) | 페이지당 비용. 텍스트 PDF인지 먼저 판정(추출량 < 임계 시 OCR로 폴백) |
| DOCX | `python-docx` | 표·이미지 캡션은 별도 청크 후보로 추출 |
| XLSX | `openpyxl` | 시트별 가상 섹션, 헤더 row 자동 감지 |
| URL | `httpx` + `selectolax` (또는 `BeautifulSoup4`) + `playwright` (JS 필요 시) | robots.txt는 `urllib.robotparser` (RFC 9309 일부 미지원, 의심 케이스는 보수적으로 차단). 차단 시 작업 실패 |

파서 출력 공통 도메인 스키마:

```
ParsedDocument
├── text: str            (전체 정규화 텍스트, 섹션 사이 \n\n)
├── sections: list[Section]
│   ├── title: str
│   ├── number: str | None   (예: "제3장 제2조")
│   ├── start: int           (text 안의 char offset)
│   └── end: int
└── pages: list[Page]
    └── (text 안 char range → 페이지 번호 매핑)
```

#### 파서 fallback

| 상황 | 처리 |
|---|---|
| 손상 파일 / 디코드 실패 | S3 객체를 `failed-parse/` prefix로 이동, job=`FAILED`, error 코드 기록, Next.js에 알림 (직접 SES 안 함) |
| 텍스트 PDF인데 추출량 < 임계 (기본 100자/페이지) | OCR(Textract)로 자동 폴백 + `warnings: OCR_FALLBACK` |
| 스캔 PDF인데 OCR confidence < 0.70 | confidence 미만 라인 폐기, `warnings: OCR_LOW_CONFIDENCE` |
| URL robots.txt 차단 | job=`FAILED`, error=`URL_BLOCKED` |
| URL 렌더링 timeout | 1회 재시도 후 `FAILED`, error=`URL_RENDER_TIMEOUT` |
| Textract throttling | exponential backoff (1s/2s/4s, 3회) |

### 3.3 청킹

| 항목 | 값 |
|---|---|
| 목표 크기 | 512 토큰 (한국어 약 800~1,000자) |
| overlap | 50 토큰 |
| 경계 우선순위 | 1) 조항 번호 (`제\d+조`, `제\d+항`, `제\d+절`) 2) 섹션 제목 3) 문단(`\n\n`) 4) 문장(`. `, `다.\n`) |
| 최소 크기 | 50 토큰 미만 → 이전 청크에 병합 |
| 최대 크기 | 1024 토큰 초과 시 문장 경계에서 분리 |
| 표·목록 | 단일 청크 유지 (분리 시 의미 손실). 1024 토큰 초과 시 표 행 단위 분리 |

토큰 카운트는 Bedrock Titan과 일치하는 토크나이저 사용 (Titan v2는 sentencepiece). `tiktoken`은 카운트가 다르므로 임베딩 한도 초과 위험 — 청크 후 임베딩 호출 전 실제 토큰 길이 검증.

청크 출력 도메인:

```
Chunk
├── chunk_id: uuid7
├── text: str
├── section: str | None     (예: "3장 2조")
├── page: int | None
├── chunk_index: int
└── char_range: tuple[int, int]
```

### 3.4 chunks.jsonl 저장 (본문 fallback 출처)

청크 결과를 S3 `s3://witive-docs/{tenant_id}/documents/{doc_id}/{version}/chunks.jsonl`에 저장한다 (`04-data-stores.md` §3.4). 라인 단위 NDJSON. **각 라인의 byte offset을 metadata.json의 versions[].chunks 필드에 기록**해 검색 시 byte-range fetch가 가능하게 한다 (`02-query-pipeline.md` §5.6).

이 단계는 Pinecone/Neo4j 색인보다 먼저 끝낸다 — 색인 도중 검색이 들어와 chunk 본문이 필요할 때(이론적 race) S3가 이미 준비된 상태여야 함.

### 3.5 임베딩

| 항목 | 값 |
|---|---|
| 모델 | Bedrock Titan Embeddings v2 (1536 차원) |
| 동시 청크 호출 | 20 |
| 동시 배치 | 4 |
| 호출당 timeout | 5s |
| 글로벌 rate limit | `BEDROCK_TITAN_RPS_LIMIT` (기본 30 RPS, `05-llm-bedrock.md` §5.2) |
| 재시도 | throttling 시 1s/2s/4s 3회 |

배치 안에서 한 청크라도 실패하면 → 해당 청크만 단일 호출로 1회 재시도. 그래도 실패면 청크 단위 격리하고 작업은 `PARTIAL_SUCCESS` 상태로 진행 (다른 청크는 색인 — 06 §4.2 status enum과 통합). 격리된 청크는 알람 + 재처리 큐.

### 3.6 색인 — staging → live (Pinecone + Neo4j)

검색 트래픽이 색인 진행 중인 신버전 청크를 보지 못하도록 두 단계로 나눈다.

**Pinecone `update_metadata`는 단건만 지원**(공식 SDK 한계, `04-data-stores.md` §1.5)이므로 staging→live 전환은 메타 update가 아닌 **upsert + delete 조합**으로 구성한다. 호출 수를 N/100 수준으로 유지.

#### Stage A: staging upsert

> **메타 사전 계산 (Stage A 직전 1회)**: `min_level_rank = min(LEVEL_RANK[lv] for lv in allowed_levels) if access_level == "LEVEL" else None`. 이 값을 Pinecone vector 메타와 Neo4j Document 노드에 박아 LEVEL access 1차 필터에 사용 (`04 §1.3`/`§2.2`, `07 §3.1`). LEVEL_RANK 매핑이 변경되면 재색인 영향 (`07 §1.4`).

1. **Pinecone upsert**: 임시 vector_id `stg:{job_id}:{chunk_index}` + 메타 `index_state="staging"` + 위 사전 계산 필드 (batch 100). 검색은 `index_state="live"` 필터로 자연 제외
2. **Neo4j MERGE**: Document/Version/Chunk 노드 + 관계, `Document.min_level_rank` 박음, `Chunk.staging=true`, `Version.is_current=false` (`04-data-stores.md` §2.5의 ON CREATE/ON MATCH 모두 false 유지)

두 작업 모두 성공해야 Stage B 진입. Stage A 한쪽 실패 → 해당 측 3회 재시도. 최종 실패 시:
- 양쪽 모두 staging이므로 검색 노출 없음 → **롤백 불필요**
- job 상태 = `FAILED_STAGE_A`, S3 jobs/*.json에 `staging_artifact_keys` 기록 (Pinecone vector_id 리스트 + Neo4j chunk_id 리스트)
- §4.5 cleanup endpoint가 24h 후 청소

#### Stage B: atomic-ish swap

순서 중요.

1. **Pinecone live upsert**: 정상 vector_id `{doc_id}:{version}:{chunk_index}` + 메타 `index_state="live"` (batch 100). 같은 청크 데이터를 두 번 전송하지만 호출 수는 N/100
2. **Pinecone staging delete**: Stage A의 staging vector ID 리스트 일괄 delete (batch 100). 1과 2 사이 짧은 race window(~수백 ms)에 staging vector가 잠시 잔존하나, `index_state="staging"`이라 검색에서 보이지 않음
3. **Neo4j swap**: 단일 transaction에서 `Chunk.staging=false`, `Version.is_current=true`, 같은 Document의 구 Version `is_current=false` 토글
4. **S3 metadata.json**: ETag 기반 conditional write, current_version 변경
5. **Redis**: `INCR epoch:{tenant_id}` (단일 명령). 자세한 무효화는 `02-query-pipeline.md` §3.6, `04-data-stores.md` §4.3
6. **비동기 후처리** (실패 무시 OK): 같은 doc의 구버전 Pinecone vector 메타에 `is_current=false` 단건 update. 실패 시 다음 색인에서 자연 보정

#### Bounded retry + 단계별 보상 트랜잭션 (H-6)

각 단계는 3회 재시도 (`STAGE_B_STEP_RETRIES=3`, 250ms/500ms/1s exponential). Stage B 전체 deadline `STAGE_B_DEADLINE_S=60s` — 초과 시 진행 단계 중단, job=`FAILED_STAGE_B`. SQS 메시지는 visibility 회수 후 maxReceiveCount(3)에 따라 DLQ.

| 단계 | 3회 모두 실패 시 |
|---|---|
| 1 (Pinecone live upsert) | live가 들어가지 않음 → Stage A 상태로 간주. job=`FAILED_STAGE_B`, cleanup endpoint 대기 |
| 2 (Pinecone staging delete) | live는 이미 들어감. staging도 잔존 → 검색은 live만 보므로 노출 영향 없음. cleanup endpoint가 처리 |
| 3 (Neo4j swap) | Pinecone live + Neo4j staging — 신버전 vector는 검색에 노출(Pinecone live). 본문 fetch는 chunk_id 기반 매칭(`04 §2.6`)이라 staging 청크도 정상 반환되어 답변 생성은 성공. sources의 `is_current` 표시는 Pinecone 메타를 1차 출처로 사용해 일관성 유지(`06 §3.1` Source.is_current). job=`PARTIAL_SUCCESS`, 알람. **admin tool 책임 (본 서버 외부)**: Neo4j Version.is_current·Chunk.staging 수동 토글. 본 서버의 cleanup endpoint(§4.4)는 staging artifact 청소 전용이며 live↔staging 되돌리기 기능 없음 — admin tool은 Next.js 또는 별도 운영 도구가 직접 Neo4j에 접속해 처리 |
| 4 (S3 metadata.json) | Pinecone·Neo4j는 새 버전이 live. metadata.json 일관성 깨짐 → 검색·답변은 정상 동작 (Pinecone·Neo4j가 진실). job=`PARTIAL_SUCCESS`, 알람. admin tool이 metadata.json 수동 복구 |
| 5 (Redis epoch INCR) | 캐시가 잠시 stale. TTL(60~300s) 만료 자연 회복. warn 로그만 (`02-query-pipeline.md` §3.6과 일관) |
| 6 (구버전 메타 후처리) | 무시 OK |

#### 멱등 보장

같은 (doc_id, version) 재색인:
- Stage A 재시작 → staging vector_id에 `job_id`가 들어가 새 job마다 다른 ID. 이전 job의 staging은 cleanup 대상
- Stage B 재시작 → 정상 vector_id가 chunk_index 기반이라 upsert 멱등. delete도 ID 리스트 기반이라 idempotent
- Neo4j는 MERGE로 멱등

### 3.7 충돌 감지 (Neo4j CONFLICTS_WITH 후보 생성)

같은 doc 내에서 새 버전과 구버전 청크의 조항 번호가 같고 의미 차이가 임계 이상이면 자동 후보 생성.

| 항목 | 값 |
|---|---|
| 의미 차이 측정 | 청크 임베딩 코사인 유사도 |
| 임계 | < 0.92 (`CONFLICT_SIMILARITY_THRESHOLD`) |
| 조항 번호 매칭 | `Chunk.section_number` 일치 |
| 결과 | `(new_version)-[:CONFLICTS_WITH]->(old_version)` 관계 생성 (양방향 처리는 어드민 확인 후) |

자동 생성된 후보는 어드민이 검토·확정하는 워크플로(Next.js)로 넘어간다. 본 서버는 후보 생성까지.

### 3.8 완료

- job 상태 = `COMPLETED`, S3 jobs/*.json 갱신 + Redis 캐시 갱신
- SQS 메시지 삭제
- 메트릭: `documents_indexed_total`, `chunks_indexed_total`, `parse_duration_seconds`, `embed_duration_seconds`, `index_duration_seconds`
- Next.js는 polling으로 완료 확인 (외부 웹훅 발송은 Next.js 책임)

## 4. 재시도·DLQ·실패 격리

### 4.1 재시도 정책

| 단계 | 재시도 | 비고 |
|---|---|---|
| Bedrock 호출 (임베딩) | 3회 exponential backoff | throttling/5xx에 한해 |
| Pinecone upsert | 3회 (250ms/500ms/1s) | 네트워크/5xx에 한해. 4xx는 즉시 실패 |
| Neo4j 쓰기 | 3회 | TransientError에 한해 (driver 자동) |
| Textract | 3회 (1s/2s/4s) | |
| 파싱 | 0회 (deterministic 실패는 재시도 무의미) | |
| metadata.json conditional write | 3회 (ETag conflict는 재읽기 후 재시도) | |

### 4.2 SQS 메시지 단위 재시도

- `maxReceiveCount = 3` (INFRA §SQS)
- `VisibilityTimeout = 300s`
- `attempt` MessageAttribute로 본 서버 측 카운터, redrive policy로 자동 DLQ 이동

### 4.3 DLQ 처리

- DLQ에 1건이라도 들어오면 CloudWatch alarm (`09-observability.md`)
- 본 서버는 DLQ 메시지를 자동으로 다시 큐에 돌리지 않는다 (원인 미해결 상태에서 무한 루프 위험)
- 운영팀이 원인 수정 후 admin tool로 redrive (admin tool은 본 서버 외)

### 4.4 Orphan staging cleanup endpoint (H-2)

본 서버는 `POST /internal/admin/cleanup/orphan-staging?tenant_id={tenant_id}&older_than_hours=24`를 제공한다. admin tool이 EventBridge cron(권장 1일 1회)으로 호출.

동작:
1. S3 jobs prefix에서 `status ∈ {FAILED_STAGE_A, FAILED_STAGE_B, PARTIAL_SUCCESS}` 이고 `created_at < now - older_than_hours`인 job 목록 조회
2. 각 job의 `staging_artifact_keys` (Pinecone vector_id 리스트)로 일괄 delete (batch 100)
3. Neo4j의 `MATCH (c:Chunk) WHERE c.staging = true AND c.chunk_id IN $ids DETACH DELETE c`
4. job 상태 = `CLEANED_UP`

이 endpoint는 `X-Internal-Auth` + `X-Role=WITIVE_SUPER_ADMIN` 둘 다 검증. `00-scope.md` §2.3의 "이미 존재하는 리소스 read·write" 안에 들어간다 (자체 staging artifact 정리이므로).

응답:
```json
{
  "tenant_id": "...",
  "scanned_jobs": 12,
  "cleaned_jobs": 8,
  "deleted_pinecone_vectors": 432,
  "deleted_neo4j_chunks": 432,
  "errors": []
}
```

### 4.5 실패 격리 prefix

| prefix | 용도 |
|---|---|
| `s3://witive-docs/{tenant_id}/documents/{doc_id}/{version}/...` | 정상 |
| `s3://witive-docs/{tenant_id}/jobs/{job_id}.json` | Job 상태 (진실 출처) |
| `s3://witive-docs/{tenant_id}/failed-parse/{doc_id}/...` | 파싱 실패 |
| `s3://witive-docs/{tenant_id}/failed-sqs/{doc_id}/...` | SQS 발행 실패 |
| `s3://witive-docs/{tenant_id}/quarantine/{doc_id}/...` | MIME 위장 등 보안 격리 |
| `s3://witive-docs/{tenant_id}/archived/{doc_id}/...` | 소프트 삭제 |

## 5. URL·API 등록 (스케줄 동기화)

ARC §5.1·API §3.3·§3.4 반영.

- URL 등록 시 `sync_schedule ∈ {DAILY, WEEKLY, MONTHLY}` → 본 서버는 스케줄러 entry point만 제공 (Worker가 cron 트리거로 발화). 실제 cron 스케줄러는 ECS Scheduled Task 또는 EventBridge로 설정 (`10-config-and-secrets.md`)
- API 등록 시 외부 인증 토큰은 AWS Secrets Manager에 저장 (`witive/{env}/external/{tenant_id}/{integration_id}`). 본 서버는 secret 이름만 보유, 값은 런타임 로드
- 토큰 만료/실패 시 job=`FAILED`, error=`EXTERNAL_AUTH_FAILED`, Next.js 알림

## 6. 멱등성 보장

- 동일 SHA-256 파일 재업로드 → 409 (덮어쓰기 명시 옵션 시에만 진행)
- 동일 SQS 메시지 중복 수신 → S3 jobs/*.json conditional write로 1회만 진행
- Worker 중간 충돌(OOM, ECS 재시작) → 메시지 visibility 만료 시 다른 Worker가 처음부터 재시작. staging 청크는 자연 stale로 둠 (검색 영향 없음)
- 같은 (doc_id, version) 재색인 → vector_id·chunk_id 멱등 → 안전

## 7. 환경 변수 한 곳

| 항목 | 기본값 | 환경 변수 |
|---|---|---|
| 최대 파일 크기 | 100MB | `MAX_UPLOAD_BYTES` |
| MIME 화이트리스트 | (위 §2.1) | `ALLOWED_MIME_TYPES` |
| 청크 크기 / overlap | 512 / 50 | `CHUNK_SIZE_TOKENS` / `CHUNK_OVERLAP_TOKENS` |
| 청크 최소/최대 | 50 / 1024 | `CHUNK_MIN_TOKENS` / `CHUNK_MAX_TOKENS` |
| 임베딩 동시 호출 | 20 | `EMBED_BATCH_SIZE` |
| 동시 임베딩 배치 | 4 | `MAX_CONCURRENT_EMBED_BATCHES` |
| Bedrock Titan 글로벌 RPS 한도 | 30 | `BEDROCK_TITAN_RPS_LIMIT` |
| Pinecone upsert 배치 | 100 | `PINECONE_UPSERT_BATCH` |
| Worker 동시 처리 | 4 (prod) | `MAX_CONCURRENT_DOCS` |
| OCR 폴백 임계 | 100자/페이지 | `OCR_FALLBACK_CHAR_PER_PAGE` |
| OCR confidence 임계 | 0.70 | `OCR_MIN_CONFIDENCE` |
| 충돌 감지 임계 (코사인) | 0.92 | `CONFLICT_SIMILARITY_THRESHOLD` |
| Stage B 단계별 재시도 | 3회 | `STAGE_B_STEP_RETRIES` |
| Stage B 전체 deadline | 60s | `STAGE_B_DEADLINE_S` |
| Orphan staging 보존 시간 | 24h | (cleanup endpoint 파라미터) |
| SQS Visibility | 300s | `SQS_VISIBILITY_TIMEOUT_S` |
| Job 캐시 TTL | 5s | `JOB_CACHE_TTL_S` |

## 8. 변경 시 영향 범위

- 청킹 알고리즘 변경 → 모든 기존 문서 **재색인 필요**. 점진적 재색인 admin tool 또는 Next.js 책임. 본 서버는 재색인을 트리거할 endpoint만 제공
- 임베딩 모델 변경 (Titan v2 → v3 등) → 차원 변경 시 새 Pinecone Index 생성 + 전체 재색인. 차원 동일이라도 의미 공간이 달라 재색인 권장
- 새 포맷 지원 추가 → 파서 모듈 + MIME 화이트리스트 + 테스트 케이스
- 색인 staging→live 정책 변경 → `02-query-pipeline.md` §5.1의 Pinecone 필터(`index_state=="live"`)와 `04-data-stores.md` §1.3 메타 스키마 동기화
- chunks.jsonl byte offset 포맷 변경 → `02-query-pipeline.md` §5.6 본문 fetch 코드와 동기화
