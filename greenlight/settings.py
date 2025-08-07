import time
import logging
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from .hardware.label_printer import BradyM511Printer, MockLabelPrinter, discover_brady_printers_sync
from .hardware.interfaces import PrintJob

logger = logging.getLogger(__name__)

class settingsUI:
    def __init__(self, ui_base):
        self.ui = ui_base

    def go(self):
        menu_items = [
            "Printer Connection Test",
            "System Information",
            "Debug Logs",
            "Exit (q)",
            ]
        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, (name) in enumerate(menu_items)
        ]

        self.ui.layout["body"].update(Panel("", title=""))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Settings"))
        while True:
            self.ui.console.print(self.ui.layout)
            choice = self.ui.console.input("Choose: ")
            if choice == "1":
                self.printer_test_screen()
            elif choice == "2":
                self.system_info_screen()
            elif choice == "3":
                self.debug_logs_screen()
            elif choice in ["4", "q"]:
                return
            else:
                continue
    
    def printer_test_screen(self):
        """Printer connection test and debug screen"""
        while True:
            # Create printer test menu
            menu_items = [
                "Scan for Brady Printers",
                "Test USB Printer Connection",
                "Test Bluetooth Printer Connection",
                "Test Mock Printer",
                "Print Test Label",
                "Back (q)",
            ]
            
            rows = [
                f"[green]{i + 1}.[/green] {name}"
                for i, name in enumerate(menu_items)
            ]
            
            # Display current printer status
            status_info = self._get_printer_status_info()
            
            self.ui.layout["body"].update(Panel(status_info, title="Printer Status"))
            self.ui.layout["footer"].update(Panel("\n".join(rows), title="Printer Test Menu"))
            
            self.ui.console.print(self.ui.layout)
            choice = self.ui.console.input("Choose: ")
            
            if choice == "1":
                self._scan_printers()
            elif choice == "2":
                self._test_usb_printer()
            elif choice == "3":
                self._test_bluetooth_printer()
            elif choice == "4":
                self._test_mock_printer()
            elif choice == "5":
                self._print_test_label()
            elif choice in ["6", "q"]:
                return
            else:
                continue
    
    def _get_printer_status_info(self):
        """Get current printer status information"""
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details", style="yellow")
        
        # Check Bluetooth availability
        try:
            import bleak
            bt_status = "[green]Available[/green]"
            try:
                bt_details = f"bleak v{bleak.__version__}"
            except AttributeError:
                # Some versions don't have __version__
                bt_details = "bleak library installed"
        except ImportError:
            bt_status = "[red]Not Available[/red]"
            bt_details = "bleak library not installed"
        
        table.add_row("Bluetooth BLE", bt_status, bt_details)
        
        # Check CUPS availability
        import subprocess
        try:
            result = subprocess.run(['lpstat', '-p'], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                cups_status = "[green]Available[/green]"
                printer_count = len([line for line in result.stdout.split('\n') if line.strip().startswith('printer')])
                cups_details = f"{printer_count} printers configured"
            else:
                cups_status = "[yellow]No Printers[/yellow]"
                cups_details = "CUPS running but no printers"
        except FileNotFoundError:
            cups_status = "[red]Not Available[/red]"
            cups_details = "CUPS not installed"
        
        table.add_row("CUPS Printing", cups_status, cups_details)
        
        # Check Brady M511 specific
        try:
            result = subprocess.run(['lpstat', '-p', 'M511'], capture_output=True, text=True, check=False)
            if result.returncode == 0 and 'idle' in result.stdout:
                m511_status = "[green]Ready[/green]"
                m511_details = "Connected via USB/CUPS"
            else:
                m511_status = "[yellow]Not Found[/yellow]"
                m511_details = "Not configured in CUPS"
        except:
            m511_status = "[red]Error[/red]"
            m511_details = "Unable to check status"
        
        table.add_row("Brady M511 (USB)", m511_status, m511_details)
        
        return table
    
    def _scan_printers(self):
        """Scan for available Brady printers"""
        self.ui.layout["body"].update(Panel("[yellow]Scanning for Brady printers...[/yellow]", title="Bluetooth Scan"))
        self.ui.console.print(self.ui.layout)
        
        printers = discover_brady_printers_sync()
        
        if printers:
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan")
            table.add_column("Address", style="green")
            table.add_column("RSSI", style="yellow")
            table.add_column("Type", style="blue")
            
            for printer in printers:
                table.add_row(
                    printer['name'],
                    printer['address'],
                    str(printer['rssi']),
                    printer['connection_type']
                )
            
            self.ui.layout["body"].update(Panel(table, title="Found Brady Printers"))
        else:
            self.ui.layout["body"].update(Panel("[red]No Brady printers found via Bluetooth[/red]", title="Scan Results"))
        
        self.ui.console.print(self.ui.layout)
        self.ui.console.input("Press Enter to continue...")
    
    def _test_usb_printer(self):
        """Test USB printer connection"""
        self.ui.layout["body"].update(Panel("[yellow]Testing USB printer connection...[/yellow]", title="USB Test"))
        self.ui.console.print(self.ui.layout)
        
        printer = BradyM511Printer(connection_type="usb")
        
        # Test connection
        if printer.initialize():
            status = printer.get_status()
            
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            
            for key, value in status.items():
                table.add_row(str(key), str(value))
            
            result_panel = Panel(table, title="[green]USB Connection Success[/green]")
        else:
            result_panel = Panel("[red]USB connection failed[/red]", title="USB Test Results")
        
        printer.close()
        
        self.ui.layout["body"].update(result_panel)
        self.ui.console.print(self.ui.layout)
        self.ui.console.input("Press Enter to continue...")
    
    def _test_bluetooth_printer(self):
        """Test Bluetooth printer connection"""
        # First scan for printers
        self.ui.layout["body"].update(Panel("[yellow]Scanning for Bluetooth printers...[/yellow]", title="Bluetooth Test"))
        self.ui.console.print(self.ui.layout)
        
        printers = discover_brady_printers_sync()
        
        if not printers:
            self.ui.layout["body"].update(Panel("[red]No Bluetooth printers found[/red]", title="Bluetooth Test"))
            self.ui.console.print(self.ui.layout)
            self.ui.console.input("Press Enter to continue...")
            return
        
        # Use first found printer
        printer_info = printers[0]
        
        self.ui.layout["body"].update(Panel(f"[yellow]Testing connection to {printer_info['name']}...[/yellow]", title="Bluetooth Test"))
        self.ui.console.print(self.ui.layout)
        
        printer = BradyM511Printer(
            connection_type="bluetooth",
            device_path=printer_info['address']
        )
        
        # Test connection
        if printer.initialize():
            status = printer.get_status()
            
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Printer Name", printer_info['name'])
            table.add_row("Bluetooth Address", printer_info['address'])
            table.add_row("RSSI", str(printer_info['rssi']))
            
            for key, value in status.items():
                table.add_row(str(key), str(value))
            
            result_panel = Panel(table, title="[green]Bluetooth Connection Success[/green]")
        else:
            result_panel = Panel(f"[red]Bluetooth connection failed to {printer_info['name']}[/red]", title="Bluetooth Test Results")
        
        printer.close()
        
        self.ui.layout["body"].update(result_panel)
        self.ui.console.print(self.ui.layout)
        self.ui.console.input("Press Enter to continue...")
    
    def _test_mock_printer(self):
        """Test mock printer"""
        self.ui.layout["body"].update(Panel("[yellow]Testing mock printer...[/yellow]", title="Mock Printer Test"))
        self.ui.console.print(self.ui.layout)
        
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
        self.ui.console.print(self.ui.layout)
        self.ui.console.input("Press Enter to continue...")
    
    def _print_test_label(self):
        """Print a test label"""
        # Ask user to choose printer type
        printer_menu = [
            "USB Printer",
            "Bluetooth Printer", 
            "Mock Printer",
            "Cancel"
        ]
        
        rows = [f"[green]{i + 1}.[/green] {name}" for i, name in enumerate(printer_menu)]
        
        self.ui.layout["body"].update(Panel("Select printer for test label:", title="Test Label"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Printer Selection"))
        self.ui.console.print(self.ui.layout)
        
        choice = self.ui.console.input("Choose printer: ")
        
        printer = None
        if choice == "1":
            printer = BradyM511Printer(connection_type="usb")
        elif choice == "2":
            # Find Bluetooth printer
            printers = discover_brady_printers_sync()
            if printers:
                printer = BradyM511Printer(
                    connection_type="bluetooth",
                    device_path=printers[0]['address']
                )
            else:
                self.ui.layout["body"].update(Panel("[red]No Bluetooth printers found[/red]", title="Test Label"))
                self.ui.console.print(self.ui.layout)
                self.ui.console.input("Press Enter to continue...")
                return
        elif choice == "3":
            printer = MockLabelPrinter()
        else:
            return
        
        # Initialize printer and print test label
        self.ui.layout["body"].update(Panel("[yellow]Connecting to printer and printing test label...[/yellow]", title="Test Label"))
        self.ui.console.print(self.ui.layout)
        
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
        self.ui.console.print(self.ui.layout)
        self.ui.console.input("Press Enter to continue...")
    
    def system_info_screen(self):
        """Display system information"""
        import platform
        import psutil
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Component", style="cyan")
        table.add_column("Information", style="green")
        
        table.add_row("OS", f"{platform.system()} {platform.release()}")
        table.add_row("Python", platform.python_version())
        table.add_row("Architecture", platform.machine())
        table.add_row("CPU Count", str(psutil.cpu_count()))
        table.add_row("Memory", f"{psutil.virtual_memory().total // (1024**3)} GB")
        
        self.ui.layout["body"].update(Panel(table, title="System Information"))
        self.ui.layout["footer"].update(Panel("Press Enter to return...", title=""))
        self.ui.console.print(self.ui.layout)
        self.ui.console.input()
    
    def debug_logs_screen(self):
        """Display recent debug logs"""
        self.ui.layout["body"].update(Panel("[yellow]Debug logs would be displayed here[/yellow]", title="Debug Logs"))
        self.ui.layout["footer"].update(Panel("Press Enter to return...", title=""))
        self.ui.console.print(self.ui.layout)
        self.ui.console.input()
