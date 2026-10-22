/* Searchable dropdowns: every <select> becomes a field that opens a floating card with a search box and the
 * list below it; click a result to choose it (progressive enhancement). The native <select> stays in the DOM as the source of truth (form submit, htmx,
 * vat-suggest.js, validation); the combobox only mirrors it. Opt out with <select data-native>. Rows added later are picked up via htmx:load. */
(function () {
  var uid = 0;
  var valueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");

  function fold(s) {
    s = String(s || "").toLowerCase();
    return s.normalize ? s.normalize("NFD").replace(/[̀-ͯ]/g, "") : s;
  }

  var SVG = "http://www.w3.org/2000/svg";
  function icon(cls, d) {
    var s = document.createElementNS(SVG, "svg");
    s.setAttribute("class", cls);
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("aria-hidden", "true");
    var p = document.createElementNS(SVG, "path");
    p.setAttribute("d", d);
    s.appendChild(p);
    return s;
  }
  var ICON_SEARCH = "M11 4a7 7 0 1 0 4.4 12.4l4.1 4.1 1.4-1.4-4.1-4.1A7 7 0 0 0 11 4z";
  var ICON_CHECK = "M5 12.5l4.5 4.5L19 7.5";
  var ICON_CLOSE = "M7 7l10 10M17 7L7 17";

  function enhance(select) {
    if (select.multiple || select.size > 1 || select.hasAttribute("data-native") || select.hasAttribute("data-cb")) return;
    select.setAttribute("data-cb", "");
    var id = "cb" + (++uid);
    var cs = getComputedStyle(select);
    var fills = cs.width.slice(-1) === "%" || (select.parentNode.clientWidth > 0 && select.offsetWidth >= select.parentNode.clientWidth - 2);

    var wrap = document.createElement("div");
    wrap.className = "cb" + (fills ? " cb--fill" : "");
    wrap.setAttribute("data-combobox", "");
    var input = document.createElement("input");
    input.type = "text";
    input.readOnly = true; // the field only shows the choice; searching happens in the panel
    input.className = "cb__input";
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-haspopup", "listbox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", id + "-list");
    input.autocomplete = "off";
    input.spellcheck = false;
    var label = select.getAttribute("aria-label") || (select.labels && select.labels[0] && select.labels[0].textContent.trim());
    if (label) input.setAttribute("aria-label", label);
    if (select.getAttribute("aria-describedby")) input.setAttribute("aria-describedby", select.getAttribute("aria-describedby"));
    var panel = document.createElement("div");
    panel.className = "cb__panel";
    panel.hidden = true;
    var searchRow = document.createElement("div");
    searchRow.className = "cb__search";
    var search = document.createElement("input");
    search.type = "text";
    search.className = "cb__q";
    search.placeholder = "Zoeken…";
    search.autocomplete = "off";
    search.spellcheck = false;
    search.setAttribute("role", "combobox");
    search.setAttribute("aria-autocomplete", "list");
    search.setAttribute("aria-expanded", "true");
    search.setAttribute("aria-controls", id + "-list");
    search.setAttribute("aria-label", (label || "Keuze") + ": zoeken");
    var clear = document.createElement("button");
    clear.type = "button";
    clear.className = "cb__clear";
    clear.hidden = true;
    clear.tabIndex = -1;
    clear.setAttribute("aria-label", "Zoekopdracht wissen");
    clear.appendChild(icon("cb__icon", ICON_CLOSE));
    searchRow.appendChild(icon("cb__icon cb__icon--search", ICON_SEARCH));
    searchRow.appendChild(search);
    searchRow.appendChild(clear);
    var meta = document.createElement("div");
    meta.className = "cb__meta";
    meta.hidden = true;
    var list = document.createElement("ul");
    list.className = "cb__list";
    list.id = id + "-list";
    list.setAttribute("role", "listbox");
    panel.appendChild(searchRow);
    panel.appendChild(meta);
    panel.appendChild(list);

    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    wrap.appendChild(input);
    wrap.appendChild(panel);
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    select.classList.add("cb__native");

    var items = [];      // {li, opt}
    var active = -1;     // index into visible items
    var visible = [];
    var dirty = false;   // user typed since opening: only then filter

    function selectedText() {
      var o = select.options[select.selectedIndex];
      return o ? o.text.trim() : "";
    }
    function sync() {
      input.value = selectedText();
      input.placeholder = "";
      input.disabled = select.disabled;
      wrap.classList.toggle("is-placeholder", !select.value);
      if (select.getAttribute("aria-invalid")) input.setAttribute("aria-invalid", select.getAttribute("aria-invalid"));
    }

    function build() {
      list.textContent = "";
      items = [];
      var group = null, groupLabel = null;
      Array.prototype.forEach.call(select.querySelectorAll("option"), function (opt, i) {
        var g = opt.parentNode.tagName === "OPTGROUP" ? opt.parentNode : null;
        var li = document.createElement("li");
        li.className = "cb__opt";
        li.setAttribute("role", "option");
        li.id = id + "-o" + i;
        var txt = opt.text.trim(), m = /^(\d{3,6})\s+(.+)$/.exec(txt);
        if (m) {
          var code = document.createElement("span");
          code.className = "cb__code";
          code.textContent = m[1];
          li.appendChild(code);
          txt = m[2];
        }
        var name = document.createElement("span");
        name.className = "cb__name";
        name.textContent = txt;
        li.appendChild(name);
        li.appendChild(icon("cb__check", ICON_CHECK));
        if (opt.disabled || (g && g.disabled)) li.setAttribute("aria-disabled", "true");
        if (!opt.value) li.classList.add("cb__opt--empty");
        items.push({ li: li, opt: opt, group: g ? g.label : null, text: fold(opt.text) });
      });
    }

    function render() {
      var q = dirty ? fold(search.value).split(/\s+/).filter(Boolean) : [];
      visible = items.filter(function (it) {
        return q.every(function (t) { return it.text.indexOf(t) !== -1; });
      });
      list.textContent = "";
      clear.hidden = !search.value;
      meta.hidden = !q.length;
      meta.textContent = visible.length === 1 ? "1 resultaat" : visible.length + " resultaten";
      var last = null;
      visible.forEach(function (it) {
        if (it.group && it.group !== last) {
          var h = document.createElement("li");
          h.className = "cb__group";
          h.setAttribute("role", "presentation");
          h.textContent = it.group;
          list.appendChild(h);
        }
        last = it.group;
        it.li.setAttribute("aria-selected", String(it.opt.selected));
        it.li.classList.remove("is-active");
        list.appendChild(it.li);
      });
      if (!visible.length) {
        var none = document.createElement("li");
        none.className = "cb__none";
        none.setAttribute("role", "presentation");
        var ic = document.createElement("span");
        ic.className = "cb__none-icon";
        ic.appendChild(icon("cb__icon", ICON_SEARCH));
        var t = document.createElement("strong");
        t.textContent = "Niets gevonden";
        var h = document.createElement("span");
        h.textContent = "Probeer een andere zoekterm.";
        none.appendChild(ic); none.appendChild(t); none.appendChild(h);
        list.appendChild(none);
      }
      var sel = visible.findIndex(function (it) { return it.opt.selected; });
      setActive(dirty ? firstEnabled(0) : (sel >= 0 ? sel : firstEnabled(0)), true);
    }

    function firstEnabled(from) {
      for (var i = from; i < visible.length; i++) if (!visible[i].li.hasAttribute("aria-disabled")) return i;
      return -1;
    }

    function setActive(i, scroll) {
      if (visible[active]) visible[active].li.classList.remove("is-active");
      active = i;
      var it = visible[i];
      if (!it) { search.removeAttribute("aria-activedescendant"); return; }
      it.li.classList.add("is-active");
      search.setAttribute("aria-activedescendant", it.li.id);
      if (scroll) {
        var top = it.li.offsetTop, bottom = top + it.li.offsetHeight;
        if (top < list.scrollTop) list.scrollTop = top;
        else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
      }
    }

    function place() {
      var r = input.getBoundingClientRect();
      var gap = 6, chrome = 64; // search row + paddings
      var below = window.innerHeight - r.bottom - gap - 8, above = r.top - gap - 8;
      var up = below < 280 && above > below;
      var w = Math.max(r.width, 260);
      panel.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + "px";
      panel.style.width = w + "px";
      list.style.maxHeight = Math.max(120, Math.min(280, (up ? above : below) - chrome)) + "px";
      if (up) { panel.style.top = ""; panel.style.bottom = (window.innerHeight - r.top + gap) + "px"; }
      else { panel.style.bottom = ""; panel.style.top = (r.bottom + gap) + "px"; }
      wrap.classList.toggle("is-up", up);
    }

    function isOpen() { return !panel.hidden; }
    function open() {
      if (isOpen() || input.disabled) return;
      dirty = false;
      search.value = "";
      build();
      panel.hidden = false;
      input.setAttribute("aria-expanded", "true");
      wrap.classList.add("is-open");
      render();
      place();
      search.focus();
    }
    function close(refocus) {
      if (!isOpen()) return;
      panel.hidden = true;
      input.setAttribute("aria-expanded", "false");
      wrap.classList.remove("is-open");
      search.removeAttribute("aria-activedescendant");
      dirty = false;
      sync();
      if (refocus) input.focus();
    }
    function choose(it) {
      if (!it || it.li.hasAttribute("aria-disabled")) return;
      var changed = select.selectedIndex !== it.opt.index;
      valueDesc.set.call(select, it.opt.value);
      select.selectedIndex = it.opt.index;
      close(true);
      if (changed) {
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    input.addEventListener("mousedown", function (e) {
      e.preventDefault(); // keep focus handling in our hands; the search box takes it on open
      if (isOpen()) close(true); else open();
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
    search.addEventListener("input", function () {
      dirty = true;
      render();
    });
    clear.addEventListener("mousedown", function (e) {
      e.preventDefault();
      search.value = "";
      dirty = false;
      render();
      search.focus();
    });
    search.addEventListener("keydown", function (e) {
      var k = e.key;
      if (k === "ArrowDown" || k === "ArrowUp") {
        e.preventDefault();
        var step = k === "ArrowDown" ? 1 : -1, i = active;
        do { i += step; } while (visible[i] && visible[i].li.hasAttribute("aria-disabled"));
        if (visible[i]) setActive(i, true);
      } else if (k === "Enter") {
        e.preventDefault(); choose(visible[active]);
      } else if (k === "Escape") {
        e.preventDefault(); e.stopPropagation(); close(true);
      } else if (k === "Tab") {
        if (dirty && visible[active]) choose(visible[active]); else close(false);
      }
    });
    search.addEventListener("blur", function () { close(false); });
    list.addEventListener("mousedown", function (e) {
      e.preventDefault();
      var li = e.target.closest(".cb__opt");
      if (!li) return;
      choose(visible.filter(function (it) { return it.li === li; })[0]);
    });
    list.addEventListener("mousemove", function (e) {
      var li = e.target.closest(".cb__opt");
      var i = visible.findIndex(function (it) { return it.li === li; });
      if (i >= 0 && i !== active && !visible[i].li.hasAttribute("aria-disabled")) setActive(i, false);
    });
    panel.addEventListener("mousedown", function (e) { if (e.target !== search) e.preventDefault(); });
    window.addEventListener("scroll", function (e) { if (isOpen() && !panel.contains(e.target)) close(false); }, true);
    window.addEventListener("resize", function () { close(false); });

    // Labels / validation bubbles / scripts that focus the native select land on the visible input instead.
    select.addEventListener("focus", function () { input.focus(); });
    select.addEventListener("change", sync);
    select.addEventListener("invalid", function () { input.setAttribute("aria-invalid", "true"); });
    if (select.form) select.form.addEventListener("reset", function () { setTimeout(sync, 0); });

    // Scripts that set select.value directly (vat-suggest.js) do not fire events: mirror them.
    Object.defineProperty(select, "value", {
      configurable: true,
      get: function () { return valueDesc.get.call(this); },
      set: function (v) { valueDesc.set.call(this, v); sync(); }
    });

    sync();
  }

  // Undo for the htmx history snapshot: the restored page is enhanced again from clean markup.
  function teardown() {
    document.querySelectorAll("[data-combobox]").forEach(function (wrap) {
      var select = wrap.querySelector("select");
      if (select) {
        select.removeAttribute("data-cb");
        select.removeAttribute("aria-hidden");
        select.removeAttribute("tabindex");
        select.classList.remove("cb__native");
        wrap.parentNode.insertBefore(select, wrap);
      }
      wrap.remove();
    });
  }

  function init(root) {
    (root || document).querySelectorAll("select").forEach(enhance);
  }

  document.addEventListener("htmx:beforeHistorySave", teardown);
  document.addEventListener("htmx:historyRestore", function () { init(document); });
  document.addEventListener("htmx:load", function (e) { init(e.target && e.target.querySelectorAll ? e.target : document); });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { init(document); });
  else init(document);
})();
