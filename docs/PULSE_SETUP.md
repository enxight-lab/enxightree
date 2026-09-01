# ENXIGHT Market Pulse — 구성 & 운영 (v2 · 전부 자동)

> 원본: enxight_market_pulse_v1_final.zip (2026-06-10 설계). 2026-06-11 Enxightree repo 통합 배포.
> **v2 (2026-06-11)**: 집계기를 GAS → **GitHub Actions(Python)** 로 전면 대체 — 수동 설치 0.
> 사유: 원안이 전제한 GAS 뉴스 수집기(ENXIGHT_news_collector + NEWS 시트)의 실존 불확실 +
> 구글 콘솔 수동 설치 필요. 뉴스 밀도는 GDELT DOC API 직접 집계로 대체 (원래도 GDELT 기반 설계).
> `docs/pulse_aggregator.gs` 는 폐기된 GAS 원안 참고용.

## 구성 (전부 배포 완료 — 사람 손 0)

```
[GitHub Actions pulse-refresh — 매일 07:30 KST]
  scripts/build_pulse.py
  ├─ Yahoo v8: 7지역 지수 종가·등락 (실패 지역 null → 프론트 회색)
  ├─ GDELT DOC: 7지역×5테마 24h 영문 기사 수 (5.2s 간격 + 429 백오프, artlist cap 250)
  └─ 온도차: data.enxight.com 이력 7일 베이스라인 × 가격 괴리
       ↓ POST (PULSE_TOKEN)
[data.enxight.com — Worker enxight-pulse + KV PULSE_KV]
  pulse:latest + pulse:YYYY-MM-DD 이력 · 엣지 캐시 15분 · 토큰 외 POST 401
       ↓ fetch
[map.enxight.com/pulse — 3탭 프론트 (뉴스 밀도·가격·온도차)]
```

| 자원 | 위치 |
|---|---|
| 집계기 | `scripts/build_pulse.py` (표준 라이브러리만 — CI 의존성 0) |
| cron | `.github/workflows/pulse-refresh.yml` (07:30 KST + 수동 트리거, 실패 시 텔레그램) |
| Worker | `pulse-worker/` (`cd pulse-worker && npx wrangler deploy`) |
| 프론트 | `public/pulse/index.html` (루트 build+deploy 에 포함) |
| Secrets | Actions `PULSE_TOKEN` ✅ · Worker `PULSE_TOKEN` ✅ (동일 값, 로컬 `.env` 에 사본) |

## 운영 메모

- 온도차 탭은 이력 7일 축적 후 활성 — 첫 주 "특이 괴리 없음" 정상
- 임계값(newsRatio 1.8/0.8 · absChg 0.5/1.5)은 2주 운영 후 보정
- Yahoo v8 비공식 — 장애 시 해당 지역만 회색. GDELT 429 는 백오프 재시도로 흡수
- 가격·뉴스 모두 전멸 시 push 중단 (이전 데이터 유지 — silent 회귀 방지 가드)
- 수동 실행: Actions `pulse-refresh` workflow_dispatch 또는 로컬 `python scripts/build_pulse.py`

## 백로그

- [ ] GDELT artlist cap 250 — 광역 쿼리(미국 등)가 cap 에 자주 닿아 상대 변별 약화.
      쿼리 구체화 또는 timelinevol 모드 검토 (온도차 ratio 가 1로 수렴하는 부작용 관찰)
- [ ] pulse 디자인 Harbor 패밀리룩 정합 (현재 자체 CI 다크)
- [x] Enxightree 본체 ↔ /pulse 상호 링크 ✅ 2026-06-11 (헤더 📡 Pulse · 펄스 푸터 🌳)
- [ ] v2 금리 탭 (FRED) · v3 시그널 탭 (원 WORKLOG 로드맵)
