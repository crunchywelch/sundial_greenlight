#!/usr/bin/env python3
"""
Test script for Brady M511 label printer
"""

import logging
from greenlight.hardware.label_printer import BradyM511Printer
from greenlight.hardware.interfaces import PrintJob

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_brady_printer():
    """Test Brady M511 printer functionality"""
    
    print("🧪 Testing Brady M511 Label Printer")
    print("=" * 40)
    
    # Initialize printer
    printer = BradyM511Printer(connection_type="usb")
    
    # Test initialization
    print("\n1. Testing printer initialization...")
    if printer.initialize():
        print("✅ Printer initialized successfully")
    else:
        print("❌ Printer initialization failed")
        return False
    
    # Test status
    print("\n2. Testing printer status...")
    status = printer.get_status()
    print(f"Status: {status}")
    
    if printer.is_ready():
        print("✅ Printer ready")
    else:
        print("❌ Printer not ready")
        return False
    
    # Test label printing
    print("\n3. Testing label printing...")
    test_data = {
        'sku': 'TEST-001',
        'serial_numbers': ['TST240805001', 'TST240805002'],
        'cable_name': 'Test Cable XLR-M to TRS'
    }
    
    print_job = PrintJob(
        template="cable_label",
        quantity=2,
        data=test_data
    )
    
    if printer.print_labels(print_job):
        print("✅ Test labels sent to printer")
        print("📄 Check the Brady M511 for printed labels")
    else:
        print("❌ Label printing failed")
        return False
    
    # Close printer
    printer.close()
    print("\n✅ Test completed successfully!")
    return True

if __name__ == "__main__":
    try:
        success = test_brady_printer()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        exit(1)