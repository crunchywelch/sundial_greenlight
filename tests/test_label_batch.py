#!/usr/bin/env python3
"""Tests for planning a retail label run from an order's line items.

Pure planning, so the awkward parts are testable without a printer, Postgres
or Shopify: which SKUs cannot take a UPC label, how many roll swaps a run
costs, and what happens to a line the catalog doesn't recognise.

The cases here are drawn from real draft orders in the store -- #D14 (24
cables over 6 SKUs) and #D4 (five MISC one-offs), which is where the MISC
problem came from. A wholesale order that quietly prints 20 labels instead of
24 is worse than one that refuses, so every unprintable line has to surface.

Run: pytest tests/test_label_batch.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greenlight.hardware.tsc_label_printer import BOX_STOCK_MM, CABLE_ROLL_MM
from greenlight.label_batch import (
    RETAIL_TEMPLATES, describe_plan, merge_line_items, plan_order,
)

# Shape of what shopify_client.get_draft_orders() puts in `line_items`.
def line(sku, qty, title=""):
    return {"sku": sku, "quantity": qty, "title": title}


# #D14, as the store actually holds it.
D14 = [line("SC-12GL", 4), line("SC-12GL-R", 4), line("SV-12GL", 4),
       line("TC-15FF", 4), line("TC-15FF-R", 4), line("TV-15FF", 4)]

UPCS = {s: "036000291452" for s in
        ("SC-12GL", "SC-12GL-R", "SV-12GL", "TC-15FF", "TC-15FF-R",
         "TV-15FF", "SC-20GL", "SC-6GL")}


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------

def test_the_same_sku_twice_becomes_one_job():
    """An order can list a SKU twice -- a price override, or two cart adds.
    Two jobs of 2 is two connections printing what one job of 4 would."""
    merged = merge_line_items([line("SC-20GL", 2), line("SC-20GL", 2)])
    assert merged == [{"sku": "SC-20GL", "quantity": 4, "title": ""}]


@pytest.mark.parametrize("junk", [
    line("", 4), line(None, 4), line("SC-20GL", 0), line("SC-20GL", None),
])
def test_unusable_lines_are_dropped(junk):
    assert merge_line_items([junk]) == []


def test_skus_are_normalised_and_sorted():
    merged = merge_line_items([line("tv-15ff", 1), line(" sc-12gl ", 1)])
    assert [r["sku"] for r in merged] == ["SC-12GL", "TV-15FF"]


# --------------------------------------------------------------------------
# Planning a real order
# --------------------------------------------------------------------------

def test_plans_both_labels_for_every_line():
    plan = plan_order(D14, upc_by_sku=UPCS)
    assert not plan.warnings
    assert len(plan.jobs) == 12          # 6 SKUs x 2 templates
    assert plan.label_count == 48        # 24 cables x 2
    assert plan.roll_swaps == 1


def test_quantity_rides_on_the_job_not_the_job_count():
    """Per-variant grain: four identical cables are one PRINT 4, not four
    jobs. That is the whole reason a 24-cable order is 12 connections."""
    plan = plan_order(D14, upc_by_sku=UPCS)
    assert all(job.quantity == 4 for job in plan.jobs)


def test_grouped_by_stock_so_a_run_swaps_once():
    plan = plan_order(D14, upc_by_sku=UPCS)
    groups = plan.by_stock
    assert set(groups) == {BOX_STOCK_MM, CABLE_ROLL_MM}
    assert all(j.template == "box_label" for j in groups[BOX_STOCK_MM])
    assert all(j.template == "shelf_label" for j in groups[CABLE_ROLL_MM])


def test_one_template_means_no_swap():
    """What the per-job label prompt buys: deselecting the UPC label takes
    the run from one swap to none."""
    plan = plan_order(D14, templates=("shelf_label",))
    assert plan.roll_swaps == 0
    assert plan.label_count == 24


def test_the_side_label_needs_no_upc():
    """It carries no barcode by design, so it must plan without Shopify."""
    plan = plan_order(D14, templates=("shelf_label",), upc_by_sku=None)
    assert len(plan.jobs) == 6
    assert not plan.warnings


# --------------------------------------------------------------------------
# Lines that cannot be printed
# --------------------------------------------------------------------------

def test_misc_builds_are_skipped_with_a_warning():
    """Straight from #D4. MISC one-offs have no retail UPC (audio_upc_sync
    excludes them by kind) and no catalog length or connector, so most of a
    side label would be blank."""
    plan = plan_order([line("TC-MISC-51", 1), line("TC-MISC-52", 1)],
                      upc_by_sku=UPCS)
    assert plan.jobs == []
    assert len(plan.warnings) == 2
    assert all("MISC" in w for w in plan.warnings)


def test_an_unknown_sku_warns_rather_than_vanishing():
    plan = plan_order([line("NOT-A-SKU", 3)], upc_by_sku=UPCS)
    assert plan.jobs == []
    assert "NOT-A-SKU" in plan.warnings[0]
    assert "3 cables" in plan.warnings[0]


def test_a_missing_upc_skips_only_the_upc_label():
    """The side label still prints: losing one label type should not lose
    the other."""
    plan = plan_order([line("SC-20GL", 2)], upc_by_sku={})
    assert [j.template for j in plan.jobs] == ["shelf_label"]
    assert any("no UPC in Shopify" in w for w in plan.warnings)


def test_a_mixed_order_plans_what_it_can():
    plan = plan_order([line("SC-20GL", 2), line("TC-MISC-51", 1)],
                      upc_by_sku=UPCS)
    assert {j.sku for j in plan.jobs} == {"SC-20GL"}
    assert len(plan.warnings) == 1


def test_a_non_label_template_is_rejected_not_planned():
    plan = plan_order([line("SC-20GL", 1)], templates=("nonsense",),
                      upc_by_sku=UPCS)
    assert plan.jobs == []
    assert "nonsense" in plan.warnings[0]


# --------------------------------------------------------------------------
# Job contents and summary
# --------------------------------------------------------------------------

def test_the_upc_job_carries_everything_box_label_needs():
    plan = plan_order([line("SC-20GL", 1)], templates=("box_label",),
                      upc_by_sku=UPCS)
    data = plan.jobs[0].data
    assert data["upc"] == UPCS["SC-20GL"]
    assert data["sku"] == "SC-20GL"
    assert data["product_title"] and data["subtitle"]


def test_the_side_job_carries_the_catalog_rows():
    plan = plan_order([line("SC-20GL", 1)], templates=("shelf_label",))
    data = plan.jobs[0].data
    assert data["brand_line"] == "Sundial Audio Studio Series"
    assert data["spec_line"] == "20' Instrument Cable"
    assert data["connector_line"] == "TS-TS - Canare GS-6"


def test_registration_labels_are_not_planned_here():
    """They are per-cable, keyed to serials that live in Postgres rather than
    in the order, so they belong with the cable batch in screens/wholesale.py
    where the serials already are."""
    assert "registration_label" not in RETAIL_TEMPLATES
    plan = plan_order(D14, upc_by_sku=UPCS)
    assert all(j.template != "registration_label" for j in plan.jobs)


def test_an_empty_order_plans_nothing_without_raising():
    for empty in ([], None):
        plan = plan_order(empty, upc_by_sku=UPCS)
        assert plan.jobs == [] and plan.roll_swaps == 0


def test_the_summary_names_the_stock_and_the_swaps():
    text = "\n".join(describe_plan(plan_order(D14, upc_by_sku=UPCS)))
    assert '3" x 2"' in text and '3" x 1"' in text
    assert "48 label(s) total, 1 roll swap" in text


def test_the_tall_stock_is_listed_first():
    """Print the 2in work first: it is the roll already on the printer after
    a box-label run, and the 1in roll is the everyday one to end on."""
    lines = describe_plan(plan_order(D14, upc_by_sku=UPCS))
    assert '3" x 2"' in lines[0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
