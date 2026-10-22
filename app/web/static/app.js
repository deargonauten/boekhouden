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

  // --- Drawer: [data-drawer-open="#id"] opens <aside class="drawer" id="id">; htmx triggers open it after the swap ---
  var lastTrigger = null;
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function drawerScrim(d) { var n = d.nextElementSibling; return n && n.classList.contains("drawer-scrim") ? n : null; }
  function openDrawer(d, trigger) {
    if (!d || !d.hidden) return;
    lastTrigger = trigger || document.activeElement;
    var scrim = drawerScrim(d);
    d.hidden = false;
    if (scrim) scrim.hidden = false;
    root.setAttribute("data-drawer-open", "");
    void d.offsetWidth; // let the slide-in transition start from the closed position
    d.setAttribute("data-open", "");
    if (scrim) scrim.setAttribute("data-open", "");
    d.focus();
  }
  function closeDrawer(d) {
    if (!d || d.hidden) return;
    var scrim = drawerScrim(d);
    d.removeAttribute("data-open");
    if (scrim) scrim.removeAttribute("data-open");
    root.removeAttribute("data-drawer-open");
    var done = function () { d.hidden = true; if (scrim) scrim.hidden = true; };
    if (reduceMotion) done(); else setTimeout(done, 200);
    if (lastTrigger && document.contains(lastTrigger) && lastTrigger.focus) lastTrigger.focus();
    lastTrigger = null;
  }
  function openDrawerEl() { return document.querySelector(".drawer[data-open]"); }
  document.addEventListener("click", function (e) {
    var trig = e.target.closest("[data-drawer-open]:not(html)");
    if (trig) {
      var d = document.querySelector(trig.getAttribute("data-drawer-open"));
      if (!d) return; // no drawer on this page: the link keeps working as a normal link
      if (trig.hasAttribute("hx-get")) { lastTrigger = trig; return; } // htmx loads the body, afterSwap opens it
      e.preventDefault();
      openDrawer(d, trig);
      return;
    }
    var close = e.target.closest("[data-drawer-close]");
    if (close) closeDrawer(close.closest(".drawer") || openDrawerEl());
  });
  document.addEventListener("htmx:afterSwap", function (e) {
    var t = e.detail && e.detail.target;
    if (t && /-body$/.test(t.id || "") && t.closest(".drawer")) openDrawer(t.closest(".drawer"), lastTrigger);
  });
  document.addEventListener("htmx:beforeHistorySave", function () {
    root.removeAttribute("data-drawer-open");
    document.querySelectorAll(".drawer, .drawer-scrim").forEach(function (n) { n.hidden = true; n.removeAttribute("data-open"); });
  });
  document.addEventListener("keydown", function (e) {
    var d = openDrawerEl();
    if (!d) return;
    if (e.key === "Escape") { closeDrawer(d); return; }
    if (e.key !== "Tab") return;
    var f = d.querySelectorAll("a[href], button:not([disabled]), input:not([type=hidden]), select, textarea, [tabindex]:not([tabindex='-1'])");
    if (!f.length) { e.preventDefault(); return; }
    var first = f[0], last = f[f.length - 1];
    if (!d.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && (document.activeElement === first || document.activeElement === d)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // --- Modal: native <dialog class="modal">. [data-modal-open="#id"] opens, [data-modal-close] closes ---
  document.addEventListener("click", function (e) {
    var open = e.target.closest("[data-modal-open]");
    if (open) {
      var m = document.querySelector(open.getAttribute("data-modal-open"));
      if (m && m.showModal) { e.preventDefault(); if (!m.open) m.showModal(); }
      return;
    }
    if (e.target.closest("[data-modal-close]")) { var dlg = e.target.closest("dialog"); if (dlg) dlg.close(); }
    else if (e.target.matches && e.target.matches("dialog.modal") && e.target.open) e.target.close(); // backdrop click
  });
  function initDialogs() {
    document.querySelectorAll("dialog.modal[data-open-on-load]").forEach(function (m) {
      if (m.showModal && !m.open) m.showModal();
    });
    var id = location.hash.length > 1 ? location.hash : "";
    var target = id && document.querySelector("dialog.modal" + id.replace(/[^#\w-]/g, ""));
    if (target && target.showModal && !target.open) target.showModal();
  }
  initDialogs();
  document.addEventListener("htmx:afterSettle", initDialogs);

  // --- Dropzone: drag-over state and chosen file names (the native input covers the whole zone) ---
  function dragState(on) { return function (e) { var z = e.target.closest && e.target.closest(".dropzone"); if (z) { if (on) z.setAttribute("data-dragover", ""); else z.removeAttribute("data-dragover"); } }; }
  ["dragenter", "dragover"].forEach(function (t) { document.addEventListener(t, dragState(true)); });
  ["dragleave", "drop"].forEach(function (t) { document.addEventListener(t, dragState(false)); });
  document.addEventListener("change", function (e) {
    var zone = e.target.closest && e.target.closest(".dropzone");
    var out = zone && zone.querySelector(".dropzone__files");
    if (out && e.target.files) out.textContent = Array.prototype.map.call(e.target.files, function (f) { return f.name; }).join(", ");
  });

  // --- Sidebar collapse (desktop): html.sidebar-collapsed, remembered in localStorage (may be blocked) ---
  function syncSidebar() {
    var collapsed = root.classList.contains("sidebar-collapsed");
    document.querySelectorAll("[data-sidebar-collapse]").forEach(function (b) {
      b.setAttribute("aria-expanded", String(!collapsed));
      var label = collapsed ? "Menu uitklappen" : "Menu inklappen";
      b.setAttribute("aria-label", label);
      b.setAttribute("title", label);
    });
  }
  document.addEventListener("click", function (e) {
    if (!e.target.closest("[data-sidebar-collapse]")) return;
    var collapsed = root.classList.toggle("sidebar-collapsed");
    try { localStorage.setItem("bh.sidebar", collapsed ? "collapsed" : "expanded"); } catch (err) { /* storage blocked: stays for this page only */ }
    syncSidebar();
  });
  syncSidebar();
  document.addEventListener("htmx:afterSettle", syncSidebar);

  // --- Keep the scroll position of a list when you act on a row and come back (link or form with data-keep-scroll) ---
  function listKey() {
    var u = new URL(location.href);
    u.searchParams.delete("melding");
    return u.pathname + u.search;
  }
  function saveScroll(e) {
    if (!e.target.closest || !e.target.closest("[data-keep-scroll]")) return;
    try { sessionStorage.setItem("bh.scroll", JSON.stringify({ key: listKey(), y: window.scrollY })); } catch (err) { /* storage blocked: list opens at the top */ }
  }
  document.addEventListener("click", saveScroll);
  document.addEventListener("submit", saveScroll);
  function restoreScroll() {
    try {
      var saved = JSON.parse(sessionStorage.getItem("bh.scroll") || "null");
      if (!saved || saved.key !== listKey()) return;
      sessionStorage.removeItem("bh.scroll");
      window.scrollTo(0, saved.y);
    } catch (err) { /* nothing saved */ }
  }
  restoreScroll();
  document.addEventListener("htmx:afterSettle", restoreScroll);

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
