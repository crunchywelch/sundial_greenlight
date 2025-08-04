from rich.panel import Panel
from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.config import APP_NAME
from greenlight.hardware.interfaces import hardware_manager


class PrintLabelsScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")
        
        if not cable_type or not cable_type.is_loaded():
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel("No cable type selected", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"Print labels for: {cable_type.name()}\n\n"
            f"SKU: {cable_type.sku}\n"
            f"This will generate serial numbers and print labels for assembly team.",
            title="Print Labels for Assembly"
        ))
        self.ui.layout["footer"].update(Panel("Enter number of labels to print (1-100):", title="Quantity"))
        self.ui.render()
        
        try:
            quantity_str = self.ui.console.input("Quantity: ")
            quantity = int(quantity_str)
            if quantity < 1 or quantity > 100:
                raise ValueError("Quantity must be between 1 and 100")
        except (ValueError, KeyboardInterrupt):
            return ScreenResult(NavigationAction.POP)
        
        return self.print_label_batch(operator, cable_type, quantity)
    
    def print_label_batch(self, operator, cable_type, quantity):
        """Generate serial numbers and print labels"""
        from greenlight.db import create_cable_for_assembly
        
        # Generate cable records for the batch
        serial_numbers = []
        for i in range(quantity):
            cable_record = create_cable_for_assembly(cable_type.sku)
            if cable_record:
                serial_numbers.append(cable_record['serial_number'])
            else:
                # Handle error in serial generation
                self.ui.layout["body"].update(Panel(
                    f"❌ Error creating cable record {i+1} of {quantity}\n\n"
                    f"Generated {len(serial_numbers)} serial numbers before error.",
                    title="Error", style="red"
                ))
                self.ui.layout["footer"].update(Panel("Press enter to continue", title=""))
                self.ui.render()
                self.ui.console.input("Press enter to continue...")
                return ScreenResult(NavigationAction.POP)
        
        # Show confirmation and prompt to print
        self.ui.layout["body"].update(Panel(
            f"📄 Ready to Print {quantity} Labels\n\n"
            f"Cable Type: {cable_type.name()}\n"
            f"SKU: {cable_type.sku}\n"
            f"Quantity: {quantity} labels\n\n"
            f"Serial numbers {serial_numbers[0]} through {serial_numbers[-1]} have been reserved in the database.\n\n"
            f"Press Enter when ready to send labels to printer...",
            title="Labels Ready", style="green"
        ))
        self.ui.layout["footer"].update(Panel("Press Enter to print, 'q' to cancel", title=""))
        self.ui.render()
        
        choice = self.ui.console.input("Print labels? ").lower()
        if choice == 'q':
            return ScreenResult(NavigationAction.POP)
        
        # Print labels using hardware manager
        return self.execute_label_printing(cable_type, serial_numbers, quantity)
    
    def execute_label_printing(self, cable_type, serial_numbers, quantity):
        """Execute the actual label printing using hardware manager"""
        from greenlight.hardware.interfaces import PrintJob
        
        # Check if label printer is available
        printer_available = hardware_manager.label_printer and hardware_manager.label_printer.is_ready()
        
        if not printer_available:
            self.ui.layout["body"].update(Panel(
                f"⚠️  Label printer not available\n\n"
                f"Serial numbers have been reserved in database:\n"
                f"{serial_numbers[0]} through {serial_numbers[-1]}\n\n"
                f"Please check printer connection and try again.",
                title="Printer Error", style="yellow"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to continue", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
        
        # Show printing in progress
        self.ui.layout["body"].update(Panel(
            f"🖨️  Printing {quantity} labels...\n\n"
            f"Cable Type: {cable_type.name()}\n"
            f"SKU: {cable_type.sku}\n\n"
            f"Please wait while labels are printed...",
            title="Printing", style="blue"
        ))
        self.ui.layout["footer"].update(Panel("Printing in progress...", title="Status"))
        self.ui.render()
        
        # Create print job
        print_job = PrintJob(
            template="cable_label",
            data={
                'sku': cable_type.sku,
                'cable_name': cable_type.name(),
                'serial_numbers': serial_numbers
            },
            quantity=quantity
        )
        
        # Send to printer
        print_success = hardware_manager.label_printer.print_labels(print_job)
        
        if print_success:
            self.ui.layout["body"].update(Panel(
                f"✅ {quantity} labels printed successfully!\n\n"
                f"Cable Type: {cable_type.name()}\n"
                f"SKU: {cable_type.sku}\n\n"
                f"Serial numbers {serial_numbers[0]} through {serial_numbers[-1]}\n"
                f"are ready for the assembly team.",
                title="Print Complete", style="green"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"❌ Label printing failed\n\n"
                f"Serial numbers have been reserved in database:\n"
                f"{serial_numbers[0]} through {serial_numbers[-1]}\n\n"
                f"Please check printer and try printing again.",
                title="Print Error", style="red"
            ))
        
        self.ui.layout["footer"].update(Panel("Press enter to continue", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class TestAssembledCableScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "🔍 Test Assembled Cable\n\n"
            "Scan the barcode on the cable label or manually enter the serial number\n"
            "to look up cable information and run tests.",
            title="Test Assembled Cable"
        ))
        
        # Check if scanner is available
        scanner_available = hardware_manager.scanner and hardware_manager.scanner.is_connected()
        
        if scanner_available:
            self.ui.layout["footer"].update(Panel(
                "Scan barcode or press 'm' for manual entry | Back (q)",
                title="Input Method"
            ))
        else:
            self.ui.layout["footer"].update(Panel(
                "Enter serial number (SD######) | Back (q)",
                title="Serial Number"
            ))
        
        self.ui.render()
        
        # Try barcode scanning first if available
        if scanner_available:
            serial_number = self.get_serial_number_with_scanner()
        else:
            serial_number = self.get_serial_number_manual()
        
        if not serial_number:
            return ScreenResult(NavigationAction.POP)
        
        # Look up cable record
        return self.lookup_and_test_cable(operator, serial_number)
    
    def get_serial_number_with_scanner(self):
        """Get serial number via barcode scanner or manual entry"""
        import time
        import sys
        import select
        
        self.ui.layout["footer"].update(Panel(
            "🔍 Ready to scan barcode... (press 'm' for manual entry, 'q' to quit)",
            title="Scanning", style="blue"
        ))
        self.ui.render()
        
        # Wait for scan or manual input
        start_time = time.time()
        timeout = 10.0  # 10 second timeout
        
        while time.time() - start_time < timeout:
            # Check for keyboard input (manual mode)
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                key = sys.stdin.read(1).lower()
                if key == 'q':
                    return None
                elif key == 'm':
                    return self.get_serial_number_manual()
            
            # Try barcode scan
            scan_result = hardware_manager.scanner.scan(timeout=0.5)
            if scan_result and scan_result.success:
                serial_number = scan_result.data.strip().upper()
                self.ui.layout["footer"].update(Panel(
                    f"✅ Scanned: {serial_number}",
                    title="Scan Complete", style="green"
                ))
                self.ui.render()
                time.sleep(1)  # Brief pause to show result
                return serial_number
            
            time.sleep(0.1)  # Brief pause between scan attempts
        
        # Timeout - fallback to manual entry
        self.ui.layout["footer"].update(Panel(
            "⏰ Scan timeout - switching to manual entry",
            title="Timeout", style="yellow"
        ))
        self.ui.render()
        time.sleep(1)
        return self.get_serial_number_manual()
    
    def get_serial_number_manual(self):
        """Get serial number via manual keyboard entry"""
        self.ui.layout["footer"].update(Panel(
            "Enter serial number (SD######):",
            title="Manual Entry"
        ))
        self.ui.render()
        
        try:
            serial_number = self.ui.console.input("Serial number: ").strip().upper()
            return serial_number if serial_number else None
        except KeyboardInterrupt:
            return None
    
    def lookup_and_test_cable(self, operator, serial_number):
        """Look up cable by serial number and start testing"""
        from greenlight.db import get_audio_cable
        from greenlight.cable import CableType
        
        # Check if serial number exists
        cable_record = get_audio_cable(serial_number)
        
        if not cable_record:
            self.ui.layout["body"].update(Panel(
                f"❌ Serial number not found: {serial_number}\n\n"
                f"This serial number may not exist or has not been generated yet.\n"
                f"Check the label and try again.",
                title="Serial Number Not Found", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.REPLACE, TestAssembledCableScreen, self.context)
        
        # Check if already tested
        if cable_record.get('resistance_ohms') is not None:
            return self.show_existing_test_results(operator, serial_number, cable_record)
        
        # Load cable type for testing
        try:
            cable_type = CableType()
            cable_type.load(cable_record['sku'])
            
            # Show cable info and start testing
            new_context = self.context.copy()
            new_context['cable_type'] = cable_type
            new_context['serial_number'] = serial_number
            new_context['testing_mode'] = 'assembled'  # Flag to indicate this is testing assembled cable
            
            return ScreenResult(NavigationAction.PUSH, CableTestScreen, new_context)
            
        except ValueError as e:
            self.ui.layout["body"].update(Panel(
                f"❌ Error loading cable type: {str(e)}\n\n"
                f"Serial: {serial_number}\n"
                f"SKU: {cable_record.get('sku', 'Unknown')}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to continue", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
    
    def show_existing_test_results(self, operator, serial_number, cable_record):
        """Display results for already tested cable"""
        resistance = cable_record.get('resistance_ohms', 'N/A')
        capacitance = cable_record.get('capacitance_pf', 'N/A')
        test_operator = cable_record.get('operator', 'Unknown')
        arduino_unit = cable_record.get('arduino_unit_id', 'Unknown')
        test_time = cable_record.get('test_timestamp', 'Unknown')
        
        if hasattr(test_time, 'strftime'):
            timestamp_str = test_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = str(test_time)
        
        self.ui.layout["body"].update(Panel(
            f"📋 Cable Already Tested\n\n"
            f"Serial: {serial_number}\n"
            f"SKU: {cable_record.get('sku', 'Unknown')}\n"
            f"Name: {cable_record.get('series', '')} {cable_record.get('length', '')}ft {cable_record.get('color_pattern', '')}\n\n"
            f"Test Results:\n"
            f"• Resistance: {resistance} Ω\n"
            f"• Capacitance: {capacitance} pF\n"
            f"• Tested by: {test_operator}\n"
            f"• Arduino Unit: #{arduino_unit}\n"
            f"• Test Time: {timestamp_str}",
            title="Test Results", style="green"
        ))
        self.ui.layout["footer"].update(Panel("Press 'r' to retest, Enter to continue", title=""))
        self.ui.render()
        
        choice = self.ui.console.input("Action: ").lower()
        if choice == 'r':
            # Allow retesting - load cable type and start test
            try:
                cable_type = CableType()
                cable_type.load(cable_record['sku'])
                
                new_context = self.context.copy()
                new_context['cable_type'] = cable_type
                new_context['serial_number'] = serial_number
                new_context['testing_mode'] = 'retest'
                
                return ScreenResult(NavigationAction.PUSH, CableTestScreen, new_context)
            except ValueError as e:
                return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.POP)