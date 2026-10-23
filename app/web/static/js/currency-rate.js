/* Review form: show the wisselkoers field when the valuta is not EUR, and the btw-tarief for
 * verlegde btw when a line uses a verlegd btw-code (option[data-shifted]). Delegated, so rows
 * added later work too, and it re-runs after an hx-boost swap (the page is re-evaluated). */
(function () {
  function sync() {
    var currency = document.getElementById('currency');
    if (currency) {
      var code = (currency.value || 'EUR').trim().toUpperCase() || 'EUR';
      document.querySelectorAll('[data-foreign-only]').forEach(function (el) { el.hidden = code === 'EUR'; });
      document.querySelectorAll('[data-currency-name]').forEach(function (el) { el.textContent = code; });
    }
    var shifted = Array.prototype.some.call(
      document.querySelectorAll('select[name="line_vat_code"]'),
      function (select) { var o = select.options[select.selectedIndex]; return !!o && o.hasAttribute('data-shifted'); }
    );
    document.querySelectorAll('[data-shifted-only]').forEach(function (el) { el.hidden = !shifted; });
  }

  document.addEventListener('input', function (e) { if (e.target && e.target.id === 'currency') sync(); });
  document.addEventListener('change', function (e) {
    if (e.target && (e.target.id === 'currency' || e.target.name === 'line_vat_code')) sync();
  });
  document.addEventListener('htmx:afterSwap', sync);
  document.addEventListener('htmx:load', sync);
  sync();
})();
