# work_rule (app/infra/)

## 규칙

- [2026-05-08] Protocol 스텁 파라미터 vulture 오탐 허용: `@runtime_checkable Protocol` 메서드 본문이 `...`인 경우 vulture이 파라미터를 "unused variable"로 오탐한다. `pyproject.toml`의 `[tool.vulture]` 섹션에 `ignore_names` 또는 whitelist 파일로 억제해야 함. CI에서 vulture 실행 시 Protocol 스텁 파일은 `--ignore-names` 또는 whitelist를 적용해야 함. (`TASK-4 QA, 2026-05-08`)
- [2026-05-08] Protocol 모듈 내 `__init__` 메서드 docstring: 클래스 docstring이 있어도 `__init__`에도 docstring을 추가해야 interrogate 100% 달성. 현재 `_base.py`의 `TenantMismatchError.__init__`은 docstring 없음 (interrogate 98.2% — 80% 기준 통과). (`TASK-4 QA, 2026-05-08`)
- [2026-05-08] 외부 SDK import 금지 (`aioboto3`, `boto3`, `pinecone`, `neo4j`, `redis`) — Protocol 파일에 실 SDK를 import하면 의존 방향이 무너짐. 구현체 파일은 `infra/impl/` 하위에 분리하여 Protocol 파일과 SDK import를 격리할 것. (`@docs/12-coding-conventions.md §3.2`)
- [2026-05-08] `app/infra/CLAUDE.md`의 `| infra/ | 외부 SDK 어댑터 | aioboto3, pinecone, neo4j, redis |` 표는 구현체 레이어 설명이므로 Protocol-only 파일에는 해당 없음. Protocol 파일과 구현 파일 경로를 분리해 표 혼동 방지 필요. (`TASK-4 QA, 2026-05-08`)

## 변경 이력

| 일자 | 추가/수정 | 사유 |
|---|---|---|
| 2026-05-08 | 초기 규칙 4건 등록 | TASK-4 QA 검수 완료 |
