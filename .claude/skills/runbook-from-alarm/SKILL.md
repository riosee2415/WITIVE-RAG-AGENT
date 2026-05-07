---
name: runbook-from-alarm
description: 새 CloudWatch 알람 등록 시 docs/operations/runbooks/<alarm>.md 초기 템플릿을 자동 작성한다. 09 §4에 새 알람 추가 시 호출. 운영 누락(현재 9개 미작성) 점진 채움.
---

# Skill: runbook-from-alarm

## 사용 대상

- B implementer — `09 §4` 새 알람 추가 시 동시 호출
- C qa-tester — 새 알람 등록됐는데 runbook이 없으면 차단
- 운영팀 — 새 사고 패턴 발견 시 수동 호출

## 입력

- 알람 이름 (kebab-case, 예: `cost-spike`)
- 알람 트리거 임계 (예: `bedrock_estimated_cost_usd 시간 평균 2배`)
- 심각도 (Critical/High/Medium)
- SLO 영향 (어떤 SLO 위반인지)
- 1차 대응 힌트 (작성자가 알 수 있는 것만)

## 동작

1. `docs/operations/runbooks/<alarm-name>.md` 신규 파일 생성
2. 표준 5단계 형식으로 초기화 (1차 대응·진단·완화·근본 원인·사후)
3. `docs/operations/runbooks/README.md` 인덱스에 새 행 추가
4. "추가 작성 예정" 목록에서 해당 항목 제거
5. `docs/09-observability.md` §4 알람 표와 cross-ref 명시

## 표준 템플릿 (`@docs/operations/runbooks/README.md`)

```
- 심각도: <Critical|High|Medium>
- 알람 트리거: <CloudWatch 알람 이름·임계>
- SLO 영향: <어떤 SLO 위반>
- 평균 복구 시간 목표: N분

## 1. 1차 대응 (5분 안)
- 알람 확인·격리 조치
## 2. 진단
- 명령·쿼리·로그
## 3. 완화 (Mitigation)
- 임시 복구
## 4. 근본 원인 해결
- 영구 수정
## 5. 사후
- 기록·예방·docs 갱신
```

## 출력

- `docs/operations/runbooks/<alarm>.md` 신규
- `docs/operations/runbooks/README.md` 인덱스 갱신

## 의존성

stdlib만.

## 참조

- `@docs/operations/runbooks/README.md` — 표준 형식
- 기존 3개 runbook (`bedrock-outage`, `redis-outage`, `dlq-message-handling`) 패턴
- `@docs/09-observability.md` §4 — 알람 임계 단일 진실 출처
