# ADR-0004: EXECUTIVE만 응답 직전 post-filter, access_sig는 user_id 미포함

- 상태: Accepted
- 일자: 2026-05-07
- 결정자: 본 서버 설계팀
- 관련 docs: `02-query-pipeline.md` §3.2·§5.4, `07-multitenancy-and-access.md` §1.3·§3

## Context

문서 접근 레벨 4종(COMPANY_WIDE / DEPARTMENT / LEVEL / EXECUTIVE) 중 EXECUTIVE는 명시 사용자(user_id 화이트리스트)에게만 노출되어야 한다.

1차 시안은 캐시 키 `access_sig`에 `user_id`를 포함시켜 사용자 단위 캐시 분리였다. 검수 1차 라운드에서 비용·hit ratio 문제가 발견됐다:
- EXECUTIVE 사용자가 다수면 같은 질문이라도 user 단위로 캐시 쪼개짐 → hit ratio 사실상 0
- 비-EXECUTIVE 사용자(전체 트래픽의 90%+)도 똑같이 user 단위 분리 → 캐시 hit ratio 전체 급락
- 캐시 미스 폭주 → Bedrock 호출 비율 ↑ → 비용 ↑
- ARC §8 "권한 단위 캐시" 의도와 어긋남

## Decision

`access_sig = sha256(role + sorted(departments) + (level or ""))` — **user_id 미포함**.

EXECUTIVE 청크는 **응답 직전 post-filter로 폐기**:
```python
for chunk in top_5:
    if chunk.access_level == "EXECUTIVE":
        if str(ctx.user_id) not in chunk.allowed_user_ids:
            drop(chunk)
```

폐기 후 0개면 `error: NO_ACCESSIBLE_RESULTS`.

EXECUTIVE는 1차 저장소 필터에도 user_id 조건 포함되지만(같은 access_sig 내에서 user_id 다른 사용자가 캐시 hit하면) post-filter가 안전망 역할.

## Alternatives

| 대안 | 거부 사유 |
|---|---|
| `access_sig`에 user_id 포함 (1차 시안) | EXECUTIVE 사용자 hit ratio 0, 비-EXECUTIVE 전체 hit ratio 급락. 5,000 쿼리/월 기준 추가 비용 ~$30/테넌트/월 |
| EXECUTIVE 청크를 Pinecone에 따로 저장 (별도 namespace) | 색인 복잡도 증가. EXECUTIVE 외 access_level과 결합 검색 어려움 |
| EXECUTIVE 캐시 자체 비활성화 | EXECUTIVE 사용자만 캐시 미사용 — 그러나 같은 질문을 다른 access_level 사용자가 요청 시 캐시 hit이 EXECUTIVE 청크를 포함할 수 있음 (post-filter 없이는 누수) |

## Consequences

긍정적:
- 캐시 hit ratio 보존 (90%+ 트래픽 권한 클래스 단위 공유)
- Bedrock 비용 폭증 회피 (~$30/테넌트/월 절감)
- 1차 저장소 필터로 대부분의 권한 처리가 처리됨 (저장소 native 비용)

부정적:
- 응답 직전 post-filter 단계 추가 — 무시 가능 latency
- EXECUTIVE 청크가 캐시 hit 결과에 일시 포함될 수 있음 → post-filter가 반드시 실행되어야 보안 유지
- post-filter 폐기 후 0개인 경우 `NO_ACCESSIBLE_RESULTS` — 사용자 경험상 모호 (관련 문서가 있는지 없는지 모름)

후속 작업:
- `07 §6` 멀티테넌트 격리 점검 체크리스트에 EXECUTIVE post-filter 자동화 테스트 명시
- `02 §5.4` post-filter 함수 명세
- 만약 향후 EXECUTIVE 외 user 단위 제한이 도입되면 본 ADR을 supersede하는 새 ADR 작성

## References

- `docs/02-query-pipeline.md` §3.2 (access_sig 정의), §5.4 (post-filter)
- `docs/07-multitenancy-and-access.md` §1.3·§3 (정책 매트릭스 + 코드)
- 검수 1차 라운드 H-1 (캐시 키 user_id 포함 문제 발견)
- ARC §8 (권한 단위 캐시 의도)
