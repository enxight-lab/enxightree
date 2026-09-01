#!/usr/bin/env python3
"""pulse 이력 분포 분석 — z-score 시그널 임계·정의를 데이터로 확정 (재캘리브레이션용).

일부 네트워크에서 data.enxight.com 이 차단되므로 GitHub Actions 러너에서 실행한다
(pulse 발행처). 표준 라이브러리만 (build_pulse.py 원칙 동일, CI 의존성 0).

목적 — 추측 임계(절대 0.5%/1.5%·1.8/0.8배)를 실분포로 검증하고 다음을 확정:
  1) 지역별 절대임계 백분위가 갈리는가 = 정규화(z-score) 필요성
  2) |z|>=1.5σ 실제비율이 정규(13.4%) 대비 큰가 = fat-tail = 경험적 분위수 권장
  3) 뉴스 ratio 의 ln 분포·현재 1.8/0.8배 위치
  4) baseline 기사수 안정성 = 소표본 가드 필요성
출력 로그를 근거로 docs 정의서 + build_pulse 캘리브레이션을 확정한다.
"""
import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone
from statistics import mean, median, pstdev

KST = timezone(timedelta(hours=9))
WORKER = "https://data.enxight.com"
LOOKBACK = 150  # 받을 최대 일수 (있는 만큼)
# UA 필수 — Cloudflare 가 기본 Python-urllib UA 를 봇 차단(403). build_pulse.http_json 과 동일.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) enxight-analyze"}


def get(date):
    try:
        req = urllib.request.Request(f"{WORKER}/pulse/{date}.json", headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception:
        return None


def pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def rank_top(sorted_vals, x):
    """x 가 분포에서 상위 몇 % 인가 (큰 값이 상위)."""
    if not sorted_vals:
        return 0.0
    below = sum(1 for v in sorted_vals if v < x)
    return (1 - below / len(sorted_vals)) * 100


def excess_kurtosis(xs):
    if len(xs) < 4:
        return 0.0
    m, s = mean(xs), pstdev(xs)
    if s == 0:
        return 0.0
    return sum(((x - m) / s) ** 4 for x in xs) / len(xs) - 3


def main():
    days = [(datetime.now(KST) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(LOOKBACK)]
    got = [(d, v) for d, v in ((d, get(d)) for d in days) if v]
    got.sort(key=lambda x: x[0])  # 과거 -> 현재
    print(f"[dist] 이력 수집: {len(got)}/{LOOKBACK}일", end="")
    print(f" (최古 {got[0][0]} ~ 최신 {got[-1][0]})" if got else " — 데이터 0")
    if len(got) < 20:
        print("[dist] WARN 표본 부족(<20일) — sigma 추정 불안정. 결과는 잠정.")
    if not got:
        return

    REG = {}
    for _, v in got:
        mat = (v.get("news") or {}).get("matrix") or {}
        for r in (v.get("price") or {}).get("regions", []):
            rid = r["id"]
            REG.setdefault(rid, {"name": r["name"], "chg": [], "news": []})
            if r.get("chg") is not None:
                REG[rid]["chg"].append(r["chg"])
            REG[rid]["news"].append(sum(mat.get(rid, [])))

    print("\n=== (1) 가격 |chg| 분포 — 현재 절대임계 0.5%/1.5% 의 지역별 상위 백분위 ===")
    print(f"{'지역':<6}{'n':>4}{'sigma%':>8}{'p50':>7}{'p85':>7}{'p95':>7}{'kurt':>7}{'0.5%=상위':>10}{'1.5%=상위':>10}")
    for o in REG.values():
        chg = o["chg"]
        if len(chg) < 10:
            continue
        ab = sorted(abs(c) for c in chg)
        print(f"{o['name']:<6}{len(chg):>4}{pstdev(chg):>8.2f}{median(ab):>7.2f}"
              f"{pct(ab,.85):>7.2f}{pct(ab,.95):>7.2f}{excess_kurtosis(chg):>7.1f}"
              f"{rank_top(ab,0.5):>9.0f}%{rank_top(ab,1.5):>9.0f}%")

    print("\n=== (2) z-score 검증: |chg| >= 1.5sigma / 2sigma 실제비율 (정규=13.4% / 4.6%) ===")
    for o in REG.values():
        chg = o["chg"]
        if len(chg) < 10:
            continue
        m, s = mean(chg), pstdev(chg)
        if s == 0:
            continue
        o15 = sum(1 for c in chg if abs((c - m) / s) >= 1.5) / len(chg) * 100
        o2 = sum(1 for c in chg if abs((c - m) / s) >= 2) / len(chg) * 100
        print(f"  {o['name']:<6} |z|>=1.5s: {o15:5.1f}%   |z|>=2s: {o2:5.1f}%")

    print("\n=== (3) 뉴스 ratio = today / 직전7일평균 — ln 기준 + 현재 1.8/0.8배 위치 ===")
    for o in REG.values():
        seq = o["news"]
        ratios = []
        for i in range(len(seq)):
            base = [b for b in seq[max(0, i - 7):i] if b > 0]
            if base and seq[i] is not None and mean(base) > 0:
                ratios.append(seq[i] / mean(base))
        if len(ratios) < 10:
            continue
        lr = [math.log(x) for x in ratios if x > 0]
        sr = sorted(ratios)
        ge18 = sum(1 for x in ratios if x >= 1.8) / len(ratios) * 100
        le08 = sum(1 for x in ratios if x <= 0.8) / len(ratios) * 100
        print(f"  {o['name']:<6} n={len(ratios):>3} med={median(ratios):.2f} p85={pct(sr,.85):.2f} "
              f"max={max(ratios):.2f} | >=1.8x:{ge18:4.1f}% <=0.8x:{le08:4.1f}% | ln sigma={pstdev(lr):.2f}")

    print("\n=== (4) baseline 안정성: 직전7일 평균 기사수 (작으면 ratio 노이즈) ===")
    allbase = []
    for o in REG.values():
        seq = o["news"]
        for i in range(7, len(seq)):
            base = [b for b in seq[i - 7:i] if b > 0]
            if base:
                allbase.append(mean(base))
    if allbase:
        sb = sorted(allbase)
        print(f"  baseline 평균기사수: p10={pct(sb,.1):.0f} p50={median(sb):.0f} p90={pct(sb,.9):.0f}")

    print("\n[해석] (1)에서 0.5%/1.5% 상위비율이 지역마다 크게 갈리면 절대임계 부적절(정규화 필요). "
          "(2)에서 실제비율이 13.4%보다 크면 fat-tail -> 경험적 분위수 권장. "
          "(4) baseline 이 한 자릿수면 소표본 가드 필요.")


if __name__ == "__main__":
    main()
