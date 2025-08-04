from rich.panel import Panel

from greenlight.db import pg_pool
from greenlight.enums import fetch_enum_values

def get_all_skus():
    """Fetch all SKUs from the database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT sku FROM cable_skus ORDER BY sku")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching SKUs: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def filter_skus(partial_sku, all_skus):
    """Filter SKUs that match the partial input"""
    if not partial_sku:
        return all_skus[:20]  # Show first 20 if no input
    
    partial_upper = partial_sku.upper()
    filtered = [sku for sku in all_skus if sku.upper().startswith(partial_upper)]
    return filtered[:20]  # Limit to 20 results

def get_distinct_series():
    """Fetch all distinct series from the database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT series FROM cable_skus ORDER BY series")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching series: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def get_distinct_color_patterns(series=None):
    """Fetch distinct color patterns, optionally filtered by series"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            if series:
                cur.execute("SELECT DISTINCT color_pattern FROM cable_skus WHERE series = %s ORDER BY color_pattern", (series,))
            else:
                cur.execute("SELECT DISTINCT color_pattern FROM cable_skus ORDER BY color_pattern")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching color patterns: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def get_distinct_lengths(series=None, color_pattern=None):
    """Fetch distinct lengths, optionally filtered by previous selections"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            conditions = []
            params = []
            
            if series:
                conditions.append("series = %s")
                params.append(series)
            if color_pattern:
                conditions.append("color_pattern = %s")
                params.append(color_pattern)
            
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            query = f"SELECT DISTINCT length FROM cable_skus{where_clause}"
            
            cur.execute(query, params)
            lengths = [row[0] for row in cur.fetchall()]
            # Sort numerically
            try:
                return sorted(lengths, key=lambda x: float(x))
            except ValueError:
                return sorted(lengths)
    except Exception as e:
        print(f"Error fetching lengths: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def get_distinct_connector_types(series=None, color_pattern=None, length=None):
    """Fetch distinct connector types, optionally filtered by previous selections"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            conditions = []
            params = []
            
            if series:
                conditions.append("series = %s")
                params.append(series)
            if color_pattern:
                conditions.append("color_pattern = %s")
                params.append(color_pattern)
            if length:
                conditions.append("length = %s")
                params.append(length)
            
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            query = f"SELECT DISTINCT connector_type FROM cable_skus{where_clause} ORDER BY connector_type"
            
            cur.execute(query, params)
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching connector types: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def find_cable_by_attributes(series, color_pattern, length, connector_type):
    """Find cable SKU that matches the selected attributes"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sku FROM cable_skus 
                WHERE series = %s AND color_pattern = %s AND length = %s AND connector_type = %s
                LIMIT 1
            """, (series, color_pattern, length, connector_type))
            result = cur.fetchone()
            return result[0] if result else None
    except Exception as e:
        print(f"Error finding cable by attributes: {e}")
        return None
    finally:
        pg_pool.putconn(conn)

class CableType:
    def __init__(self, sku=None, **kwargs):
        self.sku = None
        self.series = None
        self.price = None
        self.core_cable = None
        self.braid_material = None
        self.color_pattern = None
        self.length = None
        self.connector_type = None
        self.description = None

        if sku:
            self.load(sku)

    def __repr__(self):
        if self.sku:
            return f"<CableType {self.sku} - {self.name()}>"
        return "<CableType (not loaded)>"

    def name(self):
        if not self.series:
            return "Not loaded"
        
        base = f"{self.series} {self.length}ft {self.color_pattern}"
        if self.connector_type and self.connector_type.startswith("RA"):
            base += " (RA)"
        return base

    def load(self, sku):
        """Load cable data from database by SKU"""
        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM cable_skus WHERE sku = %s", (sku,))
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"SKU {sku} not found.")
                
                colnames = [desc[0] for desc in cur.description]
                cable_data = dict(zip(colnames, row))
                
                # Populate instance attributes
                self.sku = cable_data.get('sku')
                self.series = cable_data.get('series')
                self.price = cable_data.get('price')
                self.core_cable = cable_data.get('core_cable')
                self.braid_material = cable_data.get('braid_material')
                self.color_pattern = cable_data.get('color_pattern')
                self.length = cable_data.get('length')
                self.connector_type = cable_data.get('connector_type')
                self.description = cable_data.get('description')
        finally:
            pg_pool.putconn(conn)
    
    def is_loaded(self):
        """Check if cable data has been loaded"""
        return self.sku is not None
    
    def get_display_info(self):
        """Get formatted display information for UI"""
        if not self.is_loaded():
            return "No cable selected"
        
        return f"""SKU: {self.sku}
Name: {self.name()}

Series: {self.series}
Length: {self.length} ft
Color: {self.color_pattern}
Connector: {self.connector_type}
Core Cable: {self.core_cable}
Braid Material: {self.braid_material}
Description: {self.description}"""

class cableUI:
    def __init__(self, ui_base):
        self.ui = ui_base
        self.cable_type = CableType()

    def select_cable(self):
        #CABLE_TYPE_ENUMS = fetch_enum_values("series")
        #CONNECTOR_TYPE_ENUMS = fetch_enum_values("length")
        menu_items = [
            {"label": "Enter SKU", "action": self.select_by_sku},
            {"label": "Select By Attribute", "action": self.select_by_attribute},
        ]
        choice = self.ui.render_footer_menu(menu_items, "Audio Cable Management")
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

        choice = self.ui.render_footer_menu(menu_items, "Audio Cable Management")
        if choice == "":
            return
        else: 
            menu_items[choice]["action"]()

        if self.cable_type.sku:
            self.ui.layout["body"].update(Panel("Success", title="Selected Cable Type"))
            menu_items.prepend({"label": "Run Test", "action": self.test_cable})

            choice = self.ui.render_footer_menu(menu_items, "Audio Cable Management")
            if choice == "":
                return
            else: 
                menu_items[choice]["action"]()
        else:
            self.ui.layout["body"].update(Panel("Fail", title="Selected Cable Type"))
            self.ui.render()
            while True:
                x=1
