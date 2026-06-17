/**
 * App Proxy page: Custom Cable Sets configurator.
 *
 * Storefront URL: https://sundialaudio.com/apps/custom-cables
 *   → Shopify HMAC-signs the request and proxies it to this route via the
 *     [app_proxy] block in shopify.app.toml. authenticate.public.appProxy
 *     verifies the signature and gives us a `liquid()` helper that renders
 *     our markup inside the live theme (so it looks native).
 *
 * The page is server-rendered HTML + a self-contained vanilla-JS controller.
 * The option catalog and pricing constants are embedded from
 * custom-config.server.js so the client renders the same options and shows
 * the same live price the server will recompute on submit.
 *
 * Copy is lifted from custom_cable_sets_page.md.
 */

import { authenticate } from "../shopify.server.js";
import { configCatalog } from "../custom-config.server.js";

export async function loader({ request }) {
  const { liquid } = await authenticate.public.appProxy(request);
  const catalog = configCatalog();
  return liquid(pageHtml(catalog));
}

function pageHtml(catalog) {
  // JSON.stringify is safe inside Liquid: it never emits `{{` or `{%`.
  const catalogJson = JSON.stringify(catalog);
  return `
<div class="ccs">
  <section class="ccs-hero">
    <h1>Custom Cable Sets</h1>
    <p class="ccs-lede">Your pattern. Your colors. Built by hand.</p>
    <p>Every Sundial Audio cable starts from the same foundation: Canare GS-6 or Star Quad core,
       Neutrik connectors, hand-soldered terminations, and our signature cloth overbraid.
       A custom run lets you decide how it looks &mdash; any pattern, any color in
       our catalog, cut and terminated to your spec.</p>
    <p>Outfitting a studio. Matching a touring rig to your brand. Or just building a cable
       that looks like nothing else on the rack. Tell us what you want, and we&rsquo;ll
       braid it to order in our Massachusetts shop.</p>
  </section>

  <ol class="ccs-how">
    <li><strong>Choose your cable type</strong> &mdash; 1/4" instrument, or XLR/microphone.</li>
    <li><strong>Choose a braid pattern</strong> &mdash; solid, houndstooth, tracer, zig-zag, and more.</li>
    <li><strong>Choose your colors</strong> &mdash; any color in our catalog.</li>
    <li><strong>Give us your lengths and quantities</strong> &mdash; one long run cut into however many finished cables you need.</li>
    <li><strong>We braid, build, test, and ship.</strong></li>
  </ol>

  <form id="ccs-form" class="ccs-form" novalidate>
    <div class="ccs-grid">
      <label class="ccs-field">
        <span>Cable type</span>
        <select name="cableType" id="ccs-cableType"></select>
      </label>
      <label class="ccs-field">
        <span>Fabric</span>
        <select name="fabric" id="ccs-fabric"></select>
      </label>
      <label class="ccs-field">
        <span>Pattern</span>
        <select name="pattern" id="ccs-pattern"></select>
        <img class="ccs-pattern-img" id="ccs-patternImg" alt="" hidden />
        <p class="ccs-pattern-note" id="ccs-patternNote"></p>
      </label>
      <label class="ccs-field">
        <span>Primary color</span>
        <div class="ccs-color-row">
          <select name="primaryColor" id="ccs-primaryColor"></select>
          <span class="ccs-chip" id="ccs-primaryChip" aria-hidden="true"></span>
        </div>
      </label>
      <label class="ccs-field" id="ccs-accentWrap">
        <span>Accent color</span>
        <div class="ccs-color-row">
          <select name="accentColor" id="ccs-accentColor"></select>
          <span class="ccs-chip" id="ccs-accentChip" aria-hidden="true"></span>
        </div>
      </label>
      <label class="ccs-field" id="ccs-accent2Wrap">
        <span>Second accent color</span>
        <div class="ccs-color-row">
          <select name="accentColor2" id="ccs-accent2"></select>
          <span class="ccs-chip" id="ccs-accent2Chip" aria-hidden="true"></span>
        </div>
      </label>
    </div>

    <fieldset class="ccs-lines">
      <legend>Cables in your set</legend>
      <p class="ccs-hint">One run cut into as many finished cables as you like &mdash;
         each line is a length, a quantity, and (for instrument cables) a connector
         style. Minimum order is <strong>100 ft of total cable</strong>.</p>
      <div id="ccs-lineRows"></div>
      <button type="button" class="ccs-link" id="ccs-addLine">+ Add another length</button>
      <p class="ccs-total" id="ccs-lineTotal"></p>
    </fieldset>

    <div class="ccs-quote" id="ccs-quote" aria-live="polite"></div>

    <fieldset class="ccs-contact">
      <legend>Your details</legend>
      <div class="ccs-grid">
        <label class="ccs-field"><span>Name</span>
          <input type="text" name="name" id="ccs-name" required /></label>
        <label class="ccs-field"><span>Email</span>
          <input type="email" name="email" id="ccs-email" required /></label>
        <label class="ccs-field"><span>Phone (optional)</span>
          <input type="tel" name="phone" id="ccs-phone" /></label>
      </div>
      <label class="ccs-field ccs-wide"><span>Notes for our team (optional)</span>
        <textarea name="notes" id="ccs-notes" rows="3"
          placeholder="Tell us about your gear, your setup, your deadline&hellip;"></textarea></label>
    </fieldset>

    <button type="submit" class="ccs-submit" id="ccs-submit">Request my quote</button>
    <div class="ccs-result" id="ccs-result" aria-live="polite"></div>
    <p class="ccs-fallback">Prefer to talk it through?
       <a href="mailto:custserv@sundialwire.com">custserv@sundialwire.com</a> &middot;
       413-582-6909 &middot; Handcrafted in Florence, Massachusetts.</p>
  </form>
</div>

<style>
  .ccs { max-width: 820px; margin: 0 auto; padding: 1.5rem; line-height: 1.5; }
  .ccs h1 { margin-bottom: .25rem; }
  .ccs-lede { font-size: 1.25rem; font-weight: 600; margin: 0 0 1rem; }
  .ccs-how { margin: 1.5rem 0 2rem; padding-left: 1.25rem; }
  .ccs-how li { margin: .35rem 0; }
  .ccs-form { border-top: 1px solid #ddd; padding-top: 1.5rem; }
  .ccs-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
  .ccs-field { display: flex; flex-direction: column; gap: .35rem; margin-bottom: 1rem; }
  .ccs-field.ccs-wide { grid-column: 1 / -1; }
  .ccs-field > span { font-weight: 600; font-size: .9rem; }
  .ccs-field select, .ccs-field input, .ccs-field textarea {
    padding: .55rem .6rem; border: 1px solid #bbb; border-radius: 6px; font: inherit; width: 100%;
  }
  .ccs-color-row { display: flex; align-items: center; gap: .5rem; }
  .ccs-color-row select { flex: 1 1 auto; min-width: 0; }
  .ccs-chip { width: 24px; height: 24px; border-radius: 50%; border: 1px solid rgba(0,0,0,.3); flex: 0 0 auto; box-shadow: inset 0 0 0 1px rgba(255,255,255,.4); }
  .ccs-pattern-img { display: block; max-width: 280px; width: 100%; height: auto; border-radius: 8px; margin: .25rem 0 .5rem; filter: grayscale(1); }
  .ccs-pattern-note { font-size: .9rem; color: #555; margin: -.25rem 0 1rem; }
  .ccs-lines, .ccs-contact { border: 1px solid #ddd; border-radius: 8px; padding: 1rem 1.25rem; margin: 1.5rem 0; }
  .ccs-lines legend, .ccs-contact legend { font-weight: 700; padding: 0 .4rem; }
  .ccs-hint { font-size: .9rem; color: #555; margin-top: 0; }
  .ccs-line-row { display: grid; grid-template-columns: 1fr 1fr 1.6fr auto; gap: .75rem; align-items: end; margin-bottom: .6rem; }
  .ccs-line-row.no-conn { grid-template-columns: 1fr 1fr auto; }
  .ccs-line-row.no-conn .ccs-conn { display: none; }
  .ccs-line-row label { display: flex; flex-direction: column; gap: .3rem; font-size: .85rem; font-weight: 600; }
  .ccs-line-row input, .ccs-line-row select { padding: .5rem; border: 1px solid #bbb; border-radius: 6px; font: inherit; }
  .ccs-total { font-weight: 600; margin: .75rem 0 0; }
  .ccs-link { background: none; border: none; color: #1a6; font: inherit; font-weight: 600; cursor: pointer; padding: .25rem 0; }
  .ccs-remove { background: none; border: 1px solid #ccc; border-radius: 6px; cursor: pointer; padding: .5rem .7rem; }
  .ccs-quote { background: #f6f6f4; border-radius: 8px; padding: 1rem 1.25rem; margin: 1rem 0; }
  .ccs-quote table { width: 100%; border-collapse: collapse; }
  .ccs-quote td { padding: .25rem 0; }
  .ccs-quote td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .ccs-quote .total td { border-top: 1px solid #ccc; font-weight: 700; padding-top: .5rem; }
  .ccs-quote .warn { color: #b00; font-weight: 600; }
  .ccs-submit { background: #111; color: #fff; border: none; border-radius: 8px; padding: .8rem 1.4rem; font: inherit; font-weight: 700; cursor: pointer; }
  .ccs-submit[disabled] { opacity: .5; cursor: not-allowed; }
  .ccs-result { margin-top: 1rem; font-weight: 600; }
  .ccs-result.ok { color: #1a6; }
  .ccs-result.err { color: #b00; }
  .ccs-fallback { margin-top: 1.5rem; font-size: .9rem; color: #555; }
  @media (max-width: 560px) { .ccs-grid { grid-template-columns: 1fr; } }
</style>

<script>
(function () {
  var CATALOG = ${catalogJson};
  var P = CATALOG.pricing;
  var fmt = function (n) {
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  var el = function (id) { return document.getElementById(id); };

  // Ask Shopify's CDN to resize the image to ~2x the 280px display box, so
  // large originals don't ship full-size. Scales with device pixel ratio,
  // capped. No-op on non-Shopify URLs.
  function sized(url) {
    if (!url || url.indexOf("cdn.shopify.com") === -1) return url;
    var w = Math.min(840, Math.round(280 * (window.devicePixelRatio || 1)));
    return url + (url.indexOf("?") === -1 ? "?" : "&") + "width=" + w;
  }

  function opt(value, label) {
    var o = document.createElement("option");
    o.value = value; o.textContent = label; return o;
  }
  function fill(select, items, getV, getL) {
    select.innerHTML = "";
    items.forEach(function (it) { select.appendChild(opt(getV(it), getL(it))); });
  }

  var cableTypeSel = el("ccs-cableType");
  fill(cableTypeSel, CATALOG.cableTypes, function (t) { return t.value; }, function (t) { return t.label; });
  fill(el("ccs-pattern"), CATALOG.patterns, function (p) { return p.value; }, function (p) { return p.label; });
  fill(el("ccs-fabric"), CATALOG.fabrics, function (f) { return f.value; }, function (f) { return f.label; });

  // Colors depend on fabric (rayon vs cotton). Repopulate both color
  // dropdowns from the selected fabric's list, keeping the current pick if
  // it's still offered.
  function fillColors(select, list) {
    var keep = select.value;
    fill(select, list, function (c) { return c.value; }, function (c) { return c.label; });
    if (list.some(function (c) { return c.value === keep; })) select.value = keep;
  }
  function syncColors() {
    var list = CATALOG.colors[el("ccs-fabric").value] || [];
    fillColors(el("ccs-primaryColor"), list);
    fillColors(el("ccs-accentColor"), list);
    fillColors(el("ccs-accent2"), list);
    updateChips();
  }
  // Swatch chip beside each color dropdown reflects the selected color's hex.
  function chipHex(selectId) {
    var list = CATALOG.colors[el("ccs-fabric").value] || [];
    var c = list.find(function (x) { return x.value === el(selectId).value; });
    return c && c.hex ? c.hex : null;
  }
  function setChip(chipId, hex) {
    var chip = el(chipId);
    if (hex) { chip.style.background = hex; chip.style.visibility = "visible"; }
    else { chip.style.visibility = "hidden"; }
  }
  function updateChips() {
    setChip("ccs-primaryChip", chipHex("ccs-primaryColor"));
    setChip("ccs-accentChip", chipHex("ccs-accentColor"));
    setChip("ccs-accent2Chip", chipHex("ccs-accent2"));
  }
  ["ccs-primaryColor", "ccs-accentColor", "ccs-accent2"].forEach(function (id) {
    el(id).addEventListener("change", updateChips);
  });
  el("ccs-fabric").addEventListener("change", syncColors);
  syncColors();

  function connectorsForType() {
    var t = CATALOG.cableTypes.find(function (x) { return x.value === cableTypeSel.value; });
    return (t && t.connectors) || [];
  }
  // Connectors are chosen per cable (per line). Microphone is always XLR–XLR,
  // so its rows show no connector picker; instrument rows let you pick
  // straight/straight vs straight/right-angle.
  function syncRowConnectors() {
    var conns = connectorsForType();
    var choice = conns.length > 1;
    Array.prototype.forEach.call(rows.children, function (r) {
      var sel = r.querySelector(".ccs-connector");
      r.classList.toggle("no-conn", !choice);
      if (choice && sel) {
        var keep = sel.value;
        fill(sel, conns, function (c) { return c.value; }, function (c) { return c.label; });
        if (conns.some(function (c) { return c.value === keep; })) sel.value = keep;
      }
    });
  }
  function syncPattern() {
    var p = CATALOG.patterns.find(function (x) { return x.value === el("ccs-pattern").value; });
    var n = (p && p.colors) || 1;
    el("ccs-accentWrap").style.display = n >= 2 ? "" : "none";
    el("ccs-accent2Wrap").style.display = n >= 3 ? "" : "none";
    el("ccs-patternNote").textContent = (p && p.note) || "";
    var img = el("ccs-patternImg");
    if (p && p.image) {
      img.src = sized(p.image);
      img.alt = p.label + " braid pattern";
      img.hidden = false;
    } else {
      img.hidden = true;
      img.removeAttribute("src");
    }
  }
  cableTypeSel.addEventListener("change", syncRowConnectors);
  el("ccs-pattern").addEventListener("change", syncPattern);
  syncPattern();

  var rows = el("ccs-lineRows");
  function addRow(len, qty, connector) {
    var row = document.createElement("div");
    row.className = "ccs-line-row";
    row.innerHTML =
      '<label>Length (ft)<input type="number" class="ccs-len" min="0.5" step="0.5" value="' + (len || "") + '"></label>' +
      '<label>Quantity<input type="number" class="ccs-qty" min="1" step="1" value="' + (qty || "") + '"></label>' +
      '<label class="ccs-conn">Connector<select class="ccs-connector"></select></label>' +
      '<button type="button" class="ccs-remove" aria-label="Remove">&times;</button>';
    row.querySelector(".ccs-remove").addEventListener("click", function () {
      if (rows.children.length > 1) { row.remove(); recompute(); }
    });
    row.querySelector(".ccs-len").addEventListener("input", recompute);
    row.querySelector(".ccs-qty").addEventListener("input", recompute);
    rows.appendChild(row);
    syncRowConnectors();
    if (connector) {
      var sel = row.querySelector(".ccs-connector");
      if (sel) sel.value = connector;
    }
  }
  el("ccs-addLine").addEventListener("click", function () { addRow(); recompute(); });

  function readLines() {
    var conns = connectorsForType();
    var choice = conns.length > 1;
    var defaultConn = conns.length ? conns[0].value : "";
    var out = [];
    Array.prototype.forEach.call(rows.children, function (r) {
      var len = parseFloat(r.querySelector(".ccs-len").value);
      var qty = parseInt(r.querySelector(".ccs-qty").value, 10);
      var sel = r.querySelector(".ccs-connector");
      var conn = (choice && sel) ? sel.value : defaultConn;
      if (len > 0 && qty > 0) out.push({ lengthFt: len, quantity: qty, connector: conn });
    });
    return out;
  }

  function quote(lines) {
    var totalFeet = 0, totalCables = 0;
    lines.forEach(function (l) { totalFeet += l.lengthFt * l.quantity; totalCables += l.quantity; });
    var cableCost = totalFeet * P.perFoot, connectorCost = totalCables * P.perCable;
    return {
      totalFeet: totalFeet, totalCables: totalCables, cableCost: cableCost,
      connectorCost: connectorCost, total: cableCost + connectorCost,
      meetsMinimum: totalFeet >= P.minTotalFeet
    };
  }

  function recompute() {
    var lines = readLines();
    var box = el("ccs-quote");
    var totalEl = el("ccs-lineTotal");
    if (lines.length === 0) {
      totalEl.textContent = "";
      box.innerHTML = "<em>Add a length and quantity to see your price.</em>";
      el("ccs-submit").disabled = true;
      return;
    }
    var q = quote(lines);
    totalEl.textContent = "Total cable: " + q.totalFeet + " ft across " +
      q.totalCables + " cable" + (q.totalCables === 1 ? "" : "s") + ".";
    var html = "<table>" +
      "<tr><td>Wire &mdash; " + q.totalFeet + " ft &times; " + fmt(P.perFoot) + "/ft</td><td class='num'>" + fmt(q.cableCost) + "</td></tr>" +
      "<tr><td>Cable Qty &mdash; " + q.totalCables + " &times; " + fmt(P.perCable) + "</td><td class='num'>" + fmt(q.connectorCost) + "</td></tr>" +
      "<tr class='total'><td>Estimated total</td><td class='num'>" + fmt(q.total) + "</td></tr></table>";
    if (!q.meetsMinimum) {
      html += "<p class='warn'>Minimum order is " + P.minTotalFeet + " ft of total cable (you have " + q.totalFeet + " ft).</p>";
    }
    html += "<p class='ccs-hint'>This is an estimate. We&rsquo;ll confirm final pricing on your quote.</p>";
    box.innerHTML = html;
    el("ccs-submit").disabled = !q.meetsMinimum;
  }

  addRow(20, 5);
  recompute();

  el("ccs-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var result = el("ccs-result");
    var lines = readLines();
    var q = quote(lines);
    if (!q.meetsMinimum) { result.className = "ccs-result err"; result.textContent = "Please reach the 100 ft minimum before requesting a quote."; return; }
    var email = el("ccs-email").value.trim(), name = el("ccs-name").value.trim();
    if (!name || !email) { result.className = "ccs-result err"; result.textContent = "Name and email are required."; return; }

    var patternSel = CATALOG.patterns.find(function (x) { return x.value === el("ccs-pattern").value; });
    var payload = {
      cableType: cableTypeSel.value,
      pattern: el("ccs-pattern").value,
      fabric: el("ccs-fabric").value,
      primaryColor: el("ccs-primaryColor").value,
      accentColor: (patternSel && patternSel.colors >= 2) ? el("ccs-accentColor").value : null,
      accentColor2: (patternSel && patternSel.colors >= 3) ? el("ccs-accent2").value : null,
      lines: lines,
      name: name, email: email,
      phone: el("ccs-phone").value.trim(),
      notes: el("ccs-notes").value.trim()
    };
    var btn = el("ccs-submit");
    btn.disabled = true; result.className = "ccs-result"; result.textContent = "Sending your request\\u2026";
    fetch("/apps/custom-cables/submit", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d.success) {
          result.className = "ccs-result ok";
          result.textContent = "Thanks, " + name + "! Your custom cable request is in \\u2014 we\\u2019ll email a quote shortly.";
          el("ccs-form").reset(); rows.innerHTML = ""; addRow(20, 5); syncRowConnectors(); syncColors(); syncPattern(); recompute();
        } else {
          result.className = "ccs-result err";
          result.textContent = (res.d && res.d.error) || "Something went wrong. Please email custserv@sundialwire.com.";
          btn.disabled = false;
        }
      }).catch(function () {
        result.className = "ccs-result err";
        result.textContent = "Network error. Please email custserv@sundialwire.com.";
        btn.disabled = false;
      });
  });
})();
</script>
`;
}
