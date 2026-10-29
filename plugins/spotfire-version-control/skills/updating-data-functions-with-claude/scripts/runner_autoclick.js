// Runner: once the text area has rendered, click its "Run Pending Job"
// button. The IronPython script behind the button decides whether a job is
// pending; a click with no pending job does nothing.
(function () {
  if (window.__runnerClicked) { return; }
  var tries = 0;
  function find() {
    var all = document.querySelectorAll(
      "input.sfc-action-button, button, input[type=button], a");
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var text = (el.value || el.textContent || "").trim();
      if (text === "Run Pending Job") { return el; }
    }
    return null;
  }
  function attempt() {
    tries += 1;
    var el = find();
    if (el) {
      window.__runnerClicked = true;
      el.click();
      return;
    }
    if (tries < 60) { setTimeout(attempt, 500); }
  }
  setTimeout(attempt, 1500);
})();
