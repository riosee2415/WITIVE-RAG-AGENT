# app/workers — SQS 소비자 entry point

## 책임

- ECS Worker Task의 main entry point
- SQS Long Polling → message → `pipeline.document.orchestrator` 호출
- VisibilityTimeout·attempt 카운터 관리

## 금지

- API endpoint 정의 (그건 `api/`)
- 비즈니스 로직 (그건 `pipeline/`)
- `infra/` 직접 호출 (그건 `pipeline/`을 거쳐)

## 파일

| 파일 | 책임 |
|---|---|
| `document_worker.py` | SQS consumer 메인 루프 |
| `__main__.py` | `python -m app.workers` 진입 |

## 표준 패턴

```python
# document_worker.py
import asyncio
from app.platform.config import get_settings
from app.pipeline.document.orchestrator import process_document_message

async def consume():
    settings = get_settings()
    while True:
        messages = await sqs.receive(WaitTimeSeconds=20, MaxNumberOfMessages=settings.MAX_CONCURRENT_DOCS)
        await asyncio.gather(*[process_document_message(m) for m in messages])

if __name__ == "__main__":
    asyncio.run(consume())
```

## 참조

- `@docs/03-document-pipeline.md` §3.1 — 메시지 수신·잠금
- `@docs/01-architecture.md` §5 — 동시성 모델
- `@docs/08-resilience.md` §5.2 — Worker timeout

## work_rule

@work_rule.md
