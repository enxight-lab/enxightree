# 제3자 저작물 고지 (Third-Party Notices)

이 저장소는 아래 제3자 저작물·데이터를 포함하거나 이용합니다.
각 항목의 이용조건은 원 제공자의 고지를 따릅니다.

## 글꼴

| 항목 | 내용 |
|---|---|
| **Pretendard Variable** | `public/fonts/PretendardVariable.ttf` |
| 저작자 | Kil Hyung-jin (길형진) |
| 라이선스 | **SIL Open Font License 1.1** |
| 원출처 | https://github.com/orioncactus/pretendard |

OFL 1.1 은 폰트 파일의 자유로운 사용·재배포를 허용하되, **저작권 고지 동반**과
**폰트 자체의 단독 판매 금지**를 요구합니다. 이 저장소는 웹 서비스의 일부로
폰트를 재배포하며 위 고지로 그 요건을 이행합니다.

`index.html` 이 참조하는 **Spectral** · **IBM Plex Mono** 는 Google Fonts 에서
로드되며 각각 OFL 1.1 입니다(파일을 재배포하지 않습니다).

## 지도 경계 데이터

| 항목 | 내용 |
|---|---|
| 파일 | `public/geo/provinces.topo.json` · `public/geo/municipalities.topo.json` |
| 원출처 | https://github.com/southkorea/southkorea-maps |
| 원 데이터 | **통계청(KOSTAT) 2018 시도·시군구 행정구역 경계** |
| 가공 | mapshaper 35% 단순화(simplify) 후 TopoJSON 으로 변환 |

⚠️ 원 데이터의 이용조건은 통계청 고지를 따릅니다. 상업적 이용 전
[통계지리정보서비스(SGIS)](https://sgis.kostat.go.kr) 의 이용약관을 확인하십시오.

## 통계·시세 데이터 (배치 수집 — 저장소에 산출물만 포함)

`public/data.json` 은 아래 공공 API 로부터 **집계·가공된 산출물**입니다.
원 데이터를 그대로 재배포하지 않습니다.

| 출처 | 내용 | 이용조건 |
|---|---|---|
| 공공데이터포털 (data.go.kr) | 국토교통부 아파트 매매 실거래가 | 공공누리 — 원 고지 확인 |
| 한국부동산원 R-ONE | 아파트 매매가격지수 | 공공누리 — 원 고지 확인 |

## 시장 지표 (Pulse — 저장소에 데이터 미포함)

`scripts/build_pulse.py` 가 호출하며, 산출물은 Cloudflare KV 에 저장되고
이 저장소에는 포함되지 않습니다.

| 출처 | 용도 |
|---|---|
| **GDELT Project** DOC 2.0 API | 지역×테마 뉴스 밀도 |
| **FRED** (St. Louis Fed) | 미국 금리·거시 시계열 |
| **한국은행 ECOS** | 국내 금리 |
| **Yahoo Finance** chart API | 지수 종가 |
| **네이버 검색 API** | 지역 뉴스 (Cloudflare Worker 경유) |

각 제공자의 API 이용약관·호출 한도가 적용됩니다.

## 이 저장소의 코드

별도 `LICENSE` 파일이 없는 한 저작권은 저작자에게 유보됩니다
(All rights reserved). 이용을 원하시면 문의해 주십시오.
