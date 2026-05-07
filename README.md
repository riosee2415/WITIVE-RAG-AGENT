<div align="center">

# WITIVE Knowledge AI

### 사내 규정·매뉴얼을 위한 LLM·RAG·AI 마이크로서비스

한국어 특화 2-Stage Query Chain · Hybrid RAG · 멀티테넌트 SaaS

[![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![AWS](https://img.shields.io/badge/AWS-Bedrock_·_S3_·_SQS-FF9900?logo=amazon-aws&logoColor=white)](https://aws.amazon.com/bedrock/)
[![Pinecone](https://img.shields.io/badge/Pinecone-Serverless-3742FA?logo=pinecone&logoColor=white)](https://www.pinecone.io/)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.18+-008CC1?logo=neo4j&logoColor=white)](https://neo4j.com/)
[![Claude](https://img.shields.io/badge/Anthropic-Claude_4-D97757?logo=anthropic&logoColor=white)](https://www.anthropic.com/)

[**Docs**](docs/README.md) · [**ADR**](docs/operations/adr/README.md) · [**Runbooks**](docs/operations/runbooks/README.md) · [**Setup**](.claude/SETUP.md)

</div>

---

## 무엇을 하는 서비스인가

기업의 신규 입사자·부서 이동자가 사내 규정·복무 지침·업무 매뉴얼을 자연어로 질문하면, 출처와 함께 답변을 스트리밍으로 돌려주는 백엔드.

- **Stage 1** Claude Haiku 4.5로 질문 재작성
- **Stage 2** Pinecone(시맨틱) + Neo4j(그래프) 병렬 검색 → Cross-encoder 재랭킹 → Claude Sonnet 4.6 답변 생성
- **SSE 스트리밍** sse-starlette + 15s keep-alive ping
- **멀티테넌트** Pinecone Index·Neo4j Database 물리 격리, S3 prefix + KMS CMK 논리 격리

본 서버는 **API만 제공** — 프론트엔드와 인증·사용자 관리는 별도 NestJS 백엔드 책임 (`docs/00-scope.md`).

## 시스템 위치

```
[Client (React)]
      │
      ▼
[NestJS Backend]   ← Cognito 인증, 사용자/테넌트/통계/과금/웹훅
      │  internal HTTP (X-* 헤더로 검증된 사용자 컨텍스트 전달)
      │  SSE는 NestJS가 클라이언트로 프록시
      ▼
[FastAPI RAG/AI Service]  ← 본 프로젝트
      │
      ├─ AWS Bedrock     (Claude Haiku/Sonnet · Titan Embeddings v2)
      ├─ Pinecone        (벡터 검색)
      ├─ Neo4j           (그래프 관계 검색 — staging·prod)
      ├─ AWS S3          (원본 문서 + chunks.jsonl)
      ├─ ElastiCache     (Redis 캐시)
      └─ AWS SQS         (문서 파이프라인 큐)
```

## 핵심 특징

| 영역 | 결정 |
|---|---|
| **2-Stage Query Chain** | Haiku로 재작성 → Sonnet으로 답변. 비용 ~19% 절감 |
| **Hybrid RAG** | Pinecone 시맨틱 + Neo4j 그래프 병렬 + Cross-encoder 재랭킹 |
| **Stage A/B 색인** | staging vector_id prefix로 검색 격리 → swap (`docs/operations/adr/0002`) |
| **Epoch 캐시 무효화** | SCAN 없이 INCR 1회로 테넌트 단위 전체 무효화 (`adr/0003`) |
| **EXECUTIVE post-filter** | 캐시 hit ratio 보존 + 권한 누수 방어 (`adr/0004`) |
| **비용 가드레일** | EMF 메트릭, X-Ray reservoir, MAX_CONCURRENT_SSE, MAINTENANCE_MODE |
| **서킷 브레이커** | 외부 장애 시 비용 폭증 1차 방어선 (`docs/08-resilience.md`) |
| **4-Agent 하네스** | A planner · B implementer · C qa-tester · D kpi-tester |

## Tech Stack

**Runtime** Python 3.12 · FastAPI · sse-starlette · uv
**LLM/RAG** AWS Bedrock (Claude Haiku 4.5 · Sonnet 4.6 · Titan Embeddings v2) · sentence-transformers (cross-encoder) · ragas
**Storage** Pinecone Serverless · Neo4j Enterprise (CJK fulltext) · AWS S3 + KMS · ElastiCache Redis · AWS SQS
**Observability** structlog · aws-embedded-metrics (EMF) · aws-xray-sdk
**Resilience** pybreaker · aiolimiter (Redis 분산 token bucket)
**Quality** ruff · mypy strict · bandit · pip-audit · import-linter · pytest · radon · interrogate · vulture
**Infra (외부 책임)** AWS ECS Fargate · ALB · API Gateway · Cognito · Harness CD · Terraform

## 폴더 구조

```
WITIVE-RAG-AI/
├── docs/                          기획·운영 docs (27개)
│   ├── 00-scope.md ~ 13-glossary.md
│   └── operations/                ADR · Runbooks · SOP
├── app/                           코드 (6 레이어, /harness 실행 시 생성)
│   ├── api/                       FastAPI router
│   ├── domain/                    도메인 모델 (외부 의존 0)
│   ├── pipeline/                  유즈케이스
│   ├── infra/                     외부 의존성 어댑터
│   ├── platform/                  횡단 관심사
│   └── workers/                   SQS 소비자
├── kpi/                           D agent KPI 보고서 (HTML)
├── tests/                         단위·통합·RAG 평가·보안·부하
├── .claude/                       하네스 자산
│   ├── agents/                    A · B · C · D
│   ├── commands/                  /harness · /review-check · /rubric
│   ├── skills/                    9개 (ragas-eval · code-rubric · ...)
│   ├── scripts/                   hook scripts
│   └── settings.json              hooks + permissions
├── CLAUDE.md                      루트 전역 규칙
├── work_rule.md                   C가 갱신하는 fresh 규칙
└── .mcp.json                      AWS · Pinecone · Neo4j · GitHub MCP
```

## 시작하기

### 1. 의존성 설치

```bash
git clone <this-repo>
cd WITIVE-RAG-AI
uv venv
uv pip install ragas datasets radon interrogate vulture bandit mccabe \
               pip-audit ruff mypy import-linter tiktoken
```

### 2. 환경 변수 설정

```bash
cp .env.example .env
# .env 안의 시크릿 채우기 (Gmail 앱 비밀번호, Pinecone API key, AWS profile, GitHub PAT)
```

상세 셋업 가이드: [`.claude/SETUP.md`](.claude/SETUP.md)

### 3. Claude Code에서 검증

```
/hooks       # 4개 등록 확인
/agents      # planner · implementer · qa-tester · kpi-tester 4개
/help        # /harness · /review-check · /rubric 3개
/mcp         # aws · pinecone · neo4j · github 4개 connected
```

### 4. 첫 사용

```
/harness POST /internal/query SSE endpoint 1차 구현
```

## 슬래시 명령어

| 명령 | 동작 | 출력 |
|---|---|---|
| `/harness <feature>` | 4-agent 워크플로로 docs 기반 코드 생성 | 변경 파일 + 검수 + KPI HTML |
| `/review-check` | 안정성 KPI 측정 (커버리지·정적·CVE·docs 일치성) | upustream@gmail.com 이메일 |
| `/rubric` | 바이브코딩 정량 평가 (radon·interrogate·vulture·bandit·mccabe) | upustream@gmail.com 이메일 |

## 4-Agent 하네스

`/harness` 실행 시 4개 에이전트가 협업:

```
A planner ──► B implementer ──► C qa-tester ──► D kpi-tester ──► 사용자
   (opus)        (sonnet)         (sonnet)         (sonnet)
   docs 게이트    코드 구현        QA·work_rule     골든셋 KPI
                                  ▲
                                  │ 실패 시 B 재호출 (최대 3회)
                                  └──────────────────────────────┘
```

- **A** docs 일치성 게이트키퍼 + 작업 단위 분해
- **B** 코드 구현 (가장 가까운 `CLAUDE.md` + `work_rule.md` 자동 주입)
- **C** 검수 + `work_rule.md` 갱신 (유일 쓰기 권한)
- **D** ragas + code-rubric → `kpi/<datetime>_<feature>.html`

자세히: [`.claude/agents/`](.claude/agents/)

## docs 안내

본 프로젝트는 **docs-first** — 코드 변경은 docs와 정합해야 PR 통과.

| 영역 | 진입 |
|---|---|
| docs 인덱스 | [`docs/README.md`](docs/README.md) |
| 책임 경계 | [`docs/00-scope.md`](docs/00-scope.md) |
| 아키텍처 | [`docs/01-architecture.md`](docs/01-architecture.md) |
| 결정 근거 (ADR) | [`docs/operations/adr/`](docs/operations/adr/) |
| 사고 대응 (Runbook) | [`docs/operations/runbooks/`](docs/operations/runbooks/) |
| 표준 절차 (SOP) | [`docs/operations/sop/`](docs/operations/sop/) |

## SLO

| 지표 | 임계 |
|---|---|
| 첫 토큰 P95 (cold) | ≤ 4.0s |
| 첫 토큰 P95 (cache hit) | ≤ 0.1s |
| 전체 답변 P95 | ≤ 11s |
| RAG Recall@5 | ≥ 0.80 |
| RAG MRR | ≥ 0.70 |
| Faithfulness | ≥ 0.90 |
| 가용성 | 99.9% (월 ≤ 44분 다운) |
| 캐시 hit ratio (15분) | ≥ 0.5 |

## 보안·격리

- TLS 1.3 (전송) · AES-256 KMS (저장)
- 테넌트별 KMS CMK + Pinecone Index + Neo4j Database
- AWS PrivateLink (Bedrock·S3·SQS 인터넷 미경유)
- `tenant_id` 필터 강제 주입 (코드 레벨 + 1차 저장소)
- 감사 로그 1년 (CloudWatch 90일 → S3 WORM 275일)
- prompt injection 방어 (시스템 프롬프트 격리 + OWASP LLM Top 10 fuzz)

## 기여 가이드

PR 템플릿은 [`docs/12-coding-conventions.md`](docs/12-coding-conventions.md) §9.3 참조.

핵심 원칙:
1. **docs와 어긋나는 코드 PR 거부** — 변경 시 docs 동시 갱신 의무
2. **의존 방향 강제** (`api → pipeline → infra`, `domain ← infra`) — `import-linter`로 CI 자동
3. **`tenant_id` 필터 우회 절대 금지** (보안)
4. **새 결정은 ADR 작성** (라이브러리·비용·SLO 영향 시)
5. **PII 로그 금지** — 질문 본문은 SHA-256 해시만

## License

(미정 — 운영 진입 직전 결정)

## 문의

- Issues: GitHub Issues
- 운영 보고: upustream@gmail.com
