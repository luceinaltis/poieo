/* Theme: the bar's choice, remembered in localStorage; otherwise the OS's.
   Loaded synchronously in <head> so the right tokens are in place before
   first paint — no flash of the wrong ground. */
(function () {
  var pick = null;
  try { pick = localStorage.getItem("poieo.theme"); } catch (e) {}
  if (pick !== "light" && pick !== "dark")
    pick = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  apply(pick);

  function apply(t) {
    document.documentElement.dataset.theme = t;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = t === "light" ? "#f4f0e8" : "#14120f";
    var b = document.getElementById("theme-flip");
    if (b) b.textContent = t === "light" ? "☾" : "☀";
  }

  addEventListener("DOMContentLoaded", function () {
    apply(document.documentElement.dataset.theme);
    var b = document.getElementById("theme-flip");
    if (!b) return;
    b.addEventListener("click", function () {
      var t = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem("poieo.theme", t); } catch (e) {}
      apply(t);
    });
  });
})();
