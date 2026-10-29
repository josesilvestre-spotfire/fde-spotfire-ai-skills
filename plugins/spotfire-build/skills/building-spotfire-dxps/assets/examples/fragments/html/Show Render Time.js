// Show Render Time: writes the time of the last full render into #scripts-render-time.
// Attached through HtmlTextArea.Scripts (lib/40_scripts.py attach_js); runs after each render.
(function () {
  var el = document.getElementById("scripts-render-time");
  if (el) {
    el.textContent = "Rendered " + new Date().toLocaleTimeString();
  }
})();
