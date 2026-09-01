#!/usr/bin/env python3
"""scripts/lawd_codes.json 생성 (일회성 · 행정구역 개편 시 재실행).

소스: PublicDataReader.code_bdong() — 행정표준 법정동코드 (개발 의존성, 런타임 불필요)
산출: { "시도명(앱 단축)": { "시군구명(앱)": ["LAWD_CD 5자리", ...] } }
  - 일반구 보유 시(수원시 등)는 구 코드 복수 — 실거래가 API 는 구 단위 코드만 받음
  - 말소일자 있는 코드 제외 (현행만)
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
import re

import PublicDataReader as pdr

ROOT = Path(__file__).resolve().parent.parent

SIDO_FULL = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "전남광주": "전남광주통합특별시",  # 2026-07-01 광주광역시+전라남도 통합 (LAWD 프리픽스 12)
    "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도",
}
# 데이터 기준일(2024.8) 이전 명칭 호환
SIDO_ALIAS = {"강원": ["강원도"], "전북": ["전라북도"]}


def main() -> None:
    df = pdr.code_bdong()
    cur = df[(df["말소일자"].fillna("") == "") & (df["시군구명"].fillna("") != "")]
    pairs = cur[["시도명", "시군구코드", "시군구명"]].drop_duplicates()

    out = {}
    miss = []
    for sido, full in SIDO_FULL.items():
        names = [full] + SIDO_ALIAS.get(sido, [])
        rows = pairs[pairs["시도명"].isin(names)]
        if sido == "세종":  # 하위 없음 + 시군구명이 빈 문자열 — 일반 필터(시군구명!='') 우회, 시 코드(36110) 직접 추출
            sj = df[(df["시도명"].isin(names)) & (df["말소일자"].fillna("") == "")]
            codes = sorted(c for c in sj["시군구코드"].unique().tolist() if not str(c).endswith("000"))
            if not codes:
                miss.append("세종 세종시")
            out[sido] = {"세종시": codes}
            continue
        # 전수 추출 (2026-06-11: 옛 SAMPLE 화이트리스트 폐기 — 115 지역 한계의 뿌리).
        # 일반구("수원시장안구"/"수원시 장안구")는 시 단위로 병합 — 앱 표시·R-ONE·topo
        # (geo.js resolveMuniName prefix 병합)와 동일 입도.
        m = {}
        for _, r in rows.iterrows():
            raw = str(r["시군구명"]).replace(" ", "")
            gm = re.match(r"^(.+?시)(.+[구군])$", raw)
            disp = gm.group(1) if gm else raw
            m.setdefault(disp, set()).add(str(r["시군구코드"]))
        out[sido] = {k: sorted(v) for k, v in sorted(m.items())}

    # 2026-07-01 개편 반영 전 소스 데이터로 재실행하면 수동 실측 매핑(전남광주 프리픽스 12,
    # 인천 제물포·영종·서해·검단)을 낡은 코드로 되돌리므로 차단 (PublicDataReader 기준일 확인).
    if not out.get("전남광주"):
        sys.exit("[gen_lawd_codes] ABORT: 소스 데이터에 전남광주통합특별시 없음 — "
                 "PublicDataReader 가 2026-07 개편 미반영. lawd_codes.json 미변경.")
    if "제물포구" not in out.get("인천", {}):
        sys.exit("[gen_lawd_codes] ABORT: 인천 신설구(제물포 등) 없음 — 소스 미갱신. 미변경.")

    path = ROOT / "scripts" / "lawd_codes.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(v) for v in out.values())
    nc = sum(len(c) for v in out.values() for c in v.values())
    print(f"wrote {path.name}: regions={n}, codes={nc}")
    if miss:
        print("UNRESOLVED:", miss)


if __name__ == "__main__":
    main()
