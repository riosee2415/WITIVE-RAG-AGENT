---
name: code-rubric
description: 바이브코딩 정량 지표(복잡도·docstring·dead code·보안·결합도)를 오픈소스 5종(radon·interrogate·vulture·mccabe·bandit)으로 측정해 단일 JSON으로 반환한다. /rubric 명령어와 D(kpi-tester) 에이전트가 호출.
---

# Skill: code-rubric

## 사용 대상

- `/rubric` 명령어 — 바이브코딩 정량 평가 + 이메일 발송
- `/review-check` 명령어 — 안정성 보고의 일부
- D 에이전트 — KPI HTML 보고서

## 측정 도구

| 지표 | 도구 | 명령 |
|---|---|---|
| Cyclomatic Complexity (CC) | radon | `radon cc src/app -s -a -j` |
| Maintainability Index (MI) | radon | `radon mi src/app -s -j` |
| Halstead | radon | `radon hal src/app -j` |
| 함수당 cognitive | mccabe | `python -m mccabe --min 10 <file>` |
| Docstring coverage | interrogate | `interrogate src/app --output-format json` |
| Dead code | vulture | `vulture src/app --min-confidence 80 --json` |
| Security | bandit | `bandit -r src/app -f json` |

## 임계

| 지표 | 임계 |
|---|---|
| CC 평균 | ≤ B (≤ 10) |
| MI | ≥ 65 |
| Cognitive (per function) | ≤ 15 |
| Docstring coverage | ≥ 80% |
| Dead code count | 0 |
| Bandit High | 0 |

## 동작

각 도구를 순차 실행 (각 5초 안), JSON 출력 파싱, 단일 결과로 통합.

## 출력 (예시 구조)

```json
{
  "complexity": {
    "average_cc": "B",
    "average_mi": 72.4,
    "worst_files": [{"file": "...", "cc": "C", "complexity": 18}, ...]
  },
  "docstring_coverage": 0.82,
  "dead_code": [{"file": "...", "line": 42, "name": "..."}],
  "bandit_high": 0,
  "violations": [],
  "summary": "PASS | FAIL"
}
```

## 의존성 설치

```bash
uv pip install radon interrogate vulture bandit mccabe
```

## 참조

- `@docs/11-testing.md` §7
- `@docs/operations/sop/` (코드 품질 정기 점검)
