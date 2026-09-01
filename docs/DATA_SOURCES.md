# K-RE MAP 데이터 소스 SSoT

> 출처·갱신주기·키·계약. 상세 파라미터는 `scripts/build_data.py` docstring 참조.
> PATCH v1.1 [변경 2]: **data.go.kr 키 하나로 두 데이터 모두 커버** — R-ONE 직접 가입 불필요.

## 규모(타일 크기)·평균가 — 국토교통부 실거래가

| 항목 | 내용 |
|---|---|
| 소스 | 공공데이터포털 — 국토교통부_아파트 매매 실거래가 자료 (**15126469**) |
| 키 | `.env` `DATA_GO_API_KEY` — ✅ **2026-06-10 활성 확인** (강남구 202605 호출, resultCode 000 + 실거래 응답) |
| 호출 | `RTMSDataSvcAptTradeDev` · LAWD_CD(법정동 5자리) + DEAL_YMD(전월 — 당월은 신고 지연) |
| 산출 | 시군구별 전월 평균가(억)·거래대금 합(규모 프록시) → 시도 롤업. 해제거래(cdealType=O) 제외 |
| 코드 목록 | ✅ `scripts/lawd_codes.json` (118 지역·155 코드) — `gen_lawd_codes.py` 로 재생성 (행정구역 개편 시) |

## 색상(변동률)·추이 — 한국부동산원 R-ONE 직접 (2b ✅ 채택)

| 항목 | 내용 |
|---|---|
| 소스 | R-ONE OpenAPI `SttsApiTblData.do` — `REP_API_KEY` ✅ **2026-06-10 활성 확인** (통계표 738개 응답) |
| 통계표 | 월간 아파트 매매가격지수 **`A_2024_00045`** · 주간 매매가격지수 **`T244183132827305`** |
| 지역 식별 | `CLS_FULLNM` 계층 경로 파싱 ("서울>강남구", "경기>경부1권>수원시") — 권역·시 하위 구 무시 |
| 산출 | w=주간 최근2주, m/q/y=월간 시계열, trends=최근 12개월(최신=100 정규화), **series=월간 지수 원시 ~119개월**(반기·기타 프론트 계산용) |
| 수집 범위 | `MONTHS_BACK=121` (10년 — 기타 최대 118개월). 원천은 **2003-11부터 존재**(2026-06-10 확인) — 전체 필요 시 상수만 확대 |
| 시점 주의 | 월간 발표 lag 존재 (6/10 시점 최신 = 2026-04) — 수집기가 최신월 자동 탐지 |
| 비고 | data.go.kr 래퍼(15134761)는 미사용 — R-ONE 직접이 작동 확인되어 채택 (PATCH [변경2]의 '간소화'는 키 통합 측면만 참고) |

## 지도 경계 (2a-2 ✅)

| 항목 | 내용 |
|---|---|
| 소스 | GitHub `southkorea/southkorea-maps` — 통계청(KOSTAT) 2018 시도·시군구 |
| 배치 | `public/geo/*.topo.json` (mapshaper 35% simplify · 81KB+228KB) |
| 주의 | 코드 = KOSTAT 체계 (≠ LAWD_CD). 조인 규칙·예외는 `src/data/geo.js` |

## 뉴스 (2d 단계)

| 항목 | 내용 |
|---|---|
| 소스 | 네이버 검색(뉴스) API — 일 25,000건 무료 |
| 키 | ✅ `.env` 에 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET` 보유 확인 (2026-06-10) — Worker 환경변수로 옮겨 사용 |
| 경로 | 클라이언트 → CF Worker `/api/news?q={지역}` → 네이버 (키는 Worker 환경변수) |
| 계약 | 응답 `[{t,s,d,u}]` 형식 유지 (프론트 DetailPanel 수정 최소화) |

## 갱신 주기 (2b ✅)

`.github/workflows/data-refresh.yml` — cron **매일 06:00 KST** (UTC 21:00) + 수동 트리거.
수집 → data.json 변경 시 커밋 → 빌드 → (CF 토큰 등록 시) wrangler deploy.
repo Secrets: `DATA_GO_API_KEY` · `REP_API_KEY` (+ 2c에서 `CLOUDFLARE_API_TOKEN` · `CLOUDFLARE_ACCOUNT_ID`).

## 공통 원칙

- 키는 배치·Worker 측에만. 프론트/산출물로 절대 안 감.
- 모든 timestamp KST(+09:00).
- 출처 표기: 화면 하단 "출처: 한국부동산원 · 국토교통부 실거래가" (App.jsx 푸터).
- 안전장치: 시도 17개 미달 시 발행 중단(이전 data.json 유지) — silent 회귀 방지.

## 남은 것 (2c·2d)

- [ ] GitHub repo 생성·push + Actions Secrets 등록 (사용자와 함께)
- [ ] CF Workers 배포 + map.enxight.com 연결 + `CLOUDFLARE_API_TOKEN` Secrets
- [ ] 뉴스 Worker (네이버 키는 .env 보유 — Worker 환경변수로 이관)
