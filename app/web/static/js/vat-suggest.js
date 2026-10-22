/* Fills in the btw-tarief of a line when the user picks an account that has a standaard btw-tarief.
 * Contract: account <option> carries data-vat="CODE" ("" = Geen btw); the btw select sits in the same <tr>
 * as select[name$="vat"] or select[name$="vat_code"]. A btw select the user touched (or that the server
 * rendered with a value, data-touched="1") is never overwritten. Works for rows added later (delegation). */
(function () {
  var VAT_SELECTOR = 'select[name$="vat"], select[name$="vat_code"]';

  function vatSelectFor(el) {
    var row = el.closest('tr');
    return row ? row.querySelector(VAT_SELECTOR) : null;
  }

  document.addEventListener('change', function (event) {
    var target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;

    // The user chose a btw-tarief themselves: stop suggesting for this row.
    if (target.matches(VAT_SELECTOR)) {
      target.dataset.touched = '1';
      return;
    }

    var option = target.options[target.selectedIndex];
    if (!option || !option.hasAttribute('data-vat')) return;
    var vatSelect = vatSelectFor(target);
    if (!vatSelect || vatSelect.dataset.touched === '1') return;

    var wanted = option.getAttribute('data-vat') || '';
    var hasOption = Array.prototype.some.call(vatSelect.options, function (o) { return o.value === wanted; });
    if (hasOption) vatSelect.value = wanted;
  });
})();
