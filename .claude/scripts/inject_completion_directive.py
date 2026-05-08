"""UserPromptSubmit hook — 매 프롬프트마다 작업 종료 강제 절차를 system-reminder로 주입."""
from __future__ import annotations

import sys

DIRECTIVE = """<work-completion-protocol>
다음 작업 종료 절차는 시스템 hook이 강제 검증한다 (위반 시 Stop hook이 응답을 차단·재실행시킨다):

1. 코드(`*.py`) 또는 문서(`*.md`) 변경이 있는 작업이면, **반드시** Agent tool을 `subagent_type="tdd-runner"`로 호출해 TDD/lint 검증을 수행한다. 사용자가 요청하지 않아도 자동 실행이 원칙.
2. 변경 파일에 가까운 `work_rule.md`에 활동 로그가 자동 누적된다 (Stop hook).
3. 모든 작업의 사용자 프롬프트·도구 호출·에러·토큰 사용량은 `reports/YYYY-MM-DD-<slug>.html`로 자동 발행된다 (Stop hook).

이 프로토콜은 사용자가 명시하지 않아도 매 작업마다 자동 적용된다. 단순 질의응답(파일 변경 없음)은 (1) 생략, (2)·(3)만 자동 수행.
</work-completion-protocol>"""


def main() -> None:
    sys.stdin.read()
    print(DIRECTIVE)


if __name__ == "__main__":
    main()
