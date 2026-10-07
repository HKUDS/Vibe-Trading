import { initSite } from "/site.js?v=20260929e";

// Home page install tabs; a no-op on pages without them.
function initInstallTabs() {
  const tabs = Array.from(document.querySelectorAll("[data-tab]"));
  if (!tabs.length) return;

  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      const key = tab.getAttribute("data-tab");
      for (const item of tabs) {
        const selected = item === tab;
        item.setAttribute("aria-selected", String(selected));
        const panelId = item.getAttribute("aria-controls");
        if (panelId) {
          const panel = document.getElementById(panelId);
          if (panel) panel.hidden = !selected;
        }
      }
      if (key) {
        try {
          localStorage.setItem("vibetrading-install-tab", key);
        } catch {
          /* ignore */
        }
      }
    });
  }

  try {
    const saved = localStorage.getItem("vibetrading-install-tab");
    const selected = tabs.find((tab) => tab.getAttribute("data-tab") === saved);
    if (selected) selected.click();
  } catch {
    /* ignore */
  }
}

initSite();
initInstallTabs();
