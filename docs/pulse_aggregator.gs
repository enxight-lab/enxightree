/**
 * ⚠️ DEPRECATED (2026-06-11) — GAS 경로 폐기. 정본 = scripts/build_pulse.py (GitHub Actions).
 * 사유: 전제했던 GAS 뉴스 수집기 실존 불확실 + 수동 설치 필요. docs/PULSE_SETUP.md 참조.
 * 아래는 원안 참고용 보존.
 */
/**
 * ENXIGHT 마켓 펄스 — Apps Script 집계기 (pulse_aggregator.gs) v1.1
 * 기존 ENXIGHT_news_collector.gs 프로젝트(NEWS 시트)에 새 파일로 추가.
 *
 * [v1.1 변경] Stooq CSV 엔드포인트 폐쇄 확인(2026-06-10) → Yahoo v8 차트 API로 교체.
 *             aggregateNews_()를 실제 수집기 시트 구조(NEWS, 9열)에 매핑.
 *
 * [사전 설정 — 프로젝트 설정 > 스크립트 속성]
 *   PULSE_WORKER_URL = https://data.enxight.com/pulse
 *   PULSE_TOKEN      = (Worker Secret와 동일한 긴 랜덤 문자열)
 *   ※ NEWS_SHEET_ID 불필요 — 수집기와 같은 프로젝트면 활성 스프레드시트 사용.
 *     별도 프로젝트에 설치할 경우에만 NEWS_SHEET_ID 속성 추가.
 *
 * [트리거] setupPulseTrigger() 1회 실행 → 매일 07:30 KST buildPulse()
 */

// ───────────────────────── 설정 ─────────────────────────

const PULSE_REGIONS = [
  // Yahoo v8 차트 API 심볼 — 2026-06-10 7개 전부 실데이터 검증 완료
  { id: 'us', name: '미국',   index: 'S&P 500',    symbol: '^GSPC',     weight: 46 },
  { id: 'eu', name: '유럽',   index: 'STOXX 600',  symbol: '^STOXX',    weight: 15 },
  { id: 'cn', name: '중국',   index: '상해종합',    symbol: '000001.SS', weight: 12 },
  { id: 'jp', name: '일본',   index: 'Nikkei 225', symbol: '^N225',     weight: 10 },
  { id: 'kr', name: '한국',   index: 'KOSPI',      symbol: '^KS11',     weight: 8  },
  { id: 'br', name: '브라질', index: 'IBOVESPA',   symbol: '^BVSP',     weight: 4  },
  { id: 'em', name: '신흥국', index: 'MSCI EM',    symbol: 'EEM',       weight: 5  }, // ETF 프록시
];

const PULSE_THEMES = [
  { id: 'fed',   name: '연준·금리',   kw: ['fed', 'fomc', '연준', '금리', 'rate', 'powell', 'treasury', '국채', 'yield'] },
  { id: 'semi',  name: '반도체·AI',   kw: ['semiconductor', '반도체', 'ai', 'nvidia', 'chip', 'tsmc', '삼성전자', 'hbm', 'sk하이닉스'] },
  { id: 'geo',   name: '중동·지정학', kw: ['iran', '이란', 'middle east', '중동', 'israel', 'hormuz', '호르무즈', 'war', '전쟁', 'missile'] },
  { id: 'enrg',  name: '에너지',     kw: ['oil', '원유', 'brent', 'wti', 'gas', '가스', 'opec', 'lng', '유가'] },
  { id: 'trade', name: '무역·관세',   kw: ['tariff', '관세', 'trade', '무역', 'export', '수출', '수입', 'sanction', '제재'] },
];

// 수집기 NEWS 시트 열 매핑 (0-기준): 날짜|탭|토픽|제목|출처|원문링크|요약|키워드|수집시각
const NEWS_SHEET_NAME = 'NEWS';
const COL = { DATE: 0, TAB: 1, TOPIC: 2, TITLE: 3, SOURCE: 4, URL: 5, SUMMARY: 6, KEYWORDS: 7, COLLECTED: 8 };

// ───────────────────── 메인 (일 1회 트리거) ─────────────────────

function buildPulse() {
  const kst = Utilities.formatDate(new Date(), 'Asia/Seoul', "yyyy-MM-dd'T'HH:mm:ssXXX");

  const price = fetchPrices_();
  const news  = aggregateNews_();
  const gap   = computeGap_(price, news);

  const pulse = {
    version: 1,
    updated: kst,
    price: { regions: price },
    news:  { themes: PULSE_THEMES.map(t => t.name), matrix: news.matrix,
             window_hours: 24, total: news.total },
    gap:   gap,
  };

  pushToWorker_(pulse);
  Logger.log('pulse pushed: ' + kst);
}

// ───────────────────── 가격 수집 (Yahoo v8 차트) ─────────────────────

function fetchPrices_() {
  const out = [];
  PULSE_REGIONS.forEach(r => {
    try {
      const url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
                + encodeURIComponent(r.symbol) + '?range=10d&interval=1d';
      const res = UrlFetchApp.fetch(url, {
        muteHttpExceptions: true,
        headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' },
      });
      if (res.getResponseCode() !== 200) throw new Error('HTTP ' + res.getResponseCode());
      const result = JSON.parse(res.getContentText()).chart.result[0];
      const closes = result.indicators.quote[0].close.filter(c => c !== null && c !== undefined);
      if (closes.length < 2) throw new Error('insufficient closes');
      const close = closes[closes.length - 1];
      const prev  = closes[closes.length - 2];
      const lastTs = result.timestamp[result.timestamp.length - 1];
      out.push({
        id: r.id, name: r.name, index: r.index, weight: r.weight,
        close: Math.round(close * 100) / 100,
        chg: Math.round(((close - prev) / prev) * 10000) / 100,
        asof: Utilities.formatDate(new Date(lastTs * 1000), 'Asia/Seoul', 'yyyy-MM-dd'),
      });
      Utilities.sleep(400); // 예의상 간격
    } catch (e) {
      Logger.log('price fail ' + r.symbol + ': ' + e);
      out.push({ id: r.id, name: r.name, index: r.index, weight: r.weight,
                 close: null, chg: null, asof: null }); // null 홀딩 — 프론트에서 회색 처리
    }
  });
  return out;
}

// 심볼 검증용 수동 실행
function testYahoo() {
  PULSE_REGIONS.forEach(r => {
    try {
      const url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
                + encodeURIComponent(r.symbol) + '?range=5d&interval=1d';
      const j = JSON.parse(UrlFetchApp.fetch(url, {
        headers: { 'User-Agent': 'Mozilla/5.0' }, muteHttpExceptions: true }).getContentText());
      const c = j.chart.result[0].indicators.quote[0].close.filter(x => x);
      Logger.log(r.symbol + ' → OK, 최근 종가 ' + c[c.length - 1]);
    } catch (e) { Logger.log(r.symbol + ' → FAIL ' + e); }
  });
}

// ───────────────────── 뉴스 집계 (NEWS 시트, 최근 24h) ─────────────────────

function aggregateNews_() {
  const props = PropertiesService.getScriptProperties();
  const sheetId = props.getProperty('NEWS_SHEET_ID'); // 같은 프로젝트면 미설정
  const ss = sheetId ? SpreadsheetApp.openById(sheetId) : SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(NEWS_SHEET_NAME);
  if (!sheet) throw new Error('시트 "' + NEWS_SHEET_NAME + '" 없음 — NEWS_SHEET_NAME 확인');

  const rows = sheet.getDataRange().getValues();
  const cutoff = Date.now() - 24 * 3600 * 1000;

  // 수집기 8탭 한글명 → 펄스 지역 id (종합 탭은 특정 지역 아님 → 제외)
  const regionMap = { '미국':'us','유럽':'eu','중국':'cn','일본':'jp','한국':'kr','브라질':'br','신흥국':'em' };
  const matrix = {};
  PULSE_REGIONS.forEach(r => matrix[r.id] = PULSE_THEMES.map(() => 0));
  let total = 0;

  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    // 시각: 수집시각(I) 우선, 없으면 날짜(A)
    let ts = row[COL.COLLECTED] instanceof Date ? row[COL.COLLECTED]
           : row[COL.DATE] instanceof Date ? row[COL.DATE] : null;
    if (!ts || ts.getTime() < cutoff) continue;

    const rid = regionMap[String(row[COL.TAB]).trim()];
    if (!rid) continue; // 종합 등 매핑 외 탭 스킵

    // 테마 매칭: 제목 + 키워드 열 함께 검사 (적중률 향상)
    const text = (String(row[COL.TITLE]) + ' ' + String(row[COL.KEYWORDS] || '')).toLowerCase();
    PULSE_THEMES.forEach((t, ti) => {
      if (t.kw.some(k => text.indexOf(k) !== -1)) { matrix[rid][ti]++; total++; }
    });
  }
  return { matrix: matrix, total: total };
}

// ───────────────────── 온도차 (뉴스 × 가격 괴리) ─────────────────────

function computeGap_(price, news) {
  const base = fetchBaseline_(); // 직전 7일 평균 (이력 없으면 null → 비활성)
  const gaps = [];

  price.forEach(p => {
    if (p.chg === null) return;
    const counts = news.matrix[p.id] || [];
    const todaySum = counts.reduce((a, b) => a + b, 0);
    const baseSum = base && base[p.id] ? base[p.id].reduce((a, b) => a + b, 0) : null;
    const newsRatio = baseSum && baseSum > 0 ? todaySum / baseSum : 1;
    const absChg = Math.abs(p.chg);

    // 단순 규칙 v1 — 운영하며 임계값 보정
    let type = 'inline', label = '동행';
    if (newsRatio >= 1.8 && absChg < 0.5) { type = 'pressure'; label = '압력 축적'; }
    else if (newsRatio <= 0.8 && absChg >= 1.5) { type = 'quiet'; label = '조용한 이동'; }

    if (type !== 'inline') {
      const topTheme = PULSE_THEMES[counts.indexOf(Math.max.apply(null, counts))];
      gaps.push({ region: p.id, regionName: p.name,
                  theme: topTheme ? topTheme.name : '-',
                  newsRatio: Math.round(newsRatio * 10) / 10,
                  chg: p.chg, type: type, label: label });
    }
  });
  return gaps;
}

function fetchBaseline_() {
  try {
    const workerBase = PropertiesService.getScriptProperties()
      .getProperty('PULSE_WORKER_URL').replace(/\/pulse$/, '');
    const acc = {};
    let days = 0;
    for (let d = 1; d <= 7; d++) {
      const date = Utilities.formatDate(new Date(Date.now() - d * 864e5), 'Asia/Seoul', 'yyyy-MM-dd');
      const res = UrlFetchApp.fetch(workerBase + '/pulse/' + date + '.json', { muteHttpExceptions: true });
      if (res.getResponseCode() !== 200) continue;
      const m = JSON.parse(res.getContentText()).news.matrix;
      Object.keys(m).forEach(rid => {
        if (!acc[rid]) acc[rid] = m[rid].map(() => 0);
        m[rid].forEach((v, i) => acc[rid][i] += v);
      });
      days++;
    }
    if (days === 0) return null;
    Object.keys(acc).forEach(rid => acc[rid] = acc[rid].map(v => v / days));
    return acc;
  } catch (e) { return null; }
}

// ───────────────────── Worker 푸시 ─────────────────────

function pushToWorker_(pulse) {
  const props = PropertiesService.getScriptProperties();
  const res = UrlFetchApp.fetch(props.getProperty('PULSE_WORKER_URL'), {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + props.getProperty('PULSE_TOKEN') },
    payload: JSON.stringify(pulse),
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) throw new Error('worker push failed: ' + res.getContentText());
}

// ───────────────────── 트리거 설치 (1회 수동 실행) ─────────────────────

function setupPulseTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'buildPulse') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('buildPulse').timeBased().atHour(7).nearMinute(30).everyDays(1).create();
  Logger.log('trigger set: buildPulse daily 07:30 KST');
}
