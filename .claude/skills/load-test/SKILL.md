---
name: load-test
description: k6 부하 테스트 시나리오를 자동 생성·실행·결과 파싱한다. /review-check이 SLO 검증 시 호출. P95·오류율·backpressure 동작·메모리 임계를 측정해 KPI HTML 보고서 발행.
---

# Skill: load-test

## 사용 대상

- `/review-check` — 안정성 KPI 일부
- 사용자 — 새 기능 후 부하 회귀 검증
- D kpi-tester — 큰 변경 후 자동 호출

## 시나리오 (`@docs/11-testing.md` §6.1)

| 시나리오 | 부하 | 검증 |
|---|---|---|
| `01_query_steady` | 100 RPS × 30분 | P95·오류율·캐시 hit ratio |
| `02_query_burst` | 0 → 500 RPS spike | 429 발행 비율 (backpressure 동작) |
| `03_concurrent_sse` | 200 동시 SSE | `MAX_CONCURRENT_SSE_CONNECTIONS` 동작 |
| `04_document_upload` | 100MB × 10건 동시 | SQS·Worker throughput |
| `05_mixed_workload` | query 70% + upload 30% × 1시간 | 정상 운영 모사 |

## 동작

1. 골든셋(`tests/rag_eval/synthetic/queries.jsonl`)에서 sample 추출
2. k6 스크립트 자동 생성: `tests/load/<scenario>.js`
3. k6 실행: `k6 run --out json=output.json <script>`
4. 결과 파싱:
   - `http_req_duration` p(95) / p(99)
   - `http_req_failed`
   - 429 응답 비율
   - SSE first-token latency (k6 트레이스)
5. `@docs/11-testing.md` §6.2 임계 비교
6. KPI HTML 보고서

## 임계 (`@docs/11-testing.md` §6.2)

- 첫 토큰 P95 ≤ 4.0s (cold) / ≤ 0.1s (cache hit)
- 전체 답변 P95 ≤ 11s
- 오류율 (비-429) < 1%
- 429 발행 비율 (burst 시) > 0% (backpressure 동작 확인)
- 메모리 < 70% (정상) / < 85% (burst)

## 의존성

```bash
# Windows
choco install k6
# 또는 https://k6.io/docs/get-started/installation/

# Python wrapper (subprocess + json 파싱)
# — 추가 라이브러리 불요
```

## 출력

`kpi/load_<scenario>_<datetime>.html` + raw JSON

## 비용 주의

부하 테스트는 dev 환경에서 실행 시 Bedrock·Pinecone 호출 비용 발생:
- 5,000 query × 1회 시나리오 ≈ $100~$120 비용
- staging에서만 실행 권장 (`docs/11-testing.md` §6.3)
- prod 부하 테스트는 절대 X

## 참조

- `@docs/11-testing.md` §6
- `@docs/08-resilience.md` §6 — backpressure
- `@docs/01-architecture.md` §4 — SLO
