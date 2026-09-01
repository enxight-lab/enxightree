import React, { useState, useMemo, useEffect } from "react";
import KoreaGeoMap from "./components/KoreaGeoMap.jsx";
import Treemap from "./components/Treemap.jsx";
import DetailPanel from "./components/DetailPanel.jsx";
import useWidth from "./lib/useWidth.js";
import useRegionData from "./data/useRegionData.js";
import { PERIODS, PIDX, GREEN, RED, C, getPmax, changeFromSeries, setTheme } from "./lib/utils.js";

// 라이트 단일 모드 (2026-06-11 패밀리 전체 결정 — 모드 토글 폐지, 눈이 덜 피로한 단일 배색)
setTheme("light");

// enxight.com/map/ iframe 안에서 동작 중인지 — 홈 shell 이 nav 를 제공하므로 자체 패밀리 바 숨김
const EMBEDDED = (() => { try { return window.self !== window.top; } catch { return true; } })();

// asof 표기: "202604" → "2026-04", 주간 "202623" → "2026 W23"
const fmtYm = (v) => (v ? `${v.slice(0, 4)}-${v.slice(4)}` : "—");
const fmtWk = (v) => (v ? `${v.slice(0, 4)} W${v.slice(4)}` : "—");

export default function App() {
  const data = useRegionData(); // /data.json 우선, 실패 시 번들 샘플
  const [period, setPeriod] = useState("m");
  const [customM, setCustomM] = useState(24); // 기타(custom) 개월 수
  const [drill, setDrill] = useState(null);
  const [sel, setSel] = useState(null);
  const [outerRef, outerW] = useWidth();

  // 임베드 높이 동기화 — 홈 shell(enxight.com/map/)의 iframe 이 콘텐츠 높이만큼 늘어나
  // 내부 스크롤바 없이 창 스크롤로 동작하도록 부모에 높이 통지 (높이 외 데이터 없음)
  useEffect(() => {
    if (!EMBEDDED) return;
    const post = () => window.parent.postMessage({ type: "enxight:height", height: document.body.scrollHeight }, "*");
    const ro = new ResizeObserver(post);
    ro.observe(document.body);
    post();
    return () => ro.disconnect();
  }, []);

  const SIDO = data.sido;
  const CHILDREN = data.children;
  const series = data.series || null;
  const isSample = data.source === "sample";

  // 기타(custom) 최대 개월 = 수집된 시계열 길이 - 1 (서울 기준)
  const maxMonths = useMemo(() => {
    const v = series && series["서울"] && series["서울"].vals;
    return v ? v.length - 1 : 0;
  }, [series]);
  const hasSeries = maxMonths >= 12; // h·custom 활성 조건

  const pmax = getPmax(period, customM);

  // h(반기)·custom 은 행에 없음 → series 에서 계산해 복제 행 index 6(PIDX.h/custom)에 주입.
  // w/m/q/y 는 배치 계산값 그대로 (원본 행 반환).
  const augment = (rows, parent) => {
    if (!rows || (period !== "h" && period !== "custom")) return rows;
    const months = period === "h" ? 6 : customM;
    return rows.map((n) => {
      const label = parent ? `${parent} ${n[0]}` : n[0];
      const chg = series ? changeFromSeries(series[label]?.vals, months) : null;
      const copy = [...n];
      copy[6] = chg;
      return copy;
    });
  };
  const effSido = useMemo(() => augment(SIDO, null), [SIDO, period, customM, series]);
  const effChildren = useMemo(() => {
    if (!drill || (period !== "h" && period !== "custom")) return CHILDREN;
    return { ...CHILDREN, [drill]: augment(CHILDREN[drill], drill) };
  }, [CHILDREN, drill, period, customM, series]);

  const nodes = drill ? effChildren[drill] : effSido;
  const wide = outerW >= 680;
  const cartW = wide ? 380 : Math.min(outerW, 340);

  const stats = useMemo(() => {
    let up = 0, dn = 0, fl = 0;
    nodes.forEach((n) => {
      const c = n[PIDX[period]];
      if (c == null || Math.abs(c) < pmax * 0.05) fl++; else if (c > 0) up++; else dn++;
    });
    return { up, dn, fl };
  }, [nodes, period, pmax]);

  const selectNode = (n, parent) => {
    setSel({ name: n[0], price: n[2], chgs: { w: n[3], m: n[4], q: n[5], y: n[6] }, count: n[7], parent });
  };

  const pickSido = (n) => {
    if (CHILDREN[n[0]]) { setDrill(n[0]); selectNode(n, null); }
    else selectNode(n, null); // 세종: 하위 없음 → 바로 상세
  };

  const onTile = (n) => {
    if (!drill && CHILDREN[n[0]]) { setDrill(n[0]); selectNode(n, null); }
    else selectNode(n, drill);
  };

  const goHome = () => { setDrill(null); setSel(null); };

  const regionLabel = sel ? (sel.parent ? `${sel.parent} ${sel.name}` : sel.name) : "";

  const btn = (active, disabled) => ({
    padding: "6px 12px", borderRadius: 6, border: "1px solid " + (active ? C.primary : C.ghostBorder),
    background: active ? C.primary : C.page, color: disabled ? C.meta : active ? C.onPrimary : C.ink2,
    fontSize: 12, fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.55 : 1,
  });

  return (
    // 임베드면 minHeight 100vh 미적용 — iframe 높이를 따라 100vh 가 같이 커지는 래칫 방지 (부모 CSS min-height 가 최소 높이 보장)
    <div style={{ minHeight: EMBEDDED ? undefined : "100vh", background: C.page, color: C.ink, fontFamily: C.sans, padding: EMBEDDED ? "4px 0 32px" : "14px 12px 40px" }}>
      <div ref={outerRef} style={{ maxWidth: EMBEDDED ? "none" : 1100, margin: "0 auto" }}>

        {/* 패밀리 공통 nav 바 — 직접 방문 시만. enxight.com/map/ iframe 임베드면 홈 shell 이
            nav 를 제공하므로 숨김 (중복 헤더 = "디자인 오락가락" 피드백 해소) */}
        {!EMBEDDED && (
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", paddingBottom: 10, marginBottom: 12, borderBottom: `1px solid ${C.hair}` }}>
            <a href="https://enxight.com/" style={{ fontFamily: C.mono, fontSize: 13, fontWeight: 700, letterSpacing: ".18em", color: C.ink, textDecoration: "none" }}>
              ENXIGHT
            </a>
            <nav style={{ display: "flex", gap: 14, alignItems: "center", fontSize: 12, fontFamily: C.sans }}>
              <a href="https://enxight.com/magazine/" style={{ color: C.ink2, textDecoration: "none" }}>Magazine</a>
              <a href="https://enxight.com/enxighter/" style={{ color: C.ink2, textDecoration: "none" }}>Game</a>
              <a href="https://enxight.com/enxiview/" style={{ color: C.brass, fontWeight: 700, textDecoration: "none" }}>Charts</a>
              <a href="https://enxight.com/brand/" style={{ color: C.ink2, textDecoration: "none" }}>Brand</a>
            </nav>
          </div>
        )}

        {/* 헤더 — 직접 방문 시만. 임베드면 enxight.com 셸의 'Map' 카테고리가 정체성을
            제공하므로 자체 브랜딩(eyebrow·워드마크) 생략, 본문부터 시작 (2026-06-11) */}
        {!EMBEDDED && (
          <>
            <div style={{ fontFamily: C.mono, fontSize: 11, letterSpacing: ".22em", textTransform: "uppercase", color: C.meta, fontWeight: 500 }}>
              ENXIGHT Lab · <span style={{ color: C.brass }}>Korea Real Estate</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 4 }}>
              {/* 마크 — enxight 오방(五方) 배지, favicon.svg 와 동일 (2026-06-11 패밀리 마크 단일화 — 구 드릴다운 가지 폐기).
                  자체 ground 마크라 테마 토큰 무관 고정색 (SSoT: HOMEPAGE assets/logo/v4/enxight/mark.svg) */}
              <svg width="26" height="26" viewBox="0 0 100 100" aria-hidden="true">
                <defs><clipPath id="enx-mark-clip"><rect x="4" y="4" width="92" height="92" rx="18" /></clipPath></defs>
                <rect width="100" height="100" rx="22" fill="#F9FAFB" />
                <g clipPath="url(#enx-mark-clip)">
                  <g transform="rotate(12 50 50)">
                    <polygon points="50,50 -60,-60 160,-60" fill="#1A1E26" />
                    <polygon points="50,50 160,-60 160,160" fill="#2C4A6E" />
                    <polygon points="50,50 160,160 -60,160" fill="#7E2E2E" />
                    <polygon points="50,50 -60,160 -60,-60" fill="#B5871E" />
                  </g>
                  <g transform="rotate(12 50 50)" stroke="#F9FAFB" strokeWidth="15" strokeLinecap="round">
                    <line x1="0" y1="0" x2="100" y2="100" />
                    <line x1="100" y1="0" x2="0" y2="100" />
                  </g>
                </g>
              </svg>
              <div style={{ fontFamily: C.serif, fontSize: 26, fontWeight: 600, letterSpacing: "-0.01em" }}>
                Enxigh<span style={{ color: GREEN }}>tree</span>
              </div>
              <div style={{ fontSize: 11, color: C.meta }}>
                대한민국 부동산 히트맵 · v0.6
                {data.generated_at && <span> · 데이터 {data.generated_at.slice(0, 10)}</span>}
              </div>
            </div>
          </>
        )}

        {/* 본문: 기간토글+지도(좌) + 트리맵(우) — 레이아웃 v3 */}
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap", marginTop: 12 }}>
          {/* 좌측 패널 — 폭 고정 (기타 입력 등으로 레이아웃이 흔들리지 않게, 6/10 피드백) */}
          <div style={{ flex: "0 0 auto", width: cartW, boxSizing: "border-box", background: C.canvas, borderRadius: 8, padding: 12 }}>
            <KoreaGeoMap sido={effSido} muniData={effChildren} period={period} pmax={pmax} drill={drill} sel={sel}
              onPick={pickSido} onPickMuni={onTile} onBack={goHome} width={cartW - 24} />
            {/* 기간 토글 — 지도 하단. 반기·기타는 series 필요 */}
            <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
              {PERIODS.map(([k, label]) => {
                const disabled = (k === "h") && !hasSeries;
                return (
                  <button key={k} style={btn(period === k, disabled)} disabled={disabled}
                    onClick={() => setPeriod(k)}>{label}</button>
                );
              })}
              <button style={btn(period === "custom", !hasSeries)} disabled={!hasSeries}
                onClick={() => setPeriod("custom")}>기타</button>
            </div>
            {/* 기타 개월 입력 — 토글 아래 별도 행. 자리는 항상 확보(숨김)해 세로 점프도 방지 */}
            <div style={{ marginTop: 6, height: 32, display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: C.ink2, visibility: period === "custom" ? "visible" : "hidden" }}>
              <input type="number" min={1} max={maxMonths} value={customM}
                onChange={(e) => setCustomM(Math.max(1, Math.min(maxMonths, +e.target.value || 1)))}
                style={{ width: 64, background: C.page, color: C.ink, border: `1px solid ${C.primary}`, borderRadius: 6, padding: "5px 6px", fontSize: 12, boxSizing: "border-box" }} />
              개월 <span style={{ fontSize: 10, color: C.meta }}>(최대 {maxMonths}개월 = 약 {Math.floor(maxMonths / 12)}년)</span>
            </div>
            <div style={{ fontSize: 9, color: C.meta, marginTop: 4, maxWidth: cartW - 24 }}>
              시도를 누르면 우측 히트맵이 해당 시군구로 전환됩니다
            </div>
          </div>

          <Treemap nodes={nodes} period={period} pmax={pmax} drill={drill} sel={sel} onTile={onTile} goHome={goHome} stats={stats} />
        </div>

        {/* 상세 패널 */}
        {sel && <DetailPanel sel={sel} regionLabel={regionLabel} trends={data.trends} seriesAll={series}
          isSample={isSample} asof={data.asof} customM={period === "custom" ? customM : null} />}

        {!sel && (
          <div style={{ marginTop: 14, fontSize: 12, color: C.meta, textAlign: "center" }}>
            지도 또는 히트맵의 지역을 누르면 상세 정보와 뉴스가 표시됩니다
          </div>
        )}

        <div style={{ marginTop: 20, fontSize: 10, color: C.meta, lineHeight: 1.6 }}>
          {isSample ? (
            <>※ 현재 가격·변동률은 <b>구조 검증용 샘플 데이터</b>입니다. 2단계 배포 시 국토교통부 아파트 실거래가 API와 한국부동산원 R-ONE 가격지수로 대체되며, 뉴스는 네이버 검색 API로 연동됩니다.</>
          ) : (
            <>※ 출처: 한국부동산원 R-ONE 매매가격지수(월간 기준 {fmtYm(data.asof?.monthly)} · 주간 {fmtWk(data.asof?.weekly)}) ·
              국토교통부 아파트 실거래가 {fmtYm(data.asof?.trade_ym)}{data.asof?.trade_provisional ? " (잠정 — 신고 시차로 익월 말까지 변동 가능)" : ""}.
              해제건·직거래 제외, 중위가는 전용면적 혼합 단순 중위. 변동률은 가격지수 기준(반기·기타 = 월간 지수 환산). 갱신 {data.generated_at} KST.</>
          )}
          <span> · <a href="https://enxight.com/" style={{ color: C.meta }}>ENXIGHT</a> · <a href="https://enxight.com/magazine/" style={{ color: C.meta }}>Magazine</a></span>
        </div>
      </div>
    </div>
  );
}
