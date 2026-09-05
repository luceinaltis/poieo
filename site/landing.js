/* The landing story follows the page instead of running on a timer: the
   reader moves one real task into view, and the fixed board answers. Arrows
   perform the same move for somebody who would rather operate it directly. */
(function () {
  addEventListener("DOMContentLoaded", function () {
    var story = document.querySelector("[data-demo-story]");
    if (!story) return;

    var steps = Array.from(story.querySelectorAll("[data-demo-step]"));
    var panels = Array.from(story.querySelectorAll("[data-demo-panel]"));
    var title = story.querySelector("[data-demo-title]");
    var status = story.querySelector("[data-demo-status]");
    var controls = story.querySelector("[data-demo-controls]");
    var previous = story.querySelector("[data-demo-prev]");
    var next = story.querySelector("[data-demo-next]");
    var reduced = matchMedia("(prefers-reduced-motion: reduce)");
    var active = 0;

    if (!steps.length || steps.length !== panels.length) return;

    function nameOf(index) {
      return steps[index].querySelector("h3").textContent.trim();
    }

    function show(index) {
      active = Math.max(0, Math.min(index, steps.length - 1));
      story.dataset.active = String(active);

      steps.forEach(function (step, position) {
        if (position === active) step.setAttribute("aria-current", "step");
        else step.removeAttribute("aria-current");
      });

      panels.forEach(function (panel, position) {
        panel.setAttribute("aria-hidden", String(position !== active));
      });

      var name = nameOf(active);
      title.textContent = name;
      status.textContent = "Example " + (active + 1) + " of " + steps.length + " — " + name;
      /* Boundary arrows stay focusable. Native `disabled` drops keyboard
         focus just as the reader reaches the first or last example. */
      previous.setAttribute("aria-disabled", String(active === 0));
      next.setAttribute("aria-disabled", String(active === steps.length - 1));
    }

    function move(by) {
      var destination = Math.max(0, Math.min(active + by, steps.length - 1));
      if (destination === active) return;
      show(destination);
      steps[destination].scrollIntoView({
        behavior: reduced.matches ? "auto" : "smooth",
        block: "center",
      });
    }

    controls.hidden = false;
    previous.addEventListener("click", function () { move(-1); });
    next.addEventListener("click", function () { move(1); });

    /* A narrow band through the viewport is the playhead. Long steps can fill
       most of the screen without two examples claiming the board at once. */
    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          show(steps.indexOf(entry.target));
        });
      }, { rootMargin: "-42% 0px -42% 0px", threshold: 0 });

      steps.forEach(function (step) { observer.observe(step); });
    }

    show(0);
  });
})();
