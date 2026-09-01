#!/usr/bin/env python3
"""시그널 산출 — docs/SIGNAL_SPEC.md 구현 (경험적 백분위 기반).

build_pulse.py 가 import 하여 pulse payload 에 signal 블록을 얹는다.
- 표준 라이브러리만 (CI 의존성 0, build_pulse 원칙 동일)
- 가격 과거 분포는 다중 소스 ladder(네이버 해외지수 → TwelveData ETF)로 조달 — Yahoo 의존 제거,
  실행 환경과 무관. 뉴스 분포는 pulse 이력(누적 대기).
- 정의(임계·창)는 상수 1곳. 변경 시 SIGNAL_SPEC.md 동기화.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from statistics import mean, pstdev

SPEC_VERSION = 1
WINDOW = 60      # N 영업일 (롤링 창)
THETA = 85       # 유의 임계 백분위 (상위 15%)
M_PROV = 20      # 잠정 최소표본 (미만 = provisional)
M_MIN = 10       # 신호 표시 최소표본 (미만 = zone 미산출)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) enxight-pulse"}

# 가격 캘리브레이션 소스 매핑 (지역 → 네이버 해외지수 / TwelveData ETF 프록시)
NAVER_IDX = {"us": ".INX", "jp": ".N225", "cn": ".SSEC", "eu": ".STOXX50E", "br": ".BVSP"}
TD_ETF = {"us": "SPY", "eu": "VGK", "cn": "FXI", "jp": "EWJ", "kr": "EWY", "br": "EWZ", "em": "EEM"}


def _http_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def naver_index_closes(sym, n=WINDOW + 10):
    """네이버 해외지수 과거 n거래일 종가(최신순). 실패 None.

    api.stock.naver.com 은 pageSize 상한이 있어(큰 값은 HTTP 400) page 페이징으로 누적한다.
    """
    per = 10
    out = []
    try:
        for pg in range(1, (n + per - 1) // per + 1):
            url = f"https://api.stock.naver.com/index/{sym}/price?pageSize={per}&page={pg}"
            data = _http_json(url, headers={**UA, "Referer": "https://m.stock.naver.com/"})
            if not data:
                break
            for d in data:
                c = (d.get("closePrice") or "").replace(",", "")
                if c:
                    out.append(float(c))
            if len(data) < per:
                break
        return out or None
    except Exception:
        return None


def td_etf_closes(sym, n=WINDOW + 10):
    """TwelveData ETF 일봉 종가(최신순). 키·실패 시 None."""
    key = os.getenv("TWELVEDATA_API_KEY", "")
    if not key:
        return None
    url = (f"https://api.twelvedata.com/time_series?symbol={sym}"
           f"&interval=1day&outputsize={n}&apikey={key}")
    try:
        vals = _http_json(url).get("values") or []
        return [float(v["close"]) for v in vals] or None
    except Exception:
        return None


def yahoo_closes(symbol):
    """Yahoo v8 chart 6개월 일봉 종가(최신순). ladder 최종 폴백(무키). 실패 None."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?range=6mo&interval=1d")
    try:
        result = _http_json(url)["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        return list(reversed(closes)) or None  # Yahoo 는 오래된→최신 → 최신순으로 통일
    except Exception:
        return None


def price_history_closes(region, symbol=None):
    """지역 과거 종가(최신순) — ladder: 네이버 해외지수 → TwelveData ETF → Yahoo. 실패 (None, None)."""
    sym = NAVER_IDX.get(region)
    if sym:
        c = naver_index_closes(sym)
        if c and len(c) >= M_MIN:
            return c, "naver"
    etf = TD_ETF.get(region)
    if etf:
        c = td_etf_closes(etf)
        if c and len(c) >= M_MIN:
            return c, "twelvedata"
    if symbol:
        c = yahoo_closes(symbol)
        if c and len(c) >= M_MIN:
            return c, "yahoo"
    return None, None


def abs_returns(closes):
    """종가(최신순) → |일수익률%| list."""
    out = []
    for i in range(len(closes) - 1):
        prev = closes[i + 1]
        if prev:
            out.append(abs((closes[i] - prev) / prev * 100))
    return out


def percentile_rank(dist, x):
    """x 가 dist 에서 차지하는 백분위(0~100) — 큰 값일수록 높음. dist 비면 None."""
    if not dist:
        return None
    below = sum(1 for v in dist if v < x)
    return below / len(dist) * 100


GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"


def gdelt_news_percentile(region_q, base=None, token=None):
    """GDELT timelinevol 60일 시계열 → (today 백분위, 과거 표본수). 실패 (None, 0).

    today = 시계열 마지막 점, 분포 = 그 앞 점들 → 실시간·과거가 동일 척도(전체대비 vol%)라
    pulse KV 이력 누적 없이도 즉시 정합. region_q = build_pulse REGIONS 의 GDELT 지역 쿼리.

    base 주면 pulse-worker(data.enxight.com/gdelt) 경유 — GitHub 러너 IP 스로틀 회피
    (2026-07-06, artlist 뉴스 밀도 축과 동일 전략). 미지정 시 GDELT 직접(하위호환).
    """
    q = f"{region_q} sourcelang:english"
    if base:
        url = f"{base}?" + urllib.parse.urlencode(
            {"query": q, "mode": "timelinevol", "timespan": "60d"})
        headers = {**UA, "Authorization": f"Bearer {token}"}
    else:
        url = f"{GDELT_DOC}?query={urllib.parse.quote(q)}&mode=timelinevol&timespan=60d&format=json"
        headers = None
    for attempt in range(3):
        try:
            pts = _http_json(url, headers=headers)["timeline"][0]["data"]
            vals = [float(p["value"]) for p in pts]
            if len(vals) < M_MIN + 2:
                return None, 0
            # 마지막 점(당일)은 부분집계·최신 인덱싱 편향(실측 p≈100 쏠림 정황) → 전일을 today 로.
            # 가격의 "전일 종가" 원칙과도 시점 일관.
            today, hist = vals[-2], vals[:-2]
            return round(percentile_rank(hist, today), 1), len(hist)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(15)  # GDELT rate limit 백오프 재시도 (fetch_news 와 동일 전략)
                continue
            return None, 0
        except Exception:
            return None, 0


def build_signal(price_regions, news_matrix, news_history, region_q_map=None, symbol_map=None, gdelt_base=None, gdelt_token=None):
    """SIGNAL_SPEC signal 블록 생성.

    price_regions: pulse price.regions (각 {id, chg, ...})
    news_matrix:   오늘 news.matrix {region: [counts...]} (GDELT 실패 시 폴백용)
    news_history:  과거 news.matrix list (pulse 이력 — GDELT 실패 시 폴백용)
    region_q_map:  {region: GDELT 지역 쿼리} — 주면 뉴스축을 timelinevol 백필로(60일 즉시)
    """
    out = {"spec_version": SPEC_VERSION, "window": WINDOW, "theta": THETA, "regions": {}}

    # 뉴스 과거 분포 (지역별 일별 총량)
    news_dist = {}
    for h in news_history:
        for rid, counts in (h or {}).items():
            news_dist.setdefault(rid, []).append(sum(counts))

    for r in price_regions:
        rid = r.get("id")
        chg = r.get("chg")
        if rid is None or chg is None:
            continue

        # 가격 백분위 — 과거 |일수익률| 분포 (다중 소스 ladder)
        closes, psrc = price_history_closes(rid, (symbol_map or {}).get(rid))
        p_price = z_price = None
        n_price = 0
        if closes:
            ar = abs_returns(closes)
            n_price = len(ar)
            if ar:
                p_price = round(percentile_rank(ar, abs(chg)), 1)
                s = pstdev(ar) if len(ar) > 1 else 0
                z_price = round((abs(chg) - mean(ar)) / s, 2) if s else None

        # 뉴스 백분위 — GDELT timelinevol 우선(60일 즉시, today=마지막점·분포=과거),
        # 실패 시 pulse 이력 폴백. timelinevol 은 실시간·과거 동일 척도(전체대비 vol%)라 정합.
        p_news = None
        n_news = 0
        news_src = None
        rq = (region_q_map or {}).get(rid)
        if rq:
            p_news, n_news = gdelt_news_percentile(rq, base=gdelt_base, token=gdelt_token)
            if p_news is not None:
                news_src = "gdelt"
            time.sleep(15)  # GDELT rate limit 간격 — 4/7→7/7 위해 확대(분당 ~4 호출로 여유)
        if p_news is None:  # 폴백 — pulse 이력
            # ⚠️ 2026-08-10: today 행이 없으면 폴백 자체를 포기한다(p_news=None 유지).
            #   호출부(build_pulse.main)가 news_matrix 를 의도적으로 {} 로 넘기므로
            #   sum({}.get(rid, [])) == 0 → percentile_rank(hist, 0) == 0.0 이 되어,
            #   GDELT 조회 실패 지역이 전부 '뉴스 강도 0백분위' 로 확정 렌더됐다.
            #   0.0 은 None 이 아니라 news_ok 를 통과해 zone 까지 산출 → sig_n 이 영구 False,
            #   해당 지역은 pressure/trend 로 절대 분류되지 않는다(제품 핵심 기능 침묵 정지).
            #   '기사 0건'과 '수집 실패'는 다르다 — 후자는 점을 그리지 않는 것이 정직하다
            #   (렌더러가 p_news==null 을 이미 skip 처리: public/pulse/index.html:502).
            today_row = news_matrix.get(rid)
            hist = news_dist.get(rid, [])
            n_news = len(hist)
            if hist and today_row:
                p_news = round(percentile_rank(hist, sum(today_row)), 1)
                news_src = "pulse_hist"

        # 축별 독립 신뢰 — 가격(네이버/TD 과거 N일)은 즉시, 뉴스(pulse 이력)는 가용분.
        # 한 축이 부족해도 다른 축은 살린다(min 묶음 폐기). zone(영역)은 두 축 모두 신뢰일 때만.
        price_ok = p_price is not None and n_price >= M_MIN
        news_ok = p_news is not None and n_news >= M_MIN
        zone = strength = None
        if price_ok and news_ok:
            sig_p = p_price >= THETA
            sig_n = p_news >= THETA
            zone = ("trend" if (sig_n and sig_p)
                    else "pressure" if sig_n
                    else "quiet" if sig_p
                    else "calm")
            strength = round((p_news ** 2 + p_price ** 2) ** 0.5 / (2 ** 0.5), 1)

        out["regions"][rid] = {
            "p_news": p_news, "p_price": p_price, "chg": chg,
            "zone": zone, "strength": strength,
            "n_price": n_price, "n_news": n_news,
            "price_provisional": n_price < M_PROV,
            "news_provisional": n_news < M_PROV,
            "price_src": psrc, "news_src": news_src, "z_price": z_price,
        }
    return out
