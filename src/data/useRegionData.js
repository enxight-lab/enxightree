import { useState, useEffect } from "react";
import sample from "./sample.json";

// 데이터 레이어 — /data.json(배치 산출물) 우선, 실패 시 번들 샘플 fallback.
// data.json 스키마: { schema_version, generated_at, source, sido, children, trends? }
// trends?: { "지역라벨": [12개 월별 지수] } — 있으면 의사난수 차트 대신 사용 (HANDOFF §3-2)
const FALLBACK = {
  schema_version: "sample",
  generated_at: null,
  source: "sample",
  sido: sample.sido,
  children: sample.children,
  trends: null,
};

export default function useRegionData() {
  const [data, setData] = useState(FALLBACK);
  useEffect(() => {
    let alive = true;
    fetch("/data.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (alive && d && Array.isArray(d.sido) && d.children) setData(d);
      })
      .catch(() => {}); // 샘플 fallback 유지
    return () => { alive = false; };
  }, []);
  return data;
}
