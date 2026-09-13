/* The landing's sun or moon. The body follows the page's theme, which Auto sets from the same
   06:00–18:00 clock; the arc always keeps the local clock. The two 12-hour arcs are a visual
   convention, not sunrise or moon-phase data. */
(function () {
  const sky = document.getElementById("landing-sky");
  if (!sky) return;
  let timer;
  let previous;

  function pause() {
    clearTimeout(timer);
  }

  function update() {
    pause();
    if (document.hidden) return;
    const now = new Date();
    const hour = now.getHours();
    const minute = now.getMinutes();
    const clock = hour * 60 + minute;
    const daytime = clock >= 360 && clock < 1080;
    const progress = (daytime ? clock - 360 : (clock + 360) % 1440) / 720;
    const time = String(hour).padStart(2, "0") + ":" + String(minute).padStart(2, "0");
    const theme = document.documentElement.dataset.theme;
    const sun = theme ? theme === "light" : daytime;

    const period = sun ? "day" : "night";
    // Do not animate a whole crossing when the body changes or a sleeping tab returns.
    sky.classList.toggle("sky-jump", sky.dataset.period !== period || previous === undefined || Math.abs(clock - previous) > 1);
    previous = clock;
    if (sky.dataset.period !== period) {
      const body = sky.querySelector("img");
      if (body) body.src = sun ? "img/sun.png" : "img/moon.png";
    }
    sky.dataset.period = period;
    sky.style.setProperty("--sky-progress", progress.toFixed(4));
    sky.style.setProperty("--sky-rise", Math.sin(progress * Math.PI).toFixed(4));
    sky.setAttribute("aria-label", `${sun ? "Sun" : "Moon"} at ${time}, your local time`);
    sky.hidden = false;
    // Align to the next minute, including the 06:00 and 18:00 boundaries.
    timer = setTimeout(update, 60_000 - now.getTime() % 60_000);
  }

  new MutationObserver(update).observe(document.documentElement, { attributeFilter: ["data-theme"] });
  document.addEventListener("visibilitychange", update);
  window.addEventListener("pagehide", pause);
  window.addEventListener("pageshow", update);
  update();
})();
