# Operations docs

본 폴더는 **운영팀과 코드 작성자가 결정 근거·사고 대응·표준 절차를 추적**하는 docs.
14개 개발 docs (`docs/00~13.md`)와 분리되며, 운영 진입(prod 배포) 직전까지 점진 보강.

## 폴더 구조

| 폴더 | 용도 |
|---|---|
| `adr/` | Architecture Decision Records — 본 시스템에서 내린 결정의 근거·대안·영향 영구 기록 |
| `runbooks/` | 운영 사고 대응 절차. CloudWatch Critical 알람과 1:1 매핑 |
| `sop/` | Standard Operating Procedure. 시크릿 회전, 테넌트 온보딩, cleanup 등 정기/수동 작업 절차 |

## 14 docs와의 관계

| 14 docs (`../*.md`) | operations docs |
|---|---|
| **무엇을 / 어떻게 만드는가** (코드 작성 진입점) | **왜 이렇게 결정했는가 (ADR) / 사고 시 무엇을 하는가 (Runbook·SOP)** |
| 단일 진실 출처 — 코드 변경 시 동기 갱신 | ADR은 변경 불가(supersede 패턴), Runbook·SOP는 운영 학습으로 진화 |
| 하네스(자동화 에이전트) 우선 | 사람(운영팀·온콜·신규 합류자) 우선 |

## 사용 가이드

| 상황 | 첫 진입점 |
|---|---|
| "왜 X 라이브러리/패턴을 골랐지?" | `adr/README.md` 검색 |
| "Redis 알람이 떴어, 뭐하지?" | `runbooks/redis-outage.md` |
| "테넌트 추가해줘" / "시크릿 회전 시기" | `sop/README.md` |
| "이 결정을 바꾸고 싶음" | 기존 ADR을 supersede하는 새 ADR 작성 |

## 인덱스

- [`adr/README.md`](./adr/README.md) — ADR 인덱스 + template
- [`runbooks/README.md`](./runbooks/README.md) — Runbook 인덱스
- [`sop/README.md`](./sop/README.md) — SOP 인덱스

## 메타

- 1차 작성: 2026-05-07
- 본 docs는 14 docs 작성 완료 후, 코드 작성·운영 진입 사이의 **운영 준비 단계**에서 보강
- 누락된 ADR/Runbook/SOP은 코드 작성·운영 학습 진행 중 점진 추가
