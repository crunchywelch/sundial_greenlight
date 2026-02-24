"""
Greenlight Application Screens

This package contains all UI screens organized by functionality:
- main: Application entry, operator selection, main menu
- cable: Cable registration, testing, and QC workflows
- inventory: Order fulfillment and inventory management
- settings: System configuration and preferences
"""

# Main application screens
from greenlight.screens.main import (
    SplashScreen,
)

# Cable workflow screens
from greenlight.screens.cable import (
    ScanCableLookupScreen,
    SeriesSelectionScreen,
    ColorPatternSelectionScreen,
    MiscCableEntryScreen,
    LengthSelectionScreen,
    ConnectorTypeSelectionScreen,
    ScanCableIntakeScreen
)

# Inventory screens
from greenlight.screens.inventory import (
    InventoryDashboardScreen,
    SeriesHeatmapScreen,
    ProductionSuggestionsScreen,
)

# Wire label screens
from greenlight.screens.wire import (
    WireLabelScreen
)

# Wholesale screens
from greenlight.screens.wholesale import (
    WholesaleBatchScreen
)

# Shopify scan mode
from greenlight.screens.shopify_scan import (
    ShopifyScanModeScreen
)

# Settings screens
from greenlight.screens.settings import (
    SettingsScreen,
    DatabaseSettingsScreen,
    UserManagementScreen,
    SystemInfoScreen
)

__all__ = [
    # Main
    'SplashScreen',
    # Cable
    'ScanCableLookupScreen',
    'SeriesSelectionScreen',
    'ColorPatternSelectionScreen',
    'MiscCableEntryScreen',
    'LengthSelectionScreen',
    'ConnectorTypeSelectionScreen',
    'ScanCableIntakeScreen',
    # Wire
    'WireLabelScreen',
    # Wholesale
    'WholesaleBatchScreen',
    # Shopify
    'ShopifyScanModeScreen',
    # Inventory
    'InventoryDashboardScreen',
    'SeriesHeatmapScreen',
    'ProductionSuggestionsScreen',
    # Settings
    'SettingsScreen',
    'DatabaseSettingsScreen',
    'UserManagementScreen',
    'SystemInfoScreen',
]
