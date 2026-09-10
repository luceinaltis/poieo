/* Apply a saved preference before first paint, falling back to the OS. */
(function () {
  var pick = null;
  try { pick = localStorage.getItem("poieo.theme"); } catch (e) {}
  if (pick !== "light" && pick !== "dark")
    pick = matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  apply(pick);

  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "light" ? "#f3f5f2" : "#14221b";
    var button = document.getElementById("theme-flip");
    if (button) {
      button.textContent = theme === "light" ? "Dark" : "Light";
      button.setAttribute("aria-label", "Switch to " + (theme === "light" ? "dark" : "light") + " theme");
    }
  }

  addEventListener("DOMContentLoaded", function () {
    apply(document.documentElement.dataset.theme);
    var button = document.getElementById("theme-flip");
    if (!button) return;
    button.addEventListener("click", function () {
      var theme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem("poieo.theme", theme); } catch (e) {}
      apply(theme);
    });
  });
})();
