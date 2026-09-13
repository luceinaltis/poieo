/* Apply the saved mode before first paint. Auto follows the local 06:00–18:00 day. */
(function () {
  let pick = read();
  let timer;

  function read() {
    try {
      const saved = localStorage.getItem("poieo.theme");
      if (saved === "light" || saved === "dark") return saved;
    } catch (e) {}
    return "auto";
  }

  function pause() {
    clearTimeout(timer);
  }

  function update() {
    pause();
    const now = new Date();
    const day = now.getHours() >= 6 && now.getHours() < 18;
    apply(pick === "auto" ? (day ? "light" : "dark") : pick);
    if (pick === "auto" && !document.hidden)
      timer = setTimeout(update, 60_000 - now.getTime() % 60_000);
  }

  function apply(theme) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themeMode = pick;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "light" ? "#f8f5ef" : "#100e0c";
    const control = document.getElementById("theme-mode");
    if (control) {
      control.value = pick;
      control.hidden = false;
    }
  }

  addEventListener("DOMContentLoaded", function () {
    const control = document.getElementById("theme-mode");
    if (!control) return;
    control.addEventListener("change", function () {
      pick = control.value;
      try { localStorage.setItem("poieo.theme", pick); } catch (e) {}
      update();
    });
    update();
  });
  addEventListener("storage", function (event) {
    if (event.key !== "poieo.theme" && event.key !== null) return;
    pick = read();
    update();
  });
  document.addEventListener("visibilitychange", update);
  addEventListener("pagehide", pause);
  addEventListener("pageshow", update);
  update();
})();
