// K-RE MAP — 공용 상수·유틸 (HANDOFF §8 원본 로직 보존)
import { interpolateRgb } from "d3-interpolate";

// 기간 체계 v2: 주간·월간·분기·반기·연간 + 기타(custom, 개월 수 사용자 설정 — 최대 = series 길이)
export const PERIODS = [["w", "주간"], ["m", "월간"], ["q", "분기"], ["h", "반기"], ["y", "연간"]];
// 행 인덱스: w/m/q/y 는 배치 계산값. h/custom 은 App 이 series 에서 계산해 복제 행 index 6 에 주입.
export const PIDX = { w: 3, m: 4, q: 5, y: 6, h: 6, custom: 6 };
// 기간 → series 개월 수 (h/custom 프론트 계산용)
export const PERIOD_MONTHS = { m: 1, q: 3, h: 6, y: 12 };

// 기간별 색상 ±스케일 (HANDOFF §6 확장). custom 은 개월 수 보간.
const PMAX_BASE = { w: 0.3, m: 1.2, q: 3.2, h: 5.5, y: 9 };
const PMAX_PTS = [[1, 1.2], [3, 3.2], [6, 5.5], [12, 9]];
export function getPmax(period, customMonths) {
  if (period !== "custom") return PMAX_BASE[period];
  const M = Math.max(1, customMonths || 12);
  if (M >= 12) return Math.min(60, Math.round(9 * Math.pow(M / 12, 0.75) * 10) / 10);
  for (let i = 1; i < PMAX_PTS.length; i++) {
    const [m0, p0] = PMAX_PTS[i - 1], [m1, p1] = PMAX_PTS[i];
    if (M <= m1) return Math.round((p0 + ((M - m0) / (m1 - m0)) * (p1 - p0)) * 10) / 10;
  }
  return 9;
}

// ── Harbor 패밀리 팔레트 (다크/라이트 테마) ──────────────────────────
// 원본 SSoT: ENXIGHT-HOMEPAGE styles/harbor.css (라이트 기본 + [data-theme=dark]) — 2026-06-08 리뉴얼.
// SVG 속성·d3 보간 호환을 위해 CSS var 대신 JS 라이브 바인딩(export let) —
// setTheme() 재할당 후 React 리렌더로 전 컴포넌트에 반영 (ES 모듈 라이브 바인딩 활용).
// 등락 시그널은 채도 높은 데이터색 유지 (2026-06-11 사용자: Harbor 톤다운은 임팩트 부족).

const FONTS = {
  serif: '"Spectral", Georgia, serif',
  sans: '"Pretendard Variable", "Pretendard", -apple-system, system-ui, "Segoe UI", sans-serif',
  mono: '"IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace',
};

export const THEMES = {
  dark: {
    ...FONTS,
    page: "#0E141C", canvas: "#0B1016", panel: "#19222E",
    hair: "#323F4F", hairSoft: "#2A3543",
    ink: "#E9EDF2", ink2: "#AAB4C0", meta: "#7B8794",
    primary: "#5A79A6", onPrimary: "#FFFFFF", primaryHover: "#6E8BB5",
    brass: "#D9BC96", ghostBorder: "#4D5B70",
    green: "#1FC25A", red: "#E8404A",   // 채도 복귀 (구 핀비즈 시그널)
    gray: "#3B4654", nodata: "#1A222C",
  },
  light: {
    ...FONTS,
    page: "#F5F7F8", canvas: "#E7EBEE", panel: "#EEF1F3",
    hair: "#DCE1E5", hairSoft: "#E7EBEE",
    ink: "#1B232C", ink2: "#42505C", meta: "#73818C",
    primary: "#36507A", onPrimary: "#FFFFFF", primaryHover: "#2A3C57",
    brass: "#B58B55", ghostBorder: "#C9D2DA", // brass 는 라이트 가독 위해 한 단계 진하게
    green: "#15A24A", red: "#D5332B",   // 라이트 배경 + 흰 타일 글씨 대비 확보 (명도↓ 채도 유지)
    gray: "#76828F", nodata: "#DCE1E5",
    isLight: true,
  },
};

export let C = THEMES.dark;
export let GREEN = C.green, RED = C.red, GRAY = C.gray, NODATA = C.nodata;

export function setTheme(name) {
  C = THEMES[name] || THEMES.dark;
  GREEN = C.green; RED = C.red; GRAY = C.gray; NODATA = C.nodata;
  if (typeof document !== "undefined") {
    document.body.style.background = C.page;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", C.page);
  }
  try { localStorage.setItem("kremap-theme", name); } catch { /* 시크릿 모드 등 */ }
}

export function getInitialTheme() {
  // 우선순위: URL ?theme=(임베드 시 enxight.com 셸이 부모 테마 전달) > 저장값 > light.
  // 기본 light = 홈·매거진과 동일 (2026-06-11 패밀리룩 통일 — 시스템 다크 추종 제거)
  try {
    const q = new URLSearchParams(location.search).get("theme");
    if (q === "dark" || q === "light") return q;
  } catch { /* noop */ }
  try {
    const saved = localStorage.getItem("kremap-theme");
    if (saved === "dark" || saved === "light") return saved;
  } catch { /* noop */ }
  return "light";
}

// pmax 는 숫자 (getPmax 산출). chg=null = 해당 기간 데이터 부족 → 무채색.
export function colorFor(chg, pmax) {
  if (chg == null) return NODATA;
  if (Math.abs(chg) < pmax * 0.05) return GRAY;
  const t = Math.max(-1, Math.min(1, chg / pmax));
  return t > 0
    ? interpolateRgb(GRAY, GREEN)(Math.pow(t, 0.65))
    : interpolateRgb(GRAY, RED)(Math.pow(-t, 0.65));
}

// 월간 지수 시계열(vals, 끝=최신)에서 N개월 변동률(%) — 범위 밖이면 null
export function changeFromSeries(vals, months) {
  if (!vals || vals.length <= months) return null;
  const cur = vals[vals.length - 1], base = vals[vals.length - 1 - months];
  if (!base) return null;
  return Math.round((cur / base - 1) * 10000) / 100;
}

export const fmt = (c) => (c > 0 ? "+" : "") + c.toFixed(2) + "%";

// 이름 해시 기반 결정적 의사난수 추이 — 실데이터(data.json trends) 없을 때만 사용
export function trendSeries(name, yChg) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const rnd = () => { h = (h * 1664525 + 1013904223) >>> 0; return h / 4294967296; };
  const start = 100 / (1 + yChg / 100);
  const pts = [];
  for (let i = 0; i < 12; i++) {
    const base = start + (100 - start) * (i / 11);
    pts.push(i === 11 ? 100 : base * (1 + (rnd() - 0.5) * 0.014));
  }
  return pts;
}

// 최근 12개월 라벨 — endYm("202604") 기준으로 끝나는 12개. 미지정 시 KST 현재 월.
// ⚠️ 실데이터 추이는 지수 기준월(asof.monthly)로 끝나므로 반드시 endYm 을 줘야 라벨↔데이터 정합.
export function monthLabels(endYm) {
  let y, m;
  if (endYm && /^\d{6}$/.test(endYm)) {
    y = +endYm.slice(0, 4); m = +endYm.slice(4);
  } else {
    const now = new Date(Date.now() + 9 * 3600 * 1000); // KST 근사 (UTC+9)
    y = now.getUTCFullYear(); m = now.getUTCMonth() + 1;
  }
  const out = [];
  for (let i = 0; i < 12; i++) {
    out.unshift(`${String(y).slice(2)}.${String(m).padStart(2, "0")}`);
    m--; if (m === 0) { m = 12; y--; }
  }
  return out;
}
