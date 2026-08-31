document.querySelectorAll(".pw-toggle").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var id = btn.getAttribute("data-for");
    var el = id ? document.getElementById(id) : null;
    if (!el) return;
    var show = el.type === "password";
    el.type = show ? "text" : "password";
    btn.textContent = show ? "Hide" : "Show";
  });
});
