(function () {
  try {
    var stored = localStorage.getItem("vibetrading-theme");
    var resolved = stored === "dark" || stored === "light"
      ? stored
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", resolved);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "light");
  }
})();

(function () {
  function hydrateAlphaStats() {
    fetch("content/index.json", { cache: "default" })
      .then(function (r) {
        if (!r.ok) throw new Error("index.json " + r.status);
        return r.json();
      })
      .then(function (data) {
        var total = document.getElementById("stat-total");
        var totalSub = document.getElementById("stat-total-sub");
        var zoos = document.getElementById("stat-zoos");
        var gen = document.getElementById("stat-generated");
        if (total) total.textContent = String(data.total_alphas || 0);
        if (totalSub) totalSub.textContent = "across " + (data.zoo_count || 0) + " zoos";
        if (zoos) zoos.textContent = String(data.zoo_count || 0);
        if (gen && data.generated_at) {
          try { gen.textContent = new Date(data.generated_at).toISOString().slice(0, 10); }
          catch (e) { gen.textContent = "unknown"; }
        }
        var countEls = Array.prototype.slice.call(document.querySelectorAll(".count[data-zoo]"));
        (data.zoos || []).forEach(function (z) {
          var zooId = String(z.zoo_id || "");
          var el = countEls.find(function (candidate) {
            return candidate.dataset.zoo === zooId;
          });
          if (el) el.textContent = z.count + " alphas";
        });
      })
      .catch(function () {
        var totalSub = document.getElementById("stat-total-sub");
        if (totalSub) totalSub.textContent = "manifest not generated yet";
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", hydrateAlphaStats);
  } else {
    hydrateAlphaStats();
  }
})();
