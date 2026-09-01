# Enxightree 

> **Enxightree(엔자이트리)** — 자산을 타일로 보는 ENXIGHT Lab 시각화. 1호 = 대한민국 부동산 히트맵.
> `map.enxight.com` — ENXIGHT 패밀리.

## 무엇인가

- **좌측**: 실제 행정구역 경계 한국 지도 (통계청 경계, 시도→시군구 줌인 코로플레스)
- **우측**: 핀비즈식 트리맵 (타일 크기 = 시장 규모, 색상 = 변동률)
- **드릴다운**: 전국(시도) → 시군구 (세종은 하위 없음 → 바로 상세)
- **기간**: 주간 / 월간 / 3개월 / 연간 — 기간별 색상 스케일(PMAX) 자동 조정
- **상세 패널**: 평균가, 4개 기간 변동률, 12개월 추이 차트, 지역 뉴스(2d 연동 예정)

## 아키텍처 (한 줄)

```
[배치 build_data.py: R-ONE + 국토부 실거래가] → public/data.json → [React 앱이 fetch]
        (키는 .env/Secrets 에만)                  (커밋·배포 대상)      (브라우저, 키 없음)
```

## 개발

```powershell
npm install
npm run dev        # localhost:5173
npm run build      # dist/
python scripts/build_data.py --sample   # 샘플 data.json 재생성
```

## 로드맵

| 단계 | 작업 | 상태 |
|---|---|---|
| 1 | 프로토타입 UX (트리맵+픽셀맵+드릴다운+상세) | ✅ v0.3 |
| 2a | Vite 이관 + 컴포넌트 분리 + data.json 분리 | ✅ 2026-06-10 |
| 2a-2 | 실제 행정구역 경계 지도 (PATCH v1.1로 승격) | ✅ 2026-06-10 |
| 2b | 배치 수집기 (R-ONE 지수 + 실거래가) + cron workflow | ✅ 2026-06-10 |
| 2c | CF 배포 + map.enxight.com 연결 | ⬜ |
| 2d | 뉴스 Worker (네이버 검색 API) | ⬜ |
| 4 | 읍면동 딥스, 전세/월세 모드, PWA | ⬜ 백로그 |

## 규칙

시간은 전부 KST(UTC+9) · API 키 커밋 금지(.env.example만) · 샘플 데이터 정본은 `src/data/sample.json` 하나.
설계 결정은 [docs/adr/](docs/adr/) · 데이터 출처는 [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)
· 제3자 저작물 고지는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
