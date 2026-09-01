#!/usr/bin/env python3
"""ENXIGHT Market Pulse 집계기 — GAS 원안의 GitHub Actions 대체 (2026-06-11, ADR: PULSE_SETUP.md).

흐름:  Yahoo v8(가격 7지역) + GDELT DOC(뉴스 밀도 7지역×5테마) + 온도차(이력 7일 베이스라인)
       → data.enxight.com/pulse 에 POST(PULSE_TOKEN) → KV 저장 → map.enxight.com/pulse 가 표시

원칙:
  - 표준 라이브러리만 (CI 의존성 0 — feedback_requirements_completeness 무풍지대)
  - 모든 시간 KST. 실패 지역은 null 홀딩 (프론트 회색 처리) — 전체 중단 금지
  - 산출 스키마 = public/pulse/index.html 계약 (version/updated/price/news/gap)

뉴스 밀도: GDELT 는 24h 내 (지역 AND 테마) 영문 기사 수 (artlist cap 250 — 상대 밀도 용도로 충분).
원안(GAS+뉴스시트)은 수집기 실존 불확실 + 수동 설치 필요로 폐기 — docs/pulse_aggregator.gs 는 참고용.
"""
from __future__ import annotations

import functools
import atexit
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pulse_signal import build_signal  # SIGNAL_SPEC 구현 (같은 scripts/ 디렉토리)

# ── 구간 계측 (2026-09-01 신설) ───────────────────────────────────────────
# 왜: pulse 런이 8월 GHA 에서 750분(전 워크플로의 27%)을 썼는데 **어느 구간이
#     먹는지 아무도 몰랐다.** 근거 없이 상수를 줄이면 수집 품질만 깨진다(R101).
# 무엇을: 구간별 벽시계를 **「의도적 휴지」와 「네트워크 대기」로 쪼개** 잰다.
#     rate-limit 회피용 sleep 은 우리가 정한 값이라 줄일 수 있고, 망 대기는 물리다.
#     줄일 몫이 어디 있는지는 이 둘을 갈라야만 보인다.
# 어떻게: `time.sleep` 를 한 번 감싼다 — 같은 `time` 모듈을 쓰는
#     `pulse_signal.py` 의 휴지(7지역 × 15초 + 재시도)까지 자동으로 잡힌다.
_PHASES: list[dict] = []
_cur: dict | None = None
_real_sleep = time.sleep


def _counted_sleep(sec):
    if _cur is not None:
        _cur["sleep"] += sec
        _cur["naps"] += 1
    _real_sleep(sec)


time.sleep = _counted_sleep  # ⚠️계측 전용 — 휴지는 그대로 일어난다(동작 불변)


@contextmanager
def phase(name: str):
    """구간 하나를 잰다. 중첩하지 않는다 — main 의 단계는 순차라 평면으로 충분하다."""
    global _cur
    rec = {"name": name, "sleep": 0.0, "naps": 0, "t0": time.monotonic(), "wall": 0.0}
    prev, _cur = _cur, rec
    try:
        yield rec
    finally:
        rec["wall"] = time.monotonic() - rec["t0"]
        _PHASES.append(rec)
        _cur = prev


def _report() -> None:
    """구간 표를 stdout 에 찍는다 — GHA 로그가 그대로 근거가 된다.
    atexit 이라 sys.exit 로 죽은 런(가격·뉴스 동시 실패)에서도 남는다."""
    if not _PHASES:
        return
    tot = sum(p["wall"] for p in _PHASES)
    slp = sum(p["sleep"] for p in _PHASES)
    print("")                # 빈 줄 — 로그에서 표를 띄운다
    print(f"[pulse] ── 구간별 소요 (합계 {tot / 60:.1f}분) " + "─" * 24)
    print(f"  {'구간':<20} {'벽시계':>8} {'휴지':>8} {'망대기':>8} {'휴지%':>6} {'횟수':>5}")
    for x in sorted(_PHASES, key=lambda r: -r["wall"]):
        net = x["wall"] - x["sleep"]
        pct = (x["sleep"] / x["wall"] * 100) if x["wall"] else 0.0
        print(f"  {x['name']:<20} {x['wall']:>7.1f}s {x['sleep']:>7.1f}s "
              f"{net:>7.1f}s {pct:>5.0f}% {x['naps']:>5}")
    print("  " + "-" * 62)
    print(f"  {'합계':<20} {tot:>7.1f}s {slp:>7.1f}s {tot - slp:>7.1f}s "
          f"{(slp / tot * 100) if tot else 0:>5.0f}%")
    print(f"  → 의도적 휴지 {slp / 60:.1f}분 / 망대기 {(tot - slp) / 60:.1f}분. "
          f"**줄일 수 있는 몫은 앞쪽뿐이다.**")


atexit.register(_report)

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
WORKER = "https://data.enxight.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) enxight-pulse"}

REGIONS = [
    # id, 이름, 지수, Yahoo 심볼, 가중치, GDELT 지역 쿼리
    ("us", "미국", "S&P 500", "^GSPC", 46, '"United States"'),
    ("eu", "유럽", "STOXX 600", "^STOXX", 15, '(Europe OR "European Union" OR ECB)'),
    ("cn", "중국", "상해종합", "000001.SS", 12, "China"),
    ("jp", "일본", "Nikkei 225", "^N225", 10, "Japan"),
    ("kr", "한국", "KOSPI", "^KS11", 8, '"South Korea"'),
    ("br", "브라질", "IBOVESPA", "^BVSP", 4, "Brazil"),
    ("em", "신흥국", "MSCI EM", "EEM", 5, '"emerging markets"'),
]

THEMES = [
    ("fed", "연준·금리", '(Fed OR FOMC OR "interest rate" OR Powell OR "Treasury yield")'),
    ("semi", "반도체·AI", '(semiconductor OR Nvidia OR TSMC OR "AI chip" OR chipmaker)'),
    ("geo", "중동·지정학", '(Iran OR "Middle East" OR Israel OR Hormuz OR missile)'),
    ("enrg", "에너지", '(OPEC OR "crude oil" OR Brent OR LNG OR "natural gas")'),
    ("trade", "무역·관세", '(tariff OR sanctions OR "trade war" OR "export controls")'),
]

# 뉴스 밀도 축은 상위 5개 지역만 질의 (저비중 br·em 제외) — GDELT rate limit 호출량 감축
# (2026-07-07 R-KREMAP: 35→25 셀). 가격축(REGIONS 7)·지도·프론트 y축은 불변, 제외 지역은
# news 빈 행([])으로 렌더. 되돌리려면 이 튜플에 br·em 추가. THEMES 5는 유지(에너지·무역 시의성).
NEWS_REGIONS = ("us", "eu", "cn", "jp", "kr")
NEWS_GATE_RATIO = 12 / 35  # 뉴스 품질 게이트 비율(기존 12/35 유지) — 셀 수 변해도 자동 스케일


def now_kst() -> datetime:
    return datetime.now(KST)


def http_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── 가격 (Yahoo v8 차트 — GAS fetchPrices_ 포팅) ──────────────────

def fetch_prices() -> list[dict]:
    out = []
    for rid, name, index, symbol, weight, _ in REGIONS:
        row = {"id": rid, "name": name, "index": index, "weight": weight,
               "close": None, "chg": None, "asof": None}
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                   f"{urllib.parse.quote(symbol)}?range=10d&interval=1d")
            result = http_json(url)["chart"]["result"][0]
            closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) >= 2:
                close, prev = closes[-1], closes[-2]
                last_ts = result["timestamp"][-1]
                row.update({
                    "close": round(close, 2),
                    "chg": round((close - prev) / prev * 100, 2),
                    "asof": datetime.fromtimestamp(last_ts, KST).strftime("%Y-%m-%d"),
                })
        except Exception as e:
            print(f"  [price] {symbol} 실패: {e} — null 홀딩")
        out.append(row)
        time.sleep(0.4)
    return out


# ── 뉴스 밀도 (GDELT DOC 2.0 — 24h 영문 기사 수) ──────────────────

TOP_ARTICLES = 5  # 셀당 보존할 상위 기사 수 (클릭 시 하단 표시 — 추가 호출 0)


def gdelt_query(theme_q: str, region_q: str) -> tuple[int, list[dict]]:
    """GDELT 1쿼리 → (기사수, 상위 기사 list). 단일 시도 fail-fast — 재시도는
    fetch_news 의 다패스 구조가 담당 (2026-07-03 재설계).

    구 구조(셀당 25s 타임아웃×3회 + 12s 백오프)는 GDELT 가 GitHub 공유 runner IP 를
    스로틀하는 날 셀당 최대 99초를 태워 run 이 40~57분 — 그러고도 미수집 7~10셀.
    429 는 IP 단위 시간창 문제라 즉시 재시도가 무의미, 휴지 후 패스 재개가 정답.

    ★ 2026-07-06: GDELT 를 직접 호출하지 않고 pulse-worker(data.enxight.com/gdelt) 경유.
      GDELT 가 GitHub 공유 러너 IP 를 지속 스로틀해 며칠째 0/35 이던 근본 문제를, CF Worker
      IP 경유로 우회한다. GDELT 파라미터는 Worker 가 고정 → 여기선 query 만 전달 + Bearer 인증.

    이미 호출하는 artlist 응답에서 상위 N개의 {t:제목, u:링크, s:출처, d:날짜}만
    추출 — 셀 클릭 시 실기사 표시용 (네트워크 추가 0, Worker 응답 계약 [{t,s,d,u}] 정합).
    """
    q = urllib.parse.urlencode({"query": f"{theme_q} {region_q} sourcelang:english"})
    req = urllib.request.Request(
        f"{WORKER}/gdelt?{q}",
        headers={**UA, "Authorization": f"Bearer {load_token()}"})
    with urllib.request.urlopen(req, timeout=30) as r:  # 30s: Worker+artlist 250건 왕복이 무거워 15s 는 read timeout (2026-07-06)
        arts = json.loads(r.read()).get("articles", [])
    top = [{
        "t": a.get("title", "")[:160],
        "u": a.get("url", ""),
        "s": a.get("domain", ""),
        "d": (a.get("seendate", "") or "")[:8],  # YYYYMMDD
    } for a in arts[:TOP_ARTICLES] if a.get("url")]
    return len(arts), top


NEWS_PASSES = 3          # 최대 패스 수 (1차 + 재시도 2)
NEWS_PAUSES = (75, 120)  # 패스 간 휴지(초) — 429 시간창이 넘어가도록


def fetch_news() -> dict:
    """NEWS_REGIONS(5)×5테마 GDELT 밀도 수집 — 다패스 (2026-07-03 재설계 · 2026-07-07 25셀).

    각 셀 단일 시도(10s 타임아웃), 실패 셀은 다음 패스로 이월. 최종 실패 셀은
    0 홀딩(설계된 fail-soft).

    2026-08-19 조기중단(CONSEC_429_ABORT) 제거 — 8/10~11 조사의 응급처치 1순위.
    옛 장치는 "429 가 연속되면 스로틀 시간창 안이라 나머지도 전멸"을 전제로 4연속
    429 에서 패스를 끊었는데, **전제가 틀렸다**: 실측 셀당 성공률 p=0.28 에서 25셀
    패스가 4연속 429 를 만날 확률은 96.2%(DP 계산) — GDELT 이상이 아니라 확률
    구조가 만드는 자기 차단이었다. 429 는 지속 창이 아니라 확률적이라(5.2s 간격
    유지 시) 연속 429 뒤의 셀도 살 수 있다. 실증 = 8/3 이 유일하게 중단 없이 25셀
    전수를 때려 12/25(48%)로 8일 중 최고. 끊어서 아끼는 시간은 패스당 최대 ~2분,
    잃는 것은 그날 뉴스축 전체였다.
    """
    matrix = {rid: [0] * len(THEMES) for rid in NEWS_REGIONS}
    # articles[rid][ti] = 상위 기사 list (셀 클릭 시 표시). 키 = f"{rid}:{ti}"
    articles: dict[str, list[dict]] = {}
    region_q_of = {rid: rq for rid, _, _, _, _, rq in REGIONS}

    def attempt(rid: str, ti: int) -> str:
        """'ok' | 'rate'(429) | 'err'(타임아웃 등)"""
        try:
            cnt, top = gdelt_query(THEMES[ti][2], region_q_of[rid])
            matrix[rid][ti] = cnt
            if top:
                articles[f"{rid}:{ti}"] = top
            return "ok"
        except urllib.error.HTTPError as e:
            if e.code == 429:
                return "rate"
            print(f"  [news] {rid}×{ti} 실패: {e}")
            return "err"
        except Exception as e:
            print(f"  [news] {rid}×{ti} 실패: {e}")
            return "err"

    pending = [(rid, ti) for rid in NEWS_REGIONS for ti in range(len(THEMES))]
    for p in range(NEWS_PASSES):
        if not pending:
            break
        if p:
            print(f"  [news] {p + 1}차 재시도 {len(pending)}셀 ({NEWS_PAUSES[p - 1]}s 휴지)")
            time.sleep(NEWS_PAUSES[p - 1])
        t0 = time.time()
        still: list[tuple[str, int]] = []
        for rid, ti in pending:
            status = attempt(rid, ti)
            if status != "ok":
                still.append((rid, ti))
            time.sleep(5.2)  # GDELT 공개 API 안전 간격
        print(f"  [news] {p + 1}차: {len(pending) - len(still)}/{len(pending)}셀 수집 · {time.time() - t0:.0f}s")
        pending = still
        # 폭풍 단락 (2026-07-06 R-KREMAP 재정의): pending(=still)에는 429·timeout 실패 셀만
        # 담긴다. 잔여 셀이 없는데(전 셀이 HTTP 200) 값이 전부 0 이면 GDELT 가 200+빈 배열만
        # 주는 진짜 '빈-응답 폭풍' → 재시도 무의미, 잔여 패스 포기. 반대로 pending 이 남아 있으면
        # 스로틀(429)·일시 timeout 이라 휴지 후 재시도가 유효하므로 단락하지 않는다.
        # (구 조건 `if not any(v>0)` 은 429/timeout 로 matrix 가 0 인 것을 '빈 응답'과 혼동해
        #  2·3차 재시도를 조기 종료 → 7/3~7/6 0/35 정지의 직접 원인. HANDOFF_NEXT §0-1.)
        if not pending and not any(v > 0 for row in matrix.values() for v in row):
            print(f"  [news] 전 셀 성공·유효 값 0 — GDELT 빈-응답 폭풍, 잔여 패스 포기")
            break
    if pending:
        print(f"  [news] 최종 미수집 {len(pending)}셀 — 0 홀딩")

    total = sum(v for row in matrix.values() for v in row)
    return {"themes": [t[1] for t in THEMES], "matrix": matrix,
            "articles": articles, "window_hours": 24, "total": total}


# ── 온도차 (GAS computeGap_ 포팅 — 이력 7일 베이스라인) ──────────────────

def fetch_baseline() -> dict | None:
    acc, days = {}, 0
    for d in range(1, 8):
        date = (now_kst() - timedelta(days=d)).strftime("%Y-%m-%d")
        try:
            pj = http_json(f"{WORKER}/pulse/{date}.json")
            if pj.get("news", {}).get("stale"):
                continue  # carry-forward 된 날 — 베이스라인 오염 방지 위해 제외 (2026-07-06)
            m = pj["news"]["matrix"]
        except Exception:
            continue
        for rid, counts in m.items():
            acc.setdefault(rid, [0] * len(counts))
            for i, v in enumerate(counts):
                acc[rid][i] += v
        days += 1
    if not days:
        return None
    return {rid: [v / days for v in counts] for rid, counts in acc.items()}


def compute_gap(price: list[dict], news: dict) -> list[dict]:
    base = fetch_baseline()
    gaps = []
    for p in price:
        if p["chg"] is None or p["id"] not in NEWS_REGIONS:
            continue  # 뉴스축 미포함 지역(br·em)은 온도차 산출 제외 — 뉴스 0 오인 방지 (2026-07-07)
        counts = news["matrix"].get(p["id"], [])
        today = sum(counts)
        base_sum = sum(base[p["id"]]) if base and p["id"] in base else None
        ratio = today / base_sum if base_sum else 1
        abs_chg = abs(p["chg"])
        if ratio >= 1.8 and abs_chg < 0.5:
            t, label = "pressure", "압력 축적"
        elif ratio <= 0.8 and abs_chg >= 1.5:
            t, label = "quiet", "조용한 이동"
        else:
            continue
        top = THEMES[counts.index(max(counts))][1] if counts and max(counts) > 0 else "-"
        gaps.append({"region": p["id"], "regionName": p["name"], "theme": top,
                     "newsRatio": round(ratio, 1), "chg": p["chg"], "type": t, "label": label})
    return gaps


def fetch_news_history(days=60):
    """직전 days 일 pulse 이력의 news.matrix list (signal 백분위용). 없는 날 skip — fail-soft."""
    hist = []
    for d in range(1, days + 1):
        date = (now_kst() - timedelta(days=d)).strftime("%Y-%m-%d")
        try:
            pj = http_json(f"{WORKER}/pulse/{date}.json")
            if pj.get("news", {}).get("stale"):
                continue  # carry-forward 된 날 제외 (2026-07-06)
            hist.append(pj["news"]["matrix"])
        except Exception:
            continue
    return hist


def _carry_forward_news(gate: int = 12) -> dict | None:
    """GDELT 폭풍일 직전 유효 뉴스(값 있는 셀 ≥ gate)를 찾아 stale 마커 부착해 반환 (2026-07-06).

    라이브(오늘 /pulse.json)→7일 전 역순 탐색. 이미 carry(stale)된 날이면 원본 stale_since 보존(체인).
    폭풍의 날 0 투성이 매트릭스를 저장하는 대신 이 값을 재사용 → 이력 베이스라인 오염 없이
    라이브 신선(updated 갱신)을 유지하고 GHA 를 실패로 표시하지 않는다.
    """
    for d in range(0, 8):
        date = (now_kst() - timedelta(days=d)).strftime("%Y-%m-%d")
        url = f"{WORKER}/pulse.json" if d == 0 else f"{WORKER}/pulse/{date}.json"
        try:
            p = http_json(url)
        except Exception:
            continue
        n = p.get("news")
        if not n or "matrix" not in n:
            continue
        filled = sum(1 for row in n["matrix"].values() for v in row if v > 0)
        if filled >= gate:
            n = dict(n)
            n["stale"] = True
            n["stale_since"] = n.get("stale_since") or p.get("updated") or date
            return n
    return None


# ── 금리 한·미·일 (FRED API + ECOS — 2026-06-11 추천안: 좌 점 현황판 + 우 계단 추이) ──
# fredgraph.csv 는 Worker 520·Actions timeout 실측 → 공식 API(키)로 전환.
# 키: FRED_API_KEY·BOK_ECOS_API_KEY (Actions Secrets). 일본은 OECD 월별(콜금리·10y — 정책은 계단이라 충분).

RATE_COUNTRIES = [
    # id, 정책금리 (source, code...), 10년물
    ("us", ("fred", "DFEDTARU"), ("fred", "DGS10")),
    ("kr", ("ecos", "722Y001", "0101000"), ("ecos", "817Y002", "010210000")),
    ("jp", ("fred", "IRSTCI01JPM156N"), ("fred", "IRLTLT01JPM156N")),
]


def _env_key(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    envp = ROOT / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return None


def _fred_api(series_id: str, start_iso: str, key: str) -> list[tuple[str, float]]:
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
           f"&api_key={key}&file_type=json&observation_start={start_iso}&sort_order=asc")
    rows = []
    for o in http_json(url, timeout=30).get("observations", []):
        if o.get("value") not in (None, "."):
            rows.append((o["date"], float(o["value"])))
    return rows


def _ecos(stat: str, item: str, start: str, end: str, key: str) -> list[tuple[str, float]]:
    url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/5000/"
           f"{stat}/D/{start}/{end}/{item}")
    rows = []
    for r in http_json(url, timeout=30).get("StatisticSearch", {}).get("row", []):
        try:
            t = r["TIME"]
            rows.append((f"{t[:4]}-{t[4:6]}-{t[6:8]}", float(r["DATA_VALUE"])))
        except (KeyError, ValueError):
            continue
    return rows


def _series_fetch(spec: tuple, start_iso: str, fred_key: str | None, ecos_key: str | None):
    if spec[0] == "fred":
        if not fred_key:
            raise RuntimeError("FRED_API_KEY 없음")
        return _fred_api(spec[1], start_iso, fred_key)
    if not ecos_key:
        raise RuntimeError("BOK_ECOS_API_KEY 없음")
    try:
        return _ecos(spec[1], spec[2], start_iso.replace("-", ""), now_kst().strftime("%Y%m%d"), ecos_key)
    except Exception as e:
        item = spec[2]
        # stooq 폴백 (GitHub Actions 해외 IP → ECOS timeout 대응)
        if item in _ECOS_STOOQ:
            try:
                rows = _stooq(_ECOS_STOOQ[item], start_iso)
                if rows:
                    print(f"  [bonds] ECOS→stooq {_ECOS_STOOQ[item]} OK")
                    return rows
            except Exception as e2:
                print(f"  [bonds] stooq {_ECOS_STOOQ[item]} 실패: {e2}")
        # FRED 폴백 (10Y만 가능, 월별)
        if fred_key and item in _ECOS_FRED:
            try:
                rows = _fred_api(_ECOS_FRED[item], start_iso, fred_key)
                if rows:
                    print(f"  [bonds] ECOS→FRED {_ECOS_FRED[item]} OK (월별)")
                    return rows
            except Exception as e3:
                print(f"  [bonds] FRED {_ECOS_FRED[item]} 실패: {e3}")
        raise


def _align(rows: list[tuple[str, float]], dates: list[str]) -> list[float | None]:
    """날짜 기준 carry-forward 정렬 (월별·영업일 결측 정합)."""
    i, last, out = 0, None, []
    for d in dates:
        while i < len(rows) and rows[i][0] <= d:
            last = rows[i][1]
            i += 1
        out.append(last)
    return out


def fetch_rates() -> dict | None:
    fred_key = _env_key("FRED_API_KEY")
    ecos_key = _env_key("BOK_ECOS_API_KEY")
    start_1y = (now_kst() - timedelta(days=365)).strftime("%Y-%m-%d")
    raw = {}
    for cid, pol_spec, y10_spec in RATE_COUNTRIES:
        for kind, spec in (("policy", pol_spec), ("y10", y10_spec)):
            try:
                raw[(cid, kind)] = _series_fetch(spec, start_1y, fred_key, ecos_key)
            except Exception as e:
                print(f"  [rates] {cid}.{kind} 실패: {e}")
                raw[(cid, kind)] = None
            time.sleep(0.6)
    base = raw.get(("us", "policy")) or next((r for r in raw.values() if r and len(r) > 10), None)
    if not base:
        return None
    dates = [r[0] for i, r in enumerate(base) if i % 5 == 0]
    if dates[-1] != base[-1][0]:
        dates.append(base[-1][0])
    policy, snapshot = {}, {}
    for cid, *_ in RATE_COUNTRIES:
        pol, y10 = raw.get((cid, "policy")), raw.get((cid, "y10"))
        policy[cid] = _align(pol, dates) if pol else None
        snapshot[cid] = {
            "policy": pol[-1][1] if pol else None,
            "y10": y10[-1][1] if y10 else None,
            "policy_prev": pol[0][1] if pol else None,
            "y10_prev": y10[0][1] if y10 else None,
        }
    out = {"dates": dates, "policy": policy, "snapshot": snapshot}
    # 홈 보드용 Fed 3년 주별
    try:
        if fred_key:
            fed3 = _fred_api("DFEDTARU", (now_kst() - timedelta(days=3 * 365)).strftime("%Y-%m-%d"), fred_key)
            weekly = [v for i, (_, v) in enumerate(fed3) if i % 7 == 0]
            if weekly and fed3 and weekly[-1] != fed3[-1][1]:
                weekly.append(fed3[-1][1])
            out["fed3y"] = weekly
    except Exception as e:
        print(f"  [rates] fed3y 실패: {e}")
    return out


# ── 채권 한·미·일 × 2y·10y·30y + 일변동(bp) — 2026-06-15 시장 탭 ──
# 미=FRED 일별 / 한=ECOS 일별 / 일=MOF jgbcm.csv(令和 날짜·shift_jis). 일변동 = 최근 2영업일.

BOND_MATS = ["2y", "10y", "30y"]
BOND_SPECS = {
    "us": {"2y": ("fred", "DGS2"), "10y": ("fred", "DGS10"), "30y": ("fred", "DGS30")},
    "kr": {"2y": ("ecos", "817Y002", "010195000"),
           "10y": ("ecos", "817Y002", "010210000"),
           "30y": ("ecos", "817Y002", "010230000")},
    # jp = MOF (별도 경로)
}

# ECOS item → stooq 폴백 심볼 (무키·일별 — GitHub Actions 해외 IP timeout 대응)
_ECOS_STOOQ: dict[str, str] = {
    "010195000": "2kry.b",   # KR 2Y
    "010210000": "10kry.b",  # KR 10Y
    "010230000": "30kry.b",  # KR 30Y
}
# stooq 실패 시 FRED 폴백 (OECD, 월별 — chg=None)
_ECOS_FRED: dict[str, str] = {
    "010210000": "IRLTLT01KRM156N",  # KR 10Y만 FRED 제공
}


def _stooq(symbol: str, start_iso: str) -> list[tuple[str, float]]:
    """stooq.com 일별 CSV → [(date, close)] — Date,Open,High,Low,Close,Volume."""
    d1 = start_iso.replace("-", "")
    url = f"https://stooq.com/q/d/l/?s={symbol}&d1={d1}&i=d"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        text = r.read().decode("utf-8", "replace")
    rows = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 5:
            try:
                rows.append((parts[0], float(parts[4])))
            except (ValueError, IndexError):
                pass
    return rows


def _mof_jgb() -> dict[str, list[tuple[str, float]]]:
    """일본 재무성 jgbcm.csv (당해연도 일별) → {mat: [(date, yield)...]} 최근분.

    제목줄 + 헤더(基準日,1年,2年,...,40年) + 데이터(令和 날짜 'R8.6.12') + 안내(※).
    令和N = 2018+N년. 무키. shift_jis."""
    url = "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("shift_jis", "replace")
    rows = [ln.split(",") for ln in text.splitlines() if ln.strip() and not ln.startswith("※")]
    hdr = [h.strip() for h in rows[1]]
    idx = {"2y": hdr.index("2年"), "10y": hdr.index("10年"), "30y": hdr.index("30年")}
    out = {m: [] for m in BOND_MATS}
    for row in rows[2:]:
        d = row[0].strip()
        m = re.match(r"R(\d+)\.(\d+)\.(\d+)", d)  # 令和
        if not m:
            continue
        iso = f"{2018 + int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        for mat, ci in idx.items():
            try:
                out[mat].append((iso, float(row[ci])))
            except (ValueError, IndexError):
                pass
    return out


def fetch_bonds() -> dict | None:
    """{cid: {mat: {y: 수익률, chg: 일변동bp}}} — 3국 × 3만기."""
    fred_key, ecos_key = _env_key("FRED_API_KEY"), _env_key("BOK_ECOS_API_KEY")
    start = (now_kst() - timedelta(days=12)).strftime("%Y-%m-%d")  # 영업일 2개+ 확보
    out: dict[str, dict] = {}

    def last2(rows):  # (현재값, 일변동bp) — 최근 2개 차이
        if not rows:
            return None
        v = rows[-1][1]
        chg = round((v - rows[-2][1]) * 100, 1) if len(rows) >= 2 else None
        return {"y": round(v, 3), "chg": chg}

    for cid in ("us", "kr"):
        out[cid] = {}
        for mat, spec in BOND_SPECS[cid].items():
            try:
                out[cid][mat] = last2(_series_fetch(spec, start, fred_key, ecos_key))
            except Exception as e:
                print(f"  [bonds] {cid}.{mat} 실패: {e}")
                out[cid][mat] = None
            time.sleep(0.5)
    try:
        mof = _mof_jgb()
        out["jp"] = {mat: last2(mof.get(mat, [])) for mat in BOND_MATS}
    except Exception as e:
        print(f"  [bonds] jp(MOF) 실패: {e}")
        out["jp"] = {m: None for m in BOND_MATS}

    has = any((out.get(c) or {}).get(m) for c in ("us", "kr", "jp") for m in BOND_MATS)
    if not has:
        return None
    # 10년물 1년 주별 추이 (히트맵 아래 꺾은선용) — us=FRED일별·kr=ECOS일별·jp=FRED월별
    try:
        start_1y = (now_kst() - timedelta(days=365)).strftime("%Y-%m-%d")
        raw10 = {}
        for cid, spec in (("us", ("fred", "DGS10")), ("kr", ("ecos", "817Y002", "010210000"))):
            try:
                raw10[cid] = _series_fetch(spec, start_1y, fred_key, ecos_key)
            except Exception:
                raw10[cid] = None
            time.sleep(0.5)
        try:
            raw10["jp"] = _fred_api("IRLTLT01JPM156N", start_1y, fred_key) if fred_key else None
        except Exception:
            raw10["jp"] = None
        base = raw10.get("us") or next((r for r in raw10.values() if r and len(r) > 10), None)
        if base:
            dates = [r[0] for i, r in enumerate(base) if i % 5 == 0]
            if dates and dates[-1] != base[-1][0]:
                dates.append(base[-1][0])
            ser = {"dates": dates}
            for cid in ("us", "kr", "jp"):
                ser[cid] = _align(raw10[cid], dates) if raw10[cid] else None
            out["series"] = ser
    except Exception as e:
        print(f"  [bonds] series 실패: {e}")
    return out


# ── push ──────────────────

@functools.lru_cache(maxsize=1)  # gdelt_query 35셀 × 파일 재읽기 방지 (2026-07-06)
def load_token() -> str:
    if os.environ.get("PULSE_TOKEN"):
        return os.environ["PULSE_TOKEN"]
    envp = ROOT / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PULSE_TOKEN="):
                return line.split("=", 1)[1].strip()
    sys.exit("[pulse] PULSE_TOKEN 없음 (.env 또는 환경변수)")


def main() -> None:
    print(f"[pulse] {now_kst().isoformat(timespec='seconds')} KST 집계 시작")
    with phase('fetch_prices'):
        price = fetch_prices()
    ok_price = sum(1 for p in price if p["chg"] is not None)
    print(f"  가격 {ok_price}/{len(REGIONS)}")

    # 시그널 GDELT(timelinevol 7) 를 fetch_news GDELT(artlist 35) 보다 *먼저* 실행 — rate limit
    # 여유 상태에서 7지역 백필 확보. 순서 역전이 근본책(429 재시도·완충만으론 2~3/7 에 그침).
    # GDELT 우선이므로 today 폴백용 news_matrix 는 빈 dict, 과거 분포 폴백만 pulse 이력으로 전달.
    try:  # signal 실패가 발행(POST) 전체를 막지 않게 — fail-soft
        with phase('news_history(60d)'):
            _hist = fetch_news_history()
        with phase('build_signal'):
            signal = build_signal(price, {}, _hist,
                                  region_q_map={r[0]: r[5] for r in REGIONS},
                                  symbol_map={r[0]: r[3] for r in REGIONS},
                                  gdelt_base=f"{WORKER}/gdelt", gdelt_token=load_token())
        _sig = sum(1 for s in signal["regions"].values() if s["zone"])
        _gd = sum(1 for s in signal["regions"].values() if s.get("news_src") == "gdelt")
        print(f"  시그널 {_sig} 신호 / {len(signal['regions'])} 지역 (gdelt 백필 {_gd})")
    except Exception as e:
        print(f"  [signal] 산출 실패(무시): {e}")
        signal = None
    with phase('buffer_sleep30'):
        time.sleep(30)  # signal GDELT 후 fetch_news GDELT 전 완충

    with phase('fetch_news(25cell)'):
        news = fetch_news()
    filled = sum(1 for row in news["matrix"].values() for v in row if v > 0)
    news_cells = len(NEWS_REGIONS) * len(THEMES)
    gate = max(6, round(news_cells * NEWS_GATE_RATIO))  # 셀 수 비례 게이트(25셀→9). floor 6 안전장치
    print(f"  뉴스 total {news['total']} · 값있는 셀 {filled}/{news_cells} (게이트 {gate})")
    if ok_price == 0 and news["total"] == 0:
        sys.exit("[pulse] FAIL: 가격·뉴스 모두 실패 — push 중단 (이전 데이터 유지)")
    # 뉴스 품질 게이트 (2026-07-03 → 2026-07-06 carry-forward → 2026-07-07 디커플링): GDELT
    # 폭풍의 날 0 투성이 매트릭스를 신선 저장하면 이력 베이스라인(온도차·시그널 백분위)이 오염된다.
    # ① filled ≥ gate: 정상 push (자연 0 포함 정상일 ~15-19/25).
    # ② filled < gate + 직전 유효 뉴스 존재: 뉴스만 carry-forward(stale) — 가격·금리·채권은 신선.
    # ③ filled < gate + carry-forward 원천까지 고갈(라이브·이력 7일 전부 폭풍): 옛 버전은 exit 1
    #    로 push 를 통째 막아 정상 수집된 가격·금리·채권마저 미갱신 → freshness 경보의 직접 원인.
    #    → 디커플링: 뉴스만 degraded 마커(stale=True) 부착해 baseline/history/signal 이 skip,
    #    가격·금리·채권은 신선 push. 라이브 updated 갱신으로 freshness 회복 + 이력 오염 없음.
    #    이 상태는 GDELT 호출량 감축(NEWS_REGIONS 25셀·maxrecords)으로 gate 재도달 시 자연 해소.
    if filled < gate:
        carried = _carry_forward_news(gate)
        if carried:
            print(f"  [news] GDELT 폭풍(값 있는 셀 {filled}/{news_cells} < {gate}) — 직전 유효 뉴스 "
                  f"carry-forward (stale_since={carried.get('stale_since')})")
            news = carried
        else:
            print(f"  [news] {filled}/{news_cells} < {gate} 且 carry-forward 원천 없음 — "
                  f"뉴스 degraded 격리·가격/금리/채권 신선 push (freshness 회복)")
            news["stale"] = True
            news["degraded"] = True
            news["stale_since"] = news.get("stale_since") or now_kst().isoformat(timespec="seconds")
    with phase('fetch_rates'):
        rates = fetch_rates()
    print(f"  금리 {'OK' if rates else 'null 홀딩'}")
    with phase('fetch_bonds'):
        bonds = fetch_bonds()
    print(f"  채권 {'OK' if bonds else 'null 홀딩'}")
    pulse = {
        "version": 1,
        "updated": now_kst().isoformat(timespec="seconds"),
        "price": {"regions": price},
        "news": news,
        "gap": [] if news.get("degraded") else compute_gap(price, news),
        "signal": signal,
        "rates": rates,
        "bonds": bonds,
    }
    req = urllib.request.Request(
        f"{WORKER}/pulse", data=json.dumps(pulse, ensure_ascii=False).encode(),
        headers={**UA, "Content-Type": "application/json",
                 "Authorization": f"Bearer {load_token()}"}, method="POST")
    with phase('push'):
        with urllib.request.urlopen(req, timeout=25) as r:
            print(f"[pulse] push {r.status}: {r.read().decode()}")


if __name__ == "__main__":
    main()
