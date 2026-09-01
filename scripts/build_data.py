#!/usr/bin/env python3
"""K-RE MAP 데이터 배치 빌더 — public/data.json 생성.

흐름 (HANDOFF §4 + PATCH v1.1):
  [R-ONE 매매가격지수 + 국토부 실거래가]  ->  public/data.json  ->  (push)  ->  CF 재배포

모드:
  python scripts/build_data.py            # 실데이터 수집 (기본)
  python scripts/build_data.py --sample   # 샘플 데이터로 생성 (구조 검증)

소스:
  - 색상(변동률)·추이: 한국부동산원 R-ONE OpenAPI (REP_API_KEY)
      월간 아파트 매매가격지수 STATBL_ID=A_2024_00045 (m/q/y/trends)
      주간 매매가격지수      STATBL_ID=T244183132827305 (w)
      지역 식별: CLS_FULLNM 계층 경로 ("서울>강남구", "경기>경부1권>수원시")
  - 규모(타일)·중위가: 국토부 아파트 매매 실거래가 (DATA_GO_API_KEY)
      RTMSDataSvcAptTradeDev · scripts/lawd_codes.json 의 LAWD_CD · 전월 1개월 집계
      정제: 해제건·직거래 제외, 소표본(<5건) 대표가 비표시 — docs/DATA_QUALITY_CHECKLIST.md

원칙:
  - 모든 시간 KST(UTC+9). 키는 .env/OS env 에서만 — 산출물·프론트로 절대 안 감.
  - 지역 목록 기준 = src/data/sample.json 이름 (지도·트리맵 조인 검증된 SSoT).
  - 두 소스(지수+실거래) 모두 있는 시군구만 children 에 포함 — 없는 곳은 지도에서 회색.

산출 스키마 v1.2 (src/data/useRegionData.js 와 계약):
  { schema_version, generated_at, source, sido, children, trends, series, asof }
  행 = [이름, 규모, 중위가(억)|null, 주간%, 월간%, 분기%, 연간%, 거래건수]
  series = { "지역라벨": {start: "YYYYMM", vals: [...]} }  # 월간 지수 ~120개월 — 반기·기타 프론트 계산
  asof = { monthly, weekly, trade_ym, trade_provisional }  # 잠정 = 신고 시차 (익월 말까지)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "src" / "data" / "sample.json"
LAWD = ROOT / "scripts" / "lawd_codes.json"
OUT = ROOT / "public" / "data.json"

RONE_BASE = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
RONE_MONTHLY = "A_2024_00045"      # (월) 매매가격지수_아파트
RONE_WEEKLY = "T244183132827305"   # (주) 매매가격지수
# 2026-08-03: 평문 http 는 국토부가 더 이상 받지 않는다(무응답 → 30s TimeoutError).
# 7/31·8/3 data-refresh 실패 원인 — 연속 6건 timeout 이 '전면 장애' 가드를 정확히 발동시켰고,
# 가드는 의도대로 동작했으나 진짜 원인은 스킴이었다. https 는 0.1초 정상 응답(resultCode 000).
# R-ONE(https)이 같은 런에서 성공한 것이 스킴 문제라는 결정적 단서였다.
TRADE_BASE = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

# 2026-07-01 행정구역 개편: 광주+전남 → 전남광주통합특별시 (시도 17→16)
SIDO16 = ["서울", "부산", "대구", "인천", "전남광주", "대전", "울산", "세종",
          "경기", "강원", "충북", "충남", "전북", "경북", "경남", "제주"]

# R-ONE 지역 체계가 아직 舊 시도명(광주/전남)이라 별칭으로 흡수.
# 부동산원이 통합 명칭으로 개정해도 그대로 매핑되도록 신명칭도 등재.
RONE_SIDO_ALIAS = {"광주": "전남광주", "전남": "전남광주",
                   "전남광주통합특별시": "전남광주"}


def now_kst() -> datetime:
    return datetime.now(KST)


def load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    for k in ("DATA_GO_API_KEY", "REP_API_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def http_json(url: str, retries: int = 3) -> dict:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kremap-batch)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(4 * (i + 1))  # 2026-07-07: R-ONE 산발적 RemoteDisconnected 대비 백오프 확대(4·8s)


def http_xml(url: str, retries: int = 3) -> ET.Element:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kremap-batch)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return ET.fromstring(r.read())
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


# ──────────────────────────────────────────────────────────────
# R-ONE — 가격지수 (변동률·추이)
# ──────────────────────────────────────────────────────────────

def rone_rows(key: str, statbl: str, cycle: str, start: str, end: str) -> list[dict]:
    rows, page = [], 1
    while True:
        q = urllib.parse.urlencode({
            "KEY": key, "Type": "json", "STATBL_ID": statbl, "DTACYCLE_CD": cycle,
            "START_WRTTIME": start, "END_WRTTIME": end, "pIndex": page, "pSize": 1000,
        })
        d = http_json(f"{RONE_BASE}?{q}")
        if "SttsApiTblData" not in d:  # 데이터 없음 (RESULT 만 반환)
            break
        got = [r for blk in d["SttsApiTblData"] if "row" in blk for r in blk["row"]]
        rows += got
        if len(got) < 1000:
            break
        page += 1
    return rows


def preflight(env: dict) -> list[str]:
    """수집 전 외부 API 1건씩 실제 호출해 가용성·스킴을 확인한다.

    R66(2026-08-03) 대응 — 국토부가 평문 http 를 폐지했을 때 증상이 '30초 무응답'
    이었다. 인증 오류나 4xx 가 아니라 타임아웃이라 코드 버그처럼 보였고, 진단에
    두 번의 실패일(7/31·8/3)이 걸렸다. 여기서 먼저 1건을 때려 보면 같은 유형의
    엔드포인트 변경이 **수집 시작 전에, 명확한 문장으로** 드러난다.

    실패해도 중단하지 않는다(반환값은 경고 목록) — 판단은 기존 가드가 한다.
    """
    warns: list[str] = []
    probes = [
        ("R-ONE 지수", f"{RONE_BASE}?" + urllib.parse.urlencode({
            "KEY": env.get("REP_API_KEY", ""), "Type": "json", "STATBL_ID": RONE_MONTHLY,
            "DTACYCLE_CD": "MM", "START_WRTTIME": "202601", "END_WRTTIME": "202601",
            "pIndex": 1, "pSize": 1})),
        ("국토부 실거래가", f"{TRADE_BASE}?" + urllib.parse.urlencode({
            "serviceKey": env.get("DATA_GO_API_KEY", ""), "LAWD_CD": "11680",
            "DEAL_YMD": (now_kst().replace(day=1) - timedelta(days=1)).strftime("%Y%m"),
            "numOfRows": 1, "pageNo": 1})),
    ]
    for name, url in probes:
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (kremap-batch)"})
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read(512)
            print(f"  [preflight] {name}: OK ({time.time() - t0:.1f}s)")
        except Exception as e:
            scheme = url.split("://", 1)[0]
            hint = ""
            if isinstance(e, TimeoutError) and scheme == "http":
                hint = " ← 평문 http 폐지 의심: https 로 바꿔 재시도해 볼 것 (R66 과 동일 유형)"
            msg = f"{name} 사전점검 실패 [{scheme}] {type(e).__name__}{hint}"
            warns.append(msg)
            print(f"  [preflight] ⚠️ {msg} ({time.time() - t0:.1f}s)")
    return warns


def parse_region(cls_fullnm: str | None, app_names: dict) -> tuple[str, str | None] | None:
    """CLS_FULLNM → (시도, 시군구|None). 권역·시 하위 구·전국은 None 반환."""
    # 2026-07-29: R-ONE 이 7/16부터 CLS_FULLNM 이 null 인 행을 섞어 반환하기 시작
    # (AttributeError 로 data-refresh 13일 연속 실패). 식별 불가 행은 조용히 버린다.
    if not cls_fullnm:
        return None
    tokens = cls_fullnm.split(">")
    sido = RONE_SIDO_ALIAS.get(tokens[0], tokens[0])
    if sido not in app_names:
        return None  # 전국·수도권 등
    if len(tokens) == 1:
        return (sido, None)
    # 2026-08-08 (R79): R-ONE 이 8/7 부터 통합시 계층을 재편 — 시도급 '광주'/'전남'
    # (1토큰)이 사라지고 '전남광주>광주'/'전남광주>전남'(2토큰)으로 강등됐다.
    # 마지막 토큰이 이 시도로 별칭되는 구성 시도명이면 **시도급 부분 시계열**로
    # 취급한다(fetch_rone 의 시점별 누적 평균이 두 부분을 병합 — 7/3 설계 그대로).
    # 시군구('전남광주>전남>목포시')는 기존 로직이 그대로 처리한다.
    if len(tokens) == 2 and RONE_SIDO_ALIAS.get(tokens[1]) == sido:
        return (sido, None)
    last = tokens[-1]
    if last in app_names[sido]:
        return (sido, last)
    return None  # 권역(경부1권 등)·앱 미사용 지역·시 하위 구


MONTHS_BACK = 121  # 월간 시계열 수집 범위 — custom 기간 최대 120개월(10년) + 1 (변동률 기준점)
# R-ONE 월간 지수는 2003-11 부터 존재 (2026-06-10 확인). 전체 필요 시 이 상수만 확대.


def fetch_rone(key: str, app_names: dict) -> dict:
    """지역별 지수 시계열 수집 → {(시도, 시군구|None): {"mm": {YYYYMM: val}, "wk": [(주차, val)...]}}"""
    now = now_kst()
    # 월간: 최근 MONTHS_BACK 개월
    y, m = now.year, now.month - (MONTHS_BACK - 1)
    while m <= 0:
        m += 12
        y -= 1
    start_mm = f"{y}{m:02d}"
    mm = rone_rows(key, RONE_MONTHLY, "MM", start_mm, now.strftime("%Y%m"))
    # 주간: 최근 ~10주 (ISO 주차 — 연초 경계 대비 전년 44주부터)
    iso_y, iso_w, _ = now.isocalendar()
    wk_start = f"{iso_y - 1}44" if iso_w <= 8 else f"{iso_y}{iso_w - 8:02d}"
    # 2026-07-07 fail-soft: RONE_WEEKLY 엔드포인트가 산발적으로 RemoteDisconnected 로 죽어
    # (7/3·7/5·7/6 data-refresh 3회 실패·매번 수동 재트리거) 전체 발행을 막던 단일장애점 제거.
    # 주간(w 컬럼)은 부가 지표라 실패 시 빈 리스트 → index_metrics 가 w=0.0 으로 degrade,
    # 월간·분기·연간·규모는 정상 발행. 월간(mm)은 핵심(색상=지수)이라 fail-soft 대상 아님.
    try:
        wk = rone_rows(key, RONE_WEEKLY, "WK", wk_start, f"{iso_y}53")
    except Exception as e:
        print(f"[build_data] WARN R-ONE 주간지수 수집 실패({type(e).__name__}) — w 컬럼 0 홀딩, 월간만으로 발행")
        wk = []

    # 시점별로 값을 누적 후 평균 — 별칭 병합(광주+전남→전남광주)으로 한 시점에
    # 복수 지수가 모이면 산술평균(과도기 근사 지수).
    # 2026-08-08 (R79): 시점별로 직접(d)/부분(p) 시계열을 분리 누적 — R-ONE 이 통합
    # 시도(1토큰 '전남광주')를 직접 제공하기 시작하면 그 시점부터 **직접값만** 쓰고,
    # 없으면 부분(전남광주>광주 + 전남광주>전남) 평균을 쓴다. 직접+부분이 공존하는
    # 시점에 셋을 평균해 왜곡되는 것을 차단.
    def _direct(row) -> bool:
        return len(str(row.get("CLS_FULLNM") or "").split(">")) == 1

    acc: dict = {}

    def _add(row, kind: str) -> None:
        reg = parse_region(row.get("CLS_FULLNM"), app_names)
        if not reg:
            return
        slot = acc.setdefault(reg, {"mm": {}, "wk": {}})[kind].setdefault(
            row["WRTTIME_IDTFR_ID"], {"d": [], "p": []})
        # 시군구 행은 항상 유일(직접 취급) · 시도 행만 1토큰=직접 / 2토큰=부분
        direct = reg[1] is not None or _direct(row)
        slot["d" if direct else "p"].append(row["DTA_VAL"])

    for r in mm:
        _add(r, "mm")
    for r in wk:
        _add(r, "wk")

    def _avg(slot: dict) -> float:
        vs = slot["d"] or slot["p"]
        return sum(vs) / len(vs)

    return {reg: {kind: {t: _avg(slot) for t, slot in s[kind].items()}
                  for kind in ("mm", "wk")}
            for reg, s in acc.items()}


def pct(cur: float, base: float | None) -> float | None:
    if base is None or not base:
        return None
    return round((cur / base - 1) * 100, 2)


def index_metrics(s: dict) -> dict | None:
    """시계열 → {w, m, q, y, trend12}. 월간 최신 기준 m/q/y, 주간 최신 2개로 w."""
    mm = sorted(s["mm"].items())
    if len(mm) < 13:
        return None
    vals = [v for _, v in mm]
    cur = vals[-1]
    m = pct(cur, vals[-2])
    q = pct(cur, vals[-4])
    y = pct(cur, vals[-13])
    wk = sorted(s["wk"].items())
    w = pct(wk[-1][1], wk[-2][1]) if len(wk) >= 2 else None
    if None in (m, q, y):
        return None
    trend = [round(v / cur * 100, 2) for v in vals[-12:]]
    return {"w": w if w is not None else 0.0, "m": m, "q": q, "y": y,
            "trend": trend, "asof_mm": mm[-1][0], "asof_wk": wk[-1][0] if wk else None}


# ──────────────────────────────────────────────────────────────
# 국토부 실거래가 — 규모(타일)·평균가
# ──────────────────────────────────────────────────────────────

def fetch_trades(key: str, lawd: dict, deal_ymd: str) -> dict:
    """{(시도, 시군구): {"n": 건수, "amt_sum": 만원합, "prices": [만원...]}} — 시군구별 전월 집계.

    정제 4대 룰 (docs/DATA_QUALITY_CHECKLIST.md A-1):
      해제건 제외(cdealType='O' 또는 해제일 존재) · 직거래 제외(dealingGbn='직거래')
      잠정 라벨은 build_real_payload 에서 · 소표본 가드는 병합 단계에서

    fail-soft (2026-06-16): data.go.kr 실거래가 API 의 산발적 timeout 으로 전체 수집이
      죽지 않게 — 코드별 호출 실패는 skip 하고 계속(부분 장애 → build_real_payload 의
      80개 가드가 판단). 단 연속 MAX_CONSEC_FAIL 건 실패는 전면 장애로 보고 조기 중단
      (→ 기존 data.json 유지 + 실패 알림). 이전엔 한 지역 timeout 의 raise 로 수집 전체가
      죽어 80개 가드에 도달조차 못 했음 (6/10·6/12·6/16 반복 거짓경보 원인).
    """
    out = {}
    total_calls = sum(len(codes) for m in lawd.values() for codes in m.values())
    done = 0
    excluded = {"cancel": 0, "direct": 0}
    failed: list = []          # API 호출 실패로 skip 한 (시도, 시군구, code)
    consec = 0                 # 연속 실패 카운터 (전면 장애 조기 감지)
    MAX_CONSEC_FAIL = 6        # 연속 이만큼 실패하면 API 전면 장애로 판단·중단
    for sido, munis in lawd.items():
        for muni, codes in munis.items():
            prices = []
            for code in codes:
                q = urllib.parse.urlencode({
                    "serviceKey": key, "LAWD_CD": code, "DEAL_YMD": deal_ymd,
                    "numOfRows": 3000, "pageNo": 1,
                })
                try:
                    root = http_xml(f"{TRADE_BASE}?{q}", retries=2)
                    consec = 0
                except Exception as e:
                    consec += 1
                    failed.append((sido, muni, code))
                    print(f"  [trade] SKIP {sido} {muni} {code}: {type(e).__name__}: {e}")
                    if consec >= MAX_CONSEC_FAIL:
                        raise RuntimeError(
                            f"실거래가 API 전면 장애 추정: 연속 {consec}건 timeout "
                            f"(누적 실패 {len(failed)}/{total_calls}). 이전 data.json 유지."
                        )
                    continue
                rc = root.findtext(".//resultCode") or ""
                if rc not in ("000", "00"):
                    print(f"  [trade] WARN {sido} {muni} {code}: resultCode={rc} {root.findtext('.//resultMsg')}")
                    continue
                tc = int(root.findtext(".//totalCount") or 0)
                if tc > 3000:
                    print(f"  [trade] WARN {sido} {muni} {code}: totalCount={tc} > 3000 (일부 누락)")
                for item in root.iter("item"):
                    raw = (item.findtext("dealAmount") or "").replace(",", "").strip()
                    if not raw:
                        continue
                    cdeal_type = (item.findtext("cdealType") or "").strip()
                    cdeal_day = (item.findtext("cdealDay") or "").strip()
                    if cdeal_type == "O" or cdeal_day:  # 해제건 — 실거래가 띄우기 방어
                        excluded["cancel"] += 1
                        continue
                    if (item.findtext("dealingGbn") or "").strip() == "직거래":  # 증여성 저가 왜곡 방어
                        excluded["direct"] += 1
                        continue
                    prices.append(int(raw))
                done += 1
                if done % 30 == 0:
                    print(f"  [trade] {done}/{total_calls} calls")
                time.sleep(0.08)
            if prices:
                out[(sido, muni)] = {"n": len(prices), "amt_sum": sum(prices), "prices": prices}
    print(f"  [trade] 제외: 해제 {excluded['cancel']}건 · 직거래 {excluded['direct']}건")
    if failed:
        print(f"  [trade] WARN API 실패로 skip {len(failed)}/{total_calls}건 (부분 장애, 수집 계속)")
    return out


# ──────────────────────────────────────────────────────────────
# 병합 → payload
# ──────────────────────────────────────────────────────────────

def _load_prev_trades() -> tuple[dict, str] | None:
    """이전 data.json 에서 거래 집계를 역산해 되살린다 (부분 성공 경로용).

    payload 는 원시 prices 배열을 담지 않으므로(용량) 행에 남은 값으로 재구성한다:
      행 = [이름, 규모(amt_sum/1e6), 중위가(억)|null, w, m, q, y, 거래건수]
    → amt_sum = 규모*1e6 · n = 거래건수 · prices 는 중위가만 복원 가능하므로
      price_of() 가 그 값을 그대로 돌려주도록 `median_hint` 로 넘긴다.
    반환: ({(시도,시군구): {...}}, 이전 trade_ym) · 없거나 손상이면 None.
    """
    if not OUT.exists():
        return None
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        if prev.get("source") != "rone+datago":
            return None  # 샘플 데이터는 이어받지 않는다
        out: dict = {}
        for sido, rows in (prev.get("children") or {}).items():
            for r in rows:
                muni, size, med, *_rest = r
                n = r[7] if len(r) > 7 else 0
                if not n:
                    continue
                out[(sido, muni)] = {"n": n, "amt_sum": round(size * 1e6),
                                     "prices": [], "median_hint": med}
        ym = (prev.get("asof") or {}).get("trade_ym")
        return (out, ym) if out and ym else None
    except Exception as e:
        print(f"  [carry] 이전 data.json 파싱 실패: {type(e).__name__}")
        return None


def build_real_payload(env: dict) -> dict:
    missing = [k for k in ("DATA_GO_API_KEY", "REP_API_KEY") if not env.get(k)]
    if missing:
        sys.exit(f"[build_data] .env 키 없음: {', '.join(missing)}")

    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    # 시군구 화이트리스트 = lawd_codes(지도 topo 전수 156) — 옛 sample 기반(115)은 R-ONE
    # 보유 22개 지역(동해·김천·남원 등)을 놓쳤음 (2026-06-11 전국 확장)
    lawd_all = json.loads(LAWD.read_text(encoding="utf-8"))
    app_names = {sido: list(munis.keys()) for sido, munis in lawd_all.items()}
    lawd = json.loads(LAWD.read_text(encoding="utf-8"))

    print("[build_data] 외부 API 사전점검…")
    preflight(env)

    print("[build_data] R-ONE 지수 수집…")
    series = fetch_rone(env["REP_API_KEY"], app_names)
    print(f"  지역 시계열 {len(series)}개")

    # 전월 거래 (당월은 신고 지연으로 불완전)
    deal_ymd = (now_kst().replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    print(f"[build_data] 실거래가 수집 (DEAL_YMD={deal_ymd})…")
    # ── 부분 성공 경로 (R66 잔존 해소, 2026-08-03) ──────────────────────────
    # 종전엔 실거래가가 죽으면 R-ONE 이 멀쩡히 수집됐어도 payload 전체가 버려졌다
    # (all-or-nothing). 지도의 **색상=지수**가 핵심 지표인데 부가 지표(타일 크기·
    # 중위가) 하나 때문에 핵심까지 하루 늙는 건 손해가 크다.
    # → 실거래가 전면 장애 시 이전 data.json 의 거래 부분을 그대로 이어받고
    #   지수만 갱신한다. 이어받은 사실은 asof.trade_carried 로 **반드시 표기**
    #   (조용한 stale 금지 — 데이터가 자기 상태를 스스로 말하게 한다).
    trade_carried = False
    try:
        trades = fetch_trades(env["DATA_GO_API_KEY"], lawd, deal_ymd)
        print(f"  거래 집계 시군구 {len(trades)}개")
    except Exception as e:
        prev = _load_prev_trades()
        if prev is None:
            raise  # 이어받을 이전 값도 없으면 종전대로 중단
        trades, deal_ymd_prev = prev
        trade_carried = True
        print(f"  ⚠️ 실거래가 수집 실패({type(e).__name__}) → 이전 값 이어받기: "
              f"시군구 {len(trades)}개 · trade_ym={deal_ymd_prev} (지수는 신규 갱신)")
        deal_ymd = deal_ymd_prev

    MIN_SAMPLE = 5  # 소표본 가드 (CHECKLIST A-1): 미만이면 대표가 비표시

    def price_of(prices: list, median_hint: float | None = None) -> float | None:
        """대표가 = 중위가(억) — 거래 믹스(고가 단지 편중) 평균 착시 방어 (A-2).

        부분 성공 경로에서는 원시 prices 가 없고 이전 중위가만 남아 있으므로
        (`median_hint`) 그 값을 그대로 쓴다 — 소표본 판정은 이미 그때 적용된 값이다.
        """
        if median_hint is not None and not prices:
            return median_hint
        if len(prices) < MIN_SAMPLE:
            return None
        return round(median(prices) / 10000, 2)

    def series_payload(s: dict) -> dict | None:
        """월간 지수 원시 시계열 (custom 기간 프론트 계산용). vals 끝 = 최신."""
        mm = sorted(s["mm"].items())
        if len(mm) < 13:
            return None
        return {"start": mm[0][0], "vals": [round(v, 2) for _, v in mm]}

    # 2026-08-08 (R79 안전망): 시도 지수가 소스에서 사라져도 소수(≤2)면 직전 발행본
    # (public/data.json)의 지수·추이·시계열을 이어받아 발행을 지속한다 — R-ONE 지역
    # 체계 재변경류 사고에서 라이브가 통째로 늙는 것(8/6~8/8 49h 열화)을 방지.
    # 규모·중위가·건수·시군구는 항상 신선분으로 계산(지수 축만 이어받음). 3개 이상
    # 결손이면 광역 장애로 보고 종전대로 fail-closed(아래 게이트).
    prev_rows, prev_trends, prev_series = {}, {}, {}
    try:
        if OUT.exists():
            _prev = json.loads(OUT.read_text(encoding="utf-8"))
            prev_rows = {r[0]: r for r in _prev.get("sido", [])}
            prev_trends = _prev.get("trends", {})
            prev_series = _prev.get("series", {})
    except Exception as _e:  # noqa: BLE001 — 이어받기 실패는 기존 fail-closed 로
        print(f"  [merge] WARN 직전 data.json 로드 실패({type(_e).__name__}) — 이어받기 비활성")

    sido_rows, children, trends, series_out = [], {}, {}, {}
    carried_sidos: list = []
    asof_mm = asof_wk = None
    for sido in SIDO16:
        sm = series.get((sido, None))
        met = index_metrics(sm) if sm else None
        carried = False
        if not met and sido in prev_rows and prev_trends.get(sido):
            pr = prev_rows[sido]  # [이름, 규모, 중위가, w, m, q, y, 건수]
            met = {"w": pr[3], "m": pr[4], "q": pr[5], "y": pr[6],
                   "trend": prev_trends[sido], "asof_mm": None, "asof_wk": None}
            carried = True
            carried_sidos.append(sido)
            print(f"  [merge] ⚠️ 시도 지수 이어받기: {sido} — 소스 결손, 직전 발행본 지수 사용(규모·거래는 신선)")
        if not met:
            print(f"  [merge] WARN 시도 지수 없음: {sido}")
            continue
        if met["asof_mm"]:  # 이어받기(asof=None)가 신선 asof 를 덮지 않게
            asof_mm = met["asof_mm"]
            asof_wk = met["asof_wk"] or asof_wk
        # 시도 규모·중위가 = 보유 시군구 롤업 (세종은 자체 LAWD)
        s_prices = [p for (s, _), t in trades.items() if s == sido for p in t["prices"]]
        t_amt = sum(t["amt_sum"] for (s, _), t in trades.items() if s == sido)
        size = round(t_amt / 1e6, 2)  # 만원 합 → 백억 단위 (상대 가중치)
        # 이어받기 모드에선 원시 prices 가 없으므로 시도 중위가·건수는 시군구 값에서 재구성
        s_hints = [t["median_hint"] for (s, _), t in trades.items()
                   if s == sido and t.get("median_hint") is not None]
        s_n = sum(t["n"] for (s, _), t in trades.items() if s == sido)
        # 행: [이름, 규모, 중위가(억)|null, w, m, q, y, 거래건수]
        sido_rows.append([sido, size,
                          price_of(s_prices, round(median(s_hints), 2) if (trade_carried and s_hints) else None),
                          met["w"], met["m"], met["q"], met["y"],
                          s_n if trade_carried else len(s_prices)])
        trends[sido] = met["trend"]
        sp = series_payload(sm) if sm else None
        if sp:
            series_out[sido] = sp
        elif carried and prev_series.get(sido):
            series_out[sido] = prev_series[sido]  # 반기·custom 기간 프론트 계산 유지

        rows = []
        for muni in app_names.get(sido, []):
            ms = series.get((sido, muni))
            mmet = index_metrics(ms) if ms else None
            tr = trades.get((sido, muni))
            if not mmet and not tr:
                continue  # 두 소스 다 없으면 제외 (2026-06-11: AND→OR — 한쪽만 있어도 표시)
            rows.append([muni,
                         round(tr["amt_sum"] / 1e6, 2) if tr else 0,
                         price_of(tr["prices"], tr.get("median_hint")) if tr else None,
                         mmet["w"] if mmet else None, mmet["m"] if mmet else None,
                         mmet["q"] if mmet else None, mmet["y"] if mmet else None,
                         tr["n"] if tr else 0])
            if mmet:
                trends[f"{sido} {muni}"] = mmet["trend"]
                msp = series_payload(ms)
                if msp:
                    series_out[f"{sido} {muni}"] = msp
        # size=0(지수만 보유·전월 거래 0) 타일이 트리맵에서 실종되지 않게 — 시도 내 최소 양수의 40%
        pos = [r[1] for r in rows if r[1] > 0]
        if pos:
            floor = round(min(pos) * 0.4, 2)
            for r in rows:
                if r[1] <= 0:
                    r[1] = floor
        if rows:
            children[sido] = rows

    n_muni = sum(len(v) for v in children.values())
    n_small = sum(1 for v in children.values() for r in v if r[2] is None)
    print(f"[build_data] 병합: 시도 {len(sido_rows)} · 시군구 {n_muni} (소표본 {n_small}) · trends {len(trends)}"
          + (f" · 이어받기 {carried_sidos}" if carried_sidos else ""))
    # 이어받기는 안전망이지 정상 운영이 아니다 — 3개 이상이면 광역 장애(소스 전멸·
    # 지역 체계 대개편 등)로 보고 낡은 지수로 덮지 않고 종전대로 발행을 멈춘다.
    if len(carried_sidos) > 2:
        sys.exit(f"[build_data] FAIL: 시도 지수 이어받기 {len(carried_sidos)}건({carried_sidos}) — 광역 장애 의심, 발행 중단")
    if len(sido_rows) < 16:
        sys.exit("[build_data] FAIL: 시도 16개 미달 — 발행 중단 (이전 data.json 유지)")
    # 거래 수집 전멸/부분 실패 가드 — size 0 시도는 트리맵에서 타일 실종 (silent 회귀 방지)
    zero_size = [r[0] for r in sido_rows if r[1] <= 0]
    if len(trades) < 80 or zero_size:
        sys.exit(f"[build_data] FAIL: 실거래 수집 이상 (시군구 {len(trades)}개, size=0 시도 {zero_size}) — 발행 중단")

    # 신고 시차 (A-1): 계약 후 30일 내 신고 → 거래월 익월 말까지 잠정
    ym = datetime.strptime(deal_ymd, "%Y%m").replace(tzinfo=KST)
    report_deadline = (ym + timedelta(days=62)).replace(day=1)  # 익익월 1일 = 익월 말 경과
    provisional = now_kst() < report_deadline

    return {
        "schema_version": "1.2",
        "generated_at": now_kst().isoformat(timespec="seconds"),
        "source": "rone+datago",
        # trade_carried=true 면 거래 지표(규모·중위가·건수)는 이전 회차 값을 이어받은 것이고
        # 지수(색상)만 신규다 — 프론트·감시가 이 플래그로 stale 여부를 판별한다.
        "asof": {"monthly": asof_mm, "weekly": asof_wk,
                 "trade_ym": deal_ymd, "trade_provisional": provisional,
                 "trade_carried": trade_carried,
                 # R79 안전망 — 지수 축을 직전 발행본에서 이어받은 시도 목록(빈 배열=전부 신선).
                 # trade_carried 와 동형의 잠정 고지 플래그. 프론트는 미인지 키 무시(additive).
                 "index_carried_sido": carried_sidos},
        "sido": sido_rows,
        "children": children,
        "trends": trends,
        "series": series_out,  # 월간 지수 원시 시계열 (최근 ~120개월) — 기타(custom)·반기 프론트 계산
    }


def build_sample_payload() -> dict:
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return {
        "schema_version": "1.0",
        "generated_at": now_kst().isoformat(timespec="seconds"),
        "source": "sample",
        "sido": sample["sido"],
        "children": sample["children"],
        "trends": None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="샘플 데이터로 data.json 생성")
    args = ap.parse_args()

    print(f"[build_data] {now_kst().isoformat(timespec='seconds')} KST · mode={'sample' if args.sample else 'real'}")
    payload = build_sample_payload() if args.sample else build_real_payload(load_env())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT)
    print(f"[build_data] wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
