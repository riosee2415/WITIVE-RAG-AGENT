---
description: 바이브코딩 rubric 정량 지표(가독성·복잡도·docstring·dead code·결합도)를 측정하고 tasks를 리스트업해서 upustream@gmail.com으로 이메일 발송.
---

# /rubric — 바이브코딩 정량 평가 + 이메일 발송

## 바이브코딩 rubric (오픈소스 5종 묶음 → `code-rubric` Skill)

| 지표 | 도구 | 의미 | 임계 |
|---|---|---|---|
| Cyclomatic Complexity (CC) | radon | 분기 수 → 가독성 | 평균 ≤ B (≤ 10) |
| Maintainability Index (MI) | radon | 종합 유지보수성 | ≥ 65 |
| Halstead Metrics | radon | 어휘 복잡도 | (참고) |
| Cognitive Complexity | mccabe | 사람 머릿속 부담 | ≤ 15/함수 |
| Docstring coverage | interrogate | 문서화 비율 | ≥ 80% |
| Dead code | vulture | 사용 안 되는 코드 | 발견 0 |
| Security | bandit | 보안 안티패턴 | High 0 |

## 본 명령어 본문 (Claude가 실행)

1. `Skill("code-rubric")` 호출 — 위 7 지표 측정
2. 임계 비교 + 분류:
   - **변경 필요**: 복잡도·MI 임계 위반 함수 → 리팩토링 후보
   - **수정 필요**: docstring 누락 함수
   - **추가 필요**: 새 모듈에 docstring·예시 코드
   - **삭제 필요**: dead code (vulture 결과)
3. HTML 보고서 생성 (`kpi/rubric_<datetime>.html`):
   - 각 지표 점수 + 임계 비교
   - 함수별 worst-offender top 10 (CC·MI·docstring 누락)
   - 권장 task 리스트 (변경/수정/추가/삭제)
4. `Skill("send-email")` 호출 — HTML 첨부, 수신 upustream@gmail.com

## 사전 조건

- Gmail SMTP 환경 변수 설정
- `uv pip install radon interrogate vulture bandit mccabe`

## 참조

- `@docs/11-testing.md` §7 — 빌드 시간 검증과 같은 도구
- `.claude/skills/code-rubric/SKILL.md` — 측정 명령어 모음
