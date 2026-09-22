/* Readable tabs with an optional, finite scripted walkthrough. No live work runs. */
(function () {
  const story = document.getElementById("story");
  if (!story) return;
  const list = story.querySelector(".story-tabs");
  const tabs = Array.from(list.querySelectorAll("button"));
  const panels = tabs.map(tab => document.getElementById(tab.getAttribute("aria-controls")));
  const stage = story.querySelector(".story-panels");
  const playback = story.querySelector(".story-playback");
  const play = story.querySelector(".story-play");
  const status = story.querySelector(".story-status");
  const records = Array.from(story.querySelectorAll(".run-record li"));
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let selected = 0;
  let timer;
  let playing = false;
  let started = false;

  function label() {
    play.textContent = motion.matches
      ? (selected === 2 ? "Replay example" : "Next step")
      : (playing ? "Stop example" : started ? "Replay example" : "Play example");
  }

  function stop() {
    clearTimeout(timer);
    records.forEach(row => row.removeAttribute("data-pending"));
    if (playing) status.textContent = "Stopped · Explore any step";
    playing = false;
    label();
  }

  function announce() {
    status.textContent = ["1 / 3 · The task", "2 / 3 · The recorded run", "3 / 3 · Ready to review"][selected];
  }

  function finish() {
    playing = false;
    records.forEach(row => row.removeAttribute("data-pending"));
    select(2, false);
    stage.setAttribute("data-complete", "");
    announce();
  }

  function reveal(index) {
    records[index].removeAttribute("data-pending");
    timer = setTimeout(() => {
      if (index + 1 < records.length) reveal(index + 1);
      else finish();
    }, index + 1 === records.length ? 2400 : 1800);
  }

  function select(index, focus) {
    if (index !== selected) stage.setAttribute("data-interacted", "");
    stage.removeAttribute("data-complete");
    selected = index;
    tabs.forEach((tab, i) => {
      tab.setAttribute("aria-selected", String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
      panels[i].inert = i !== index;
    });
    if (focus) tabs[index].focus();
    label();
  }

  list.setAttribute("role", "tablist");
  tabs.forEach((tab, index) => {
    tab.setAttribute("role", "tab");
    panels[index].setAttribute("role", "tabpanel");
    panels[index].setAttribute("aria-labelledby", tab.id);
    panels[index].tabIndex = 0;
    tab.addEventListener("click", () => { stop(); select(index, false); announce(); });
    tab.addEventListener("keydown", event => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      let next;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      stop();
      select(next, true);
      announce();
    });
  });
  play.addEventListener("click", () => {
    if (playing) { stop(); return; }
    started = true;
    if (motion.matches) {
      select((selected + 1) % tabs.length, false);
      announce();
      return;
    }
    playing = true;
    select(0, false);
    announce();
    records.forEach(row => row.setAttribute("data-pending", ""));
    timer = setTimeout(() => {
      select(1, false);
      announce();
      reveal(0);
    }, 2400);
  });
  // Never replace the panel someone is reading with a keyboard or pointer.
  stage.addEventListener("focusin", stop);
  stage.addEventListener("pointerdown", stop);
  list.addEventListener("focusin", stop);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  window.addEventListener("pagehide", stop);
  motion.addEventListener("change", stop);
  select(0, false);
  stage.setAttribute("data-ready", "");
  list.hidden = false;
  playback.hidden = false;
})();
