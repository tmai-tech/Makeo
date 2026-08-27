(function () {
  var form = document.getElementById("composeForm");
  var status = document.getElementById("composeStatus");
  var mode = document.getElementById("mode");
  var prompt = document.getElementById("prompt");
  if (!form) return;

  function sync() {
    prompt.disabled = mode.value !== "custom";
  }
  mode.addEventListener("change", sync);
  sync();

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var brand = (document.getElementById("brandName").value || "").trim();
    var custom = (prompt.value || "").trim();
    if (mode.value === "custom" && !custom) {
      status.textContent = "Add a Veo prompt, or switch to today’s trend.";
      return;
    }
    status.textContent =
      "Queued locally as a demo for " +
      brand +
      ". The live worker on your Makeo host is what actually renders and posts.";
  });
})();
