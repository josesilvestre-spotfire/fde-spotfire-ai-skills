// Highlight Open Events: colours the open-event count coral when it is above zero.
// Attached through HtmlTextArea.Scripts (lib/40_scripts.py attach_js); runs after each full render.
// The count is a Label property control inside #pcp-open-events. Text-area JavaScript does not
// re-run when a property value changes, so a MutationObserver follows the label's updates.
(function () {
  var box = document.getElementById("pcp-open-events");
  if (!box) { return; }
  function paint() {
    var n = parseInt((box.textContent || "").replace(/[^0-9-]/g, ""), 10);
    box.style.color = (n > 0) ? "#E94165" : "";
  }
  paint();
  if (window.MutationObserver && !box.getAttribute("data-pcp-observed")) {
    box.setAttribute("data-pcp-observed", "1");
    new MutationObserver(paint).observe(box, { childList: true, subtree: true, characterData: true });
  }
})();
