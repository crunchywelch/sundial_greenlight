#!/usr/bin/env python3
"""
Generate the theme app extension files for the sundial-cordsets app from the
shared UI source (build_prototype.py). Writes the block Liquid, CSS/JS assets,
and copies the catalog into the extension's assets so the block reads it.

Live cart: the bootstrap in cordset.js posts real component variants to
/cart/add.js, grouped by a `_cordset` line-item property; switch placement rides
along as a line property. Labor is added only if the merchant picks an assembly
product in the block settings.

    venv/bin/python util/wire/cordset/build_extension.py
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from util.wire.cordset.build_prototype import APP_MARKUP, CSS, JS_CORE

D = Path(__file__).parent
EXT = Path("/home/welch/projects/sundial-cordsets/extensions/cordset-configurator")

# --- live bootstrap appended to the shared controller -----------------------
BOOTSTRAP = r"""
;(function(){
  var app = document.querySelector('.cordset-app');
  if(!app || !window.startCordset) return;
  var laborVar = app.getAttribute('data-labor-variant') || "";
  var laborPrice = parseFloat(app.getAttribute('data-labor-price') || "");   // Shopify price is in cents
  var laborTitle = app.getAttribute('data-labor-title') || "";

  function addToCart(cart){
    var items = [];
    cart.forEach(function(c){
      var q = c.qty || 1;
      c.lines.forEach(function(l){
        if(!l.variantId) return;               // skip unpriced lines (e.g. labor not configured)
        var props = {}; for(var k in (l.properties||{})) props[k] = l.properties[k];
        if(q > 1) props["Cord sets"] = String(q);
        items.push({ id: Number(l.variantId), quantity: (l.quantity || 1) * q, properties: props });
      });
    });
    if(!items.length) return Promise.reject(new Error("nothing to add"));
    return fetch('/cart/add.js', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ items: items })
    }).then(function(r){
      if(!r.ok) return r.json().then(function(e){ throw new Error((e && e.description) || 'add failed'); });
      return r.json();
    }).then(function(){ window.location.href = '/cart'; });
  }

  fetch(app.getAttribute('data-catalog-url'), {headers:{'Accept':'application/json'}})
    .then(function(r){ return r.json(); })
    .then(function(C){
      var LABOR = C.labor || {price:0};
      if(laborVar){ LABOR.variantId = laborVar;
        if(!isNaN(laborPrice)) LABOR.price = laborPrice/100;
        if(laborTitle) LABOR.title = laborTitle; }
      window.startCordset(C, LABOR, {live:true, addToCart:addToCart});
    })
    .catch(function(){
      var m = document.getElementById('livePreview');
      if(m) m.textContent = 'Could not load the cord set builder — please refresh.';
    });
})();
"""

# startCordset is declared as a top-level function; expose it for the bootstrap.
JS = JS_CORE + "\nwindow.startCordset = startCordset;\n" + BOOTSTRAP

BLOCK = (
    '<div class="wrap cordset cordset-app'
    '{% unless block.settings.paper_bg %} cordset-bare{% endunless %}'
    '{% unless block.settings.constrain_width %} cordset-full{% endunless %}"\n'
    '     data-catalog-url="{{ \'cordsets.catalog.json\' | asset_url }}"\n'
    '     data-labor-variant="{{ block.settings.labor_product.selected_or_first_available_variant.id }}"\n'
    '     data-labor-price="{{ block.settings.labor_product.selected_or_first_available_variant.price }}"\n'
    '     data-labor-title="{{ block.settings.labor_product.title | escape }}">\n'
    + APP_MARKUP +
    '</div>\n\n'
    "{{ 'cordset.css' | asset_url | stylesheet_tag }}\n"
    "<script src=\"{{ 'cordset.js' | asset_url }}\" defer></script>\n\n"
    "{% schema %}\n"
    "{\n"
    '  "name": "Cord Set Builder",\n'
    '  "target": "section",\n'
    '  "settings": [\n'
    '    { "type": "checkbox", "id": "paper_bg", "label": "Paper background",\n'
    '      "info": "Off = transparent, inherits your theme background.", "default": false },\n'
    '    { "type": "checkbox", "id": "constrain_width", "label": "Constrain width",\n'
    '      "info": "On = centered, max 1180px. Off = full width of its section.", "default": true },\n'
    '    { "type": "product", "id": "labor_product", "label": "Assembly labor product",\n'
    '      "info": "Optional. Added as its own cart line per cord set. Leave empty to omit for now." }\n'
    "  ]\n"
    "}\n"
    "{% endschema %}\n"
)


def main():
    (EXT / "assets").mkdir(parents=True, exist_ok=True)
    (EXT / "blocks").mkdir(parents=True, exist_ok=True)

    (EXT / "assets" / "cordset.css").write_text(CSS)
    (EXT / "assets" / "cordset.js").write_text(JS)
    (EXT / "blocks" / "cordset.liquid").write_text(BLOCK)
    catalog = json.loads((D / "cordsets.catalog.json").read_text())
    (EXT / "assets" / "cordsets.catalog.json").write_text(json.dumps(catalog, separators=(",", ":")))

    # Sanity-check the embedded block schema is valid JSON before we ship it.
    schema = BLOCK.split("{% schema %}")[1].split("{% endschema %}")[0]
    json.loads(schema)

    # Remove the scaffold's sample block/snippet/asset so only ours ships.
    for junk in [EXT / "blocks" / "star_rating.liquid",
                 EXT / "snippets" / "stars.liquid",
                 EXT / "assets" / "thumbs-up.png"]:
        if junk.exists():
            junk.unlink()
    loc = EXT / "locales" / "en.default.json"
    if loc.exists():
        loc.write_text("{}\n")

    cat_bytes = (EXT / "assets" / "cordsets.catalog.json").stat().st_size
    print("wrote extension files to", EXT)
    print(f"  blocks/cordset.liquid, assets/cordset.css ({len(CSS)}b), "
          f"assets/cordset.js ({len(JS)}b), assets/cordsets.catalog.json ({cat_bytes}b)")


if __name__ == "__main__":
    main()
