# app/platform — 횡단 관심사

## 책임

- 누구나 사용할 수 있는 cross-cutting 모듈
- 설정·로깅·추적·메트릭·리트라이·서킷·인증·rate limit

## 금지

- 비즈니스 로직 (그건 `pipeline/`)
- 외부 SDK 직접 호출 (그건 `infra/`)

단, `auth.py`는 X-Internal-Auth 검증을 위해 stdlib `hmac`만 사용 (외부 SDK 아님).

## 파일 분리

| 파일 | 책임 |
|---|---|
| `config.py` | `Settings(BaseSettings)` — 환경 변수 단일 진실 (`@docs/10-config-and-secrets.md`) |
| `logging.py` | structlog 초기화, `LogEvent` enum, PII filter |
| `tracing.py` | aws-xray-sdk patch, span helper |
| `metrics.py` | EMF 발행 (aws-embedded-metrics) |
| `circuit_breaker.py` | 의존성별 서킷 |
| `retry.py` | exponential backoff + jitter |
| `auth.py` | `X-Internal-Auth` dual-key 검증, `TenantContext` build |

## 표준 패턴

```python
# platform/logging.py
from enum import StrEnum

class LogEvent(StrEnum):
    QUERY_RECEIVED = "query.received"
    QUERY_STAGE1_FALLBACK = "query.stage1.fallback"
    # ...

# platform/auth.py
import hmac
def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
```

## 참조

- `@docs/09-observability.md` — log event 카탈로그·메트릭 카탈로그
- `@docs/10-config-and-secrets.md` — Settings + Secrets Manager
- `@docs/00-scope.md` §3.1 — dual-key 회전
- `@docs/08-resilience.md` §3 — 서킷 브레이커 임계

## work_rule

@work_rule.md
