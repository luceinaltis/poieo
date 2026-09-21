/* A local-clock sky with a date-based lunar phase. Design: docs/branding.md.
   The two 12-hour arcs are a visual convention, not geographic rise/set times. */
(function () {
  const sky = document.getElementById("landing-sky");
  if (!sky) return;
  const body = sky.querySelector("img");
  let timer;
  let previousTime;
  let previousProgress;
  let suspended = false;

  // NASA's 2025-01-29 12:36 UT new moon and mean synodic month.
  // This is an approximate calendar phase, not a local horizon/orientation calculation.
  const epoch = Date.UTC(2025, 0, 29, 12, 36);
  const month = 29.530588 * 86_400_000;
  const phases = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous",
    "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"];

  function moon(now) {
    const phase = ((now - epoch) % month + month) % month / month;
    const light = (1 - Math.cos(2 * Math.PI * phase)) / 2;
    const side = phase < .5 ? 1 : -1;
    const terminator = Math.cos(2 * Math.PI * phase);
    const points = [];
    // The opaque lunar disc in moon.png is centred at (.5, .502), radius .342.
    // Trace the visible limb then the projected terminator, avoiding a lit full-disc outline.
    for (let i = 0; i <= 64; i++) {
      const angle = -Math.PI / 2 + i * Math.PI / 64;
      points.push([.5 + side * .342 * Math.cos(angle), .502 + .342 * Math.sin(angle)]);
    }
    for (let i = 64; i >= 0; i--) {
      const angle = -Math.PI / 2 + i * Math.PI / 64;
      points.push([.5 + side * terminator * .342 * Math.cos(angle), .502 + .342 * Math.sin(angle)]);
    }
    if (body) body.style.clipPath = `polygon(${points.map(([x, y]) => `${(x * 100).toFixed(3)}% ${(y * 100).toFixed(3)}%`).join(",")})`;
    sky.style.setProperty("--moon-light", light.toFixed(4));
    const name = phases[Math.round(phase * 8) % 8];
    sky.dataset.phase = name;
    return `${name}, approximately ${Math.round(light * 100)}% illuminated`;
  }

  function pause() {
    clearTimeout(timer);
    document.body.classList.add("sky-paused");
  }

  function update() {
    clearTimeout(timer);
    if (suspended || document.hidden) { pause(); return; }
    document.body.classList.remove("sky-paused");
    const now = new Date();
    const clock = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
    const daytime = clock >= 21600 && clock < 64800;
    const progress = (daytime ? clock - 21600 : (clock + 21600) % 86400) / 43200;
    const theme = document.documentElement.dataset.theme;
    const sun = theme ? theme === "light" : daytime;
    const period = sun ? "day" : "night";
    const changed = sky.dataset.period !== period;
    const stamp = now.getTime();
    // A mode swap, resumed tab, clock adjustment, or half-day wrap must not fly across the page.
    const jump = changed || previousTime === undefined || stamp - previousTime > 2000 ||
      stamp < previousTime || progress < previousProgress;
    sky.classList.toggle("sky-jump", jump);
    previousTime = stamp;
    previousProgress = progress;
    if (changed && body) body.src = sun ? "img/sun.png" : "img/moon.png";
    sky.dataset.period = period;
    sky.style.setProperty("--sky-progress", progress.toFixed(6));
    sky.style.setProperty("--sky-rise", Math.sin(progress * Math.PI).toFixed(6));
    const time = String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
    let label = `${sun ? "Sun" : "Moon"} at ${time}, your local time`;
    if (sun) {
      if (body) body.style.clipPath = "";
      sky.style.removeProperty("--moon-light");
      delete sky.dataset.phase;
    } else {
      label += ` — ${moon(stamp)}`;
    }
    // Do not produce an accessibility-tree change every second just for the clock position.
    if (sky.getAttribute("aria-label") !== label) sky.setAttribute("aria-label", label);
    sky.hidden = false;
    timer = setTimeout(update, 1000 - stamp % 1000);
  }

  new MutationObserver(update).observe(document.documentElement, { attributeFilter: ["data-theme"] });
  document.addEventListener("visibilitychange", function () { previousTime = undefined; update(); });
  window.addEventListener("pagehide", function () { suspended = true; pause(); });
  window.addEventListener("pageshow", function () { suspended = false; previousTime = undefined; update(); });
  update();
})();
