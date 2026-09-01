import { useState, useRef, useEffect } from "react";

// ResizeObserver 기반 컨테이너 폭 추적 (반응형 680px 분기점에 사용)
// 초기 1회는 직접 측정 — RO 초기 콜백이 누락되는 환경(일부 내장 브라우저) 보강
export default function useWidth(initial = 360) {
  const ref = useRef(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    if (!ref.current) return;
    const measure = () => { if (ref.current) setW(ref.current.getBoundingClientRect().width); };
    measure();
    const ro = new ResizeObserver((e) => setW(e[0].contentRect.width));
    ro.observe(ref.current);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, []);
  return [ref, w];
}
