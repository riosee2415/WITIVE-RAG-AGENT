# ADR-0007: request_id 생성에 uuid7 채택

- 상태: Accepted
- 일자: 2026-05-08
- 결정자: 본 서버 설계팀
- 관련 docs: `06-api.md §1.3`, `13-glossary.md`

## Context (배경)

`@docs/06-api.md §1.3`은 `request_id`를 uuid7로 명시한다. uuid7은 시간 정렬 가능한 K-Sortable UUID로, CloudWatch Logs Insights에서 시간 범위 쿼리 시 정렬 효율이 높다. 부트스트랩 초기 구현(`_middleware.py`)에서는 표준 라이브러리 `uuid.uuid4()`를 사용해 docs와 불일치 상태였다.

## Decision (결정)

PyPI 패키지 `uuid7==0.1.0`을 runtime 의존성으로 추가한다. 해당 패키지는 `uuid_extensions` 모듈을 설치하며, `from uuid_extensions import uuid7`로 임포트한다. `_middleware.py`의 `uuid.uuid4()` 호출을 `uuid7()`로 교체해 docs와 정합성을 맞춘다.

채택 패키지: **uuid7 (PyPI) → `uuid_extensions` 모듈** (`uuid7>=0.1.0`).

## Alternatives (대안)

- **uuid4 유지**: 표준 라이브러리로 의존성 없이 동작하지만, 시간 정렬이 불가해 CloudWatch Logs Insights에서 시간 범위 기반 `request_id` 필터링이 비효율적이다. `@docs/06-api.md §1.3` 명세와 직접 충돌. 거부.
- **uuid-utils (PyPI)**: Rust 기반 고성능 구현이지만, `uuid7` 패키지가 순수 Python으로 충분한 성능을 제공하며 추가 빌드 의존성 없이 설치 가능해 선택하지 않음. 향후 성능 병목 시 재검토 가능.

## Consequences (영향)

- 긍정적: `request_id`가 시간 정렬되어 CloudWatch Logs Insights 쿼리 효율 향상. docs 단일 진실 출처와 정합.
- 부정적: runtime 의존성 1개 추가 (`uuid7==0.1.0`, 순수 Python, 보안 리스크 최소).
- 후속 작업: 없음. 기존 테스트는 `len(generated) > 0`만 검증하므로 uuid7 36자 출력과 호환.

## Cost Impact

$0/월. uuid7 생성은 로컬 연산이며 외부 API 호출 없음.

## References

- `docs/06-api.md §1.3` — request_id 생성 명세 (uuid7)
- `docs/13-glossary.md` — uuid7 용어 정의
- PyPI: https://pypi.org/project/uuid7/
