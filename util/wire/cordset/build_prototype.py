#!/usr/bin/env python3
"""
Shared cord-set configurator UI source + the Artifact assembler.

Defines the markup / CSS / JS ONCE (APP_MARKUP, CSS, JS_CORE) so both this
standalone prototype and the real theme app extension (build_extension.py) are
built from the same tested source. `startCordset(CAT, LABOR, OPTS)` is the
entry point; OPTS.addToCart makes it live (real /cart/add.js), absent = demo.

    venv/bin/python util/wire/cordset/build_prototype.py   # -> prototype.html
"""
import json
import sys
from pathlib import Path

D = Path(__file__).parent

# ---------------------------------------------------------------------------
# Functional markup shared by the Artifact and the theme block (masthead is
# target-specific and prepended by each assembler).
# ---------------------------------------------------------------------------
APP_MARKUP = r"""
  <div class="bench">
    <section class="config" aria-label="Configure cord set">

      <fieldset class="step" id="step-wire">
        <legend><span class="num">1</span> Wire</legend>
        <div class="filters" id="wireFilters"></div>
        <input type="search" id="wireSearch" class="search" placeholder="Search color or pattern&hellip;"
               autocomplete="off" aria-label="Search wire" />
        <div class="wirelist" id="wireList" role="listbox" aria-label="Wire options"></div>
      </fieldset>

      <fieldset class="step optional" id="step-plug" disabled>
        <legend><span class="num">2</span> Plug <span class="endhint">(line-cord end)</span></legend>
        <div class="optgrid" id="plugList"></div>
        <div class="variantpick" id="plugVar" hidden></div>
      </fieldset>

      <fieldset class="step" id="step-length" disabled>
        <legend><span class="num">3</span> Length</legend>
        <div class="lenrow">
          <div class="stepper">
            <button type="button" data-len="-1" aria-label="Less">&minus;</button>
            <input type="number" id="lenInput" min="1" max="100" step="1" value="8" inputmode="numeric" />
            <button type="button" data-len="1" aria-label="More">+</button>
          </div>
          <span class="lenunit">feet</span>
          <div class="chips" id="lenPresets"></div>
        </div>
      </fieldset>

      <fieldset class="step optional" id="step-socket" disabled>
        <legend><span class="num">4</span> Socket <span class="endhint">(other end &mdash; makes it a pendant)</span></legend>
        <div class="optgrid socketgrid" id="socketList"></div>
        <div class="variantpick" id="socketVar" hidden></div>
      </fieldset>

      <fieldset class="step optional" id="step-switch" disabled>
        <legend><span class="num">5</span> In-line switch <span class="endhint">(optional)</span></legend>
        <div class="optgrid" id="switchList"></div>
        <div class="variantpick" id="switchVar" hidden></div>
        <div class="switchpos" id="switchPos" hidden></div>
      </fieldset>
    </section>

    <div class="sidecol">
      <aside class="panel preview" aria-label="Cord set preview">
        <div class="panel-head"><h2>Preview</h2></div>
        <div class="live" id="livePreview"></div>
        <button type="button" class="addbtn" id="addBtn" disabled>Add cord set to ticket</button>
        <p class="fineprint">Appropriate strain relief is included with every cord set.</p>
      </aside>
      <aside class="panel ticket" aria-label="Order ticket">
        <div class="panel-head">
          <h2>Your cord sets</h2>
          <span class="badge" id="cartCount">0 cord sets</span>
        </div>
        <div class="cart" id="cart"></div>
        <div class="totals" id="totals"></div>
        <button type="button" class="checkout" id="checkoutBtn" disabled>Add all to cart</button>
      </aside>
    </div>
  </div>
  <div class="toast" id="toast" role="status" aria-live="polite"></div>
"""

CSS = r"""
:root{
  /* Palette + fonts inherited from the Atlantic storefront theme:
     Fraunces headings, Halant body, Outfit micro-labels (all loaded globally
     by the theme), slate/navy ink on white. */
  --paper:#ffffff; --paper-2:#f6f5f1; --card:#ffffff; --ink:#222222; --ink-soft:#646464;
  --line:#e7e4dd; --line-2:#d8d4ca;
  --brass:#414d53; --brass-2:#2e383d; --patina:#6f8087; --patina-2:#55636a;
  --danger:#b23b3b; --good:#3f6f63;
  --disabled:#c3c0b8;
  --shadow:0 1px 0 rgba(255,255,255,.6), 0 8px 22px rgba(1,2,23,.06);
  --radius:10px;
  --display:"Fraunces","Halant",Georgia,"Times New Roman",serif;
  --body:"Halant",Georgia,"Times New Roman",serif;
  --label:"Outfit",ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
/* The storefront theme is light-only, so the form stays light regardless of the
   visitor's OS colour scheme (no prefers-color-scheme dark auto-switch). */
:root[data-theme="light"]{
  --paper:#ffffff; --paper-2:#f6f5f1; --card:#ffffff; --ink:#222222; --ink-soft:#646464;
  --line:#e7e4dd; --line-2:#d8d4ca; --brass:#414d53; --brass-2:#2e383d; --patina:#6f8087;
  --patina-2:#55636a; --danger:#b23b3b; --good:#3f6f63; --disabled:#c3c0b8;
  --shadow:0 1px 0 rgba(255,255,255,.6), 0 8px 22px rgba(1,2,23,.06);
}
:root[data-theme="dark"]{
  --paper:#1E1B17; --paper-2:#242019; --card:#2A251E; --ink:#EDE6D6; --ink-soft:#A79E8A;
  --line:#3A342A; --line-2:#4A4234; --brass:#CBA35A; --brass-2:#DAB771; --patina:#5E9488;
  --patina-2:#77ADA0; --danger:#D68472; --good:#77ADA0; --disabled:#5C5545;
  --shadow:0 1px 0 rgba(255,255,255,.03), 0 10px 26px rgba(0,0,0,.45);
}

.cordset *{box-sizing:border-box}
.wrap{max-width:1180px;margin:0 auto;padding:clamp(1rem,3vw,2.4rem);
  background:var(--paper);color:var(--ink);font-family:var(--body);line-height:1.5;
  min-height:100%;}
.wrap.cordset-bare{background:transparent}
.wrap.cordset-full{max-width:none}
.masthead{border-bottom:2px solid var(--ink);padding-bottom:1.1rem;margin-bottom:1.6rem}
.brand{display:flex;align-items:center;gap:.9rem}
.mark{width:34px;height:34px;border-radius:50%;flex:0 0 auto;
  background:
    radial-gradient(circle at 50% 50%, transparent 34%, var(--brass) 35%, var(--brass) 44%, transparent 45%),
    conic-gradient(from -90deg, var(--brass), var(--patina), var(--brass));
  box-shadow:inset 0 0 0 2px var(--paper);}
.kicker{font-family:var(--label);text-transform:uppercase;letter-spacing:.16em;
  font-size:.66rem;color:var(--ink-soft);margin:0 0 .1rem}
.wrap h1{font-family:var(--display);font-weight:800;letter-spacing:-.01em;
  font-size:clamp(1.5rem,3.4vw,2.15rem);margin:0;text-wrap:balance}
.lede{max-width:60ch;margin:.9rem 0 .3rem;color:var(--ink)}
.proto-note{font-family:var(--mono);font-size:.68rem;letter-spacing:.04em;color:var(--ink-soft);
  text-transform:uppercase;margin:.35rem 0 0}

.bench{display:grid;grid-template-columns:1fr;gap:1.4rem}
@media(min-width:900px){.bench{grid-template-columns:1.15fr .85fr;align-items:start}
  .sidecol{position:sticky;top:1rem}}

.step{border:1px solid var(--line);border-radius:var(--radius);background:var(--card);
  box-shadow:var(--shadow);padding:1rem 1.05rem 1.1rem;margin:0 0 1.1rem;min-inline-size:0}
.step[disabled]{opacity:.5;filter:saturate(.6)}
.step legend{font-family:var(--display);font-weight:700;font-size:1.02rem;display:flex;
  align-items:center;gap:.5rem;padding:0}
.num{font-family:var(--mono);font-size:.72rem;font-weight:700;background:var(--ink);color:var(--paper);
  width:1.35rem;height:1.35rem;border-radius:50%;display:inline-grid;place-items:center;letter-spacing:0}
.endhint{font-family:var(--body);font-weight:400;font-size:.8rem;color:var(--ink-soft)}
.optional legend::after{content:"optional";font-family:var(--label);font-size:.6rem;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-soft);border:1px solid var(--line-2);border-radius:20px;
  padding:.1rem .4rem;margin-left:.2rem}

.filters{display:flex;flex-direction:column;gap:.5rem;margin:.7rem 0 .7rem;align-items:stretch}
.fgroup{display:flex;gap:.3rem;flex-wrap:wrap;align-items:center}
.fgroup .flabel{font-family:var(--label);font-size:.6rem;text-transform:uppercase;letter-spacing:.1em;
  color:var(--ink-soft);margin-right:.15rem}
.chip{font:inherit;font-size:.78rem;padding:.28rem .6rem;border:1px solid var(--line-2);
  background:transparent;color:var(--ink);border-radius:20px;cursor:pointer;line-height:1}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip.chip-locked{background:var(--paper-2);color:var(--ink-soft);border-color:var(--line-2);cursor:default}
.chip:focus-visible,.optcard:focus-visible,.wireitem:focus-visible,.cordset button:focus-visible,
.search:focus-visible,.cordset input:focus-visible{outline:2px solid var(--brass);outline-offset:2px}

.wrap .search{display:block;width:100%;max-width:100%;box-sizing:border-box;padding:.55rem .7rem;
  border:1px solid var(--line-2);border-radius:8px;background:var(--paper);color:var(--ink);font:inherit;margin-bottom:.6rem}
.wirelist{max-height:270px;overflow-y:auto;border:1px solid var(--line);border-radius:8px;background:var(--paper)}
.wireitem{display:grid;grid-template-columns:auto 1fr auto;gap:.6rem;align-items:center;width:100%;
  text-align:left;font:inherit;padding:.5rem .65rem;background:transparent;border:0;
  border-bottom:1px solid var(--line);color:var(--ink);cursor:pointer}
.wireitem:last-child{border-bottom:0}
.wireitem:hover{background:var(--paper-2)}
.wireitem[aria-selected="true"]{background:color-mix(in srgb,var(--brass) 18%,var(--paper))}
.sw{width:20px;height:20px;border-radius:5px;border:1px solid rgba(0,0,0,.25);flex:0 0 auto}
.wsw{width:38px;height:38px;object-fit:cover;border-radius:6px;border:1px solid var(--line-2);flex:0 0 auto;background:var(--paper);display:block}
.wname{font-size:.86rem;line-height:1.25}
.wname small{display:block;font-family:var(--mono);font-size:.66rem;color:var(--ink-soft);letter-spacing:.02em}
.wprice{font-family:var(--mono);font-size:.78rem;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.wprice small{display:block;color:var(--ink-soft);font-size:.62rem}
.listmeta{font-family:var(--mono);font-size:.66rem;color:var(--ink-soft);margin:.45rem 0 0}

.optgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:.5rem;margin-top:.7rem}
.socketgrid{grid-template-columns:repeat(auto-fill,minmax(185px,1fr))}
.optcard{position:relative;text-align:left;font:inherit;padding:.55rem .6rem;border:1px solid var(--line-2);
  border-radius:8px;background:var(--paper);color:var(--ink);cursor:pointer;display:flex;flex-direction:column;gap:.15rem}
.optcard:hover:not([disabled]){border-color:var(--brass)}
.optcard[aria-pressed="true"]{border-color:var(--brass);background:color-mix(in srgb,var(--brass) 14%,var(--paper));
  box-shadow:inset 0 0 0 1px var(--brass)}
.optcard[disabled]{cursor:not-allowed;opacity:.5}
.optcard .oc-img{width:100%;height:82px;object-fit:cover;border-radius:6px;border:1px solid var(--line-2);background:var(--paper);margin-bottom:.15rem}
.optcard .oc-sku{font-family:var(--mono);font-size:.58rem;color:var(--ink-soft);word-break:break-word;letter-spacing:.02em}
.optcard .ot{font-size:.8rem;line-height:1.2}
.optcard .op{font-family:var(--mono);font-size:.72rem;color:var(--ink-soft);font-variant-numeric:tabular-nums}
.optcard .why{font-family:var(--mono);font-size:.6rem;color:var(--danger);letter-spacing:.02em}
.optcard .tag{font-family:var(--mono);font-size:.55rem;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-soft)}
.none{font-size:.82rem;color:var(--ink-soft);padding:.3rem 0}

.lenrow{display:flex;align-items:center;gap:.7rem;flex-wrap:wrap;margin-top:.7rem}
.stepper{display:flex;align-items:center;border:1px solid var(--line-2);border-radius:8px;overflow:hidden;background:var(--paper)}
.stepper button{width:2.1rem;height:2.2rem;border:0;background:transparent;color:var(--ink);font-size:1.1rem;cursor:pointer}
.stepper button:hover{background:var(--paper-2)}
.stepper input{width:3.4rem;height:2.2rem;border:0;border-left:1px solid var(--line-2);border-right:1px solid var(--line-2);
  text-align:center;font:inherit;font-family:var(--mono);background:var(--paper);color:var(--ink);font-variant-numeric:tabular-nums}
.lenunit{font-family:var(--mono);font-size:.8rem;color:var(--ink-soft)}
.chips{display:flex;gap:.3rem}

.addbtn{width:100%;padding:.8rem;border:0;border-radius:9px;background:var(--patina);color:#fff;
  font:inherit;font-weight:700;font-size:.98rem;cursor:pointer;letter-spacing:.01em}
.addbtn:hover:not([disabled]){background:var(--patina-2)}
.addbtn[disabled]{background:var(--disabled);cursor:not-allowed}

.sidecol{display:flex;flex-direction:column;gap:1.1rem;min-inline-size:0}
.panel{border:1px solid var(--line);border-radius:var(--radius);
  background:var(--card);box-shadow:var(--shadow);padding:1rem 1.05rem;display:flex;flex-direction:column;gap:.7rem}
.panel-head{display:flex;align-items:center;justify-content:space-between}
.panel-head h2{font-family:var(--display);font-size:1.1rem;margin:0}
.badge{font-family:var(--mono);font-size:.66rem;letter-spacing:.06em;text-transform:uppercase;
  background:var(--ink);color:var(--paper);border-radius:20px;padding:.2rem .55rem}
.live{min-height:52px}
.lp-thumbs{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.55rem}
.lp-thumb{width:54px;height:54px;object-fit:cover;border-radius:6px;border:1px solid var(--line-2);background:var(--paper);display:block}
.lp-thumb-wrap{position:relative;display:inline-block;line-height:0;cursor:zoom-in}
.lp-thumb-pop{display:none;position:absolute;left:0;top:calc(100% + 6px);z-index:60;
  width:240px;max-width:70vw;height:auto;border-radius:8px;border:1px solid var(--line-2);
  box-shadow:0 10px 28px rgba(0,0,0,.3);background:var(--paper)}
.lp-thumb-wrap:hover .lp-thumb-pop,.lp-thumb-wrap.open .lp-thumb-pop{display:block}
.live .lp-title{font-family:var(--display);font-weight:700;font-size:.92rem;margin:0 0 .35rem;text-wrap:balance}
.live .empty{color:var(--ink-soft);font-size:.85rem}
.lines{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:.2rem}
.lines li{display:flex;justify-content:space-between;gap:.5rem;font-size:.8rem}
.lines li .ll{color:var(--ink-soft)}
.lines li .lv{font-family:var(--mono);font-variant-numeric:tabular-nums}
.lp-sub{display:flex;justify-content:space-between;border-top:1px solid var(--line);margin-top:.4rem;
  padding-top:.35rem;font-weight:700;font-size:.86rem}
.lp-sub .lv{font-family:var(--mono);font-variant-numeric:tabular-nums}

.cart{display:flex;flex-direction:column;gap:.55rem}
.cs{border:1px solid var(--line);border-radius:8px;padding:.55rem .65rem;background:var(--paper)}
.cs-h{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem}
.cs-h .t{font-size:.84rem;font-weight:600;line-height:1.25}
.cs-h .t small{display:block;font-family:var(--mono);font-size:.64rem;color:var(--ink-soft);font-weight:400;letter-spacing:.03em}
.cs-h .amt{font-family:var(--mono);font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.cs .rm{background:transparent;border:0;color:var(--danger);cursor:pointer;font-family:var(--mono);font-size:.68rem;padding:.1rem .2rem}
.cs-foot{display:flex;justify-content:space-between;align-items:center;margin-top:.5rem}
.qtyctrl{display:flex;align-items:center;gap:.45rem}
.qtyctrl button{width:1.7rem;height:1.7rem;border:1px solid var(--line-2);background:var(--paper);color:var(--ink);border-radius:6px;cursor:pointer;line-height:1;font-size:1rem}
.qtyctrl button:hover{background:var(--paper-2)}
.qtyctrl .qn{font-family:var(--mono);min-width:1.4rem;text-align:center;font-variant-numeric:tabular-nums;font-weight:700}
.cs-lines{list-style:none;margin:.4rem 0 0;padding:0;display:flex;flex-direction:column;gap:.12rem}
.cs-lines li{display:flex;justify-content:space-between;font-size:.74rem;color:var(--ink-soft)}
.cs-lines li .v{font-family:var(--mono);font-variant-numeric:tabular-nums}

.totals{display:flex;justify-content:space-between;align-items:baseline;border-top:2px solid var(--ink);padding-top:.5rem}
.totals .tl{font-family:var(--mono);text-transform:uppercase;letter-spacing:.1em;font-size:.7rem;color:var(--ink-soft)}
.totals .tv{font-family:var(--display);font-weight:800;font-size:1.35rem;font-variant-numeric:tabular-nums}
.checkout{width:100%;padding:.75rem;border:0;border-radius:9px;background:var(--brass);color:#1c150a;
  font:inherit;font-weight:800;cursor:pointer}
.checkout[disabled]{background:var(--disabled);color:var(--ink-soft);cursor:not-allowed}
.checkout:hover:not([disabled]){background:var(--brass-2)}
.fineprint{font-size:.72rem;color:var(--ink-soft);margin:0}

.variantpick{margin-top:.6rem;border-top:1px dashed var(--line-2);padding-top:.55rem}
.variantpick[hidden]{display:none}
.vchips{margin-top:.3rem}
.vsku{font-family:var(--mono);font-size:.62rem;color:var(--ink-soft);display:block;margin-top:.35rem;letter-spacing:.02em}
.switchpos{margin-top:.7rem;border-top:1px dashed var(--line-2);padding-top:.6rem}
.switchpos[hidden]{display:none}
.splabel{font-family:var(--label);font-size:.6rem;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-soft);display:block;margin-bottom:.35rem}
.sprow{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;font-size:.85rem}
.sprow input{width:3.6rem;padding:.35rem .4rem;border:1px solid var(--line-2);border-radius:7px;background:var(--paper);color:var(--ink);font:inherit;font-family:var(--mono);text-align:center}
.sprow select{padding:.35rem .4rem;border:1px solid var(--line-2);border-radius:7px;background:var(--paper);color:var(--ink);font:inherit}
.spwarn{color:var(--danger);font-size:.72rem;margin:.4rem 0 0}

.toast{position:fixed;left:50%;bottom:1.4rem;transform:translateX(-50%) translateY(1.5rem);
  background:var(--ink);color:var(--paper);padding:.7rem 1.1rem;border-radius:9px;font-size:.85rem;
  box-shadow:0 8px 24px rgba(0,0,0,.3);opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;max-width:90vw;z-index:9999}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
@media(prefers-reduced-motion:reduce){.toast{transition:none}}
"""

# ---------------------------------------------------------------------------
# The controller. `startCordset(CAT, LABOR, OPTS)`; OPTS.addToCart(cart) makes
# it live (returns a Promise), absent => demo toast. Root-scoped via `root`
# (a container element) so multiple copies could coexist; here we use document.
# ---------------------------------------------------------------------------
JS_CORE = r"""
function startCordset(CAT, LABOR, OPTS){
"use strict";
OPTS = OPTS || {};
var $ = function(id){return document.getElementById(id);};
var money = function(n){return "$"+ (Math.round(n*100)/100).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});};
function sized(url,px){ if(!url||url.indexOf("cdn.shopify.com")<0) return url;
  return url+(url.indexOf("?")<0?"?":"&")+"width="+Math.round((px||64)*(window.devicePixelRatio||1)); }
function compImg(comp,varsel){ return (varsel&&varsel.image)||(comp&&comp.image)||null; }

// ---- colour swatches from cloth colour words -------------------------------
var COLORS={black:"#1c1a17","dark brown":"#3a281c",brown:"#5b3d28","light brown":"#9a6b43",
  putty:"#c7bb9d",pewter:"#8c8d8a",silver:"#c6c9cc",gray:"#8a8a86",grey:"#8a8a86",white:"#efe9db",
  "bleach white":"#f5f1e6",gold:"#c39a3b","brush gold":"#b0863a","bright gold":"#d4af37",yellow:"#e6c033",
  green:"#3f7d43","lime green":"#9cb646",red:"#b0241f",raspberry:"#9c2b53",
  "burnt orange":"#bf4d1a",orange:"#cf6a2a",pink:"#cf6f88",blue:"#3f5f86","slate blue":"#4f647d",
  turquoise:"#1f6f80",natural:"#d8cdb0",cream:"#e6d9b8"};
function labelFromTitle(t){
  var s=" "+t.toLowerCase()+" ";
  s=s.replace(/\s[-–]\s.*$/,' ');                              // drop " - UL-Listed / SJT-B ..." suffix
  s=s.replace(/[-–]?\s*\bsjt[\w-]*/g,' ')
     .replace(/[-–]?\s*\bul[- ]?listed\b/g,' ')
     .replace(/[-–]?\s*\bul\b/g,' ');
  s=s.replace(/\b\d+\s*-?\s*conductor\b/g," ").replace(/\b\d+\s*-?\s*gauge\b/g," ")
     .replace(/\bcotton\b|\brayon\b/g," ").replace(/\btwisted\b|\bparallel\b|\bpulley\b|\boverbraid\b/g," ")
     .replace(/\bheavy[- ]?duty\b/g," ")
     .replace(/\bpair\b|\bwire\b|\bcord\b|\bwith\b|\bground\b|\bthhn\b/g," ")
     .replace(/\s[-–]+\s/g," ").replace(/\s+/g," ").trim();
  // Title-case only after start / space / hyphen (keeps "zig-zag", "hound's-tooth")
  return s.replace(/(^|[\s-])([a-z])/g,function(m,p,ch){return p+ch.toUpperCase();}) || t;
}
function swatchFor(t){
  var s=t.toLowerCase(),best=null;
  Object.keys(COLORS).forEach(function(k){ if(s.indexOf(k)>-1 && (!best||k.length>best.length)) best=k; });
  return best?COLORS[best]:"var(--line-2)";
}
CAT.wires.forEach(function(w){ w._label=labelFromTitle(w.title); w._hex=swatchFor(w.title);
  w._patterned=/zig|hound|tracer|bungalow|check|stripe/i.test(w.title); });

// ---- state -----------------------------------------------------------------
var sel={wire:null,plug:null,plugVar:null,length:8,switch:null,switchVar:null,socket:null,socketVar:null,switchPos:{dist:18,unit:"in",fromEnd:"plug"}};
var cart=[];
var GROUP=0;
var filt={gauge:null,conductors:null,style:null,material:null};

// ---- wire filters + list ---------------------------------------------------
// Cable type leads; the rest are DEPENDENT facets — each only offers values
// that actually exist given the other picks, and a facet with a single
// remaining value is hidden (the choice is already made). So impossible combos
// like "2-conductor overbraid" can never be selected.
var FILTERDEFS=[
  {key:"style",label:"Cable type",vals:[["twisted","Twisted"],["parallel","Parallel"],["pulley","Pulley"],["overbraid","Overbraid"]]},
  {key:"material",label:"Cloth",vals:[["cotton","Cotton"],["rayon","Rayon"]]},
  {key:"gauge",label:"Gauge",vals:[["14","14"],["16","16"],["18","18"],["20","20"],["22","22"]]},
  {key:"conductors",label:"Conductors",vals:[["2","2-conductor"],["3","3-conductor"],["sjt","SJT Heavy Duty (3-cond)"]]}
];
// heavy-duty (SJT) wires read as their own "conductors" facet value so they sit
// as a third chip next to 2- and 3-conductor.
function wireVal(w,key){
  if(key==="conductors") return w.heavy ? "sjt" : String(w.conductors);
  return key==="gauge"?String(w.gauge):key==="style"?w.style:w.material;
}
// values for `key` among wires matching every OTHER active facet
function availSet(key){
  var s={};
  CAT.wires.forEach(function(w){
    for(var i=0;i<FILTERDEFS.length;i++){ var k=FILTERDEFS[i].key;
      if(k!==key && filt[k] && wireVal(w,k)!==filt[k]) return; }
    var v=wireVal(w,key); if(v!=null && v!=="") s[v]=true;
  });
  return s;
}
// values for `key` present anywhere in the catalog (ignores current picks)
function catSet(key){ var s={}; CAT.wires.forEach(function(w){ var v=wireVal(w,key); if(v!=null&&v!=="") s[v]=true; }); return s; }
// (facets are always shown; a facet with a single possible value renders a
//  locked indicator chip rather than hiding — see renderFilters)
// Cable type is the fixed lead axis — never pruned or hidden. Only the DEPENDENT
// facets get cleared when a pick makes them impossible (fixpoint).
function validateFilters(){
  var changed=true;
  while(changed){ changed=false;
    FILTERDEFS.forEach(function(f){ if(f.key==="style") return;
      if(filt[f.key] && !availSet(f.key)[filt[f.key]]){ filt[f.key]=null; changed=true; } });
  }
}
function renderFilters(){
  validateFilters();
  var host=$("wireFilters"); host.innerHTML="";
  FILTERDEFS.forEach(function(f){
    var isStyle=f.key==="style";
    var avail = isStyle ? catSet(f.key) : availSet(f.key);
    var vals=f.vals.filter(function(v){
      if(!avail[v[0]]) return false;
      if(f.key==="conductors" && v[0]==="sjt" && filt.style!=="pulley") return false;  // SJT only under Pulley
      return true;
    });
    if(!vals.length) return;   // no value to show (e.g. no cloth data for this set)
    var g=document.createElement("div"); g.className="fgroup";
    var l=document.createElement("span"); l.className="flabel"; l.textContent=f.label; g.appendChild(l);
    if(!isStyle && vals.length===1){
      // only one possible value — show it as a locked indicator, not a toggle
      var only=vals[0];
      var lc=document.createElement("span"); lc.className="chip chip-locked"; lc.textContent=only[1];
      lc.setAttribute("aria-label", f.label+": "+only[1]+" (only option)");
      g.appendChild(lc);
    } else {
      vals.forEach(function(v){
        var b=document.createElement("button"); b.type="button"; b.className="chip"; b.textContent=v[1];
        b.setAttribute("aria-pressed", String(filt[f.key]===v[0]));
        b.addEventListener("click",function(){ filt[f.key]= filt[f.key]===v[0]?null:v[0]; renderFilters(); renderWires(); });
        g.appendChild(b);
      });
    }
    host.appendChild(g);
  });
}
function matchWire(w){
  if(filt.conductors && wireVal(w,"conductors")!==filt.conductors) return false;
  if(filt.gauge && String(w.gauge)!==filt.gauge) return false;
  if(filt.style && w.style!==filt.style) return false;
  if(filt.material && w.material!==filt.material) return false;
  var q=$("wireSearch").value.trim().toLowerCase();
  if(q && (w._label+" "+w.title).toLowerCase().indexOf(q)<0) return false;
  return true;
}
function renderWires(){
  var host=$("wireList"); host.innerHTML="";
  var list=CAT.wires.filter(matchWire);
  var CAP=120;
  list.slice(0,CAP).forEach(function(w){
    var b=document.createElement("button"); b.type="button"; b.className="wireitem"; b.setAttribute("role","option");
    b.setAttribute("aria-selected", String(sel.wire===w));
    var oos = (w.inventoryFeet!=null && w.inventoryFeet<=0);
    var meta=(w.sku?w.sku+' &middot; ':'')+w.gauge+'/'+w.conductors+' '+w.style+(w._patterned?' &middot; pattern':(w.material?' &middot; '+w.material:''));
    var thumb=w.image?'<img class="wsw" src="'+sized(w.image,48)+'" alt="" loading="lazy">':'<span class="sw" style="background:'+w._hex+'"></span>';
    b.innerHTML=thumb+
      '<span class="wname">'+w._label+' <small>'+meta+'</small></span>'+
      '<span class="wprice">'+money(w.pricePerFoot)+'<small>/ft'+(oos?' &middot; back-order':'')+'</small></span>';
    b.addEventListener("click",function(){ pickWire(w); });
    host.appendChild(b);
  });
}

function pickWire(w){
  sel.wire=w;
  // reflect the chosen wire in the facet chips (so a direct pick lights them up)
  filt.style=w.style||null;
  filt.material=w.material||null;
  filt.gauge=(w.gauge!=null)?String(w.gauge):null;
  filt.conductors=w.heavy?"sjt":((w.conductors!=null)?String(w.conductors):null);
  // keep any termination that's still compatible with the new wire; clear only the rest
  if(sel.plug && !plugOK(sel.plug).ok){ sel.plug=null; sel.plugVar=null; }
  if(sel.socket && !socketOK(sel.socket).ok){ sel.socket=null; sel.socketVar=null; }
  if(sel.switch && !switchOK(sel.switch).ok){ sel.switch=null; sel.switchVar=null; }
  renderFilters(); renderWires(); enableSteps(); renderPlugs(); renderSockets(); renderSwitches(); update();
}
function matchMotion(){ return window.matchMedia("(prefers-reduced-motion:reduce)").matches?"auto":"smooth"; }

function enableSteps(){
  ["step-plug","step-length","step-socket","step-switch"].forEach(function(id){ $(id).disabled=!sel.wire; });
}

// ---- compatibility (data-driven: wire.classId in component.compatClasses) ---
function compatOK(item,kind){
  if(!sel.wire) return {ok:false};
  if((item.compatClasses||[]).indexOf(sel.wire.classId)>-1) return {ok:true};
  var why = (kind==="socket" && item.grounded && sel.wire.conductors!==3)
    ? "grounded needs 3-cond wire"
    : "not rated for "+(sel.wire.classId||"this wire");
  return {ok:false,why:why};
}
function plugOK(p){ return compatOK(p,"plug"); }
function switchOK(s){ return compatOK(s,"switch"); }
function socketOK(s){ return compatOK(s,"socket"); }

// ---- variant (colour / finish) picker --------------------------------------
function vlabel(v){ return (v && v.label && v.label!=="Standard") ? " ("+v.label+")" : ""; }
function compOf(kind){ return kind==="plug"?sel.plug:kind==="switch"?sel.switch:sel.socket; }
function varOf(kind){ return kind==="plug"?sel.plugVar:kind==="switch"?sel.switchVar:sel.socketVar; }
function setVarOf(kind,v){ if(kind==="plug")sel.plugVar=v; else if(kind==="switch")sel.switchVar=v; else sel.socketVar=v; }
function renderVariantPick(kind){
  var host=$(kind+"Var"), comp=compOf(kind);
  if(!comp || !comp.variants || comp.variants.length<2){ host.hidden=true; host.innerHTML=""; return; }
  host.hidden=false; var cur=varOf(kind);
  var html='<span class="splabel">'+(comp.variantAxis||"Option")+'</span><div class="chips vchips">';
  comp.variants.forEach(function(v,i){
    html+='<button type="button" class="chip vchip" data-i="'+i+'" aria-pressed="'+String(!!cur&&cur.variantId===v.variantId)+'">'+
      v.label+(v.inventory<=0?' · b/o':'')+'</button>';
  });
  var skuLine=(cur&&cur.sku)?'<span class="vsku">SKU '+cur.sku+'</span>':'';
  host.innerHTML=html+'</div>'+skuLine;
  Array.prototype.forEach.call(host.querySelectorAll(".vchip"),function(b){
    b.addEventListener("click",function(){ setVarOf(kind, comp.variants[parseInt(b.dataset.i)]); renderVariantPick(kind); update(); });
  });
}

function optCard(item,label,price,state,onclick,tagText){
  var b=document.createElement("button"); b.type="button"; b.className="optcard";
  b.disabled=!state.ok; b.setAttribute("aria-pressed",String(item._pressed===true));
  var img = item.image ? '<img class="oc-img" src="'+sized(item.image,120)+'" alt="" loading="lazy">' : '';
  var tag = tagText? '<span class="tag">'+tagText+'</span>':'';
  // single-variant parts show their one SKU here; multi-variant show the
  // selected variant's SKU in the colour/finish picker instead
  var sku = (item.variants && item.variants.length===1 && item.sku) ? '<span class="oc-sku">'+item.sku+'</span>' : '';
  b.innerHTML=img+'<span class="ot">'+label+'</span>'+sku+tag+'<span class="op">'+(price!=null?(price===0?'included':'+'+money(price)):'')+'</span>';
  if(state.ok) b.addEventListener("click",onclick);
  return b;
}
function cleanPlug(t){ return t.replace(/PLUG/ig,"").replace(/,?\s*(Black|Brown|White)\b/i,"").replace(/\s+/g," ").trim()
  .replace(/\b\w/g,function(c){return c.toUpperCase();}); }

function renderPlugs(){
  var host=$("plugList"); host.innerHTML="";
  var none=document.createElement("button"); none.type="button"; none.className="optcard";
  none.setAttribute("aria-pressed",String(sel.plug===null));
  none.innerHTML='<span class="ot">No plug</span>';
  none.addEventListener("click",function(){ sel.plug=null; sel.plugVar=null; renderPlugs(); update(); });
  host.appendChild(none);
  CAT.plugs.forEach(function(p){ p._pressed=(sel.plug===p);
    var st=plugOK(p);
    host.appendChild(optCard(p, cleanPlug(p.title), p.price, st,
      function(){ sel.plug=p; sel.plugVar=p.variants[0]; renderPlugs(); update(); },
      (p.prong?p.prong+"-prong":"")+(p.polarized?" · pol":"")));
  });
  renderVariantPick("plug");
}
function renderSwitches(){
  var host=$("switchList"); host.innerHTML="";
  var none=document.createElement("button"); none.type="button"; none.className="optcard";
  none.setAttribute("aria-pressed",String(sel.switch===null));
  none.innerHTML='<span class="ot">No switch</span><span class="op">&mdash;</span>';
  none.addEventListener("click",function(){ sel.switch=null; sel.switchVar=null; renderSwitches(); update(); });
  host.appendChild(none);
  CAT.switches.forEach(function(s){ s._pressed=(sel.switch===s); var st=switchOK(s);
    host.appendChild(optCard(s, s.title.replace(/^SWITCH:\s*/i,""), s.price, st,
      function(){ sel.switch=s; sel.switchVar=s.variants[0]; renderSwitches(); update(); }));
  });
  renderVariantPick("switch");
  renderSwitchPos();
}

// switch placement: distance from an end, as a fabrication spec (no price)
function endLabel(which){ return which==="plug" ? "plug end" : (sel.socket?"socket end":"bare end"); }
function distInches(){ return sel.switchPos.unit==="ft"? sel.switchPos.dist*12 : sel.switchPos.dist; }
function switchPosSummary(){ return sel.switchPos.dist+" "+sel.switchPos.unit+" from "+endLabel(sel.switchPos.fromEnd); }
function refreshEndLabels(){ var s=$("spEnd"); if(!s) return; s.options[0].text=endLabel("plug"); s.options[1].text=endLabel("other"); }
function checkSpWarn(){ var w=$("spWarn"); if(!w) return;
  w.textContent = distInches() >= sel.length*12 ? "That sits past the "+sel.length+" ft cord — the switch must fall between the ends." : ""; }
function renderSwitchPos(){
  var host=$("switchPos");
  if(!sel.switch){ host.hidden=true; host.innerHTML=""; return; }
  var sp=sel.switchPos; host.hidden=false;
  host.innerHTML='<span class="splabel">Switch location</span>'+
    '<div class="sprow">Place switch '+
      '<input type="number" id="spDist" min="1" step="1" value="'+sp.dist+'" inputmode="numeric" aria-label="switch distance">'+
      '<select id="spUnit" aria-label="unit"><option value="in"'+(sp.unit==="in"?" selected":"")+'>in</option>'+
        '<option value="ft"'+(sp.unit==="ft"?" selected":"")+'>ft</option></select> from '+
      '<select id="spEnd" aria-label="measured from"><option value="plug"'+(sp.fromEnd==="plug"?" selected":"")+'>'+endLabel("plug")+'</option>'+
        '<option value="other"'+(sp.fromEnd==="other"?" selected":"")+'>'+endLabel("other")+'</option></select>'+
    '</div><p class="spwarn" id="spWarn"></p>';
  $("spDist").addEventListener("input",function(){ sel.switchPos.dist=Math.max(1,parseInt(this.value)||1); checkSpWarn(); update(); });
  $("spUnit").addEventListener("change",function(){ sel.switchPos.unit=this.value; checkSpWarn(); update(); });
  $("spEnd").addEventListener("change",function(){ sel.switchPos.fromEnd=this.value; update(); });
  checkSpWarn();
}
function renderSockets(){
  var host=$("socketList"); host.innerHTML="";
  var none=document.createElement("button"); none.type="button"; none.className="optcard";
  none.setAttribute("aria-pressed",String(sel.socket===null));
  none.innerHTML='<span class="ot">Bare end</span><span class="op">cord set</span>';
  none.addEventListener("click",function(){ sel.socket=null; sel.socketVar=null; renderSockets(); update(); refreshEndLabels(); });
  host.appendChild(none);
  CAT.sockets.forEach(function(s){ s._pressed=(sel.socket===s); var st=socketOK(s);
    host.appendChild(optCard(s, s.title.replace(/^SOCKET:?\s*/i,"").replace(/^RING:/i,"Ring:"), s.price, st,
      function(){ sel.socket=s; sel.socketVar=s.variants[0]; renderSockets(); update(); refreshEndLabels(); }, s.grounded?"grounded":""));
  });
  renderVariantPick("socket");
}

// ---- pricing + live preview ------------------------------------------------
function currentLines(){
  if(!sel.wire) return null;
  var L=sel.length, lines=[];
  lines.push({label:sel.wire._label+" wire — "+L+" ft × "+money(sel.wire.pricePerFoot), amt:sel.wire.pricePerFoot*L, variantId:sel.wire.variantId, quantity:L});
  if(sel.plug){ var pv=sel.plugVar||sel.plug.variants[0];
    lines.push({label:cleanPlug(sel.plug.title)+vlabel(pv)+" plug", amt:pv?pv.price:sel.plug.price, variantId:pv&&pv.variantId, quantity:1}); }
  if(sel.socket){ var kv=sel.socketVar||sel.socket.variants[0];
    lines.push({label:sel.socket.title.replace(/^SOCKET:?\s*/i,"Socket: ")+vlabel(kv), amt:kv?kv.price:sel.socket.price, variantId:kv&&kv.variantId, quantity:1}); }
  if(sel.switch){ var wv=sel.switchVar||sel.switch.variants[0];
    lines.push({label:sel.switch.title.replace(/^SWITCH:\s*/i,"Switch: ")+vlabel(wv)+" — "+switchPosSummary(), amt:wv?wv.price:sel.switch.price, variantId:wv&&wv.variantId, quantity:1, properties:{"Switch location":switchPosSummary()}}); }
  if(LABOR.variantId) lines.push({label:LABOR.title||"Assembly", amt:LABOR.price||0, variantId:LABOR.variantId, quantity:1});
  return lines;
}
function sum(lines){ return lines.reduce(function(a,l){return a+l.amt;},0); }
function titleFor(){
  var plugPart = sel.plug ? ", "+cleanPlug(sel.plug.title)+vlabel(sel.plugVar||sel.plug.variants[0])+" plug" : ", no plug";
  return (sel.socket?"Pendant":"Cord set")+" — "+sel.length+" ft "+sel.wire._label+plugPart+
    (sel.socket?", "+sel.socket.title.replace(/^SOCKET:?\s*/i,"").toLowerCase()+" socket":"")+
    (sel.switch?", + "+sel.switch.title.replace(/^SWITCH:\s*/i,"").toLowerCase()+" @ "+switchPosSummary():"");
}
function update(){
  var lines=currentLines(); var live=$("livePreview");
  if(!lines){ live.innerHTML='<p class="empty">Start by choosing a wire.</p>';
    $("addBtn").disabled=true; return; }
  var thumbs=[];
  function addThumb(url,label){ if(url) thumbs.push(
    '<span class="lp-thumb-wrap" title="'+label+'">'+
      '<img class="lp-thumb" src="'+sized(url,64)+'" alt="'+label+'" loading="lazy">'+
      '<img class="lp-thumb-pop" src="'+sized(url,440)+'" alt="'+label+'" loading="lazy">'+
    '</span>'); }
  addThumb(sel.wire.image, sel.wire._label+" wire");
  if(sel.plug) addThumb(compImg(sel.plug,sel.plugVar), "plug");
  if(sel.socket) addThumb(compImg(sel.socket,sel.socketVar), "socket");
  if(sel.switch) addThumb(compImg(sel.switch,sel.switchVar), "switch");
  var html=(thumbs.length?'<div class="lp-thumbs">'+thumbs.join("")+'</div>':'')+
    '<p class="lp-title">'+titleFor()+'</p><ul class="lines">';
  lines.forEach(function(l){ html+='<li><span class="ll">'+l.label+'</span><span class="lv">'+money(l.amt)+'</span></li>'; });
  html+='</ul><div class="lp-sub"><span>Cord set subtotal</span><span class="lv">'+money(sum(lines))+'</span></div>';
  live.innerHTML=html; $("addBtn").disabled=false; checkSpWarn();
}

// ---- cart ------------------------------------------------------------------
function renderCart(){
  var host=$("cart"); host.innerHTML="";
  cart.forEach(function(c){
    var el=document.createElement("div"); el.className="cs";
    var lines='<ul class="cs-lines">'+c.lines.map(function(l){return '<li><span>'+l.label+'</span><span class="v">'+money(l.amt)+'</span></li>';}).join("")+'</ul>';
    el.innerHTML='<div class="cs-h"><span class="t"><small>cordset-'+c.group+'</small>'+c.title+'</span>'+
      '<span class="amt">'+money(c.unit*c.qty)+'</span></div>'+lines+
      '<div class="cs-foot"><div class="qtyctrl">'+
        '<button type="button" class="qminus" aria-label="Fewer">&minus;</button>'+
        '<span class="qn">'+c.qty+'</span>'+
        '<button type="button" class="qplus" aria-label="More">+</button></div>'+
        '<button type="button" class="rm">remove</button></div>';
    el.querySelector(".qplus").addEventListener("click",function(){ c.qty++; refreshCart(); });
    el.querySelector(".qminus").addEventListener("click",function(){ if(c.qty>1){c.qty--;}else{cart=cart.filter(function(x){return x!==c;});} refreshCart(); });
    el.querySelector(".rm").addEventListener("click",function(){ cart=cart.filter(function(x){return x!==c;}); refreshCart(); });
    host.appendChild(el);
  });
}
function refreshCart(){
  renderCart();
  var total=cart.reduce(function(a,c){return a+c.unit*c.qty;},0);
  var setCount=cart.reduce(function(a,c){return a+c.qty;},0);
  var lineCount=cart.reduce(function(a,c){return a+c.lines.length;},0);
  $("cartCount").textContent=setCount+" cord set"+(setCount===1?"":"s");
  $("totals").innerHTML='<span class="tl">'+setCount+' cord sets · '+lineCount+' cart lines</span><span class="tv">'+money(total)+'</span>';
  $("checkoutBtn").disabled=cart.length===0;
}
// a signature of the exact build, so re-adding an identical cord set just bumps qty
function buildSig(){
  var pv=sel.plug?(sel.plugVar||sel.plug.variants[0]):null;
  var kv=sel.socket?(sel.socketVar||sel.socket.variants[0]):null;
  var wv=sel.switch?(sel.switchVar||sel.switch.variants[0]):null;
  return [sel.wire.variantId, sel.length, pv?pv.variantId:"-", kv?kv.variantId:"-",
    wv?wv.variantId:"-", sel.switch?(sel.switchPos.dist+sel.switchPos.unit+sel.switchPos.fromEnd):"-"].join("|");
}
$("addBtn").addEventListener("click",function(){
  var lines=currentLines(); if(!lines) return;
  var sig=buildSig(), hit=null;
  cart.forEach(function(c){ if(c.sig===sig) hit=c; });
  if(hit){ hit.qty++; refreshCart(); toast(hit.title+" — now ×"+hit.qty); return; }
  GROUP++;
  var title=titleFor();
  lines.forEach(function(l){
    var props={"_cordset":"cordset-"+GROUP, "Cord set":title};
    if(l.properties){ for(var k in l.properties){ props[k]=l.properties[k]; } }
    l.properties=props;
  });
  cart.push({group:GROUP,sig:sig,qty:1,title:title,lines:lines,unit:sum(lines)});
  refreshCart();
  toast("Added — "+lines.length+" cart lines grouped as cordset-"+GROUP);
});
$("checkoutBtn").addEventListener("click",function(){
  if(OPTS.addToCart){
    var btn=$("checkoutBtn"); btn.disabled=true;
    OPTS.addToCart(cart).catch(function(){ toast("Sorry — couldn't add to cart. Please try again."); btn.disabled=false; });
    return;
  }
  var lineCount=cart.reduce(function(a,c){return a+c.lines.length;},0);
  toast("Demo: would add "+lineCount+" component lines across "+cart.length+" grouped cord sets to the cart.");
});

// ---- length ----------------------------------------------------------------
[6,8,10,12,16].forEach(function(n){
  var b=document.createElement("button"); b.type="button"; b.className="chip"; b.textContent=n+"'";
  b.addEventListener("click",function(){ sel.length=n; $("lenInput").value=n; syncLenChips(); update(); });
  $("lenPresets").appendChild(b);
});
function syncLenChips(){ Array.prototype.forEach.call($("lenPresets").children,function(c){
  c.setAttribute("aria-pressed", String(parseInt(c.textContent)===sel.length)); }); }
$("lenInput").addEventListener("input",function(){ var v=Math.max(1,Math.min(100,parseInt(this.value)||1)); sel.length=v; syncLenChips(); update(); });
Array.prototype.forEach.call(document.querySelectorAll(".stepper button"),function(b){
  b.addEventListener("click",function(){ var v=Math.max(1,Math.min(100,sel.length+parseInt(b.dataset.len))); sel.length=v; $("lenInput").value=v; syncLenChips(); update(); });
});

// ---- toast -----------------------------------------------------------------
var toastT;
function toast(msg){ var t=$("toast"); t.textContent=msg; t.classList.add("show");
  clearTimeout(toastT); toastT=setTimeout(function(){ t.classList.remove("show"); },3200); }

// ---- init ------------------------------------------------------------------
$("wireSearch").addEventListener("input",renderWires);
// tap a preview thumbnail to enlarge (hover handles desktop); tap elsewhere closes
document.addEventListener("click",function(e){
  var w=e.target.closest && e.target.closest(".lp-thumb-wrap");
  Array.prototype.forEach.call(document.querySelectorAll(".lp-thumb-wrap"),function(x){
    if(x===w){ x.classList.toggle("open"); } else { x.classList.remove("open"); }
  });
});
renderFilters(); renderWires(); syncLenChips(); update(); refreshCart();
}
"""

ARTIFACT_MASTHEAD = r"""  <header class="masthead">
    <div class="brand">
      <span class="mark" aria-hidden="true"></span>
      <div>
        <p class="kicker">Sundial Wire &middot; Florence, Massachusetts</p>
        <h1>Cord Set Bench</h1>
      </div>
    </div>
    <p class="lede">Build a cloth-covered cord set from real stock &mdash; choose the wire,
      terminate each end, add a switch if you like. Every part is a live catalog item;
      the ticket on the right is exactly what lands in the cart.</p>
    <p class="proto-note">Prototype &middot; prices &amp; inventory are live catalog data &middot;
      labor is a placeholder &middot; nothing is ordered.</p>
  </header>
"""


def build_artifact():
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)
    catalog = json.loads((D / "cordsets.catalog.json").read_text())
    cat_min = json.dumps(catalog, separators=(",", ":"))
    page = ('<div class="wrap cordset">\n' + ARTIFACT_MASTHEAD + APP_MARKUP + "</div>\n"
            + "<style>" + CSS + "</style>\n"
            + "<script>\n" + JS_CORE
            + "\n;(function(){var C=" + cat_min
            + ";startCordset(C, C.labor||{price:0}, {live:false});})();\n</script>\n")
    (D / "prototype.html").write_text(page)
    print("wrote prototype.html", len(page), "bytes; catalog", len(cat_min), "bytes")


if __name__ == "__main__":
    build_artifact()
