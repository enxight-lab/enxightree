# ADR 0002 — DESK 우산 → K-RE MAP 전용 repo 피벗

- **상태**: Accepted
- **일자**: 2026-06-10 (KST)
- **선행**: ADR 0001 (별도 repo + 정적 JSON — 데이터 흐름 결정은 유지)

## 배경

ADR 0001 시점엔 "부동산 + 주식 조회" 우산 repo(ENXIGHT-DESK, desk.enxight.com)로 출발했으나,
직후 사용자 핸드오프(`docs/HANDOFF_v1.md`)가 도착 — **K-RE MAP**: 핀비즈 스타일 부동산 히트맵
단독 앱, React+d3 전체 소스 포함, 배포 목표 `map.enxight.com` (DNS 위임 확인 완료 상태).

## 결정 (사용자 확정)

1. **K-RE MAP 전용 repo 로 피벗** — `enxight-lab/ENXIGHT-KREMAP` / `map.enxight.com`.
   - 제품 정체성 선명. 주식 화면은 별도 트랙(홈페이지 확장 또는 제2 앱)으로 분리.
2. **스택 = 핸드오프 그대로**: Vite + React + d3 (선별 import). DESK 의 정적 HTML 골격은 폐기.
3. **데이터 흐름은 ADR 0001 유지**: 주기 배치 → 정적 JSON(`public/data.json`) → 프론트 fetch.
   키는 배치/Worker 측에만. (핸드오프 §4 와 동일 사상)
4. **배포는 Cloudflare Workers Static Assets** (`wrangler.toml`, `dist/`).
   - 핸드오프는 CF Pages 안이었으나, 패밀리는 Pages 의 source-repo 변경 미지원 이슈로
     Workers Static Assets 로 전환한 전력 (홈페이지 ADR 참조). 동일 흐름 채택.
   - GitHub Actions cron(2b)이 data.json 갱신 커밋 후 `wrangler deploy` 하는 흐름으로 통일.

## 결과

- 2a 완료 (2026-06-10): Vite 이관 + 컴포넌트 4분리 + 데이터 레이어 분리 + 샘플 정본 단일화.
- fetchNews(키 없는 Anthropic 직접 호출, 아티팩트 전용)는 제거 — 2d 에서 Worker+네이버로.
- DESK 이름·우산 컨셉은 보류 (필요해지면 별도 논의).
