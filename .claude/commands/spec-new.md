---
description: spec.md 빈 템플릿을 specs/YYYY-MM-DD-<slug>.md로 생성. /spec-new <slug>
argument-hint: <slug>
---

# /spec-new — spec 빈 템플릿 생성

## 사용법

```
/spec-new fix-redis-cache
/spec-new add-bedrock-converse-stream
/spec-new refactor-rerank-pipeline
```

## 동작

다음 단계를 정확히 실행하세요:

1. `$ARGUMENTS`를 slug로 받는다. 비어 있으면 사용자에게 slug 요청 후 종료.
2. slug 검증: 영문 소문자·숫자·하이픈만. 공백·한글·특수문자 있으면 자동 변환 (소문자 + 공백 → 하이픈) 후 사용자에게 변환 결과 안내.
3. `Bash` 또는 `PowerShell`로 오늘 날짜(YYYY-MM-DD)를 얻는다.
4. 파일 경로: `specs/<YYYY-MM-DD>-<slug>.md`
5. 동일 경로 파일이 이미 존재하면 `-2`, `-3` ... suffix 추가.
6. `Write` tool로 다음 템플릿을 작성:

```markdown
---
target_dir: 
category: fix
refs:
  - 
accept:
  - 
reject:
  - 
---

# <작성자가 채울 제목>

## 문제 / 의도

(현재 동작과 기대 동작, 재현 단계, 영향 범위)

## 메모

(planner·implementer가 참고할 추가 컨텍스트, 선택)
```

7. 사용자에게 다음을 한 번에 출력:
   - 생성된 spec 파일 경로
   - 다음 단계 안내: "헤더 + 본문 채운 뒤 `/spec <경로>` 실행"
   - 양식 가이드 링크: `specs/README.md`

## 사전 조건

- `specs/` 디렉토리 존재 (없으면 자동 생성)

## 참조

- `specs/README.md` — 양식 명세
- `.claude/commands/spec.md` — 다음 단계
