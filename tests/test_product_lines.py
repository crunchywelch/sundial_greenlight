"""product_lines must agree with cable_config on series names."""

from greenlight.cable_config import all_series
from greenlight.product_lines import get_cost_for_special_baby, load_yaml_skus


def test_special_baby_cost_for_every_series():
    # db.py sets a cable's series from cable_config, so every series name
    # there must resolve to a cost (SV/TV once silently returned None).
    for series in all_series():
        cost = get_cost_for_special_baby(series["product_line"], 12)
        assert cost is not None, series["product_line"]


def test_yaml_skus_cover_every_series():
    assert set(load_yaml_skus()) == {s["sku_prefix"] for s in all_series()}
