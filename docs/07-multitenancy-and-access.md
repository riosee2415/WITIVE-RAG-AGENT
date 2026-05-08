# 07 — Multitenancy & Access Control

테넌트 격리 강제 메커니즘과 RBAC × 문서 접근 레벨 결합 방식의 단일 진실 출처.
원시 데이터 격리 패턴은 `04-data-stores.md`, 권한 검증 시점은 `02-query-pipeline.md` §5.4·§3.2.

본 docs는 권한 필터를 **1차 데이터 저장소(Pinecone metadata filter, Neo4j Cypher WHERE)에서 선처리**하는 정책을 강조한다 — 후처리 폐기는 Bedrock 토큰을 낭비시키므로 비용·성능 양쪽에 부정적.

## 1. 도메인 모델

### 1.1 TenantContext

`X-*` 헤더 7개로부터 build (`00-scope.md` §3.2). 모든 use case (pipeline 함수)는 `TenantContext`를 첫 인자로 받는다.

```python
@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user_id: UUID
    role: Role                           # enum
    departments: tuple[str, ...]         # 정규화 + 정렬됨, 빈 tuple 가능
    level: Level | None
    hire_date: date | None
    request_id: str

    @property
    def is_system_cron(self) -> bool:
        return self.user_id == UUID("00000000-0000-0000-0000-000000000001")
```

`frozen=True`로 immutable. `pipeline` 안에서 새 컨텍스트가 필요하면 `replace()`로 새 인스턴스 생성.

### 1.2 Role 매트릭스

| Role | 약어 | 본 서버 endpoint 권한 |
|---|---|---|
| `WITIVE_SUPER_ADMIN` | SUPER_ADMIN | 모든 endpoint + admin endpoint |
| `COMPANY_ADMIN` | ADMIN | 질의 + 문서 업로드 + cache/invalidate |
| `COMPANY_MANAGER` | MANAGER | 질의 + 담당 문서 그룹 한정 업로드 |
| `COMPANY_USER` | USER | 질의 |

매니저의 "담당 문서 그룹" 검증 자체는 Next.js 책임 (사용자→문서 그룹 매핑은 Next.js DB). 본 서버는 Next.js가 보낸 `X-Role`을 신뢰.

### 1.3 Access Level 매트릭스

| AccessLevel | 의미 | 1차 저장소 필터 가능? | 후처리 필요? |
|---|---|---|---|
| `COMPANY_WIDE` | 전 직원 | ✅ (단순 매칭) | ❌ |
| `DEPARTMENT` | 지정 부서 | ✅ (Pinecone `$in`, Neo4j `any() IN`) | ❌ |
| `LEVEL` | 지정 직급 이상 | ✅ (Pinecone `$lte`, Neo4j 비교) | ❌ |
| `EXECUTIVE` | 명시 사용자 | ⚠️ 부분 — 캐시 키에 user_id 미포함이 정책이므로 **응답 직전 post-filter** | ✅ (`02 §5.4`) |

**EXECUTIVE만 후처리**인 이유: 캐시 키 access_sig에 user_id를 포함하면 캐시 hit ratio 0에 수렴 (`02 §3.2`). 트레이드오프: EXECUTIVE 청크는 1차 필터에서 통과 후 응답 직전 화이트리스트로 잘라냄.

이 비대칭은 본 서버 docs의 정책 결정. 변경 시 `02-query-pipeline.md` §3.2와 동시 갱신.

### 1.4 Level 비교

`level_rank` 매핑(낮은 직급 → 높은 직급 순):

```python
LEVEL_RANK = {
    "사원": 1,
    "주임": 2,
    "대리": 3,
    "과장": 4,
    "차장": 5,
    "부장": 6,
    "이사": 7,
    "상무": 8,
    "전무": 9,
    "사장": 10,
}
```

매핑은 환경 변수 `LEVEL_RANK_JSON`로 외부화 (테넌트별 직급 체계 차이를 대비). 본 서버는 매핑 미정의 직급에 대해 **fail-closed** — `LEVEL` 접근 레벨 매칭 실패 처리하고 warn 로그.

## 2. 강제 주입 미들웨어

### 2.1 헤더 검증 → TenantContext build

FastAPI dependency로 모든 endpoint(`/health` 제외)에 강제 주입:

```python
async def require_tenant_context(
    x_internal_auth: str = Header(...),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-Id"),
    x_user_id: UUID = Header(..., alias="X-User-Id"),
    x_role: Role = Header(..., alias="X-Role"),
    x_department: str = Header("", alias="X-Department"),
    x_level: str | None = Header(None, alias="X-Level"),
    x_hire_date: date | None = Header(None, alias="X-Hire-Date"),
    x_request_id: str | None = Header(None, alias="X-Request-Id"),
) -> TenantContext:
    if not constant_time_eq(x_internal_auth, settings.PRIMARY_SECRET) and \
       not constant_time_eq(x_internal_auth, settings.SECONDARY_SECRET):
        raise HTTPException(401, "UNAUTHORIZED")
    departments = normalize_departments(x_department)
    return TenantContext(...)
```

`constant_time_eq`로 timing attack 방어. dual-key는 `00 §3.1`.

### 2.2 데이터 저장소 접근 강제

`infra/` 어댑터의 모든 호출은 `TenantContext`를 인자로 받고, 자체 검증한다.

```python
class PineconeAdapter:
    async def query(self, ctx: TenantContext, vector, ...) -> ...:
        index = self._index_for_tenant(ctx.tenant_id)   # 잘못된 tenant_id면 KeyError → 500
        filter = build_pinecone_filter(ctx, ...)
        return await index.query(vector=vector, filter=filter, ...)

    async def upsert(self, ctx: TenantContext, vectors) -> ...:
        if any(v["metadata"].get("tenant_id") != str(ctx.tenant_id) for v in vectors):
            raise SecurityError("cross-tenant vector detected")
        ...
```

**tenant_id 누락 코드는 코드 리뷰에서 차단**. 컴파일·런타임 양쪽에서 강제. 코드 단위 테스트(`11-testing.md`)에서 fake adapter가 cross-tenant 쿼리를 명시적으로 거부하는지 검증.

### 2.3 시스템 호출 분기

`ctx.is_system_cron`이면 cleanup·reindex 등 admin-only endpoint 통과. 일반 endpoint(query, documents/upload)는 시스템 컨텍스트 호출 거부 (403 `INVALID_SYSTEM_CONTEXT`) — 시스템 cron이 사용자 데이터를 만들거나 질의하는 경로 차단.

## 3. 권한 필터 함수 (1차 저장소)

### 3.1 Pinecone filter

```python
def build_pinecone_filter(ctx: TenantContext, version_filter: str | None) -> dict:
    access_branch: list[dict] = [
        {"access_level": "COMPANY_WIDE"},
    ]
    if ctx.departments:
        access_branch.append({
            "$and": [
                {"access_level": "DEPARTMENT"},
                {"allowed_departments": {"$in": list(ctx.departments)}},
            ]
        })
    if ctx.level:
        access_branch.append({
            "$and": [
                {"access_level": "LEVEL"},
                {"min_level_rank": {"$lte": LEVEL_RANK[ctx.level]}},
            ]
        })
    # EXECUTIVE: 1차 필터에 포함 (allowed_user_ids에 없으면 어차피 매칭 안 됨)
    access_branch.append({
        "$and": [
            {"access_level": "EXECUTIVE"},
            {"allowed_user_ids": {"$in": [str(ctx.user_id)]}},
        ]
    })

    base = [
        {"index_state": "live"},
        {"archived": False},
        {"$or": access_branch},
    ]
    if version_filter:
        base.append({"version": {"$eq": version_filter}})
    else:
        base.append({"is_current": {"$eq": True}})

    return {"$and": base}
```

EXECUTIVE는 1차 필터에 user_id가 들어가지만 캐시 키 `access_sig`에는 안 들어간다 — 같은 access_sig를 가진 다른 EXECUTIVE 사용자는 캐시 hit 시 **다른 user의 청크를 받을 수 있다**. 따라서 응답 직전 §5.4 post-filter가 안전망.

위 트레이드오프의 의도: 캐시 hit ratio를 살리되 (90%+ 사용자가 USER role이라 캐시 공유 가능) EXECUTIVE는 후처리로 안전.

### 3.2 Neo4j Cypher WHERE 절

```cypher
WHERE c.staging = false
  AND d.archived = false
  AND (
    d.access_level = 'COMPANY_WIDE'
    OR (d.access_level = 'DEPARTMENT' AND any(dept IN $departments WHERE dept IN d.allowed_departments))
    OR (d.access_level = 'LEVEL' AND d.min_level_rank <= $level_rank)
    OR (d.access_level = 'EXECUTIVE' AND $user_id IN d.allowed_user_ids)
  )
  AND ($version_filter IS NULL AND v.is_current = true OR v.version = $version_filter)
```

Pinecone filter와 동일한 의미. APOC 의존 없음 (`04 §2.4`).

### 3.3 응답 직전 EXECUTIVE post-filter

```python
def enforce_executive_post_filter(ctx: TenantContext, chunks: list[Chunk]) -> list[Chunk]:
    """캐시 hit 결과에 EXECUTIVE 청크가 섞여 있을 가능성을 차단."""
    return [
        c for c in chunks
        if c.access_level != "EXECUTIVE" or str(ctx.user_id) in c.allowed_user_ids
    ]
```

`02 §5.4`에서 호출. 폐기 후 0개면 `error: NO_ACCESSIBLE_RESULTS`.

### 3.4 비용 영향 (경제성 핵심)

권한 필터를 **1차 저장소에서** 처리하는 결정의 효과:

| 정책 | 비용 영향 |
|---|---|
| Pinecone metadata filter로 1차 적용 | top_k=10 안에 권한 통과 청크가 들어와 **재랭킹·생성 호출 비용 0 추가**. 후처리만 한다면 폐기된 청크에 대해 cross-encoder + Bedrock 재시도 비용 발생 (수배~수십배) |
| EXECUTIVE만 post-filter | EXECUTIVE는 정의상 소수 사용자 → 폐기율 낮음. 일반 사용자는 1차 필터에서 끝나므로 영향 미미 |
| `min_level_rank` 메타 사전 계산 (색인 시 1회) | 검색마다 LEVEL 비교를 단순 `$lte`로 처리 → Pinecone 쿼리 latency 영향 없음 |
| 캐시 키 access_sig 단위 공유 | 100명 USER가 같은 부서·직급이면 캐시 1개 공유 → Bedrock 호출 100건 → 1건 |

후처리 위주로 설계했을 때의 추정 추가 비용 (5,000 쿼리/월 기준): 폐기율 30%, 폐기된 호출의 Bedrock 비용 평균 $0.020 × 1,500건 = **월 $30/테넌트 추가**. 본 정책으로 회피.

## 4. 캐시와 권한 (cross-ref)

`02-query-pipeline.md` §3.2 access_sig 정의의 단일 진실 출처:

```
access_sig = sha256(role + sorted(departments) + (level or "") )
```

user_id는 **EXECUTIVE 외에 user 단위 제한이 없다는 정책 가정**으로 제외 (`02 §3.6`).

만약 향후 user 단위 제한을 다른 access_level에도 도입한다면:
- 옵션 A: 새 access_level 추가하고 같은 EXECUTIVE post-filter 패턴 적용 (권장)
- 옵션 B: access_sig에 user_id 추가 (캐시 hit ratio 급락, 비용 영향 큼)

## 5. 권한 변경 전파

Next.js가 사용자 권한을 변경할 때 본 서버에 영향:

| 변경 | 영향 | Next.js의 본 서버 호출 |
|---|---|---|
| role 변경 | access_sig 변경 → 새 캐시 키로 자연 분리 | (선택) `POST /internal/cache/invalidate` `scope=user` |
| department 추가/제거 | access_sig 변경 → 자연 분리 | 동일 |
| level 변경 | access_sig 변경 → 자연 분리 | 동일 |
| 비활성화 | Next.js가 본 서버 호출을 차단. 본 서버는 별도 처리 불필요 | — |
| document_groups 변경 (manager) | 본 서버 영향 없음 (Next.js가 검증) | — |
| 문서 access_level 변경 | tenant 전체 epoch INCR 필요 | `POST /internal/cache/invalidate` `scope=tenant_epoch` |

Next.js는 위 호출을 **best-effort**로 한다 — 실패해도 본 서버 데이터는 안전 (다음 자연 만료 시 정상). 단, role 강등(예: ADMIN→USER)이 발생한 직후 동일 사용자가 캐시 hit으로 이전 결과를 받지 않도록 invalidate 호출 권장.

## 6. 멀티테넌트 격리 점검 체크리스트 (`11-testing.md`)

자동화 테스트로 검증할 항목:

- [ ] tenant_id 누락된 PineconeAdapter / Neo4jAdapter 호출은 raise (코드 리뷰 + 테스트)
- [ ] tenant A의 컨텍스트로 tenant B의 vector_id를 query 하면 결과 0건 (Index 자체 분리)
- [ ] tenant A의 컨텍스트로 tenant B의 Neo4j Database에 connect 시도하면 driver 자체가 거부 (DB 명 매핑)
- [ ] EXECUTIVE 청크가 캐시에 들어간 후, 다른 user_id로 같은 access_sig로 hit 시 post-filter가 폐기
- [ ] 권한 강등(ADMIN→USER) 사용자에게 이전 ADMIN 결과가 SSE에 포함되지 않음 (access_sig 변경)
- [ ] 시스템 cron 컨텍스트로 일반 query endpoint 호출 시 403
- [ ] 시스템 cron 컨텍스트의 `X-User-Id`가 reserved UUID가 아니면 403

## 7. 변경 시 영향 범위

- 새 Role 추가 → §1.2 + endpoint 권한 매트릭스 + 06 갱신
- 새 AccessLevel 추가 → §1.3 + Pinecone metadata schema + Neo4j Document 스키마 + filter 함수 (3.1·3.2) + 색인 코드(03·04)
- LEVEL_RANK 매핑 변경 → 환경 변수 갱신 + 운영 시점 재색인 영향 없음 (런타임 비교)
- access_sig 정의 변경 → 02 §3.2 + 04 §4.1 + 본 절 동시 갱신, epoch 한 번 증가로 기존 캐시 무효화
- 권한 변경 전파 호출 추가 → 06 §3.2 endpoint + Next.js contract
