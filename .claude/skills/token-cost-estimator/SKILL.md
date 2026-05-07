---
name: token-cost-estimator
description: 코드 변경 전후의 Bedrock 토큰 비용 영향을 추정한다. A(planner)가 작업 단위 분해 시 호출. 시스템 프롬프트 길이·임베딩 호출 수·Stage 1·2 호출 패턴을 추적. /review-check이 월간 비용 회귀 보고에 사용.
---

# Skill: token-cost-estimator

## 사용 대상

- A planner — 작업 단위 분해 시 비용 영향 사전 가시화
- D kpi-tester — KPI 보고서에 비용 회귀 항목 포함
- `/review-check` — 월간 비용 회귀 보고

## 입력

- 변경 파일 경로 목록
- 시스템 프롬프트 변경 여부 (`@docs/05 §2.2`)
- 새 호출 경로 (예: 임베딩 호출 추가, 캐싱 정책 변경)

## 동작

1. **코드 정적 분석**:
   - Bedrock `invoke_model`·`converse_stream`·`invoke_model` 호출 위치 추출 (AST 또는 정규식)
   - 시스템 프롬프트 토큰 길이 추정 (tiktoken 또는 char/4)
   - 임베딩 호출 수 추정 (호출 경로 분석)
2. **단가 read** — `@docs/10 §2.3` 비용 단가 환경 변수
3. **1,000 query 기준 추정 비용**:
   - Stage 1 입력·출력
   - Stage 2 입력 (cache miss vs hit 분리)
   - Stage 2 출력
   - 임베딩
4. **Baseline 비교**:
   - `kpi/cost_baseline.json` (직전 측정)과 비교
   - 변화율 ±10% 이상이면 warn
5. 결과 JSON + 짧은 리포트

## 임계

| 지표 | 임계 |
|---|---|
| 쿼리당 평균 비용 | baseline × 1.10 → High |
| 시스템 프롬프트 토큰 | < 1,024 → cache 미형성 위험 (warn, `@docs/05 §4.2`) |
| 임베딩 호출 수 | 단일 query당 > 1 → 글로벌 RPS 한도 영향 (warn) |

## 출력 (예시)

```json
{
  "scenario": "1k cold queries",
  "estimated_cost_usd": {
    "stage1_input": 0.20,
    "stage1_output": 0.30,
    "stage2_input_uncached": 8.50,
    "stage2_input_cache_read": 4.00,
    "stage2_output": 5.00,
    "embedding": 0.02,
    "total": 18.02
  },
  "vs_baseline_pct": "+5.2%",
  "warnings": []
}
```

## 의존성

```bash
uv pip install tiktoken
```

(엄밀한 토큰 카운트가 필요. char/4 추정은 한국어에서 부정확)

## 참조

- `@docs/05-llm-bedrock.md` §7 — 비용 가드레일
- `@docs/09-observability.md` §2.4 — `bedrock_estimated_cost_usd` 메트릭
- `@docs/operations/adr/0004-executive-post-filter.md` (캐시 비용 결정 예시)
