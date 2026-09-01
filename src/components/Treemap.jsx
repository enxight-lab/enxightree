import React, { useMemo } from "react";
import { hierarchy, treemap } from "d3-hierarchy";
import useWidth from "../lib/useWidth.js";
import { PIDX, GREEN, RED, GRAY, C, colorFor, fmt } from "../lib/utils.js";

// 핀비즈식 트리맵 (우측 패널) — 타일 크기 = 시장 규모(√ 스케일), 색상 = 변동률
// 하단 라인 (레이아웃 v3): [컨텍스트 · 타일 크기 표기] → [범례] → [▲―▼ 통계] 순
export default function Treemap({ nodes, period, pmax, drill, sel, onTile, goHome, stats }) {
  const [mapRef, mapW] = useWidth();
  const mapH = Math.max(380, Math.min(560, mapW * 0.85));

  const leaves = useMemo(() => {
    // √스케일: 실데이터 거래대금 격차(서울 vs 세종 40:1)로 극소 타일(4px) 발생 방지.
    const root = hierarchy({ children: nodes.map((n) => ({ d: n })) }).sum((x) => (x.d ? Math.sqrt(x.d[1]) : 0));
    treemap().size([mapW, mapH]).paddingInner(2).round(true)(root);
    return root.leaves();
  }, [nodes, mapW, mapH]);

  return (
    <div style={{ flex: "1 1 340px", minWidth: 0 }}>
      {/* 브레드크럼 제거 (2026-06-11 피드백) — 전국/지역 이동은 좌측 지도가 담당,
          현재 컨텍스트는 하단 줄({drill || 전국})에 표기. 좌우 상자 상단 레벨 일치 */}
      <div ref={mapRef} style={{ position: "relative", width: "100%", height: mapH, background: C.canvas, borderRadius: 8, overflow: "hidden" }}>
        {leaves.map((l, i) => {
          const n = l.data.d;
          const chg = n[PIDX[period]];
          const w = l.x1 - l.x0, h = l.y1 - l.y0;
          const nameSize = Math.max(9, Math.min(w / (n[0].length * 1.05), h / 3.2, 17));
          const showPct = w > 44 && h > 34;
          const isSel = sel && sel.name === n[0] && ((drill && sel.parent === drill) || (!drill && !sel.parent));
          return (
            <div key={n[0] + i} onClick={() => onTile(n)}
              style={{
                position: "absolute", left: l.x0, top: l.y0, width: w, height: h,
                background: colorFor(chg, pmax),
                display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                cursor: "pointer", overflow: "hidden", borderRadius: 2,
                outline: isSel ? `2px solid ${C.brass}` : "1px solid rgba(0,0,0,0.35)",
                outlineOffset: -2, transition: "filter .12s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.filter = "brightness(1.18)")}
              onMouseLeave={(e) => (e.currentTarget.style.filter = "none")}
            >
              <div style={{ fontSize: nameSize, fontWeight: 800, color: "#fff", textShadow: "0 1px 2px rgba(0,0,0,.45)", lineHeight: 1.1, whiteSpace: "nowrap" }}>{n[0]}</div>
              {showPct && <div style={{ fontFamily: C.mono, fontSize: Math.max(8, nameSize * 0.72), color: "rgba(255,255,255,.92)", fontWeight: 500 }}>{chg == null ? "—" : fmt(chg)}</div>}
            </div>
          );
        })}
      </div>

      {/* 하단: 컨텍스트·타일 표기 → 범례 → 등락 통계 (v3 순서) */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8, fontSize: 10, color: C.meta, flexWrap: "wrap" }}>
        <span style={{ whiteSpace: "nowrap" }}>{drill || "전국"} · 타일 크기 = 시장 규모(√ 스케일)</span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flex: "1 1 180px", minWidth: 140 }}>
          <span style={{ fontFamily: C.mono, color: RED, whiteSpace: "nowrap" }}>-{pmax}%</span>
          <span style={{ flex: 1, maxWidth: 240, height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${RED}, ${GRAY}, ${GREEN})` }} />
          <span style={{ fontFamily: C.mono, color: GREEN, whiteSpace: "nowrap" }}>+{pmax}%</span>
        </span>
        {stats && (
          <span style={{ fontFamily: C.mono, fontSize: 12, color: C.ink2, whiteSpace: "nowrap" }}>
            <span style={{ color: GREEN }}>▲ {stats.up}</span>{" · "}
            <span style={{ color: C.ink2 }}>― {stats.fl}</span>{" · "}
            <span style={{ color: RED }}>▼ {stats.dn}</span>
          </span>
        )}
      </div>
    </div>
  );
}
