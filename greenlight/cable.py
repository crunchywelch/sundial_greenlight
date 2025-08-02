from rich.panel import Panel

from greenlight.db import pg_pool
from greenlight.enums import fetch_enum_values

class cableType:
    def __init__(self, sku=None, **kwargs):
        self.sku = None
        self.series = kwargs.get("series")
        self.price = kwargs.get("price")
        self.core_cable = kwargs.get("core_cable")
        self.braid_material = kwargs.get("braid_material")
        self.calor_pattern = kwargs.get("calor_pattern")
        self.lenth = kwargs.get("length")
        self.connector_type = kwargs.get("connector_type")
        self.description = kwargs.get("description")

        if sku:
            self.load(sku)

    def __repr__(self):
        return f"<CableType {self.sku} - {self.name()}>"

    def name(self):
        base = f"{self.series} {self.length}ft {self.color} {self.material}".strip()
        if self.connector_type.startswith("RA"):
            base += " (RA)"
        return base

    def load(self, sku):
        conn = pg_pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cable_skus WHERE sku = %s", (sku,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"SKU {sku} not found.")
            colnames = [desc[0] for desc in cur.description]
            cable_data = dict(zip(colnames, row))
            self.cable = CableType.from_row(cable_data)

class cableUI:
    def __init__(self, ui_base):
        self.ui = ui_base
        self.cable_type = cableType()

    def select_cable(self):
        #CABLE_TYPE_ENUMS = fetch_enum_values("series")
        #CONNECTOR_TYPE_ENUMS = fetch_enum_values("length")
        menu_items = [
            {"label": "Enter SKU", "action": self.select_by_sku},
            {"label": "Select By Attribute", "action": self.select_by_attribute},
        ]
        choice = self.ui.render_footer_menu(menu_items, "Audio Cable QC")
        if choice == "":
            return
        else: 
            return menu_items[choice]["action"]()
        return

    def select_by_sku(self):
        self.ui.layout["footer"].update(Panel("wtf", title="Select by SKU"))
        self.ui.render()
        sku = self.ui.console.input("Enter SKU: ")
        self.cable_type.load(sku)

    def select_by_attribute(self):
        return

    def test_cable(self):
        return

    def print_cable_tag(self):
        self.coming_soon("Print Cable Tag")
        return

    def print_cable_wrap(self):
        self.coming_soon("Print Cable Wrap")

    def coming_soon(self, title):
        self.ui.layout["footer"].update(Panel("Coming Soon.", title=title))
        self.ui.render()
        while True:
            sku = self.ui.console.input("(press enter to continue)")
            return

    def go(self):
        menu_items = [
            {"label": "Select Cable Type", "action": self.select_cable},
            {"label": "Print Cable Tag", "action": self.print_cable_tag},
            {"label": "Print Cable Wrap", "action": self.print_cable_wrap},
        ]

        choice = self.ui.render_footer_menu(menu_items, "Audio Cable QC")
        if choice == "":
            return
        else: 
            menu_items[choice]["action"]()

        if self.cable_type.sku:
            self.ui.layout["body"].update(Panel("Success", title="Selected Cable Type"))
            menu_items.prepend({"label": "Run Test", "action": self.test_cable})

            choice = self.ui.render_footer_menu(menu_items, "Audio Cable QC")
            if choice == "":
                return
            else: 
                menu_items[choice]["action"]()
        else:
            self.ui.layout["body"].update(Panel("Fail", title="Selected Cable Type"))
            self.ui.render()
            while True:
                x=1
