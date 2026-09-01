import React, { useMemo } from "react";
import { GREEN, RED, C, trendSeries, monthLabels } from "../lib/utils.js";

// 12개월 추이 차트 — series(실데이터) 있으면 사용, 없으면 의사난수 fallback
// endYm = 지수 기준월("202604") — 라벨이 데이터 끝 월과 일치하도록 (검증 v1에서 불일치 발견·수정)
export default function TrendChart({ name, yChg, width, series, endYm }) {
  const pts = useMemo(() => (series && series.length === 12 ? series : trendSeries(name, yChg)), [name, yChg, series]);
  const labels = useMemo(() => monthLabels(endYm), [endYm]);
  const isSample = !(series && series.length === 12);
  const W = Math.max(280, width - 28), H = 120, pad = 6;
  const min = Math.min(...pts), max = Math.max(...pts), rng = max - min || 1;
  const x = (i) => pad + (i / 11) * (W - pad * 2);
  const y = (v) => H - pad - ((v - min) / rng) * (H - pad * 2);
  const line = pts.map((p, i) => `${x(i)},${y(p)}`).join(" ");
  const up = pts[11] >= pts[0];
  const col = up ? GREEN : RED;
  return (
    <div>
      <svg width={W} height={H + 16} style={{ display: "block" }}>
        <polygon points={`${x(0)},${H - pad} ${line.split(" ").join(" ")} ${x(11)},${H - pad}`} fill={col} opacity="0.12" />
        <polyline points={line} fill="none" stroke={col} strokeWidth="2" />
        {pts.map((p, i) => <circle key={i} cx={x(i)} cy={y(p)} r="2" fill={col} />)}
        <text x={x(0)} y={H + 13} fill={C.meta} fontSize="9" fontFamily={C.mono}>{labels[0]}</text>
        <text x={x(11)} y={H + 13} fill={C.meta} fontSize="9" fontFamily={C.mono} textAnchor="end">{labels[11]}</text>
      </svg>
      <div style={{ fontSize: 10, color: C.meta }}>최근 12개월 가격지수 추이 ({isSample ? "샘플" : "R-ONE 지수"} · 지수 100 = 현재)</div>
    </div>
  );
}
