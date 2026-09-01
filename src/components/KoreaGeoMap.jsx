import React, { useState, useEffect, useMemo } from "react";
import { geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import { sidoOfFeature, resolveMuniName } from "../data/geo.js";
import { PIDX, GREEN, RED, C, colorFor, fmt } from "../lib/utils.js";

// 실제 행정구역 경계 코로플레스 (PATCH v1.1 §변경1 — 구 KoreaPixelMap 대체)
// 전국 뷰 = 시도 16 / 드릴 뷰 = 해당 시도 fitSize 줌인 + 시군구 색칠.
// 앱 데이터 없는 시군구는 어두운 회색 + 클릭 무시.
// 2026-07 개편: 2018 topo 의 광주·전남 폴리곤 2개가 앱 시도 "전남광주" 하나로 조인
// (geo.js KOSTAT_SIDO) — 색·클릭·드릴은 한 지역, 라벨만 이름 기준 중복 제거.

// 전국 뷰 라벨 위치 보정 (W,H 비율) — centroid 가 이웃 시도와 겹치는 곳만.
// 경기: centroid 가 서울을 둘러싸 서울 라벨과 충돌 → 동남쪽으로.
// 세종·대전: 인접 소형 영역 — 측정 기반 미세 조정 (검증 eval 로 충돌 0 확인).
const LABEL_NUDGE = {
  경기: [0.045, 0.028], // 사용자 피드백(6/10): 동남쪽 과이동 → 좌상향 복귀, 서울과 충돌만 회피
  세종: [-0.005, -0.035],
  대전: [0.01, 0.03],
};

let topoCache = null; // 모듈 레벨 1회 로드 (provinces + municipalities)

function useTopo() {
  const [topo, setTopo] = useState(topoCache);
  useEffect(() => {
    if (topoCache) return;
    let alive = true;
    Promise.all([
      fetch("/geo/provinces.topo.json").then((r) => r.json()),
      fetch("/geo/municipalities.topo.json").then((r) => r.json()),
    ]).then(([prov, muni]) => {
      const provFc = feature(prov, prov.objects[Object.keys(prov.objects)[0]]);
      const muniFc = feature(muni, muni.objects[Object.keys(muni.objects)[0]]);
      topoCache = { prov: provFc.features, muni: muniFc.features };
      if (alive) setTopo(topoCache);
    }).catch((e) => console.warn("[geo] 경계 로드 실패:", e));
    return () => { alive = false; };
  }, []);
  return topo;
}

export default function KoreaGeoMap({ sido, muniData, period, pmax, drill, sel, onPick, onPickMuni, onBack, width }) {
  const topo = useTopo();
  const [hov, setHov] = useState(null); // { name, chg } | null
  const W = Math.max(240, width), H = Math.round(W * 1.25);

  const bySido = useMemo(() => Object.fromEntries(sido.map((n) => [n[0], n])), [sido]);

  // 현재 뷰의 feature + 데이터 노드 결합
  const view = useMemo(() => {
    if (!topo) return null;
    if (!drill) {
      const feats = topo.prov.map((f) => {
        const name = sidoOfFeature(f);
        return { f, name, node: bySido[name] ?? null };
      });
      return { feats, fitTo: { type: "FeatureCollection", features: topo.prov } };
    }
    // sidoOfFeature 기준 필터 — 코드 prefix 가 아닌 현행 소속 (군위군 대구 편입 등 SIDO_OVERRIDE 반영)
    const feats = topo.muni
      .filter((f) => sidoOfFeature(f) === drill)
      .map((f) => {
        const appNames = (muniData[drill] ?? []).map((c) => c[0]);
        const name = resolveMuniName(f, appNames);
        const node = name ? (muniData[drill] ?? []).find((c) => c[0] === name) : null;
        return { f, name: name ?? f.properties.name, node };
      });
    return { feats, fitTo: { type: "FeatureCollection", features: feats.map((x) => x.f) } };
  }, [topo, drill, bySido, muniData]);

  const path = useMemo(() => {
    if (!view) return null;
    const proj = geoMercator().fitExtent([[4, 4], [W - 4, H - 4]], view.fitTo);
    return geoPath(proj);
  }, [view, W, H]);

  // 전국 뷰 라벨: 같은 앱 시도명으로 조인된 폴리곤이 여럿이면(전남광주 = 舊광주+舊전남)
  // 가장 넓은 폴리곤에만 라벨 — 중복·겹침 방지.
  const labelFeats = useMemo(() => {
    if (!view || !path) return [];
    const best = new Map();
    for (const x of view.feats) {
      const area = Math.abs(path.area(x.f));
      const cur = best.get(x.name);
      if (!cur || area > cur.area) best.set(x.name, { ...x, area });
    }
    return [...best.values()];
  }, [view, path]);

  const infoName = hov?.name || drill || (sel && !sel.parent ? sel.name : null);
  const infoChg = hov ? hov.chg : infoName && bySido[infoName] ? bySido[infoName][PIDX[period]] : null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.ink2 }}>
          {drill ? drill : "전국"} 지도 <span style={{ fontWeight: 400, fontSize: 10 }}>(통계청 행정구역 경계)</span>
        </div>
        {drill && (
          <button onClick={onBack} style={{
            cursor: "pointer", color: C.onPrimary, background: C.primary, border: `1px solid ${C.primary}`,
            borderRadius: 6, padding: "4px 10px", fontSize: 11, fontWeight: 700,
          }}>↩ 전국</button>
        )}
      </div>

      {!view || !path ? (
        <div style={{ width: W, height: H, display: "flex", alignItems: "center", justifyContent: "center", color: C.meta, fontSize: 11 }}>
          지도 로딩 중…
        </div>
      ) : (
        <svg width={W} height={H} style={{ display: "block" }}>
          {view.feats.map(({ f, name, node }, i) => {
            const chg = node ? node[PIDX[period]] : null;
            const fill = colorFor(chg, pmax); // chg=null(미보유·기간 데이터 부족) → NODATA 무채색
            const isSel = sel && (drill ? sel.parent === drill && sel.name === name : !sel.parent && sel.name === name);
            const isHov = hov && hov.key === f.properties.code;
            return (
              <path key={f.properties.code + i}
                d={path(f)}
                fill={fill}
                stroke={isSel ? C.brass : C.page}
                strokeWidth={isSel ? 1.6 : 0.6}
                style={{ cursor: node ? "pointer" : "default", filter: isHov ? "brightness(1.3)" : "none", transition: "fill .15s" }}
                onClick={() => {
                  if (!node) return;
                  if (drill) onPickMuni(node); else onPick(node);
                }}
                onMouseEnter={() => setHov({ key: f.properties.code, name, chg })}
                onMouseLeave={() => setHov(null)}
              >
                <title>{name}{chg != null ? ` ${fmt(chg)}` : " (데이터 준비 중)"}</title>
              </path>
            );
          })}
          {/* 전국 뷰 시도 라벨 (드릴 뷰는 hover 인포로) */}
          {!drill && labelFeats.map(({ f, name }) => {
            let [cx, cy] = path.centroid(f);
            if (!isFinite(cx)) return null;
            const nudge = LABEL_NUDGE[name];
            if (nudge) { cx += nudge[0] * W; cy += nudge[1] * H; }
            return (
              <text key={"t" + f.properties.code} x={cx} y={cy}
                textAnchor="middle" dominantBaseline="middle" pointerEvents="none"
                style={{ fontSize: 10.5, fontWeight: 800, fill: "#fff", paintOrder: "stroke", stroke: "rgba(0,0,0,.75)", strokeWidth: 2.5 }}>
                {name}
              </text>
            );
          })}
        </svg>
      )}

      {/* 인포 스트립 */}
      <div style={{
        marginTop: 8, padding: "6px 10px", background: C.panel, borderRadius: 6,
        fontSize: 12, minHeight: 18, display: "flex", justifyContent: "space-between", maxWidth: W - 20,
      }}>
        {infoName ? (
          <>
            <span style={{ fontWeight: 700 }}>{drill && hov ? `${drill} ${infoName}` : infoName}</span>
            {infoChg != null ? (
              <span style={{ fontFamily: C.mono, fontWeight: 500, color: Math.abs(infoChg) < pmax * 0.05 ? C.ink2 : infoChg > 0 ? GREEN : RED }}>
                {fmt(infoChg)}
              </span>
            ) : (
              <span style={{ color: C.meta, fontSize: 11 }}>데이터 준비 중</span>
            )}
          </>
        ) : (
          <span style={{ color: C.meta, fontSize: 11 }}>지역에 마우스를 올리거나 탭하세요</span>
        )}
      </div>
    </div>
  );
}
