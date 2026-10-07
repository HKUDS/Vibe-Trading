// Runs before first paint (a blocking external script, so pages with a strict
// CSP can use it too). Resolves the colour theme. When the page is about to be
// shown in Chinese — a Chinese article, a /docs/zh/ URL, or a language-neutral
// page (or bare /docs/) whose reader chose Chinese — it keeps the page hidden
// until site.js has swapped the English text: at most 1.5 s, so a failed load
// still shows the page.
(function () {
  var root = document.documentElement;
  try {
    var stored = localStorage.getItem("vibetrading-theme");
    var resolved = stored === "dark" || stored === "light"
      ? stored
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    root.setAttribute("data-theme", resolved);
  } catch (e) {
    root.setAttribute("data-theme", "light");
  }
  try {
    var path = location.pathname;
    var chosenZh = localStorage.getItem("vibetrading-lang") === "zh";
    var bareDocs = path === "/docs" || path === "/docs/" || path === "/docs/index.html";
    var zhUrl = path.indexOf("/docs/zh/") === 0 || root.getAttribute("data-page-lang") === "zh";
    if (zhUrl || (chosenZh && (root.hasAttribute("data-lang-neutral") || bareDocs))) {
      root.setAttribute("lang", "zh-CN");
      root.setAttribute("data-lang-pending", "");
      setTimeout(function () { root.removeAttribute("data-lang-pending"); }, 1500);
    }
  } catch (e) {
    /* storage blocked: English */
  }
})();
