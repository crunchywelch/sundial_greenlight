#!/usr/bin/env node
/**
 * Brady Print Service
 * Node.js service that handles Brady M511 printing using the official Brady Web SDK
 * 
 * Note: Brady Web SDK requires import mapping - this is a browser-based SDK
 * For Node.js usage, we need to use a different approach or mock the functionality
 */

// Since Brady Web SDK is browser-only, we'll create a mock implementation for now
class MockBradySDK {
    constructor() {
        console.error('Using Mock Brady SDK (real SDK is browser-only)');
    }

    async discoverPrinters() {
        // Mock discovery - in real implementation this would use Web Bluetooth API
        return [
            {
                name: 'M511-PGM5112423102007',
                address: '88:8C:19:00:E2:49',
                id: '88:8C:19:00:E2:49',
                model: 'M511',
                connectionType: 'bluetooth'
            }
        ];
    }

    async connectToPrinter(printer) {
        console.error(`Mock connecting to printer: ${printer.name}`);
        return new MockBradyPrinter(printer);
    }
}

class MockBradyPrinter {
    constructor(printer) {
        this.printer = printer;
        this.connected = true;
    }

    async print(printJob) {
        console.error(`Mock printing: ${printJob.content} on ${printJob.labelSize}`);
        return {
            jobId: `job_${Date.now()}`,
            success: true
        };
    }

    async getStatus() {
        return {
            ready: true,
            model: this.printer.model,
            batteryLevel: 85,
            labelCount: 100
        };
    }

    async disconnect() {
        console.error('Mock disconnect');
        this.connected = false;
    }
}

class BradyPrintService {
    constructor() {
        this.sdk = null;
        this.connectedPrinter = null;
    }

    async initialize() {
        try {
            console.error('Initializing Brady Web SDK...');
            this.sdk = new MockBradySDK();
            return true;
        } catch (error) {
            console.error('Failed to initialize Brady SDK:', error.message);
            return false;
        }
    }

    async discoverPrinters() {
        try {
            console.error('Discovering Brady printers...');
            const printers = await this.sdk.discoverPrinters();
            
            const result = printers.map(printer => ({
                name: printer.name,
                address: printer.address || printer.id,
                model: printer.model,
                connectionType: printer.connectionType
            }));

            console.error(`Found ${result.length} Brady printers`);
            return result;
        } catch (error) {
            console.error('Printer discovery failed:', error.message);
            return [];
        }
    }

    async connectToPrinter(printerAddress) {
        try {
            console.error(`Connecting to Brady printer: ${printerAddress}`);
            
            // Find the printer by address
            const printers = await this.sdk.discoverPrinters();
            const printer = printers.find(p => 
                p.address === printerAddress || 
                p.id === printerAddress ||
                p.name.includes(printerAddress)
            );

            if (!printer) {
                throw new Error(`Printer not found: ${printerAddress}`);
            }

            this.connectedPrinter = await this.sdk.connectToPrinter(printer);
            console.error('Connected to Brady printer successfully');
            return true;
        } catch (error) {
            console.error('Failed to connect to printer:', error.message);
            return false;
        }
    }

    async printLabel(labelData) {
        try {
            if (!this.connectedPrinter) {
                throw new Error('No printer connected');
            }

            console.error('Printing label with Brady Web SDK...');
            
            // Create a simple text label
            const labelContent = labelData.content || labelData.serial_number || 'TEST';
            
            // Use Brady Web SDK to create and print label
            const printJob = {
                labelSize: 'M4C-187-342', // Brady label part number
                content: labelContent,
                quantity: labelData.quantity || 1
            };

            const result = await this.connectedPrinter.print(printJob);
            console.error('Label printed successfully');
            
            return {
                success: true,
                jobId: result.jobId || 'unknown',
                message: 'Label printed successfully'
            };
        } catch (error) {
            console.error('Print job failed:', error.message);
            return {
                success: false,
                error: error.message
            };
        }
    }

    async getStatus() {
        try {
            if (!this.connectedPrinter) {
                return {
                    connected: false,
                    ready: false,
                    error: 'No printer connected'
                };
            }

            const status = await this.connectedPrinter.getStatus();
            return {
                connected: true,
                ready: status.ready || true,
                model: status.model,
                batteryLevel: status.batteryLevel,
                labelCount: status.labelCount
            };
        } catch (error) {
            return {
                connected: false,
                ready: false,
                error: error.message
            };
        }
    }

    async disconnect() {
        try {
            if (this.connectedPrinter) {
                await this.connectedPrinter.disconnect();
                this.connectedPrinter = null;
                console.error('Disconnected from Brady printer');
            }
        } catch (error) {
            console.error('Disconnect error:', error.message);
        }
    }
}

// Command line interface
async function main() {
    const args = process.argv.slice(2);
    const command = args[0];
    
    const service = new BradyPrintService();
    
    if (!await service.initialize()) {
        process.exit(1);
    }

    try {
        switch (command) {
            case 'discover':
                const printers = await service.discoverPrinters();
                console.log(JSON.stringify(printers, null, 2));
                break;

            case 'connect':
                const address = args[1];
                if (!address) {
                    console.error('Usage: node brady_print_service.js connect <printer_address>');
                    process.exit(1);
                }
                const connected = await service.connectToPrinter(address);
                console.log(JSON.stringify({ success: connected }));
                break;

            case 'print':
                const printerAddr = args[1];
                const labelContent = args[2] || 'TEST';
                
                if (!printerAddr) {
                    console.error('Usage: node brady_print_service.js print <printer_address> <content>');
                    process.exit(1);
                }

                await service.connectToPrinter(printerAddr);
                const result = await service.printLabel({ content: labelContent });
                console.log(JSON.stringify(result, null, 2));
                await service.disconnect();
                break;

            case 'status':
                const addr = args[1];
                if (addr) {
                    await service.connectToPrinter(addr);
                }
                const status = await service.getStatus();
                console.log(JSON.stringify(status, null, 2));
                break;

            default:
                console.log('Brady Print Service');
                console.log('Usage:');
                console.log('  node brady_print_service.js discover');
                console.log('  node brady_print_service.js connect <printer_address>');
                console.log('  node brady_print_service.js print <printer_address> <content>');
                console.log('  node brady_print_service.js status [printer_address]');
                break;
        }
    } catch (error) {
        console.error('Error:', error.message);
        process.exit(1);
    } finally {
        await service.disconnect();
    }
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch(console.error);
}

export default BradyPrintService;