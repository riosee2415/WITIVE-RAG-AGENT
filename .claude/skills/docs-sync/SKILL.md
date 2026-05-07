---
name: docs-sync
description: docs/27개와 src/app/ 코드의 cross-reference 정합성을 검증한다. 환경 변수·메트릭·이벤트 코드·에러 코드·도메인 모델 등이 docs와 코드 양쪽에 일치하는지 확인. A(planner)와 C(qa-tester)가 호출.
---

# Skill: docs-sync

## 사용 대상

- A planner: 작업 종료 시 docs cross-ref 최종 검증
- C qa-tester: B의 변경이 docs와 일치하는지 검증
- `/review-check`: 보고서의 docs 일치성 항목

## 검증 카테고리

### 1. 환경 변수

`docs/10-config-and-secrets.md` §2 카탈로그 ↔ `src/app/platform/config.py`의 `Settings` 필드.
- 누락: docs에 있는데 코드에 없음 → 미구현 또는 docs 청소 필요
- 추가: 코드에 있는데 docs에 없음 → docs 갱신 필요

### 2. 에러 코드

`docs/06-api.md` §1.4 + `docs/12-coding-conventions.md` §5.1 ↔ `src/app/domain/errors.py` `ErrorCode` StrEnum.

### 3. 메트릭

`docs/09-observability.md` §2.3 카탈로그 ↔ `src/app/platform/metrics.py` 발행 호출.

### 4. 로그 이벤트

`docs/09-observability.md` §1.6 카탈로그 ↔ `src/app/platform/logging.py` `LogEvent` StrEnum.

### 5. 도메인 모델

`docs/04-data-stores.md` §1.3 (Pinecone meta), §2.2 (Neo4j 노드) ↔ `src/app/domain/`·`src/app/infra/` 색인 코드.

### 6. SSE 이벤트 형식

`docs/06-api.md` §3.1 + `docs/02-query-pipeline.md` §6.3 ↔ `src/app/api/query.py` 발행 코드.

## 동작 (의사 코드)

```
1. docs에서 카탈로그 추출 (정규식)
2. 코드에서 정의 추출 (AST 또는 정규식)
3. set diff:
   - missing_in_code = docs - code
   - missing_in_docs = code - docs
4. 결과 JSON 반환
```

## 출력

```json
{
  "category_violations": {
    "env_vars": {"missing_in_code": ["..."], "missing_in_docs": ["..."]},
    "error_codes": {...},
    "metrics": {...},
    "log_events": {...}
  },
  "summary": "0 mismatch (PASS)" | "N mismatches (FAIL)"
}
```

## 비고

이 Skill은 docs와 코드 양쪽에 변경이 있을 때마다 호출. C가 PR 통과 게이트로 사용. mismatch 발견 시 PR 통과 X.
