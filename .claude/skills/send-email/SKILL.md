---
name: send-email
description: Gmail SMTP로 첨부 가능한 이메일을 발송한다. /review-check와 /rubric이 보고서 HTML을 첨부해 upustream@gmail.com으로 발송할 때 사용.
---

# Skill: send-email (Gmail SMTP)

## 사용 대상

- `/review-check` — 안정성 KPI 보고서
- `/rubric` — 바이브코딩 정량 평가 보고서

## 사전 조건 (운영자 1회 셋업)

1. Gmail 계정에 **2단계 인증** 활성화
2. **앱 비밀번호** 발급: Google 계정 → 보안 → 앱 비밀번호 → "메일" + 디바이스 선택 → 16자 비밀번호 발급
3. 환경 변수 또는 `.env` (커밋 금지):
   ```
   GMAIL_SMTP_USER=upustream@gmail.com
   GMAIL_SMTP_APP_PASSWORD=<16자 앱 비밀번호>
   GMAIL_SMTP_FROM=upustream@gmail.com
   GMAIL_SMTP_TO=upustream@gmail.com
   ```

## 동작 (Python stdlib만 사용 — 외부 라이브러리 불요)

```python
import smtplib, ssl, os
from email.message import EmailMessage
from pathlib import Path

def send_report(subject: str, body: str, attachment_path: Path | None = None) -> None:
    user = os.environ["GMAIL_SMTP_USER"]
    pwd = os.environ["GMAIL_SMTP_APP_PASSWORD"]
    msg = EmailMessage()
    msg["From"] = os.environ.get("GMAIL_SMTP_FROM", user)
    msg["To"] = os.environ["GMAIL_SMTP_TO"]
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment_path and attachment_path.exists():
        data = attachment_path.read_bytes()
        msg.add_attachment(
            data,
            maintype="text", subtype="html",
            filename=attachment_path.name,
        )
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(user, pwd)
        s.send_message(msg)
```

## 사용법

`Bash` tool 또는 inline Python으로 위 함수를 정의·호출:

```bash
python -c "from pathlib import Path; \
  import sys; sys.path.insert(0, '.claude/skills/send-email'); \
  from send import send_report; \
  send_report('[review-check] 2026-05-07', '본문...', Path('kpi/review-check_20260507.html'))"
```

또는 별도 파일 `.claude/skills/send-email/send.py`로 모듈화.

## 보안

- Gmail 앱 비밀번호는 `.env` 또는 Secrets Manager. **절대 git commit 금지**
- 90일마다 회전 (Google 권장)
- 본 SMTP는 운영용 알림 전용 — 사용자 데이터 전송 X (PII 정책)

## 비용

무료 (Gmail 일 500 mail/account 한도 안에서). 본 use case는 일 ≤ 5건 예상.
