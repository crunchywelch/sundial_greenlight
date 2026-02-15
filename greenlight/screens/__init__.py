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
    MainMenuScreen
)

# Cable workflow screens
from greenlight.screens.cable import (
    ScanCableLookupScreen,
    CableSelectionForIntakeScreen,
    SeriesSelectionScreen,
    ColorPatternSelectionScreen,
    MiscCableEntryScreen,
    LengthSelectionScreen,
    ConnectorTypeSelectionScreen,
    ScanCableIntakeScreen
)

# Inventory screens
from greenlight.screens.inventory import (
    InventoryScreen,
    ViewInventoryScreen,
    AddItemsScreen,
    UpdateStockScreen,
    ReportsScreen
)

# Wholesale screens
from greenlight.screens.wholesale import (
    WholesaleBatchScreen
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
    'MainMenuScreen',
    # Cable
    'ScanCableLookupScreen',
    'CableSelectionForIntakeScreen',
    'SeriesSelectionScreen',
    'ColorPatternSelectionScreen',
    'MiscCableEntryScreen',
    'LengthSelectionScreen',
    'ConnectorTypeSelectionScreen',
    'ScanCableIntakeScreen',
    # Wholesale
    'WholesaleBatchScreen',
    # Inventory
    'InventoryScreen',
    'ViewInventoryScreen',
    'AddItemsScreen',
    'UpdateStockScreen',
    'ReportsScreen',
    # Settings
    'SettingsScreen',
    'DatabaseSettingsScreen',
    'UserManagementScreen',
    'SystemInfoScreen',
]
