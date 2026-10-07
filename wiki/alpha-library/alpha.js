// Fills the Alpha Library landing stats from content/index.json, which the
// deploy workflow generates (wiki/scripts/build_alpha_library.py).
import { storedLang } from "/site.js?v=20260929e";

const TEXT = {
  en: { across: (n) => `across ${n} zoos`, alphas: (n) => `${n} alphas`, missing: "manifest not generated yet" },
  zh: { across: (n) => `分布在 ${n} 个因子集`, alphas: (n) => `${n} 个因子`, missing: "尚未生成因子清单" }
};

function render(data) {
  const t = TEXT[storedLang()];
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };
  if (!data) {
    set("stat-total-sub", t.missing);
    return;
  }
  set("stat-total", String(data.total_alphas || 0));
  set("stat-total-sub", t.across(data.zoo_count || 0));
  set("stat-zoos", String(data.zoo_count || 0));
  if (data.generated_at) {
    const date = new Date(data.generated_at);
    set("stat-generated", Number.isNaN(date.getTime()) ? "--" : date.toISOString().slice(0, 10));
  }
  for (const zoo of data.zoos || []) {
    const el = document.querySelector(`.count[data-zoo="${String(zoo.zoo_id || "")}"]`);
    if (el) el.textContent = t.alphas(zoo.count);
  }
}

let data = null;
fetch("/alpha-library/content/index.json")
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
  .then((json) => {
    data = json;
    render(data);
  })
  .catch(() => render(null));

// Re-render the counts in the other language when the reader switches.
document.getElementById("lang-toggle")?.addEventListener("click", () => {
  setTimeout(() => render(data), 0);
});
