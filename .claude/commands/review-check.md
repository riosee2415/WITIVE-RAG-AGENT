---
description: 현 코드의 안정성 KPI(테스트 커버리지·정적 분석·docs 일치성·CVE)를 측정하고 변경/수정/추가/삭제 리스트업 보고서를 upustream@gmail.com으로 이메일 발송.
---

# /review-check — 안정성 보고서 + 이메일 발송

## 동작

1. 현 `app/` 코드를 정적·동적 분석
2. KPI 정량 지표 산출
3. 변경/수정/추가/삭제 리스트업 보고서 생성
4. upustream@gmail.com 이메일 발송

## 측정 항목

| 카테고리 | 도구 | 임계 |
|---|---|---|
| 테스트 커버리지 | pytest --cov | ≥ 85% |
| 의존 방향 | import-linter | violation 0 |
| 정적 분석 | mypy --strict, ruff | error 0 |
| 보안 정적 | bandit | High 0 |
| CVE | pip-audit | Critical 0 |
| docs 일치성 | `docs-sync` Skill | mismatch 0 |
| RAG 골든셋 (가능 시) | ragas | `@docs/11-testing.md` §4.2 |

## 본 명령어 본문 (Claude가 실행)

1. 다음 명령들을 순차 실행 (실패해도 다음 진행, 결과 수집):
   ```bash
   pytest tests/ -v --cov=src/app --cov-report=json:coverage.json
   ruff check src/app
   mypy --strict src/app
   bandit -r src/app -f json -o bandit.json
   pip-audit --format json --output pip-audit.json
   lint-imports --config pyproject.toml
   ```
2. `Skill("docs-sync")` 호출 — docs 일치성 검증
3. 결과를 변경/수정/추가/삭제 분류 (직전 commit과 비교):
   - **변경 필요**: 임계 위반 코드 (ruff/mypy/bandit)
   - **수정 필요**: docs와 불일치 (docs-sync 결과)
   - **추가 필요**: 누락된 테스트 (커버리지 < 85% 영역)
   - **삭제 필요**: dead code (vulture), 미사용 import (ruff F401)
4. HTML 보고서 생성 (`kpi/review-check_<datetime>.html`)
5. `Skill("send-email")` 호출 (Gmail SMTP) — 첨부로 HTML 발송. 수신: upustream@gmail.com

## 사전 조건

- Gmail SMTP 환경 변수 설정 (`GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`)
- 측정 도구 설치

## 참조

- `@docs/11-testing.md` §7 — 빌드 시간 검증
- `@docs/09-observability.md` §4 — 알람 임계
