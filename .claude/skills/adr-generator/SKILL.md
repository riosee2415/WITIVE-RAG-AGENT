---
name: adr-generator
description: 새 결정 감지 시 docs/operations/adr/NNNN-*.md 템플릿을 자동 작성한다. A(planner)가 작업 단위 분해 중 새 결정(라이브러리 추가, 비용 영향, 패턴 변경 등)을 식별하면 호출해 초안 ADR 생성. PR 통과 게이트.
---

# Skill: adr-generator

## 사용 대상

- A planner — 새 결정 발생 시 강제 호출
- C qa-tester — B 코드에 새 라이브러리·패턴이 들어왔는데 ADR이 없으면 차단
- 사용자 — 수동 ADR 작성 시 템플릿 빠르게

## 트리거 조건 (A가 판단)

다음 중 하나라도 해당하면 ADR 작성 필수:

- 새 라이브러리·외부 의존성 도입 (`@docs/10 §7` 핀 갱신)
- Bedrock 모델·청킹 알고리즘·임베딩 차원 변경
- 비용 모델에 영향 (캐시 정책·메트릭 카디널리티·X-Ray 샘플링 등)
- 의존 방향·격리 정책 변경
- SLO·임계 변경
- ref docs와 의도적으로 다른 결정

## 입력

- 결정 한 줄 제목
- Context (배경) 짧은 문단
- Decision (채택안)
- Alternatives (거부 옵션 + 사유)
- Consequences (긍정·부정·후속 작업)
- 관련 docs cross-link
- 발견된 검수 라운드 또는 commit/PR (있으면)

## 동작

1. `docs/operations/adr/` 안 최대 NNNN 식별 → 다음 4자리 번호 부여
2. 표준 템플릿(`@docs/operations/adr/README.md` ADR 템플릿)을 채워 새 파일 생성
3. `docs/operations/adr/README.md` ADR 인덱스 표에 새 행 추가
4. status: `Proposed`로 시작 — 사용자/팀 승인 후 `Accepted`로 갱신
5. 같은 주제에 기존 ADR이 있으면 supersede 관계 명시

## 출력

- `docs/operations/adr/NNNN-<short-title>.md` 신규 파일
- `docs/operations/adr/README.md` 인덱스 갱신
- 사용자에게 검토·승인 요청 메시지

## 의존성

stdlib만. 외부 호출 없음.

## 참조

- `@docs/operations/adr/README.md` — 표준 템플릿
- 기존 5개 ADR (0001~0005) 패턴
- `@docs/12-coding-conventions.md` §9.3 — PR 템플릿 docs 갱신 의무
