from bleak import BleakClient, BleakScanner

async def main():
    devices = await BleakScanner.discover()
    for d in devices:
        print(d)

    # Replace with your printer's MAC
    address = "88:8C:19:00:E2:49"
    async with BleakClient(address) as client:
        print("Connected:", client.is_connected)

import asyncio
asyncio.run(main())

