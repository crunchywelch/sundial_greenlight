"""Plan a run of retail labels for an order.

Turns a list of order line items into label jobs, grouped by the stock each
needs. Pure planning: no DB, no Shopify, no printer, so the awkward parts
(which SKUs can't take a UPC label, how many roll swaps a run costs) are
testable without hardware.

Two things shape the output.

**Grain.** The retail labels are per *variant*, not per cable: four 12ft
Goldline cables take four identical side labels and four identical UPC
labels, so each is one job with `PRINT 4` rather than four jobs. Registration
labels are the opposite -- a unique code per physical cable -- and they are
deliberately NOT planned here. Codes attach to serial numbers that come from
Postgres, not from the order, so that flow belongs with the cable batch in
`screens/wholesale.py` where the serials already are.

**Stock.** The TE210 has one media path, so a run that mixes 1" and 2" labels
costs a roll swap. Grouping by stock keeps that to one swap for the whole
order instead of one per label, which is the difference between a usable
batch and an unusable one.

See docs/LABEL_PRINTING.md § Printing a batch.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from greenlight.cable_config import describe_variant
from greenlight.hardware.tsc_label_printer import stock_for_template

logger = logging.getLogger(__name__)

# The retail labels a boxed cable carries, in the order they are offered.
# `registration_label` is absent on purpose -- see the module docstring.
RETAIL_TEMPLATES = ("box_label", "shelf_label")

# What each template is called where an operator can see it, and what it needs
# from a variant beyond the catalog. A template needing a UPC cannot be
# planned for a SKU that has none.
TEMPLATE_LABELS = {
    "box_label": ("UPC label", "box back", True),
    "shelf_label": ("Side label", "box side", False),
    "prop65_label": ("Prop 65", "warning", False),
}


@dataclass
class LabelJob:
    """One PRINT command's worth of work."""
    template: str
    sku: str
    quantity: int
    data: Dict[str, Any]
    stock: Tuple[float, float]

    @property
    def label_name(self) -> str:
        return TEMPLATE_LABELS.get(self.template, (self.template, "", False))[0]


@dataclass
class BatchPlan:
    """Jobs for one order, plus everything that could not be planned."""
    jobs: List[LabelJob] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def by_stock(self) -> Dict[Tuple[float, float], List[LabelJob]]:
        """Jobs grouped by stock, so a run is one pass per roll."""
        groups: Dict[Tuple[float, float], List[LabelJob]] = {}
        for job in self.jobs:
            groups.setdefault(job.stock, []).append(job)
        return groups

    @property
    def roll_swaps(self) -> int:
        """Swaps this run costs: one fewer than the number of stocks used."""
        return max(0, len(self.by_stock) - 1)

    @property
    def label_count(self) -> int:
        return sum(job.quantity for job in self.jobs)


def merge_line_items(line_items) -> List[Dict[str, Any]]:
    """Collapse an order's lines to one row per SKU, summing quantities.

    An order can list the same SKU twice -- a price override, or two separate
    additions to the cart. Two jobs of 2 would print the same label twice as
    often as two separate connections; one job of 4 is the point.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for item in line_items or []:
        sku = (item.get("sku") or "").strip().upper()
        qty = int(item.get("quantity") or 0)
        if not sku or qty <= 0:
            continue
        row = merged.setdefault(sku, {"sku": sku, "quantity": 0,
                                      "title": item.get("title") or ""})
        row["quantity"] += qty
    return sorted(merged.values(), key=lambda r: r["sku"])


def plan_order(line_items,
               templates=RETAIL_TEMPLATES,
               upc_by_sku: Optional[Dict[str, str]] = None) -> BatchPlan:
    """Build the label jobs for an order's line items.

    Args:
        line_items: dicts with at least `sku` and `quantity`, as
            `shopify_client.get_draft_orders()` returns in `line_items`.
        templates: which label templates to include, from RETAIL_TEMPLATES.
        upc_by_sku: SKU -> GTIN-12, for templates that need one. Omit and
            UPC labels are skipped with a warning rather than guessed at.

    Returns:
        A BatchPlan. Anything unprintable lands in `warnings` rather than
        being dropped silently -- a wholesale order that quietly prints 20
        labels instead of 24 is worse than one that refuses.
    """
    upc_by_sku = {k.upper(): v for k, v in (upc_by_sku or {}).items()}
    plan = BatchPlan()

    unknown_templates = [t for t in templates if stock_for_template(t) is None]
    if unknown_templates:
        plan.warnings.append(
            f"Not label templates, ignored: {', '.join(unknown_templates)}")
    templates = [t for t in templates if stock_for_template(t) is not None]

    for row in merge_line_items(line_items):
        sku, qty = row["sku"], row["quantity"]
        described = describe_variant(sku)

        if described is None:
            plan.warnings.append(
                f"{sku}: not a SKU the catalog knows — no labels planned "
                f"({qty} cable{'s' if qty != 1 else ''})")
            continue

        # MISC and LTD builds are one-offs and limited runs. They have no
        # retail UPC (audio_upc_sync excludes them by kind), and a MISC has
        # no catalog length or connector, so most of a side label would be
        # blank. Flag rather than print something half-empty.
        if described["kind"] != "catalog":
            plan.warnings.append(
                f"{sku}: a {described['kind'].upper()} build, not a catalog "
                f"variant — retail labels skipped ({qty} "
                f"cable{'s' if qty != 1 else ''})")
            continue

        for template in templates:
            needs_upc = TEMPLATE_LABELS.get(template, (None, None, False))[2]
            data = dict(described)

            if needs_upc:
                upc = upc_by_sku.get(sku)
                if not upc:
                    plan.warnings.append(
                        f"{sku}: no UPC in Shopify — "
                        f"{TEMPLATE_LABELS[template][0]} skipped")
                    continue
                data["upc"] = upc
                # The UPC label's own text comes from Shopify's product
                # naming, which the caller passes through describe_variant's
                # keys; box_label reads product_title/subtitle.
                data.setdefault("product_title", described["headline"])
                data.setdefault("subtitle", described["spec_line"])

            plan.jobs.append(LabelJob(
                template=template, sku=sku, quantity=qty, data=data,
                stock=stock_for_template(template),
            ))

    return plan


def describe_plan(plan: BatchPlan) -> List[str]:
    """Human-readable summary lines, for a CLI or a TUI screen."""
    lines = []
    for stock, jobs in sorted(plan.by_stock.items(), key=lambda kv: -kv[0][1]):
        w, h = stock
        inches = f'{w / 25.4:.0f}" x {h / 25.4:.0f}"'
        total = sum(j.quantity for j in jobs)
        lines.append(f"{inches} stock — {total} label(s)")
        for job in sorted(jobs, key=lambda j: (j.template, j.sku)):
            lines.append(f"    {job.quantity:3} x {job.sku:14} "
                         f"{job.label_name}")
    swaps = plan.roll_swaps
    lines.append(f"{plan.label_count} label(s) total, "
                 f"{swaps} roll swap{'s' if swaps != 1 else ''}")
    return lines
