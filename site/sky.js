/* A clock-based illustration, independent of the reader's chosen theme.
   The two 12-hour arcs are a visual convention, not sunrise or moon-phase data. */
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
    const day = clock >= 360 && clock < 1080;
    const progress = (day ? clock - 360 : (clock + 360) % 1440) / 720;
    const time = String(hour).padStart(2, "0") + ":" + String(minute).padStart(2, "0");

    const period = day ? "day" : "night";
    // Do not animate a whole crossing when the body changes or a sleeping tab returns.
    sky.classList.toggle("sky-jump", sky.dataset.period !== period || previous === undefined || Math.abs(clock - previous) > 1);
    previous = clock;
    if (sky.dataset.period !== period) {
      const body = sky.querySelector("img");
      if (body) body.src = day ? "img/sun.png" : "img/moon.png";
    }
    sky.dataset.period = period;
    sky.style.setProperty("--sky-progress", progress.toFixed(4));
    sky.style.setProperty("--sky-rise", Math.sin(progress * Math.PI).toFixed(4));
    sky.setAttribute("aria-label", `${day ? "Sun" : "Moon"} at ${time}, your local time`);
    sky.hidden = false;
    // Align to the next minute, including the 06:00 and 18:00 boundaries.
    timer = setTimeout(update, 60_000 - now.getTime() % 60_000);
  }

  document.addEventListener("visibilitychange", update);
  window.addEventListener("pagehide", pause);
  window.addEventListener("pageshow", update);
  update();
})();
