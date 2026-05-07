---
name: ragas-eval
description: RAG 시스템의 품질을 ragas 라이브러리로 정량 평가한다. 골든셋(`tests/rag_eval/synthetic/queries.jsonl`)을 입력으로 Recall@5·Precision@5·MRR·Faithfulness·Answer Relevance·Latency P95 등 지표를 산출하고 JSON으로 반환. D(kpi-tester) 에이전트가 호출.
---

# Skill: ragas-eval

## 사용 대상

`/harness` 워크플로의 **D 에이전트** 또는 운영자가 RAG 회귀 측정 시.

## 입력

- 골든셋 파일 경로 (기본: `tests/rag_eval/synthetic/queries.jsonl`)
- 평가 대상 endpoint (기본: 로컬 `POST /internal/query`)

## 동작

1. 골든셋 한 줄씩 read (NDJSON)
2. 각 question에 대해 endpoint 호출 (또는 unit-level: orchestrator 직접)
3. 응답의 sources·answer를 수집
4. ragas로 계산:
   - **Recall@5** = (relevant ∩ top5) / relevant
   - **Precision@5** = (relevant ∩ top5) / 5
   - **MRR**
   - **Faithfulness** (LLM-as-judge, judge 모델은 별도 family — Sonnet self-judge 회피)
   - **Answer Relevance**
5. Latency 측정 (첫 토큰까지·완료까지)

## 임계 (`@docs/11-testing.md` §4.2)

```python
THRESHOLDS = {
    "recall_at_5": 0.80,
    "precision_at_5": 0.60,
    "mrr": 0.70,
    "faithfulness": 0.90,
    "answer_relevance": 0.75,
    "first_token_p95_ms": 4000,
    "no_results_rate": 0.10,
}
```

## 출력

JSON:
```json
{
  "thresholds": {...},
  "results": {"recall_at_5": 0.84, ...},
  "violations": [],
  "raw_per_question": [...]
}
```

## 의존성 설치

```bash
uv pip install ragas datasets
```

평가 시 judge 모델 호출 비용 발생 — 단일 골든셋(~50건) 기준 ~$0.50.
