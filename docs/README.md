# WITIVE Knowledge AI — RAG/AI Service docs

이 폴더는 본 프로젝트(LLM·RAG·AI 전담 FastAPI 서버) 작업의 단일 진입점이다.
하네스(자동화 에이전트)와 신규 개발자가 공통으로 여기서 시작한다.

## 한 줄 소개

검증된 사용자 컨텍스트와 사내 문서를 입력으로 받아 RAG 기반 답변과 색인을 만드는 FastAPI 마이크로서비스. 인증·사용자 관리·인프라는 별도 Next.js 백엔드와 DevOps 책임이며 본 서버는 다루지 않는다.

본 서버의 위치, 책임 범위, 외부 contract는 `00-scope.md`에서 시작하라.

## 작업별 진입 docs

| 작업 | 1순위 |
|---|---|
| 새 기능을 본 서버 책임으로 받아도 되는지 판단 | `00-scope.md` |
| 코드를 어디에 둘지 / 모듈 의존 방향 | `01-architecture.md`, `12-coding-conventions.md` |
| Stage 1 / Stage 2 동작 변경 | `02-query-pipeline.md`, `05-llm-bedrock.md` |
| 문서 파이프라인(파싱·청킹·임베딩) 변경 | `03-document-pipeline.md`, `04-data-stores.md` |
| Pinecone/Neo4j 스키마 변경 | `04-data-stores.md` |
| Bedrock 모델 교체·프롬프트 캐싱 | `05-llm-bedrock.md` |
| HTTP/SSE 인터페이스 변경 | `06-api.md` |
| 권한·테넌트·버전 필터 변경 | `07-multitenancy-and-access.md` |
| 외부 의존성 fallback·타임아웃 정책 | `08-resilience.md` |
| 로그·메트릭·트레이스 필드 변경 | `09-observability.md` |
| 환경 변수·시크릿 추가 | `10-config-and-secrets.md` |
| 테스트·RAG 평가 골든셋 | `11-testing.md` |
| 코딩 스타일·async 규칙·에러 모델 | `12-coding-conventions.md` |
| 도메인 용어 의미 확인 | `13-glossary.md` |

## docs 전체 인덱스

| 파일 | 한 줄 목적 |
|---|---|
| `00-scope.md` | 본 서버의 위치·책임 범위·외부 contract |
| `01-architecture.md` | 요청 흐름·외부 의존성·코드 레이어 |
| `02-query-pipeline.md` | Stage 1 + Stage 2 처리 상세 |
| `03-document-pipeline.md` | 파싱·청킹·임베딩·색인 |
| `04-data-stores.md` | Pinecone·Neo4j·S3·Redis 스키마 |
| `05-llm-bedrock.md` | Bedrock 모델·프롬프트 캐싱·스트리밍 |
| `06-api.md` | HTTP/SSE 엔드포인트 명세 |
| `07-multitenancy-and-access.md` | 테넌트 격리, RBAC × 문서 접근 레벨 |
| `08-resilience.md` | 서킷 브레이커·재시도·fallback |
| `09-observability.md` | 로깅·메트릭·추적 |
| `10-config-and-secrets.md` | 환경 변수·시크릿 |
| `11-testing.md` | 테스트·RAG 평가 |
| `12-coding-conventions.md` | 코딩 규약 |
| `13-glossary.md` | 도메인 용어집 |

## 운영 docs (별도 폴더)

본 14 docs와 분리된 운영 진입 준비 docs는 `operations/` 폴더에 있다 — ADR(결정 근거), Runbook(사고 대응), SOP(표준 절차).

| 상황 | 진입점 |
|---|---|
| "왜 이 라이브러리/패턴을 골랐지?" | `operations/adr/README.md` |
| "Critical 알람이 떴어, 뭐 하지?" | `operations/runbooks/README.md` |
| "시크릿 회전 / 신규 테넌트 추가 시기" | `operations/sop/README.md` |

본 14 docs가 "무엇·어떻게"를 다루고, operations는 "왜·사고 시 무엇을·정기 작업 절차"를 다룬다.

## ref와의 관계

`ref/`에 전체 시스템 기획안(PRD/ARC/API/INFRA/ROADMAP/SECURITY)이 있다. 본 docs는 그중 **LLM·RAG·AI 부분만 본 서버 관점에서 압축·재구성**한 것이며, 출처는 `ref/<파일>.md §<절>` 형식으로 인용한다.

ref와 docs가 충돌하면 **docs 우선**(본 서버에 한정해 더 구체적인 결정). ref가 의도적으로 갱신된 경우라면 docs를 ref에 맞춰 갱신한다.

## 메타

- 초안: 2026-05-07
- 기준 ref: PRD v0.2 / ARC v0.2 / SECURITY v0.2 / ROADMAP v0.2 / API v0.2 / INFRA v0.1
- 본 서버 스택: Python 3.12+ · FastAPI · uv · aioboto3 · Pinecone SDK · Neo4j async driver
