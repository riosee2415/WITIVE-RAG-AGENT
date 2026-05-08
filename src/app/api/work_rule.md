# work_rule (app/api/)

## 규칙

- [2026-05-08] `# noqa: B008` 금지: 현재 ruff 설정에서 B008 규칙이 비활성화되어 있으므로 `# noqa: B008` 주석을 달면 `RUF100 Unused noqa directive` 오류 발생. FastAPI Header/Form/File 기본값 패턴에 noqa 불필요. (`ruff check` TASK-6 검수에서 발견)
- [2026-05-08] `# type: ignore[assignment]` 금지 (mypy 6 이상 + FastAPI Form 기본값): mypy --strict가 실제로 타입 오류를 감지하지 않을 때 `# type: ignore` 달면 `unused-ignore` 오류 발생. Form(default_factory=list) 패턴에는 type: ignore 불필요. (`mypy --strict` TASK-6 검수에서 발견)

## 변경 이력

| 일자 | 추가/수정 | 사유 |
|---|---|---|
| 2026-05-07 | 초기 생성 | 하네스 셋업 |
| 2026-05-08 | noqa B008 금지, type ignore 금지 규칙 추가 | TASK-6 ruff/mypy 검수 |
