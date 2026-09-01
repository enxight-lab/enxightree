// K-RE MAP — 행정구역 경계 데이터 조인 (PATCH v1.1 §변경1)
// 경계: public/geo/*.topo.json (southkorea-maps KOSTAT 2018 · mapshaper 35% simplify)
// 코드 체계는 통계청(KOSTAT) — 행정표준 LAWD_CD 와 다름에 주의 (부산 21 vs 26).

// KOSTAT 시도 코드(2자리) → 앱 단축명
// 2026-07-01 개편: 광주(24)+전남(36) → 전남광주통합특별시. 2018 topo 는 두 폴리곤이
// 따로 있으므로 둘 다 같은 앱 시도명으로 조인 — 색·드릴·선택이 한 지역으로 동작.
export const KOSTAT_SIDO = {
  11: "서울", 21: "부산", 22: "대구", 23: "인천", 24: "전남광주", 25: "대전",
  26: "울산", 29: "세종", 31: "경기", 32: "강원", 33: "충북", 34: "충남",
  35: "전북", 36: "전남광주", 37: "경북", 38: "경남", 39: "제주",
};

// 2018 지도 ↔ 현행 명칭 예외 (코드 기반 — 이름보다 안전)
// ⚠️ 2026-07 인천 구 개편(중·동·서구 폐지 → 제물포·영종·서해·검단 신설)은 2018 topo 에
// 새 경계가 없어 코드 매핑 불가(중구=제물포+영종으로 분할 등) — 해당 옛 구 영역은
// resolveMuniName 미일치로 회색 처리(데이터 준비 중). 경계 데이터 현대화 시 해소.
const MUNI_RENAME = {
  23030: "미추홀구", // 인천 남구(KOSTAT 23030) → 2018-07 미추홀구 개명 (지도 데이터가 개명 직전)
};

// 2018 이후 시도 소속 변경 — 2026-06-10 전수 대조 결과 실질 차이는 이 1건뿐.
// ⚠️ 전국 뷰의 시도 폴리곤(provinces)은 2018 경계라 군위 면적이 경북 쪽에 붙어 보임 — 경계 데이터 교체 전 한계.
const SIDO_OVERRIDE = {
  37310: "대구", // 군위군: 2023-07 경북 → 대구 편입
};

export const sidoOfFeature = (f) =>
  SIDO_OVERRIDE[f.properties.code] ?? KOSTAT_SIDO[f.properties.code.slice(0, 2)];

/* 시군구 feature → 앱 데이터(CHILDREN[시도]) 이름 매핑.
   1) 코드 예외 → 2) 직접 이름 일치 → 3) prefix 일치 (일반구 분할 시 병합:
   "수원시장안구"→"수원시") → 4) null = 앱 데이터 없는 지역 (회색 표시) */
export function resolveMuniName(feature, appNames) {
  const { code, name } = feature.properties;
  const renamed = MUNI_RENAME[code];
  if (renamed && appNames.includes(renamed)) return renamed;
  if (appNames.includes(name)) return name;
  return appNames.find((a) => name.startsWith(a)) ?? null;
}
