# 00 — Scope

본 서버가 어디에 있고, 무엇을 책임지고, 누구와 어떻게 통신하는지 정의한다.
PR이 본 서버 책임 안인지 판단할 때 기준이 되는 문서다.

## 1. 본 서버의 위치

```
[Client (Next.js)]
     │
     ▼
[Next.js Backend]  ← Supabase Auth 인증, 사용자/테넌트/통계/과금/웹훅
     │  internal HTTP
     │  (검증된 사용자 컨텍스트를 헤더로 주입, SSE는 Next.js가 클라이언트로 프록시)
     ▼
[FastAPI RAG/AI Service]  ← 본 프로젝트
     │
     ├─ AWS Bedrock     (Claude Haiku/Sonnet, Titan Embeddings)
     ├─ Pinecone        (벡터 검색)
     ├─ Neo4j           (그래프 관계 검색)
     ├─ AWS S3          (원본 문서)
     ├─ ElastiCache     (Redis 캐시)
     └─ AWS SQS         (문서 파이프라인 큐)
```

본 서버는 **신뢰된 internal 호출만** 받는다. 클라이언트가 직접 호출하지 않으며, ALB/SG에서 외부 접근을 차단한다는 전제다.

## 2. 책임 범위

### 2.1 본 서버가 직접 구현 (In Scope)

| 영역 | 항목 | ref |
|---|---|---|
| 질의 | Stage 1 Query Rewriter (Claude Haiku 4.5) | PRD §4.1, ARC §4.2 |
| 질의 | Stage 2 Hybrid RAG: Pinecone + Neo4j 병렬 검색, Cross-encoder 재랭킹, Sonnet 4.6 생성 | PRD §4.1, ARC §4.3 |
| 질의 | SSE 스트리밍 응답 | API §2.1 |
| 질의 | 권한·버전·LOW_CONFIDENCE 필터링 | PRD §4.1, SECURITY §6.2 |
| 질의 | 동일 질문 Redis 캐시 | ARC §8 |
| 문서 | PDF/DOCX/XLSX/URL 파싱, 스캔본 OCR(Textract) | PRD §4.2, ARC §5 |
| 문서 | 한국어 친화 청킹 (512 토큰, 50 overlap) | PRD §4.2 |
| 문서 | Titan Embeddings v2 임베딩 생성 | ARC §5 |
| 문서 | Pinecone + Neo4j 색인, 버전 메타 갱신 | ARC §5, ARC §6 |
| 문서 | SQS Worker 소비, DLQ 처리, 재시도 backoff | ARC §5.2 |
| 운영 | Bedrock prompt caching | ARC §11.2 |
| 운영 | 서킷 브레이커, fallback | ARC §9.4 |
| 운영 | 구조적 로그·메트릭·X-Ray span 발행 | ARC §10 |

### 2.2 본 서버 밖 (Out of Scope)

| 영역 | 담당 |
|---|---|
| 로그인·로그아웃·토큰 갱신·MFA | Next.js |
| 사용자 초대·역할 변경·비활성화 | Next.js |
| 테넌트 생성/삭제 (Pinecone Index·Neo4j DB·KMS CMK 프로비저닝) | Next.js 또는 admin tool |
| 통계 집계 대시보드, 주간 리포트 SES 발송 | Next.js 또는 별도 batch |
| 과금 사용량 카운팅·티어 한도 관리 | Next.js |
| 웹훅 등록·서명·발송 | Next.js |
| 인프라 프로비저닝 (VPC·ECS·ALB·API GW·Supabase 프로젝트) | DevOps (Terraform) |
| CI/CD 파이프라인 정의 | DevOps (Harness CD). 본 레포는 Dockerfile·헬스체크·테스트만 |
| 프론트엔드 | 프론트엔드 팀 |

### 2.3 경계 판단 규칙

다음 중 **하나라도** 해당하면 본 서버 책임이 아니다:

- Supabase Auth JWT를 직접 검증·발급한다
- 사용자/테넌트의 식별자 자체를 만들거나 변경한다
- 다른 서비스가 이미 책임지는 기능(인증, 통계 집계, 과금, 웹훅 발송)을 호출한다
- 인프라 리소스(Index, DB, 키)를 새로 프로비저닝한다 — 본 서버는 **이미 존재하는 리소스에 read·write만**

## 3. 경계 인터페이스

### 3.1 신뢰 모델

Next.js↔FastAPI는 같은 VPC Private Subnet 안에서 통신한다. Next.js가 Supabase Auth JWT를 이미 검증한 후 사용자 컨텍스트를 헤더로 주입하므로, **본 서버는 JWT를 재검증하지 않는다**.

신뢰 근거 두 가지:

1. 네트워크 격리 (외부에서 도달 불가)
2. `X-Internal-Auth` 공유 시크릿 (또는 mTLS)

#### 시크릿 회전 (dual-key)

본 서버는 `X-Internal-Auth` 값을 **dual-key 검증**으로 운영한다. 환경 변수 `INTERNAL_AUTH_SECRET_PRIMARY`와 `INTERNAL_AUTH_SECRET_SECONDARY` 두 값을 모두 받아들이고, 둘 중 하나라도 일치하면 통과. 회전 절차:

1. Next.js·FastAPI 양측에 새 secret을 SECONDARY로 추가 배포
2. Next.js가 새 secret으로 호출 전환
3. PRIMARY를 새 secret으로 교체, SECONDARY를 비움
4. 양측 재배포

이 절차로 다운타임 없이 회전. 회전 주기 권장: 90일 (`10-config-and-secrets.md`).

### 3.2 입력: Next.js → FastAPI

| 헤더 | 타입 | 필수 | 용도 |
|---|---|---|---|
| `X-Internal-Auth` | string | ✅ | 신뢰 검증. 실패 시 401 |
| `X-Tenant-Id` | uuid | ✅ | 모든 데이터 접근의 강제 필터 키. 시스템 호출(예: cleanup cron)도 대상 tenant 명시 |
| `X-User-Id` | uuid | ✅ | 감사 로그·캐시 키·EXECUTIVE 접근 판단. 시스템 호출은 reserved UUID `00000000-0000-0000-0000-000000000001` (`SYSTEM_CRON`) 사용 |
| `X-Role` | enum | ✅ | `WITIVE_SUPER_ADMIN` / `COMPANY_ADMIN` / `COMPANY_MANAGER` / `COMPANY_USER` |
| `X-Department` | csv | ❌ | 다중 부서 가능. DEPARTMENT 레벨 필터에 사용 |
| `X-Level` | string | ❌ | 직급 코드. LEVEL 레벨 필터에 사용 |
| `X-Hire-Date` | ISO date | ❌ | Stage 1 컨텍스트 주입에 사용 |
| `X-Request-Id` | string | ❌ | 분산 추적용. 없으면 본 서버에서 생성 |

이 헤더 묶음은 본 서버 안에서 `TenantContext` 도메인 객체로 변환되어 모든 데이터 저장소 접근에 강제 주입된다. 자세한 강제 주입 메커니즘은 `07-multitenancy-and-access.md`.

#### 헤더 정규화 규약 (Next.js↔FastAPI contract)

캐시 키 안정성을 위해 헤더 값 정규화 규칙을 contract로 고정한다.

| 헤더 | 정규화 |
|---|---|
| `X-Department` | 콤마(`,`) 구분, 콤마 주변 공백은 본 서버에서 trim, NFC 유니코드, 영문은 소문자, 빈 항목 제거 후 사전순 정렬 |
| `X-Role` / `X-Level` | trim, enum 값 그대로 (`COMPANY_USER` 등) |
| `X-Tenant-Id` / `X-User-Id` | UUID, lowercase hex with dashes |
| `X-Hire-Date` | ISO 8601 date (`YYYY-MM-DD`) |

#### 시스템 호출 reserved 컨텍스트

EventBridge cron이나 admin tool에서 본 서버 endpoint를 호출할 때(예: `/internal/admin/cleanup/orphan-staging`) 사용자 컨텍스트가 없다. 다음 reserved 값을 사용한다:

| 헤더 | 값 |
|---|---|
| `X-User-Id` | `00000000-0000-0000-0000-000000000001` (SYSTEM_CRON) |
| `X-Role` | `WITIVE_SUPER_ADMIN` |
| `X-Department` | (생략) |
| `X-Level` | (생략) |

본 서버는 `X-User-Id`의 reserved UUID를 감사 로그에 그대로 기록(`audit.actor=system_cron`)해 사후 추적 가능하게 한다.

Next.js는 동일 사용자에 대해 위 정규화 결과가 항상 같도록 헤더를 보낸다. 본 서버는 받은 값을 다시 정규화해 캐시 키를 생성한다 (방어적).

### 3.3 출력: FastAPI → Next.js

- HTTP/JSON 또는 SSE 스트림 (자세한 명세는 `06-api.md`)
- 에러는 `RagError` 도메인 모델을 일관된 형식으로 직렬화 (`12-coding-conventions.md`)
- 외부 사이드 이펙트(웹훅 등)는 본 서버가 직접 발송하지 않는다. 상태 조회 API + 내부 이벤트로만 노출하고, 외부 웹훅은 Next.js가 발송한다.

### 3.4 신뢰하지 않는 입력

internal 호출이라도 다음 입력은 본 서버가 자체 검증한다:

- **사용자 질문 본문**: 길이 1~2,000자, 특수문자/이모지만 포함된 경우 거부, prompt injection 방어
- **업로드 파일**: MIME 화이트리스트, 크기 ≤ 100MB
- **`tenant_id`가 알 수 없는 값**: 존재하지 않는 Pinecone Index/Neo4j DB 접근 시 명시적 에러

## 4. PR 수용 가이드

```
인증·세션·계정 관리 기능?           → 거부
JWT 직접 디코드/검증?                → 거부 (X-Internal-Auth만 검증)
Supabase Auth·SES·Cost Explorer 호출? → 거부
새 통계 집계 화면?                   → 거부 (메트릭만 노출)
tenant_id 필터 우회?                 → 절대 거부
새 인프라 리소스 프로비저닝?         → 거부
Bedrock 모델·프롬프트 변경?          → 02·05 갱신과 함께 수용
파서·청킹·임베딩 변경?               → 03 갱신 + 재색인 영향 평가 후 수용
새 fallback 경로?                    → 08 갱신과 함께 수용
새 메트릭/로그 필드?                 → 09 갱신과 함께 수용
```
