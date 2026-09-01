/**
 * ENXIGHT — Google Analytics 4 동적 로더
 *
 * Phase 0-2 (2026-05-23) — GA4 측정 ID가 설정된 경우에만 gtag 스크립트를
 * 동적으로 inject한다. 미설정 시 아무 동작 없이 skip하므로 개발 환경에서도 안전.
 *
 * Phase 0-3 (2026-05-28) — 옵션 강화:
 *   · anonymize_ip 명시 (PIPA/GDPR 친화 · GA4 default 이지만 선언)
 *   · page_type 자동 분류 (home / magazine_hub / magazine_issue / brand / enxighter)
 *   · content_language segment (KO/EN 분기)
 *   · window.enxightTrack(name, params) custom event helper 노출
 *   · 미설정 시 enxightTrack 도 no-op 로 노출 (호출부 안전)
 *
 * Phase 0-4 (2026-05-28) — 멀티 호스트 측정 ID 분기:
 *   · enxight.com / enxight.co.kr 두 도메인을 같은 코드로 추적
 *   · hostname 자동 매칭, 매칭 실패 시 비활성 (localhost·preview 안전)
 *   · 새 도메인 추가 시 GA4_IDS_BY_HOST 만 갱신
 *
 * 사용자 액션 (신규 도메인 추가 시):
 *   1) GA4 콘솔에서 데이터 스트림 추가 → 측정 ID 발급 (G-XXXXXXXXXX)
 *   2) Cloudflare 콘솔 → Workers → enxight-homepage → Domains & Routes 에 도메인 추가
 *   3) 아래 GA4_IDS_BY_HOST 에 hostname → ID 매핑 추가
 *   4) git commit + push → Cloudflare Workers 자동 배포
 *
 * GA4 ID는 공개 자산(브라우저로 전송됨)이라 .env가 아니라 본 파일에 직접
 * 넣어도 보안 문제 없음. service account 키 같은 secret은 절대 여기 두지 말 것.
 */
(function () {
  // ↓ hostname → GA4 측정 ID 매핑. 새 도메인 추가 시 여기에만 추가.
  // 2026-05-28: enxight.co.kr 은 Cloudflare 측에서 301 redirect → enxight.com 처리.
  // hostname 이 redirect 후 .com 으로 바뀌어 도착하므로 .co.kr 매핑은 둘 필요 없음.
  // 도메인별 트래픽 비교는 Cloudflare Analytics 가 redirect 전 hits 를 자동 집계.
  const GA4_IDS_BY_HOST = {
    // K-RE MAP — enxight.com 과 같은 GA4 속성으로 통합 추적 (page_type 으로 구분)
    "map.enxight.com":   "G-FW69SY69TF",
  };

  const host = (window.location.hostname || "").toLowerCase();
  const GA4_MEASUREMENT_ID = GA4_IDS_BY_HOST[host] || "";

  if (!GA4_MEASUREMENT_ID || !/^G-[A-Z0-9]+$/.test(GA4_MEASUREMENT_ID)) {
    // 미활성 (localhost·preview·미매핑 도메인) — enxightTrack 도 no-op 로 노출
    window.enxightTrack = function () {};
    return;
  }

  // page_type 자동 분류 — site 영역별 행동 segment 용
  function detectPageType() {
    const p = window.location.pathname;
    if (p === "/" || p === "/en/") return "home";
    if (/^\/(en\/)?magazine\/$/.test(p)) return "magazine_hub";
    if (/^\/(en\/)?magazine\/\d{4}-\d{2}-\d{2}/.test(p)) return "magazine_issue";
    if (/^\/(en\/)?brand\//.test(p)) return "brand";
    if (/^\/(en\/)?enxighter\//.test(p)) return "enxighter";
    return "other";
  }

  // gtag.js 외부 스크립트 로드
  const gtagScript = document.createElement("script");
  gtagScript.async = true;
  gtagScript.src = "https://www.googletagmanager.com/gtag/js?id=" + GA4_MEASUREMENT_ID;
  document.head.appendChild(gtagScript);

  // dataLayer 초기화 + gtag 함수 등록
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () {
    window.dataLayer.push(arguments);
  };
  window.gtag("js", new Date());

  window.gtag("config", GA4_MEASUREMENT_ID, {
    // 페이지 경로 정규화 — 쿼리스트링 제거 (RSS·deep link 매개변수 노이즈 차단)
    page_path: window.location.pathname,
    // PIPA/GDPR 친화 — IP 익명화 명시 (GA4 default 이지만 명시 선언)
    anonymize_ip: true,
    // 커스텀 segment — 보고서에서 페이지 영역별로 분리 가능
    page_type: detectPageType(),
    // 언어 — 매거진 KO/EN 분기 시각화
    content_language: document.documentElement.lang || "ko",
    // 도메인 식별자 — 두 도메인 데이터 합쳐서 볼 때 segment 가능
    site_host: host,
  });

  // ============================================================
  // Custom event helper — 호출부에서 window.enxightTrack('event_name', {...}) 사용
  //
  // 예시:
  //   enxightTrack('subscribe_click', { channel: 'telegram' });
  //   enxightTrack('magazine_open', { issue_id: '2026-05-28' });
  //   enxightTrack('series_card_click', { series: 'daily' });
  //   enxightTrack('coverage_region_click', { region: 'korea' });
  //
  // GA4 콘솔 "보고서 → 이벤트" 에서 자동 수집. params 키를 custom dimension 으로
  // 등록하면 슬라이스 가능 (예: series 별 클릭 수, region 별 hover 분포).
  // ============================================================
  window.enxightTrack = function (eventName, params) {
    if (typeof eventName !== "string" || !eventName) return;
    window.gtag("event", eventName, params || {});
  };
})();

// ============================================================
// Site-wide click tracking — DOMContentLoaded 후 정적 element 에 listener attach.
// 동적 element (archive chip) 는 부모 .archive-grid 에 event delegation.
// 모든 호출은 window.enxightTrack — GA4 미활성 시 no-op (호출부 안전).
// ============================================================
document.addEventListener("DOMContentLoaded", function () {
  if (typeof window.enxightTrack !== "function") return;

  // Subscribe channels (telegram · RSS)
  document.querySelectorAll('a[href*="t.me/"]').forEach(function (el) {
    el.addEventListener("click", function () {
      window.enxightTrack("subscribe_click", { channel: "telegram" });
    });
  });
  document.querySelectorAll('a[href$="/rss.xml"], a[href*="rss"]').forEach(function (el) {
    el.addEventListener("click", function () {
      window.enxightTrack("subscribe_click", { channel: "rss" });
    });
  });

  // Series card (Daily · Weekly · Monthly) — root + magazine hub
  document.querySelectorAll(".series-card[data-series]").forEach(function (card) {
    card.addEventListener("click", function () {
      window.enxightTrack("series_card_click", {
        series: card.dataset.series || "",
      });
    });
  });

  // Folio issue (root + magazine hub) — daily/weekly/monthly 슬롯
  document.querySelectorAll(".folio-issue[data-slot]").forEach(function (folio) {
    folio.addEventListener("click", function () {
      window.enxightTrack("folio_click", {
        slot: folio.dataset.slot || "",
      });
    });
  });

  // Product card (root) — magazine · enxighter · brand
  document.querySelectorAll(".product-card").forEach(function (card) {
    card.addEventListener("click", function () {
      // 카드 안 .product-num 의 "01 · MAGAZINE" 같은 텍스트로 product 식별
      var num = card.querySelector(".product-num");
      var name = num ? num.textContent.replace(/^\d+\s*·\s*/, "").trim().toLowerCase() : "";
      window.enxightTrack("product_card_click", { product: name });
    });
  });

  // Archive chip — JS 로 dynamic 추가됨. event delegation 으로 부모 .archive-grid 에 attach.
  document.querySelectorAll(".archive-grid").forEach(function (grid) {
    grid.addEventListener("click", function (e) {
      var chip = e.target.closest(".archive-chip");
      if (!chip) return;
      window.enxightTrack("archive_chip_click", {
        issue_id: chip.getAttribute("title") || "",
        issue_type: chip.dataset.type || "",
      });
    });
  });
});
