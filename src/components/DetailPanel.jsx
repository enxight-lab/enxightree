import React, { useState, useEffect } from "react";
import TrendChart from "./TrendChart.jsx";
import useWidth from "../lib/useWidth.js";
import { PERIODS, GREEN, RED, C, fmt, getPmax, changeFromSeries } from "../lib/utils.js";

// 뉴스 — CF Worker(/api/news) → 네이버 검색 API (2d ✅). 실패·로컬 dev 시 샘플 fallback.
// Worker 응답 계약: [{t:제목, s:언론사, d:날짜, u:링크}]
const sampleNews = (name) => [
  { t: `${name} 아파트 매매가 흐름 점검 — 거래량·호가 동향`, s: "샘플", d: "프로토타입" },
  { t: `${name} 분양·입주 물량 캘린더 정리`, s: "샘플", d: "프로토타입" },
  { t: `${name} 전세가율 및 수급 지표 체크`, s: "샘플", d: "프로토타입" },
];

function useNews(regionLabel) {
  const [news, setNews] = useState(null); // null = 미수신(샘플 표시) / [] 아님
  useEffect(() => {
    let alive = true;
    setNews(null);
    fetch(`/api/news?q=${encodeURIComponent(regionLabel)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive && Array.isArray(d) && d.length) setNews(d); })
      .catch(() => {}); // 샘플 fallback 유지
    return () => { alive = false; };
  }, [regionLabel]);
  return news;
}

export default function DetailPanel({ sel, regionLabel, trends, seriesAll, isSample, asof, customM }) {
  const [ref, w] = useWidth(560);
  const news = useNews(regionLabel);
  const series = trends ? trends[regionLabel] : null;
  // 반기(h)·기타는 행에 없음 — 월간 지수 시계열에서 계산 (없으면 카드에 — 표시)
  const regionSeries = seriesAll ? seriesAll[regionLabel] : null;
  const chgOf = (k) => (k === "h" ? changeFromSeries(regionSeries?.vals, 6) : sel.chgs[k]);
  // 기타 기간 선택 중이면 카드 1장 동적 추가 (히트맵과 같은 기준으로 비교 가능)
  const cards = customM
    ? [...PERIODS, ["custom", `기타 ${customM}개월`]]
    : PERIODS;
  const chgOfCard = (k) => (k === "custom" ? changeFromSeries(regionSeries?.vals, customM) : chgOf(k));
  // 대표가 표시 규칙 (DATA_QUALITY_CHECKLIST A-1/A-2): 중위가 + 건수 세트, 소표본은 비표시, 잠정 고지
  const provisional = !isSample && asof?.trade_provisional;
  const priceLine = isSample ? (
    <>아파트 평균 매매가 <span style={{ color: C.ink, fontWeight: 700 }}>{sel.price}억원</span> <span style={{ fontSize: 10 }}>(샘플)</span></>
  ) : sel.price != null ? (
    <>아파트 중위 매매가 <span style={{ color: C.ink, fontWeight: 700 }}>{sel.price}억원</span>
      <span style={{ fontSize: 10 }}> · {sel.count}건{provisional ? " · 잠정" : ""}</span></>
  ) : (
    <>아파트 중위 매매가 <span style={{ color: C.ink2 }}>표본 부족</span>
      <span style={{ fontSize: 10 }}> · {sel.count ?? 0}건 (월 5건 미만)</span></>
  );
  // 레이아웃 v2 (사용자 화면 피드백): 좌 = 기간 카드(위) + 추이 그래프(아래) 상하 배치 · 우 = 뉴스
  const twoCol = w >= 680;
  return (
    <div ref={ref} style={{ marginTop: 16, background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 10, padding: 14 }}>
      <div>
        <div style={{ fontSize: 18, fontWeight: 800 }}>{regionLabel}</div>
        <div style={{ fontSize: 12, color: C.ink2, marginTop: 2 }}>{priceLine}</div>
      </div>

      <div style={{ display: "flex", gap: 18, alignItems: "flex-start", flexWrap: "wrap", marginTop: 12 }}>
        {/* 좌: 기간별 변동률 + 추이 (상하) */}
        <div style={{ flex: "1 1 340px", minWidth: 0 }}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {cards.map(([k, label]) => {
              const c = chgOfCard(k);
              if (c == null && (k === "h" || k === "custom")) return null; // series 없는 모드(샘플) — 생략
              const pm = getPmax(k === "custom" ? "custom" : k, customM);
              const col = c == null || Math.abs(c) < pm * 0.05 ? C.ink2 : c > 0 ? GREEN : RED;
              const active = k === "custom";
              return (
                <div key={k} style={{ background: C.page, borderRadius: 8, padding: "6px 12px", textAlign: "center", border: active ? `1px solid ${C.primary}` : `1px solid ${C.hair}` }}>
                  <div style={{ fontSize: 9, color: C.meta }}>{label}</div>
                  <div style={{ fontFamily: C.mono, fontSize: 13, fontWeight: 500, color: col }}>{c == null ? "—" : fmt(c)}</div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 12 }}>
            <TrendChart name={regionLabel} yChg={sel.chgs.y} width={twoCol ? Math.min(w * 0.52, 520) : Math.min(w, 520)} series={series} endYm={asof?.monthly} />
          </div>
        </div>

        {/* 우: 뉴스 — 네이버 검색 (Worker 프록시) · 실패 시 샘플 */}
        <div style={{ flex: "1 1 280px", minWidth: 0, borderLeft: twoCol ? `1px solid ${C.hair}` : "none", paddingLeft: twoCol ? 18 : 0, borderTop: twoCol ? "none" : `1px solid ${C.hair}`, paddingTop: twoCol ? 0 : 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>📰 {regionLabel} 부동산 뉴스</div>
          {(news ?? sampleNews(regionLabel)).map((a, i) => (
            <div key={i} style={{ padding: "8px 0", borderBottom: `1px solid ${C.hairSoft}` }}>
              <div style={{ fontSize: 13, lineHeight: 1.4 }}>
                {a.u ? (
                  <a href={a.u} target="_blank" rel="noopener noreferrer" style={{ color: C.ink, textDecoration: "none" }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = C.primaryHover)}
                    onMouseLeave={(e) => (e.currentTarget.style.color = C.ink)}>{a.t} ↗</a>
                ) : a.t}
              </div>
              <div style={{ fontSize: 10, color: C.meta, marginTop: 2 }}>{a.s}{a.d ? ` · ${a.d}` : ""}</div>
            </div>
          ))}
          <div style={{ fontSize: 10, color: C.meta, marginTop: 6 }}>
            {news
              ? "출처: 네이버 뉴스 검색 — 기사 제목·링크만 표시하며 본문은 각 언론사 페이지에서. 매물 호가와 실거래가는 다릅니다."
              : "※ 위 목록은 자리표시용 샘플입니다 (뉴스 서버 미연결 또는 로컬 미리보기)."}
          </div>
        </div>
      </div>
    </div>
  );
}
