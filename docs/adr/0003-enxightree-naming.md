# ADR 0003 — 제품명 Enxightree (구 K-RE MAP)

- **상태**: Accepted
- **일자**: 2026-06-11 (KST) · 사용자 확정

## 배경

K-RE MAP 은 기능 설명형 가칭. 사용자 요청: "ENXIGHT 패밀리룩답게" + 패턴 제시
"ENXIGHT·ENXIGHTER·ENXIGHTING 처럼 앞 고정, 뒤만 조정". 추가 비전: 부동산 외 자산도
타일로 시각화하는 플랫폼 → 부동산 한정 아닌 **시각화 정체성** 접미어.

## 결정

1. **제품명 = Enxightree** (전대문자 ENXIGHTREE · 한글 발음 엔자이트리)
   - ENXIGH + TREE — ENXIGHT 의 끝 T 를 접미어 첫 글자와 공유하는 합성
   - TREE = **treemap**(핵심 시각화)의 어원. 드릴다운(전국→시도→시군구) = 나무 구조
   - 확장 서사: 뿌리(땅·부동산) → 가지·잎(성장·주식 등) — 멀티 자산 타일 플랫폼
2. ~~**로고 마크 = 컨셉 B "드릴다운 가지"**~~ — **개정 (2026-06-11 저녁, 사용자 결정)**:
   패밀리 마크 전면 단일화 — 전 제품(매거진·게임·맵·펄스)이 **enxight 풀 X(100% 확장)
   오방 배지** 하나만 사용. 드릴다운 가지 마크는 같은 날 폐기 (git 이력 보존).
   - `public/favicon.svg`·ico·apple-touch·og-image + 앱 헤더 인라인 마크 전부 오방 배지로 교체
   - 워드마크: Enxigh**tree** — tree 만 시그널 그린 (제품명·워드마크는 유지, 마크만 통일)
3. **내부 배관 유지** (NOWEADOES 표기 원칙과 동일): repo `ENXIGHT-KREMAP`, 폴더, 도메인 `map.enxight.com`, 메모리 슬러그 kremap — 변경 없음.
   도메인의 map 은 기능 설명으로 유효. tree.enxight.com 신설은 백로그(수요 시).

## 기각된 후보 (기록)

Anchor(Harbor 연쇄)·LANDSIGHT(-IGHT 운율)·여지 YEOJI(대동여지도) — 1차.
ENXIGHTERRA·ENXIGHTOPIA·ENXIGHTOWN — 부동산 한정 결. ENXIGHTESSEL·ENXIGHTILE·ENXIGHTINT — 시각화 결 차점.
