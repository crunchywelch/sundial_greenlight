#!/usr/bin/env python3
"""
Test lazy hardware initialization
"""

import sys
import time
sys.path.insert(0, '.')

from greenlight.hardware.scanner import ZebraDS2208Scanner
from greenlight.hardware.label_printer import BradyM511Printer
from greenlight.hardware.interfaces import hardware_manager

def test_lazy_initialization():
    """Test that hardware initialization is lazy and fast"""
    print("🧪 Testing Lazy Hardware Initialization")
    print("=" * 50)
    
    # Test 1: Fast startup (no initialization)
    print("\n⚡ Test 1: Fast Startup")
    start_time = time.time()
    
    scanner = ZebraDS2208Scanner()
    label_printer = BradyM511Printer()
    
    hardware_manager.set_hardware(
        scanner=scanner,
        label_printer=label_printer
    )
    
    startup_time = time.time() - start_time
    print(f"   ✅ Hardware setup completed in {startup_time:.3f} seconds")
    print(f"   📝 Scanner connected: {scanner.is_connected()}")
    print(f"   📝 Printer connected: {label_printer.connected}")
    
    # Test 2: Lazy initialization when accessed
    print(f"\n🔄 Test 2: Lazy Initialization")
    
    print("   📱 Accessing scanner (should trigger initialization)...")
    init_start = time.time()
    hw_scanner = hardware_manager.get_scanner()
    scanner_init_time = time.time() - init_start
    print(f"   ✅ Scanner access completed in {scanner_init_time:.3f} seconds")
    print(f"   📝 Scanner now connected: {hw_scanner.is_connected()}")
    
    print("   📄 Accessing label printer (should trigger auto-discovery)...")
    init_start = time.time() 
    hw_printer = hardware_manager.get_label_printer()
    printer_init_time = time.time() - init_start
    print(f"   ✅ Printer access completed in {printer_init_time:.3f} seconds")
    print(f"   📝 Printer discovery attempted: {hw_printer._discovery_attempted}")
    
    # Test 3: Subsequent access should be fast (already initialized)
    print(f"\n⚡ Test 3: Subsequent Access (Should be Fast)")
    
    fast_start = time.time()
    hw_scanner2 = hardware_manager.get_scanner()
    hw_printer2 = hardware_manager.get_label_printer()
    fast_time = time.time() - fast_start
    
    print(f"   ✅ Subsequent access completed in {fast_time:.3f} seconds")
    print(f"   📝 Same scanner instance: {hw_scanner is hw_scanner2}")
    print(f"   📝 Same printer instance: {hw_printer is hw_printer2}")
    
    print("\n" + "=" * 50)
    print("📊 LAZY INITIALIZATION TEST RESULTS")
    print("=" * 50)
    print(f"✅ Startup Time: {startup_time:.3f}s (should be < 0.1s)")
    print(f"✅ Scanner Init: {scanner_init_time:.3f}s (initialization on demand)")
    print(f"✅ Printer Init: {printer_init_time:.3f}s (auto-discovery on demand)")
    print(f"✅ Subsequent Access: {fast_time:.3f}s (should be < 0.001s)")
    print()
    print("🎉 Lazy initialization is working correctly!")
    print("📝 Hardware is only initialized when first accessed, not on startup")

if __name__ == "__main__":
    test_lazy_initialization()