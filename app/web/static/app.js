/* Boekhouden UI helpers: vanilla, no dependencies. Every page works without this file. */
(function () {
  var root = document.documentElement;

  // --- Info tooltips: fixed placement (never clipped by .table-wrap), Escape closes ---
  function placeTip(info) {
    var tip = info.querySelector(".info-tip");
    var btn = info.querySelector(".info-btn");
    if (!tip || !btn) return;
    tip.classList.add("is-fixed");
    tip.classList.remove("is-above");
    var b = btn.getBoundingClientRect();
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.max(8, Math.min(b.left + b.width / 2 - w / 2, window.innerWidth - w - 8));
    var above = b.bottom + 8 + h > window.innerHeight && b.top - 8 - h > 0;
    tip.style.left = left + "px";
    tip.style.top = (above ? b.top - 8 - h : b.bottom + 8) + "px";
    tip.style.setProperty("--arrow-x", (b.left + b.width / 2 - left) + "px");
    tip.classList.toggle("is-above", above);
  }
  function infoOf(e) { return e.target.closest ? e.target.closest(".info") : null; }
  ["mouseover", "focusin"].forEach(function (type) {
    document.addEventListener(type, function (e) { var i = infoOf(e); if (i) placeTip(i); });
  });
  ["mouseout", "focusout"].forEach(function (type) {
    document.addEventListener(type, function (e) {
      var i = infoOf(e);
      if (i && !i.contains(e.relatedTarget)) i.removeAttribute("data-dismissed");
    });
  });

  // --- Kebab menus: fixed placement inside scrolling tables, close on outside click ---
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.matches || !d.matches("details.menu") || !d.open) return;
    var list = d.querySelector(".menu__list"), r = d.getBoundingClientRect();
    list.classList.add("is-fixed");
    list.style.top = r.bottom + 4 + "px";
    list.style.left = Math.max(8, r.right - list.offsetWidth) + "px";
  }, true);
  function closeMenus(except) {
    document.querySelectorAll("details.menu[open]").forEach(function (d) { if (d !== except) d.open = false; });
  }
  document.addEventListener("click", function (e) { closeMenus(e.target.closest("details.menu")); });
  window.addEventListener("scroll", function () { closeMenus(null); }, true);

  // --- Mobile drawer ---
  function setNav(open) {
    if (open) root.setAttribute("data-nav-open", ""); else root.removeAttribute("data-nav-open");
    document.querySelectorAll("[data-nav-toggle]").forEach(function (b) { b.setAttribute("aria-expanded", String(open)); });
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-nav-toggle]")) setNav(!root.hasAttribute("data-nav-open"));
    else if (e.target.closest(".scrim, .sidebar a")) setNav(false);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var focused = document.activeElement && document.activeElement.closest ? document.activeElement.closest(".info") : null;
    var hovered = document.querySelector(".info:hover");
    (focused || hovered || { setAttribute: function () {} }).setAttribute("data-dismissed", "");
    closeMenus(null);
    if (root.hasAttribute("data-nav-open")) {
      setNav(false);
      var t = document.querySelector("[data-nav-toggle]");
      if (t) t.focus();
    }
  });

  // --- Client-side row filter: <input data-filter-table="#table-id"> (progressive enhancement) ---
  document.addEventListener("input", function (e) {
    var sel = e.target.getAttribute && e.target.getAttribute("data-filter-table");
    var table = sel && document.querySelector(sel);
    if (!table) return;
    var q = e.target.value.trim().toLowerCase(), shown = 0;
    table.querySelectorAll("tbody tr").forEach(function (tr) {
      var hit = !q || tr.textContent.toLowerCase().indexOf(q) !== -1;
      tr.classList.toggle("data-hidden", !hit);
      if (hit) shown++;
    });
    var empty = document.querySelector("[data-filter-empty='" + sel + "']");
    if (empty) empty.hidden = shown > 0;
  });

  // --- Boosted navigation swaps only <body>: load stylesheets the new page adds in <head> ---
  document.addEventListener("htmx:beforeSwap", function (e) {
    var html = e.detail.serverResponse || "";
    (html.match(/<link\b[^>]*rel=["']stylesheet["'][^>]*>/gi) || []).forEach(function (tag) {
      var m = tag.match(/href=["']([^"']+)["']/i);
      if (m && !document.querySelector('link[href="' + m[1] + '"]')) {
        var l = document.createElement("link");
        l.rel = "stylesheet";
        l.href = m[1];
        document.head.appendChild(l);
      }
    });
  });
})();
