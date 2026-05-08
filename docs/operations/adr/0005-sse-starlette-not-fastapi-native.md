# ADR-0005: SSE 응답에 sse-starlette 라이브러리 채택

- 상태: Accepted
- 일자: 2026-05-07
- 결정자: 본 서버 설계팀
- 관련 docs: `02-query-pipeline.md` §6.2, `06-api.md` §3.1, `10-config-and-secrets.md` §7.1

## Context

본 서버 `POST /internal/query`는 Stage 2 답변 토큰을 Server-Sent Events로 클라이언트에 스트리밍한다. SSE는 다음 운영 요건이 있다:

- 프록시·로드 밸런서의 idle timeout(Next.js 30s, ALB 60s)을 회피하기 위한 keep-alive ping
- Nginx 등 reverse proxy 버퍼링 차단 (`X-Accel-Buffering: no`)
- 클라이언트 reconnection 시 `Last-Event-ID` 헤더 처리
- `Cache-Control: no-cache` 응답 헤더

3단계 docs 작성 중 context7 라이브러리 docs에서 `fastapi.sse.EventSourceResponse`라는 모듈을 참조 정보로 받았다. 검수 6차 라운드에서 **이 모듈은 FastAPI 공식 패키지에 존재하지 않음**이 확인됐다 (`fastapi.sse` 모듈 부재). 확인 결과 위 운영 요건을 자동 처리하는 것은 별도 PyPI 패키지인 `sse-starlette`이었다.

## Decision

`sse-starlette` 라이브러리(`>=2.1,<3.0` 핀)의 `EventSourceResponse`를 사용한다.

```python
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

@app.post("/internal/query")
async def query(...) -> EventSourceResponse:
    return EventSourceResponse(generator(...), ping_interval=15)
```

FastAPI 자체에는 SSE 모듈이 없다 — `sse-starlette`은 FastAPI 생태계의 사실상 표준 SSE 라이브러리.

## Alternatives

| 대안 | 거부 사유 |
|---|---|
| `fastapi.sse.EventSourceResponse` (1차 시안) | **모듈이 존재하지 않음**. ImportError로 즉시 차단 |
| Starlette `StreamingResponse` 직접 사용 + 자체 keep-alive task | keep-alive·헤더·resumable 모두 자체 구현. 표준 라이브러리 있는데 재발명 |
| WebSocket으로 대체 | Next.js 프록시·ALB·클라이언트 EventSource API 호환성 ↓. SSE 단방향이 본 use case에 충분 |
| HTTP/2 push | 브라우저 지원 deprecated, Next.js 프록시 지원 불확실 |

## Consequences

긍정적:
- 표준 라이브러리로 운영 요건 자동 충족 (15s ping, 헤더, resumable)
- 코드 단순화 — 자체 heartbeat task 불필요
- FastAPI 생태계 표준이라 학습 비용 낮음

부정적:
- 별도 패키지 의존 (`pip install sse-starlette`). FastAPI 메이저 업그레이드 시 호환성 확인 필요
- `Last-Event-ID` resumable은 본 서버에서 미지원 결정 — 헤더 받지만 무시 (`06 §3.1`). 향후 활용하려면 별도 결정

후속 작업:
- `10 §7.1` 라이브러리 핀에 `sse-starlette>=2.1,<3.0` 명시 (완료)
- `02 §6.2`·`06 §3.1` 라이브러리 명·import 경로 정정 (완료)
- `13 §6` glossary에 sse-starlette 항목 추가 (완료)
- 통합 테스트에 `sse-starlette` 버전 호환성 확인 (`11-testing.md` §3)

## References

- `docs/02-query-pipeline.md` §6.2
- `docs/06-api.md` §3.1
- `docs/10-config-and-secrets.md` §7.1
- 검수 6차 라운드 H-1 (`fastapi.sse` 모듈 부재 발견)
- PyPI `sse-starlette`: https://pypi.org/project/sse-starlette/
- FastAPI 공식 docs: https://fastapi.tiangolo.com/ (SSE는 `StreamingResponse` 기반 예제만 제공)
