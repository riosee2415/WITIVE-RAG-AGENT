# SOP — Standard Operating Procedure

본 폴더는 정기/수동 운영 작업의 표준 절차다. 사고 대응(runbook)이 아닌 **계획된 작업**.

## SOP 인덱스

| 파일 | 주기 | 책임자 |
|---|---|---|
| [`secret-rotation.md`](./secret-rotation.md) | 90일 (시크릿별) | DevOps |
| [`tenant-onboarding.md`](./tenant-onboarding.md) | 신규 테넌트 추가 시 | DevOps + Backend (Next.js) |

## 추가 작성 예정

- `deployment.md` — Blue/Green 배포 절차 (Harness CD 책임이지만 본 서버 측 체크리스트)
- `orphan-cleanup-cron.md` — EventBridge cron 설정·모니터링
- `library-version-upgrade.md` — SDK 메이저 버전 업그레이드 절차
- `cost-review-monthly.md` — 월간 비용 회귀 검토
- `golden-set-curation.md` — RAG 평가 골든셋 갱신
- `prod-shadow-traffic.md` — 신규 모델 검증 시 prod 트래픽 일부 shadow

## 표준 형식

```markdown
# SOP: <작업 명>

- 주기: <주기 또는 "이벤트 기반">
- 책임자: <팀/역할>
- 소요 시간: 약 N분
- 사전 조건: <필요한 권한·환경·도구>

## 1. 사전 점검

작업 시작 전 확인할 것.

## 2. 절차 (순서)

단계별. 각 단계에서 결과 검증.

## 3. 사후 확인

작업 후 확인. 메트릭·로그.

## 4. 롤백 절차

문제 발생 시 되돌리기.

## 5. 변경 이력

작업 일자·담당자·결과 기록 (선택).
```

## SOP vs Runbook 구분

| 항목 | SOP | Runbook |
|---|---|---|
| 트리거 | 계획된 (cron, 신규 테넌트, 정기 점검) | 사고 (알람) |
| 결과 | 정상 운영 유지 | 사고 복구 |
| 압박감 | 낮음 (계획) | 높음 (사용자 영향 중) |
| 롤백 명세 | 필수 | 부분 (사고 자체가 비정상이라 정상 상태 정의 모호) |
