# work_rule (app/pipeline/)

## 규칙

- [2026-05-08] execute 메서드 내 Step 주석 번호는 docs/03 §2 단계 번호와 1:1 일치 필수: Step 7(도메인 검증)과 Step 8(ID 생성)을 같은 블록에 묶고 주석에서 Step 8을 생략하면 명세 추적성이 깨짐. ID 생성은 별도 `# Step 8 — ID generation` 주석으로 분리할 것. (TASK-6 수동 리뷰에서 발견)
- [2026-05-08] `version_id` 할당 후 미사용 금지: `F841 Local variable assigned to but never used`. Step 8에서 uuid7()로 생성된 `version_id`가 사용되지 않음. 필요 없으면 제거, 추후 Phase 2에서 필요하면 명시적 주석으로 보류 의도 표시. (`ruff check` TASK-6 검수에서 발견)

## 변경 이력

| 일자 | 추가/수정 | 사유 |
|---|---|---|
| 2026-05-07 | 초기 생성 | 하네스 셋업 |
| 2026-05-08 | execute step 번호 일치 규칙 추가, version_id 미사용 금지 추가 | TASK-6 ruff/수동 검수 |
