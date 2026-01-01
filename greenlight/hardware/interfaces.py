"""
Hardware interface abstractions for Greenlight Terminal

Provides abstract base classes for all hardware components to enable
easy testing and hardware swapping.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result from barcode scanner"""
    data: str
    format: str  # "CODE128", "QR", etc.
    timestamp: float
    success: bool


@dataclass
class PrintJob:
    """Print job specification"""
    template: str
    data: Dict[str, Any]
    quantity: int = 1
    priority: str = "normal"  # "low", "normal", "high"


class ScannerInterface(ABC):
    """Abstract interface for barcode scanners"""
    
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize scanner hardware"""
        pass
    
    @abstractmethod
    def scan(self, timeout: float = 5.0) -> Optional[ScanResult]:
        """Scan for barcode with timeout"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if scanner is connected and ready"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close scanner connection"""
        pass


class LabelPrinterInterface(ABC):
    """Abstract interface for label printers (Brady M511, etc.)"""
    
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize printer hardware"""
        pass
    
    @abstractmethod
    def print_labels(self, print_job: PrintJob) -> bool:
        """Print cable labels with serial numbers"""
        pass
    
    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Get printer status (ready, paper, ribbon, etc.)"""
        pass
    
    @abstractmethod
    def is_ready(self) -> bool:
        """Check if printer is ready to print"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close printer connection"""
        pass


class CardPrinterInterface(ABC):
    """Abstract interface for card printers"""
    
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize card printer hardware"""
        pass
    
    @abstractmethod
    def print_qc_card(self, print_job: PrintJob) -> bool:
        """Print QC test result card"""
        pass
    
    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Get printer status (ready, cards, ribbon, etc.)"""
        pass
    
    @abstractmethod
    def is_ready(self) -> bool:
        """Check if printer is ready to print"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close printer connection"""
        pass


class GPIOInterface(ABC):
    """Abstract interface for Raspberry Pi GPIO operations"""
    
    @abstractmethod
    def initialize(self) -> bool:
        """Initialize GPIO pins"""
        pass
    
    @abstractmethod
    def set_status_led(self, led_name: str, state: bool) -> None:
        """Control status LEDs (ready, testing, pass, fail, etc.)"""
        pass
    
    @abstractmethod
    def read_input(self, pin_name: str) -> bool:
        """Read digital input pin"""
        pass
    
    @abstractmethod
    def set_output(self, pin_name: str, state: bool) -> None:
        """Set digital output pin"""
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """Clean up GPIO resources"""
        pass


class HardwareManager:
    """Central manager for all hardware interfaces"""
    
    def __init__(self):
        self.scanner: Optional[ScannerInterface] = None
        self.label_printer: Optional[LabelPrinterInterface] = None
        self.card_printer: Optional[CardPrinterInterface] = None
        self.gpio: Optional[GPIOInterface] = None
        self._initialized = False
    
    def set_hardware(self, 
                    scanner: Optional[ScannerInterface] = None,
                    label_printer: Optional[LabelPrinterInterface] = None,
                    card_printer: Optional[CardPrinterInterface] = None,
                    gpio: Optional[GPIOInterface] = None) -> None:
        """Set hardware components without initialization (lazy loading)"""
        self.scanner = scanner
        self.label_printer = label_printer
        self.card_printer = card_printer
        self.gpio = gpio
        self._initialized = True  # Components will initialize when first used
        logger.info("Hardware components set for lazy initialization")
    
    def get_scanner(self) -> Optional[ScannerInterface]:
        """Get scanner with lazy initialization"""
        if self.scanner and hasattr(self.scanner, 'initialize'):
            if not self.scanner.is_connected():
                logger.info("Lazily initializing scanner...")
                self.scanner.initialize()
        return self.scanner
    
    def get_label_printer(self) -> Optional[LabelPrinterInterface]:
        """Get label printer (already initialized at startup)"""
        # No lazy initialization - printer is initialized in main.py init_hardware()
        return self.label_printer
    
    def get_card_printer(self) -> Optional[CardPrinterInterface]:
        """Get card printer with lazy initialization"""
        if self.card_printer and hasattr(self.card_printer, 'initialize'):
            # Card printer lazy initialization if needed
            pass
        return self.card_printer
    
    def get_gpio(self) -> Optional[GPIOInterface]:
        """Get GPIO with lazy initialization"""
        if self.gpio and hasattr(self.gpio, 'initialize'):
            # GPIO lazy initialization if needed
            pass
        return self.gpio
    
    def initialize(self, 
                   scanner: Optional[ScannerInterface] = None,
                   label_printer: Optional[LabelPrinterInterface] = None,
                   card_printer: Optional[CardPrinterInterface] = None,
                   gpio: Optional[GPIOInterface] = None) -> bool:
        """Initialize all hardware components"""
        self.scanner = scanner
        self.label_printer = label_printer
        self.card_printer = card_printer
        self.gpio = gpio
        
        success = True
        
        if self.scanner:
            # Skip re-initialization if scanner is already connected
            if hasattr(self.scanner, 'is_connected') and self.scanner.is_connected():
                logger.info("Scanner already initialized, skipping re-initialization")
            else:
                success &= self.scanner.initialize()
        
        if self.label_printer:
            success &= self.label_printer.initialize()
            
        if self.card_printer:
            success &= self.card_printer.initialize()
            
        if self.gpio:
            success &= self.gpio.initialize()
        
        self._initialized = success
        return success
    
    def is_initialized(self) -> bool:
        """Check if hardware manager is initialized"""
        return self._initialized
    
    def get_hardware_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all hardware components"""
        status = {}
        
        if self.scanner:
            status['scanner'] = {
                'connected': self.scanner.is_connected(),
                'type': type(self.scanner).__name__
            }
        
        if self.label_printer:
            status['label_printer'] = self.label_printer.get_status()
            status['label_printer']['type'] = type(self.label_printer).__name__
        
        if self.card_printer:
            status['card_printer'] = self.card_printer.get_status()
            status['card_printer']['type'] = type(self.card_printer).__name__
        
        if self.gpio:
            status['gpio'] = {
                'initialized': True,
                'type': type(self.gpio).__name__
            }
        
        return status
    
    def shutdown(self) -> None:
        """Shutdown all hardware components"""
        if self.scanner:
            self.scanner.close()
        
        if self.label_printer:
            self.label_printer.close()
            
        if self.card_printer:
            self.card_printer.close()
            
        if self.gpio:
            self.gpio.cleanup()
        
        self._initialized = False


# Global hardware manager instance
hardware_manager = HardwareManager()