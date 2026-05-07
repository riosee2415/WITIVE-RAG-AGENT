---
description: 멀티 에이전트(A/B/C/D)로 docs 기반 코드를 만든다. /harness <feature> 형식으로 호출.
argument-hint: <feature 설명>
---

# /harness — 멀티 에이전트 코드 생성

## 사용법

```
/harness POST /internal/query SSE endpoint 1차 구현
/harness 문서 업로드 파이프라인 Stage A
/harness Bedrock prompt cache 적용
```

## 동작 순서

1. **A planner 시동**: 사용자 인자(`$ARGUMENTS`)를 받아 docs 분석 + 작업 단위 분해
2. **B implementer 호출**: 작업 단위마다 명세 전달 (A가 직접 Agent tool 호출)
3. **C qa-tester 호출**: B 결과 검수 → 통과/실패 결정
4. **루프**: C 실패 시 → A가 B 재호출 (최대 3회)
5. **D kpi-tester 호출**: C 통과 시 → 골든셋 측정 → `kpi/<datetime>_<feature>.html` 발행
6. **완료 보고**: A가 사용자에게 변경 파일·검수·KPI 결과 요약

## 본 명령어 본문 (Claude가 실행)

다음 단계를 정확히 실행하세요:

1. `$ARGUMENTS`가 비어 있으면 사용자에게 feature 설명을 요청하고 종료.
2. `Agent` tool을 `subagent_type="planner"`로 호출. prompt에:
   - 사용자 feature 인자: `$ARGUMENTS`
   - 지시: "docs/14개와 operations/ADR을 읽고 작업 단위를 분해하라. 각 단위마다 implementer/qa-tester/kpi-tester를 명시적으로 Agent tool로 호출하라. 모든 단위 완료 후 사용자에게 변경 파일 + 검수 결과 + KPI 보고서 경로를 요약 보고하라."
3. planner의 응답을 받아 사용자에게 그대로 또는 짧게 요약 전달.

## 사전 조건

- `docs/` 폴더 27개 docs 존재
- `.claude/agents/{planner,implementer,qa-tester,kpi-tester}.md` 정의 완료
- `.claude/settings.json` hook 활성
- ragas / radon / interrogate / vulture / bandit 설치 (`uv pip install ragas radon interrogate vulture bandit`)

## 참조

- `@CLAUDE.md` — 4 agent 매트릭스
- `@docs/operations/adr/` — 기존 결정
- `.claude/agents/planner.md` — A 정체성
