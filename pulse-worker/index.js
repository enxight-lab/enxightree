/**
 * ENXIGHT 마켓 펄스 — Cloudflare Worker
 * 라우트: data.enxight.com/*
 * 필요 바인딩: KV namespace "PULSE_KV", Secret "PULSE_TOKEN"
 *
 * POST /pulse              ← 집계기가 JSON 푸시 (Bearer 토큰 — GitHub Actions build_pulse.py)
 * GET  /pulse.json         ← 최신 데이터 (프론트가 fetch)
 * GET  /pulse/YYYY-MM-DD.json ← 이력 조회 (온도차 베이스라인용)
 * GET  /eod-spark.json     ← 홈 전일종가 보드 스파크라인용 1년 주봉 (Yahoo 프록시 + KV 6h 캐시)
 * ※ 금리(FRED)는 Worker IP 가 520 차단 — Actions 집계기가 수집해 pulse 페이로드(rates)로 동봉
 */

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

// ── 외부 heartbeat (2026-09-02 신설) ───────────────────────────────────────
// 왜 여기인가: 감시자 4종(routine-health·freshness-check·OPS collect·secret-audit)이
//   전부 GitHub Actions 에 얹혀 있었다. 8/31 Actions 가 과금으로 전면 차단되자
//   **데이터도 죽고 알림도 같이 죽어** pulse 결번을 9/2 에야 발견했다.
//   이 Worker 는 Cloudflare 인프라라 GitHub 쿼터·결제와 무관하다 — 그날에도 살아 있었다.
// 설계 원칙:
//   ① 정상일 땐 침묵한다. routine_health 가 이미 매일 다이제스트를 보내므로
//      여기서 또 보내면 「경보가 정상 알림에 묻히는」 기존 문제를 되풀이한다.
//   ② 대신 매 실행 결과를 KV `heartbeat:last` 에 남긴다. Actions 쪽 감시가
//      이 값의 신선도를 보면 **서로가 서로를 감시**하는 구조가 된다.
//   ③ 실패해도 절대 throw 하지 않는다 — heartbeat 가 죽어서 알림이 끊기면 본말전도다.

// ⚠️펄스는 **KV 를 직접 읽는다.** 이 Worker 가 자기 도메인(data.enxight.com)을
//   fetch 하면 루프가 되어 522 가 난다(2026-09-02 실측 — 첫 실행에서 바로 걸렸다).
//   외부 도메인만 HTTP 로 본다.
const HB_TARGETS = [
  // [이름, URL, 시각필드, 허용시간(h)]
  // 허용치는 「일 1회 갱신 + GHA 지연 2h + 1회 실패까지」를 기준으로 잡았다.
  ['부동산', 'https://map.enxight.com/data.json', 'generated_at', 40],
];

async function hbCheckPulseKV(env) {
  const raw = await env.PULSE_KV.get('pulse:latest');
  if (!raw) return { name: '펄스', ok: false, detail: 'KV pulse:latest 없음' };
  const age = hbAgeHours(JSON.parse(raw).updated);
  return {
    name: '펄스', ok: age !== null && age < 30,
    detail: age === null ? 'updated 파싱 실패' : `${age.toFixed(1)}h / 30h`,
  };
}

function hbAgeHours(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 3600000;
}

async function hbCheckLatestIssue() {
  // 매거진 발행이 멎었는지 — archive.json 의 최신 **정식** 호(백필 제외) 나이를 본다.
  const r = await fetch('https://enxight.com/data/archive.json', {
    headers: { 'User-Agent': 'enxight-heartbeat' },
  });
  if (!r.ok) return { name: '발행', ok: false, detail: `archive.json HTTP ${r.status}` };
  const issues = (await r.json()).issues || [];
  const real = issues.filter((e) => !e.backfill && e.issue_id).map((e) => e.issue_id).sort();
  const last = real[real.length - 1];
  if (!last) return { name: '발행', ok: false, detail: '정식 호가 하나도 없음' };
  // issue_id 는 YYYY-MM-DD 또는 YYYY-MM-DD-monthly/-weekly
  const age = hbAgeHours(last.slice(0, 10) + 'T00:00:00+09:00');
  // 주말·공휴일 결장이 정상이므로 관용치를 크게 잡는다(4일).
  return { name: '발행', ok: age !== null && age < 96, detail: `최신 ${last} (${age === null ? '?' : age.toFixed(0)}h)` };
}

async function hbRun(env) {
  const results = [];
  for (const [name, url, key, maxH] of HB_TARGETS) {
    try {
      const r = await fetch(url, { headers: { 'User-Agent': 'enxight-heartbeat' } });
      if (!r.ok) { results.push({ name, ok: false, detail: `HTTP ${r.status}` }); continue; }
      const age = hbAgeHours((await r.json())[key]);
      results.push({
        name, ok: age !== null && age < maxH,
        detail: age === null ? `${key} 파싱 실패` : `${age.toFixed(1)}h / ${maxH}h`,
      });
    } catch (e) {
      results.push({ name, ok: false, detail: `${e.name}: ${String(e.message).slice(0, 60)}` });
    }
  }
  try {
    results.push(await hbCheckPulseKV(env));
  } catch (e) {
    results.push({ name: '펄스', ok: false, detail: `${e.name}` });
  }
  try {
    results.push(await hbCheckLatestIssue());
  } catch (e) {
    results.push({ name: '발행', ok: false, detail: `${e.name}` });
  }
  return results;
}

async function hbNotify(env, bad) {
  const token = env.TELEGRAM_BOT_TOKEN;
  const chat = env.TELEGRAM_CHAT_ID;
  if (!token || !chat) return 'secret 미설정';
  const lines = bad.map((b) => `· ${b.name}: ${b.detail}`).join('\n');
  const text =
    '🔴 ENXIGHT heartbeat (Cloudflare)\n' +
    'GitHub Actions 밖에서 도는 감시다. Actions 가 죽어도 이건 운다.\n\n' +
    lines +
    '\n\n확인: https://data.enxight.com/heartbeat.json';
  const r = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chat, text, disable_web_page_preview: true }),
  });
  return r.ok ? 'sent' : `telegram HTTP ${r.status}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    // ── 수신: Apps Script → KV 저장 ──
    if (request.method === 'POST' && url.pathname === '/pulse') {
      const auth = request.headers.get('Authorization') || '';
      if (auth !== `Bearer ${env.PULSE_TOKEN}`) {
        return json({ error: 'unauthorized' }, 401);
      }
      let body;
      try {
        body = await request.json();
      } catch {
        return json({ error: 'invalid json' }, 400);
      }
      if (!body.updated || !body.price || !body.news) {
        return json({ error: 'missing required fields (updated/price/news)' }, 400);
      }
      const dateKey = body.updated.slice(0, 10); // YYYY-MM-DD
      const payload = JSON.stringify(body);
      await env.PULSE_KV.put('pulse:latest', payload);
      await env.PULSE_KV.put(`pulse:${dateKey}`, payload); // 이력 보존
      return json({ ok: true, stored: dateKey }, 200);
    }

    // ── 홈 전일종가 보드 — 90일 일봉 스파크 (2026-06-11, 사용자 피드백) ──
    if (request.method === 'GET' && url.pathname === '/eod-spark.json') {
      return eodSpark(env);
    }

    // ── GDELT 뉴스 밀도 프록시 (2026-07-06) — GitHub 러너 IP 스로틀 회피 ──
    if (request.method === 'GET' && url.pathname === '/gdelt') {
      return gdelt(url, request, env);
    }

    // ── 서빙: 최신 ──
    if (request.method === 'GET' && url.pathname === '/pulse.json') {
      const data = await env.PULSE_KV.get('pulse:latest');
      if (!data) return json({ error: 'no data yet' }, 404);
      return new Response(data, {
        headers: {
          ...CORS,
          'Content-Type': 'application/json; charset=utf-8',
          'Cache-Control': 'public, max-age=900', // 15분 엣지 캐시
        },
      });
    }

    // ── 서빙: 날짜별 이력 ──
    const hist = url.pathname.match(/^\/pulse\/(\d{4}-\d{2}-\d{2})\.json$/);
    if (request.method === 'GET' && hist) {
      const data = await env.PULSE_KV.get(`pulse:${hist[1]}`);
      if (!data) return json({ error: 'not found' }, 404);
      return new Response(data, {
        headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8',
                   'Cache-Control': 'public, max-age=86400' },
      });
    }

    // 상호 감시용 — Actions 쪽 감시가 이 값의 신선도를 보면 서로를 감시하게 된다.
    if (request.method === 'GET' && url.pathname === '/heartbeat.json') {
      const raw = await env.PULSE_KV.get('heartbeat:last');
      if (!raw) return json({ error: 'no heartbeat yet' }, 404);
      return new Response(raw, {
        headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8',
                   'Cache-Control': 'public, max-age=60' },
      });
    }

    return json({ error: 'not found' }, 404);
  },

  // Cron Trigger — wrangler.toml 의 [triggers] crons 참조.
  // ⚠️절대 throw 하지 않는다. heartbeat 가 죽어 알림이 끊기면 본말전도다.
  async scheduled(event, env, ctx) {
    ctx.waitUntil((async () => {
      let results = [];
      let notify = 'skipped';
      try {
        results = await hbRun(env);
        const bad = results.filter((r) => !r.ok);
        if (bad.length) notify = await hbNotify(env, bad);
        else notify = 'ok(무음)';
      } catch (e) {
        results = [{ name: 'heartbeat', ok: false, detail: `${e.name}: ${e.message}` }];
        try { notify = await hbNotify(env, results); } catch (_) { notify = 'notify 실패'; }
      }
      const payload = {
        checked_at: new Date().toISOString(),
        cron: event.cron,
        ok: results.every((r) => r.ok),
        notify,
        results,
      };
      try { await env.PULSE_KV.put('heartbeat:last', JSON.stringify(payload)); } catch (_) {}
    })());
  },
};

function json(obj, status, extra) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8', ...(extra || {}) },
  });
}

// ── 90일 일봉 스파크 (홈 eod-board) ──
// Yahoo v8 차트 프록시 — 클라이언트는 CORS 로 직접 못 부르므로 Worker 가 대행.
// KV 6시간 캐시 (eodspark:latest) — Yahoo 부하·차단 방지. 실패 심볼은 null (프론트 폴백).
const SPARK_SYMS = [
  ['S&P 500', '^GSPC'],
  ['NASDAQ', '^IXIC'],
  ['KOSPI', '^KS11'],
  ['USD/KRW', 'KRW=X'],
  ['Gold', 'GC=F'],
  // Fed Rate 는 Yahoo 미제공 — fetchFedRate() 가 FRED 공개 CSV(무키)로 별도 수집
];

// Fed 목표금리 상단(DFEDTARU) 3년 — FOMC 결정이 그대로 계단으로 보임 (2026-06-11 사용자 요청).
// fredgraph.csv 는 API 키 불필요. 일별 → 주별 샘플링(매 7번째) + 마지막 값 보존.
async function fetchFedRate() {
  const start = new Date(Date.now() - 3 * 365 * 86400 * 1000).toISOString().slice(0, 10);
  const r = await fetch(
    'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU&cosd=' + start,
    { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) enxight-eod' } }
  );
  if (!r.ok) throw new Error('fred http ' + r.status);
  const lines = (await r.text()).trim().split('\n').slice(1); // 헤더 제거
  const daily = [];
  for (const line of lines) {
    const v = parseFloat(line.split(',')[1]);
    if (!isNaN(v)) daily.push(v);
  }
  if (daily.length < 10) throw new Error('fred too few rows');
  const weekly = daily.filter((_, i) => i % 7 === 0);
  if (weekly[weekly.length - 1] !== daily[daily.length - 1]) weekly.push(daily[daily.length - 1]);
  return weekly;
}

async function eodSpark(env) {
  const now = Date.now();
  const cached = await env.PULSE_KV.get('eodspark:latest', 'json');
  if (cached && now - cached.ts < 6 * 3600 * 1000) {
    return json(cached.data, 200, { 'Cache-Control': 'public, max-age=3600' });
  }
  const series = {};
  for (const [label, sym] of SPARK_SYMS) {
    try {
      const r = await fetch(
        'https://query1.finance.yahoo.com/v8/finance/chart/' +
          encodeURIComponent(sym) + '?range=1y&interval=1wk',
        { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) enxight-eod' } }
      );
      if (!r.ok) throw new Error('http ' + r.status);
      const res = (await r.json()).chart.result[0];
      const closes = res.indicators.quote[0].close || [];
      const vals = closes.map((c) => (c == null ? null : Math.round(c * 100) / 100));
      series[label] = vals.some((v) => v != null) ? vals : null;
    } catch (e) {
      series[label] = null; // 프론트가 git 이력 폴백
    }
  }
  // Fed 3년: ① pulse:latest 페이로드(rates.fed3y — Actions 가 FRED 수집, Worker IP 는 520 차단)
  // ② FRED 직접(통과 시) ③ 직전 캐시 ④ null(프론트 git 폴백)
  try {
    const pulse = await env.PULSE_KV.get('pulse:latest', 'json');
    series['Fed Rate'] = (pulse && pulse.rates && pulse.rates.fed3y && pulse.rates.fed3y.length > 10)
      ? pulse.rates.fed3y : await fetchFedRate();
  } catch (e) {
    series['Fed Rate'] = (cached && cached.data && cached.data.series && cached.data.series['Fed Rate']) || null;
  }
  const data = { updated: new Date(now).toISOString(), range: '1y', interval: '1wk', series };
  if (Object.values(series).some((v) => v && v.length)) {
    await env.PULSE_KV.put('eodspark:latest', JSON.stringify({ ts: now, data }));
  } else if (cached) {
    return json(cached.data, 200, { 'Cache-Control': 'public, max-age=600' }); // 전멸 시 stale 서빙
  }
  return json(data, 200, { 'Cache-Control': 'public, max-age=3600' });
}

// ── GDELT 뉴스 밀도 프록시 (2026-07-06) ──
// build_pulse.py 가 GitHub 러너에서 직접 호출하면 GDELT 가 공유 IP 를 스로틀(며칠째 0/35).
// CF Worker IP 경유로 우회. Bearer PULSE_TOKEN 인증(오픈 프록시 방지) + 10분 엣지 캐시.
// GDELT 파라미터(mode/maxrecords/timespan/sort)는 여기서 고정 — caller 는 query 만 전달.
async function gdelt(url, request, env) {
  const auth = request.headers.get('Authorization') || '';
  if (auth !== `Bearer ${env.PULSE_TOKEN}`) return json({ error: 'unauthorized' }, 401);
  const query = (url.searchParams.get('query') || '').trim();
  if (!query || query.length > 300) return json({ error: 'bad query' }, 400);

  // 쿼리별 10분 엣지 캐시 — 재시도·재실행 시 GDELT 부하 완화
  const cache = caches.default;
  const cacheKey = new Request(url.toString(), { method: 'GET' });
  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  // mode/timespan 화이트리스트 — artlist(뉴스 밀도 1d) + timelinevol(시그널 60d 시계열)
  const mode = url.searchParams.get('mode') === 'timelinevol' ? 'timelinevol' : 'artlist';
  const timespan = url.searchParams.get('timespan') === '60d' ? '60d' : '1d';
  const p = { query, mode, timespan, format: 'json' };
  if (mode === 'artlist') { p.maxrecords = '250'; p.sort = 'datedesc'; }
  const params = new URLSearchParams(p);
  let r;
  try {
    r = await fetch('https://api.gdeltproject.org/api/v2/doc/doc?' + params, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) enxight-pulse' },
    });
  } catch (e) {
    return json({ error: 'gdelt fetch failed', detail: String(e) }, 502);
  }
  // GDELT 비200(429 rate limit 등)은 상태코드 그대로 전달 — build_pulse 다패스가 429 를
  // 인식해 휴지·재시도한다(502 고정 시 rate limit 을 일반 err 로 오인해 휴지 로직 미발동).
  if (!r.ok) return json({ error: 'gdelt http ' + r.status }, r.status);
  const text = await r.text();
  // GDELT 가 간혹 비 JSON(빈/HTML) 반환 — 파싱은 caller(build_pulse)가 판단하도록 원문 전달.
  const res = new Response(text, {
    status: 200,
    headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8',
               'Cache-Control': 'public, max-age=600' },
  });
  await cache.put(cacheKey, res.clone());
  return res;
}
