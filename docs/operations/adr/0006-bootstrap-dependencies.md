# ADR-0006: 1차 부트스트랩 의존성 범위 한정

- 상태: Accepted
- 일자: 2026-05-08
- 결정자: 본 서버 설계팀
- 관련 docs: `00-scope.md`, `01-architecture.md`, `10-config-and-secrets.md`

## Context (배경)

프로젝트 1차 부트스트랩 시점에 AWS 계정이 미발급 상태다. AWS Bedrock, S3, SQS, Textract 등 AWS 의존 서비스와, Pinecone(벡터 DB), Neo4j(그래프 DB), Redis(캐시) 모두 실제 엔드포인트에 접근할 수 없다. 이 상태에서 해당 SDK를 `pyproject.toml`에 추가하면 설치 환경만 복잡해지고 실행 가능한 테스트를 작성할 수 없다.

동시에 레이어 의존 방향(`api → pipeline → infra → domain`), import-linter 강제, 구조적 로깅(structlog), 타입 안전성(mypy strict) 등 아키텍처 골격은 지금 확립해야 한다.

## Decision (결정)

1차 부트스트랩에서는 FastAPI·uvicorn·sse-starlette·structlog·pydantic·pydantic-settings·python-json-logger만 runtime 의존성으로 도입한다. AWS(`aioboto3`), Pinecone(`pinecone`), Neo4j(`neo4j`), Redis(`redis`) 라이브러리는 해당 계정·인프라가 발급되는 시점에 별도 ADR 없이 `pyproject.toml`에 추가한다. dev 의존성에는 pytest·ruff·mypy·import-linter를 포함한다.

## Alternatives (대안)

- **전체 SDK 선행 설치**: 계정 없이 설치만 해두면 가상 환경 무게가 늘고, 실제 호출 경로가 없어 테스트 커버리지가 거짓 통과할 위험이 있다. 거부.
- **mock 라이브러리로 SDK shim**: `tests/_factories.py` 규칙에 따라 fake 객체를 쓰는 것은 허용되지만, SDK 자체를 설치 목록에 올리는 것은 동일한 이유로 거부.

## Consequences (영향)

- 긍정적: 설치 즉시 `pytest` 실행 가능. import-linter·ruff·mypy가 CI에서 즉시 동작. 환경 재현이 빠름.
- 부정적: 인프라 어댑터(`app/infra/`) 구현 시 SDK가 없어 타입 힌트 불완전 구간이 발생한다. 해당 파일은 `# type: ignore` 최소 사용 또는 Protocol 기반 stub으로 대체한다.
- 후속 작업: AWS 계정 발급 후 `aioboto3`, `pinecone`, `neo4j`, `redis` 추가 및 `app/infra/` 어댑터 구현.

## Cost Impact

$0/월. 이번 ADR에서 외부 API 호출은 0건이다.

## References

- `docs/01-architecture.md` §2 외부 의존성 표
- `docs/10-config-and-secrets.md`
- Memory: AWS 계정 미발급 (2026-05-08)
