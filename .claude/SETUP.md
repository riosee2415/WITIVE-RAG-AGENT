# 하네스 셋업 가이드 (사용자 1회 작업)

본 하네스를 동작시키려면 다음을 1회 셋업해야 한다.

## 1. Python 의존성 설치

```bash
uv venv
uv pip install ragas datasets radon interrogate vulture bandit mccabe pip-audit ruff mypy import-linter tiktoken
```

## 2. Gmail SMTP 환경 변수 (이메일 발송)

### 2.1 Gmail 앱 비밀번호 발급

1. Google 계정 → 보안 → 2단계 인증 활성화
2. 보안 → 앱 비밀번호 → "메일" + 디바이스 → 16자 발급

### 2.2 환경 변수 (`.env` 또는 시스템)

```
GMAIL_SMTP_USER=upustream@gmail.com
GMAIL_SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx
GMAIL_SMTP_FROM=upustream@gmail.com
GMAIL_SMTP_TO=upustream@gmail.com
```

PowerShell:
```powershell
[System.Environment]::SetEnvironmentVariable("GMAIL_SMTP_USER", "upustream@gmail.com", "User")
[System.Environment]::SetEnvironmentVariable("GMAIL_SMTP_APP_PASSWORD", "xxxxxxxxxxxxxxxx", "User")
```

### 2.3 발송 테스트

```bash
python -c "from email.message import EmailMessage; import smtplib, ssl, os; m=EmailMessage(); m['From']=os.environ['GMAIL_SMTP_USER']; m['To']=os.environ['GMAIL_SMTP_USER']; m['Subject']='harness setup test'; m.set_content('hello'); ctx=ssl.create_default_context(); s=smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ctx); s.login(os.environ['GMAIL_SMTP_USER'], os.environ['GMAIL_SMTP_APP_PASSWORD']); s.send_message(m); s.quit()"
```

## 3. MCP 셋업 (4개)

`.mcp.json` 파일은 이미 생성됨. 환경 변수만 설정하면 Claude Code가 자동 인식.

### 3.1 AWS Labs MCP (`aws`)

```bash
# uvx 설치 (없으면): pip install uv
# 환경 변수 (PowerShell)
[System.Environment]::SetEnvironmentVariable("AWS_PROFILE", "witive-dev", "User")

# AWS profile 사전 셋업
aws configure --profile witive-dev
# Access Key·Secret·region(ap-northeast-2) 입력
```

**보안 주의**: dev 계정 한정으로 시작. prod 호출은 별도 profile + 명시 게이트.

### 3.2 Pinecone MCP (`pinecone`)

```powershell
[System.Environment]::SetEnvironmentVariable("PINECONE_API_KEY", "pc-xxxxxxx", "User")
```

(Pinecone 콘솔 → API Keys 발급)

### 3.3 Neo4j MCP (`neo4j`)

```powershell
[System.Environment]::SetEnvironmentVariable("NEO4J_URI", "bolt://10.0.1.50:7687", "User")
[System.Environment]::SetEnvironmentVariable("NEO4J_USER", "neo4j", "User")
[System.Environment]::SetEnvironmentVariable("NEO4J_PASSWORD", "xxxxxxx", "User")
```

dev 환경엔 Neo4j 미사용이므로 staging 진입 직전 셋업해도 무방.

### 3.4 GitHub MCP (`github`)

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. 권한: `repo`, `read:org`, `pull_requests:write`, `issues:write`
3. 환경 변수:

```powershell
[System.Environment]::SetEnvironmentVariable("GITHUB_PERSONAL_ACCESS_TOKEN", "ghp_xxxxx", "User")
```

### 3.5 MCP 검증

Claude Code 재시작 후:
```
/mcp
```

4개(`aws`, `pinecone`, `neo4j`, `github`) 모두 connected 표시 확인.

## 4. .gitignore 갱신

프로젝트 루트 `.gitignore`:
```
.env
.env.*
!.env.example
.mcp.local.json
kpi/*.html
kpi/*.jsonl
.claude/scripts/__pycache__/
__pycache__/
*.pyc
.venv/
.coverage
coverage.json
bandit.json
pip-audit.json
```

`.mcp.json`은 환경 변수 placeholder만 있어 commit 가능.

## 5. Claude Code 측 검증

| 명령 | 확인 |
|---|---|
| `/hooks` | PostToolUse·Stop·SubagentStop·UserPromptSubmit 4개 |
| `/agents` | planner·implementer·qa-tester·kpi-tester 4개 |
| `/help` | `/harness`, `/review-check`, `/rubric` 3개 |
| `/mcp` | aws·pinecone·neo4j·github 4개 connected |

## 6. Skill 9개 자동 인식

`.claude/skills/` 안 9개 (외부 의존 없음 + 외부 라이브러리 의존):
- `ragas-eval` (ragas)
- `code-rubric` (radon·interrogate·vulture·bandit·mccabe)
- `docs-sync` (stdlib)
- `send-email` (stdlib + Gmail SMTP)
- `prompt-injection-test` (stdlib)
- `load-test` (k6 별도 설치)
- `adr-generator` (stdlib)
- `runbook-from-alarm` (stdlib)
- `token-cost-estimator` (tiktoken)

## 7. k6 설치 (load-test Skill)

```powershell
choco install k6
# 또는 https://k6.io/docs/get-started/installation/
```

## 8. 첫 사용

```
/harness POST /internal/query SSE endpoint 1차 구현
```

A planner가 docs를 읽고 작업 계획 → B·C·D 호출 시작.

## 9. 문제 해결

| 문제 | 해결 |
|---|---|
| `python` 명령 안 됨 (Windows) | `py` 또는 `python3`. hook script `command` 필드 조정 |
| Gmail SMTP 인증 실패 | 2단계 인증 + 앱 비밀번호. 일반 비밀번호 X |
| MCP 서버 connection 실패 | 환경 변수 확인 + Claude Code 재시작. `/mcp` 로그 확인 |
| ragas 설치 실패 | Python 3.12 확인. `uv pip install --upgrade pip` 후 재시도 |
| AWS MCP 권한 부족 | profile에 충분한 권한 부여. dev 계정 read-only 시작 권장 |
| GitHub MCP 401 | PAT 만료·권한 부족. fine-grained token 재발급 |
| `uvx` 명령 없음 | `pip install uv` 또는 `pip install pipx` |
