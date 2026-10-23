/* Keeps bedrag excl. btw, btw-bedrag and bedrag incl. btw of a nakijken-regel in sync.
 * Contract: a <tr> holds input[name="line_amount_excl"], input[name="line_vat_amount"], input.js-amount-incl
 * (no name, never submitted) and select[name="line_vat_code"] whose <option> carries data-rate-bp.
 * Typing excl or incl rekent de rest terug; a hand-typed btw-bedrag only updates incl. Works for rows added later. */
(function () {
  function parse(text) {
    var t = (text || '').trim().replace(/[€\s]/g, '');
    if (!t) return null;
    t = t.indexOf(',') >= 0 ? t.replace(/\./g, '').replace(',', '.') : t;
    var n = Number(t);
    return isFinite(n) ? Math.round(n * 100) : null;
  }

  function format(cents) {
    var sign = cents < 0 ? '-' : '';
    var abs = Math.abs(cents);
    var euros = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    return sign + euros + ',' + String(abs % 100).padStart(2, '0');
  }

  function fields(row) {
    return {
      excl: row.querySelector('input[name="line_amount_excl"]'),
      vat: row.querySelector('input[name="line_vat_amount"]'),
      incl: row.querySelector('input.js-amount-incl'),
      code: row.querySelector('select[name="line_vat_code"]'),
    };
  }

  function rateBp(code) {
    var opt = code && code.options[code.selectedIndex];
    var bp = opt && opt.getAttribute('data-rate-bp');
    return bp === null || bp === '' || bp === undefined ? null : Number(bp);
  }

  function setVat(f, vatCents, bp) {
    // Rate 0 (verlegd, export) keeps the btw-bedrag empty, as the form hint asks.
    f.vat.value = bp === 0 ? '' : format(vatCents);
  }

  function fromExcl(f) {
    var excl = parse(f.excl.value);
    if (excl === null) return;
    var bp = rateBp(f.code);
    var vat;
    if (bp === null) {
      vat = parse(f.vat.value) || 0;
    } else {
      vat = Math.round(excl * bp / 10000);
      setVat(f, vat, bp);
    }
    f.incl.value = format(excl + vat);
  }

  function fromIncl(f) {
    var incl = parse(f.incl.value);
    if (incl === null) return;
    var bp = rateBp(f.code);
    if (bp === null) return; // no rate known: nothing to calculate back from
    var excl = Math.round(incl * 10000 / (10000 + bp));
    f.excl.value = format(excl);
    setVat(f, incl - excl, bp);
  }

  function fromVat(f) {
    var excl = parse(f.excl.value);
    if (excl !== null) f.incl.value = format(excl + (parse(f.vat.value) || 0));
  }

  document.addEventListener('input', function (event) {
    var el = event.target;
    var row = el.closest && el.closest('tr.line-row');
    if (!row) return;
    var f = fields(row);
    if (!f.incl) return;
    if (el === f.excl) fromExcl(f);
    else if (el === f.incl) fromIncl(f);
    else if (el === f.vat) fromVat(f);
  });

  document.addEventListener('change', function (event) {
    var row = event.target.closest && event.target.closest('tr.line-row');
    if (!row) return;
    var f = fields(row);
    if (f.incl && event.target === f.code) fromExcl(f);
  });

  document.querySelectorAll('tr.line-row').forEach(function (row) {
    var f = fields(row);
    if (f.incl && !f.incl.value) fromVat(f);
  });
})();
