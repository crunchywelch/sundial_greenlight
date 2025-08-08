import time
import logging
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.hardware.label_printer import BradyM511Printer, MockLabelPrinter, discover_brady_printers_sync
from greenlight.hardware.interfaces import PrintJob

logger = logging.getLogger(__name__)


class SettingsScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        menu_items = [
            "Database Settings",
            "Printer Settings", 
            "User Management",
            "System Information",
            "Back (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Configure system settings and preferences", title="Settings"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Settings"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        if choice == "1":
            return ScreenResult(NavigationAction.PUSH, DatabaseSettingsScreen, self.context)
        elif choice == "2":
            return ScreenResult(NavigationAction.PUSH, PrinterSettingsScreen, self.context)
        elif choice == "3":
            return ScreenResult(NavigationAction.PUSH, UserManagementScreen, self.context)
        elif choice == "4":
            return ScreenResult(NavigationAction.PUSH, SystemInfoScreen, self.context)
        elif choice in ["5", "q"]:
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, SettingsScreen, self.context)


class DatabaseSettingsScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Database settings functionality coming soon", title="Database Settings"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class PrinterSettingsScreen(Screen):
    def run(self) -> ScreenResult:
        while True:
            operator = self.context.get("operator", "")
            menu_items = [
                "Scan for Brady Printers",
                "Test Bluetooth Printer Connection", 
                "Pair Brady Printer (System)",
                "Test Mock Printer",
                "Print Test Label", 
                "Printer Status Overview",
                "Back (q)"
            ]

            rows = [
                f"[green]{i + 1}.[/green] {name}"
                for i, name in enumerate(menu_items)
            ]

            # Display current printer status
            status_info = self._get_printer_status_info()
            
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(status_info, title="Printer Connection Test"))
            self.ui.layout["footer"].update(Panel("\n".join(rows), title="Printer Test Menu"))
            self.ui.render()

            choice = self.ui.console.input("Choose: ")
            
            if choice == "1":
                self._scan_printers()
            elif choice == "2":
                self._test_bluetooth_printer()
            elif choice == "3":
                self._pair_system_bluetooth()
            elif choice == "4":
                self._test_mock_printer()
            elif choice == "5":
                self._print_test_label()
            elif choice == "6":
                self._show_detailed_status()
            elif choice in ["7", "q"]:
                return ScreenResult(NavigationAction.POP)
            else:
                continue
    
    def _get_printer_status_info(self):
        """Get current printer status information"""
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan", width=18)
        table.add_column("Status", style="green", width=12)
        table.add_column("Details", style="yellow")
        
        # Check Bluetooth availability
        try:
            import bleak
            bt_status = "[green]Available[/green]"
            try:
                bt_details = f"bleak v{bleak.__version__}"
            except AttributeError:
                bt_details = "bleak library installed"
        except ImportError:
            bt_status = "[red]Not Available[/red]"
            bt_details = "bleak library not installed"
        
        table.add_row("Bluetooth BLE", bt_status, bt_details)
        
        # Check Brady M511 Bluetooth status
        try:
            printers = discover_brady_printers_sync()
            if printers:
                m511_status = "[green]Discoverable[/green]" 
                m511_details = f"Found {len(printers)} Brady printer(s)"
            else:
                m511_status = "[yellow]Not Found[/yellow]"
                m511_details = "No Brady printers advertising"
        except Exception as e:
            m511_status = "[red]Error[/red]"
            m511_details = f"Scan failed: {str(e)[:30]}..."
        
        table.add_row("Brady M511 (BT)", m511_status, m511_details)
        
        return table
    
    def _scan_printers(self):
        """Scan for available Brady printers"""
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("[yellow]Scanning for Brady printers...[/yellow]", title="Bluetooth Scan"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()
        
        printers = discover_brady_printers_sync()
        
        if printers:
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan")
            table.add_column("Address", style="green")
            table.add_column("Type", style="blue")
            
            for printer in printers:
                table.add_row(
                    printer['name'],
                    printer['address'],
                    printer['connection_type']
                )
            
            result_panel = Panel(table, title="Found Brady Printers")
        else:
            result_panel = Panel("[red]No Brady printers found via Bluetooth[/red]", title="Scan Results")
        
        self.ui.layout["body"].update(result_panel)
        self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
        self.ui.render()
        self.ui.console.input()
    
    def _test_bluetooth_printer(self):
        """Test Bluetooth printer connection with detailed error reporting"""
        operator = self.context.get("operator", "")
        
        # First scan for printers
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("[yellow]Scanning for Bluetooth printers...[/yellow]", title="Bluetooth Test"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()
        
        printers = discover_brady_printers_sync()
        
        if not printers:
            self.ui.layout["body"].update(Panel("[red]No Bluetooth printers found[/red]", title="Bluetooth Test"))
            self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
            self.ui.render()
            self.ui.console.input()
            return
        
        # Use first found printer
        printer_info = printers[0]
        
        # Show detailed connection attempt progress
        progress_table = Table(show_header=True, header_style="bold magenta")
        progress_table.add_column("Step", style="cyan")
        progress_table.add_column("Status", style="yellow")
        progress_table.add_column("Details", style="green")
        
        progress_table.add_row("1. Printer Found", "✓ Success", f"{printer_info['name']}")
        progress_table.add_row("2. Address", "✓ Ready", f"{printer_info['address']}")
        progress_table.add_row("3. Connection", "⏳ Connecting...")
        
        self.ui.layout["body"].update(Panel(progress_table, title="Bluetooth Connection Progress"))
        self.ui.layout["footer"].update(Panel("Testing connection with retry logic for multi-app printer...", title=""))
        self.ui.render()
        
        # Direct connection test - the method that was working
        connection_success = False
        error_details = ""
        
        try:
            # Import for connection testing
            import asyncio
            import time
            
            async def test_direct_connection():
                """Direct connection test using centralized connection logic"""
                from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady
                
                # Use centralized connection that makes LED go solid
                client, connected = await connect_to_brady(printer_info['address'], timeout=15.0)
                
                if connected and client:
                    # Hold connection briefly to see LED behavior
                    await asyncio.sleep(5)
                    await disconnect_from_brady(client)
                    return True
                return False
            
            # Run direct connection test in new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                connection_success = loop.run_until_complete(test_direct_connection())
            finally:
                loop.close()
                
        except Exception as e:
            error_details = str(e)
        
        if connection_success:
            progress_table.add_row("3. Connection", "✓ Success", "Connected to Brady M511")
            progress_table.add_row("4. LED Check", "👁️  Observe", "LED should have been SOLID during connection")
            
            self.ui.layout["body"].update(Panel(progress_table, title="Bluetooth Connection Progress"))
            self.ui.render()
            
            # Success - show connection results
            result_table = Table(show_header=True, header_style="bold magenta")
            result_table.add_column("Property", style="cyan")
            result_table.add_column("Value", style="green")
            
            result_table.add_row("Printer Name", printer_info['name'])
            result_table.add_row("Bluetooth Address", printer_info['address'])
            result_table.add_row("Connection Type", "Bluetooth BLE")
            result_table.add_row("Connection Test", "✅ SUCCESS")
            result_table.add_row("LED Behavior", "Should have gone SOLID during test")
            result_table.add_row("Connection Duration", "5 seconds (then auto-disconnected)")
            
            result_panel = Panel(result_table, title="[green]Brady M511 Connection Test Success![/green]")
        else:
            # Connection failed - show detailed error info
            progress_table.add_row("3. Connection", "✗ Failed", "All retry attempts failed")
            
            error_table = Table(show_header=True, header_style="bold red")
            error_table.add_column("Issue", style="red")
            error_table.add_column("Possible Causes", style="yellow")
            error_table.add_column("Solutions", style="cyan")
            
            error_table.add_row(
                "Connection Timeout", 
                "• Printer cycling pairing modes\n• Another app using printer\n• System pairing required\n• BLE interference",
                "• Try multiple times (wait 10s between)\n• Close other Brady apps\n• Pair via system Bluetooth first\n• Move closer to printer"
            )
            
            error_table.add_row(
                "Brady M511 Behavior",
                "• Multi-app printer cycles modes\n• May appear/disappear in scans\n• Connection window is brief",
                "• This is normal Brady behavior\n• Keep trying every 10-15 seconds\n• Success rate improves with patience"
            )
            
            if error_details:
                error_table.add_row("Technical Details", error_details, "Check logs for more info")
            
            result_panel = Panel(error_table, title="[red]Bluetooth Connection Failed[/red]")
        
        # No printer object to close with direct connection test
        
        self.ui.layout["body"].update(result_panel)
        self.ui.layout["footer"].update(Panel("Press Enter to continue... (Try again if failed - printer cycles pairing modes)", title=""))
        self.ui.render()
        self.ui.console.input()
    
    def _pair_system_bluetooth(self):
        """Attempt to pair Brady printer at system level"""
        operator = self.context.get("operator", "")
        
        # First scan for printers
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("[yellow]Scanning for Brady printers to pair...[/yellow]", title="System Pairing"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()
        
        printers = discover_brady_printers_sync()
        
        if not printers:
            self.ui.layout["body"].update(Panel("[red]No Bluetooth printers found[/red]", title="System Pairing"))
            self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
            self.ui.render()
            self.ui.console.input()
            return
        
        printer_info = printers[0]
        
        # Show pairing instructions
        instructions = f"""[yellow]System Bluetooth Pairing Instructions:[/yellow]

1. Brady M511 found: [green]{printer_info['name']}[/green]
2. Address: [cyan]{printer_info['address']}[/cyan]
3. Follow these steps:

[bold]Manual Pairing Process:[/bold]
• Open system Bluetooth settings
• Look for "M511-PGM5112423102007" 
• Click "Pair" or "Connect"
• If prompted for PIN, try: 0000 or 1234

[bold]Command Line Option:[/bold]
The system will attempt automatic pairing...
"""
        
        self.ui.layout["body"].update(Panel(instructions, title="Brady M511 System Pairing"))
        self.ui.layout["footer"].update(Panel("Press Enter to attempt automatic pairing...", title=""))
        self.ui.render()
        self.ui.console.input()
        
        # Attempt system-level pairing
        self.ui.layout["body"].update(Panel(f"[yellow]Attempting to pair {printer_info['name']}...[/yellow]", title="System Pairing"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()
        
        import subprocess
        try:
            # Try to pair using bluetoothctl
            result = subprocess.run([
                'bluetoothctl', '--', 'pair', printer_info['address']
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                result_panel = Panel(f"[green]Successfully paired with {printer_info['name']}![/green]\n\nTry the Bluetooth connection test now.", title="Pairing Success")
            else:
                result_panel = Panel(f"[yellow]Automatic pairing failed.[/yellow]\n\nError: {result.stderr}\n\nTry manual pairing through system Bluetooth settings.", title="Pairing Result")
                
        except subprocess.TimeoutExpired:
            result_panel = Panel("[yellow]Pairing timeout.[/yellow]\n\nTry manual pairing through system Bluetooth settings.", title="Pairing Timeout")
        except Exception as e:
            result_panel = Panel(f"[red]Pairing error: {e}[/red]\n\nTry manual pairing through system Bluetooth settings.", title="Pairing Error")
        
        self.ui.layout["body"].update(result_panel)
        self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
        self.ui.render()
        self.ui.console.input()
    
    def _test_mock_printer(self):
        """Test mock printer"""
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("[yellow]Testing mock printer...[/yellow]", title="Mock Printer Test"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()
        
        printer = MockLabelPrinter()
        
        if printer.initialize():
            status = printer.get_status()
            
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            
            for key, value in status.items():
                table.add_row(str(key), str(value))
            
            result_panel = Panel(table, title="[green]Mock Printer Ready[/green]")
        else:
            result_panel = Panel("[red]Mock printer initialization failed[/red]", title="Mock Test Results")
        
        printer.close()
        
        self.ui.layout["body"].update(result_panel)
        self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
        self.ui.render()
        self.ui.console.input()
    
    def _print_test_label(self):
        """Print a test label"""
        operator = self.context.get("operator", "")
        
        # Ask user to choose printer type
        printer_menu_items = [
            "Bluetooth Printer",
            "Mock Printer", 
            "Cancel"
        ]
        
        rows = [f"[green]{i + 1}.[/green] {name}" for i, name in enumerate(printer_menu_items)]
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Select printer for test label:", title="Test Label"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Printer Selection"))
        self.ui.render()
        
        choice = self.ui.console.input("Choose printer: ")
        
        printer = None
        if choice == "1":
            # Find Bluetooth printer
            printers = discover_brady_printers_sync()
            if printers:
                printer = BradyM511Printer(device_path=printers[0]['address'])
            else:
                self.ui.layout["body"].update(Panel("[red]No Bluetooth printers found[/red]", title="Test Label"))
                self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
                self.ui.render()
                self.ui.console.input()
                return
        elif choice == "2":
            printer = MockLabelPrinter()
        else:
            return
        
        # Initialize printer and print test label
        self.ui.layout["body"].update(Panel("[yellow]Connecting to printer and printing test label...[/yellow]", title="Test Label"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()
        
        if printer.initialize():
            # Create test print job
            test_job = PrintJob(
                template="test_label",
                quantity=1,
                data={
                    'sku': 'TEST-001',
                    'cable_name': 'Test Cable',
                    'serial_numbers': ['TEST123']
                }
            )
            
            if printer.print_labels(test_job):
                result_panel = Panel("[green]Test label printed successfully![/green]", title="Test Label Results")
            else:
                result_panel = Panel("[red]Test label printing failed[/red]", title="Test Label Results")
        else:
            result_panel = Panel("[red]Failed to connect to printer[/red]", title="Test Label Results")
        
        printer.close()
        
        self.ui.layout["body"].update(result_panel)
        self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
        self.ui.render()
        self.ui.console.input()
    
    def _show_detailed_status(self):
        """Show detailed system information"""
        operator = self.context.get("operator", "")
        
        import platform
        try:
            import psutil
            has_psutil = True
        except ImportError:
            has_psutil = False
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan")
        table.add_column("Information", style="green")
        
        table.add_row("OS", f"{platform.system()} {platform.release()}")
        table.add_row("Python", platform.python_version())
        table.add_row("Architecture", platform.machine())
        
        if has_psutil:
            table.add_row("CPU Count", str(psutil.cpu_count()))
            table.add_row("Memory", f"{psutil.virtual_memory().total // (1024**3)} GB")
        else:
            table.add_row("System Info", "Install psutil for detailed system info")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(table, title="Detailed System Information"))
        self.ui.layout["footer"].update(Panel("Press Enter to continue...", title=""))
        self.ui.render()
        self.ui.console.input()


class UserManagementScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("User management functionality coming soon", title="User Management"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class SystemInfoScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("System information functionality coming soon", title="System Information"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)
