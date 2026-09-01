// K-RE MAP Worker — 정적 자산 + /api/news 네이버 뉴스 프록시 (2d, HANDOFF §3-1)
// 키는 Worker 시크릿(NAVER_CLIENT_ID/SECRET)에만 — 클라이언트 노출 금지.
// 응답 계약: [{t:제목, s:언론사(도메인), d:YYYY-MM-DD, u:링크}] — DetailPanel 과 합의된 형식.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/news") return news(url, request, env);
    // 그 외 — 정적 자산 (SPA fallback). enxight.com/map·/pulse iframe 임베드 허용:
    // cf 자동 부여 X-Frame-Options: SAMEORIGIN 제거 + CSP frame-ancestors 로 대체
    // *.enxight.com 포함 — www 등 변형 호스트 임베드 차단(ERR_BLOCKED_BY_RESPONSE) 해소 (2026-06-15)
    const res = await env.ASSETS.fetch(request);
    const h = new Headers(res.headers);
    h.delete("X-Frame-Options");
    h.set("Content-Security-Policy", "frame-ancestors 'self' https://enxight.com https://*.enxight.com");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
  },
};

// 시도 단축명 → 검색 쿼리 보정 (동음이의: "세종"=법무법인, "광주"=경기 광주시 혼동)
// 2026-07 개편: 앱 시도명 "전남광주" → 공식 명칭으로 검색 (舊 "광주" 보정은 이력 호환 보존)
const QUERY_FIX = { 세종: "세종시", 광주: "광주광역시", 전남광주: "전남광주통합특별시" };

async function news(url, request, env) {
  let q = (url.searchParams.get("q") || "").trim();
  if (!q || q.length > 30) return json([], 400);
  q = QUERY_FIX[q] || q;

  // 지역별 10분 캐시 — 네이버 일 25,000건 한도 보호
  const cache = caches.default;
  const cacheKey = new Request(url.toString(), { method: "GET" });
  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  const api = "https://openapi.naver.com/v1/search/news.json?" +
    new URLSearchParams({ query: `${q} 부동산`, display: "4", sort: "sim" });
  const r = await fetch(api, {
    headers: {
      "X-Naver-Client-Id": env.NAVER_CLIENT_ID,
      "X-Naver-Client-Secret": env.NAVER_CLIENT_SECRET,
    },
  });
  if (!r.ok) return json([], 502);

  const d = await r.json();
  const items = (d.items || []).map((it) => ({
    t: strip(it.title),
    s: host(it.originallink || it.link),
    d: ymdKst(it.pubDate),
    u: it.link || it.originallink || "",
  }));

  const res = json(items, 200, { "Cache-Control": "public, max-age=600" });
  await cache.put(cacheKey, res.clone());
  return res;
}

const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });

// 네이버 title 의 <b> 태그·HTML 엔티티 제거
function strip(s) {
  return (s || "")
    .replace(/<[^>]+>/g, "")
    .replace(/&quot;/g, '"').replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&apos;|&#39;/g, "'");
}

function host(u) {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; }
}

// pubDate(RFC 1123, +0900) → KST YYYY-MM-DD
function ymdKst(s) {
  const t = Date.parse(s);
  if (!t) return "";
  return new Date(t + 9 * 3600 * 1000).toISOString().slice(0, 10);
}
