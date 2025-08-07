#!/usr/bin/env python3
"""
Centralized Brady M511 Connection Management

This module provides a single, reliable way to connect to Brady M511 printers
that ensures the LED indicator behavior works correctly (goes solid during connection).

Based on the working connection method that successfully makes the LED go solid.
"""

import asyncio
import logging
from typing import Optional, Tuple
from bleak import BleakClient

logger = logging.getLogger(__name__)

# Brady M511 Protocol Constants
BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"

async def connect_to_brady(device_address: str, timeout: float = 15.0) -> Tuple[Optional[BleakClient], bool]:
    """
    Connect to Brady M511 printer using the proven working method
    
    This method ensures the LED indicator goes SOLID during connection,
    matching the behavior of the Android app and working test scripts.
    
    Args:
        device_address: Bluetooth MAC address of Brady M511
        timeout: Connection timeout in seconds
        
    Returns:
        Tuple of (client, success) where:
        - client: BleakClient instance if connected, None if failed
        - success: True if connection established, False otherwise
    """
    client = None
    try:
        logger.info(f"Connecting to Brady M511 at {device_address} (timeout: {timeout}s)")
        
        # Use the proven working connection method
        client = BleakClient(device_address, timeout=timeout)
        
        # Simple connection that makes LED go solid
        await client.connect()
        
        if client.is_connected:
            logger.info(f"✅ Brady M511 connected successfully (LED should be SOLID)")
            return client, True
        else:
            logger.error("Brady M511 connection failed - client reports not connected")
            return None, False
            
    except Exception as e:
        logger.error(f"Brady M511 connection error: {e}")
        if client:
            try:
                await client.disconnect()
            except:
                pass
        return None, False

async def disconnect_from_brady(client: BleakClient) -> bool:
    """
    Disconnect from Brady M511 printer
    
    Args:
        client: Connected BleakClient instance
        
    Returns:
        True if disconnected successfully, False otherwise
    """
    try:
        if client and client.is_connected:
            logger.info("Disconnecting from Brady M511")
            await client.disconnect()
            logger.info("✅ Brady M511 disconnected (LED should return to blinking)")
            return True
        return False
    except Exception as e:
        logger.error(f"Error disconnecting from Brady M511: {e}")
        return False

async def test_brady_connection(device_address: str, hold_duration: float = 5.0) -> bool:
    """
    Test Brady M511 connection with LED observation period
    
    This function connects to the printer, holds the connection for the specified
    duration to observe LED behavior, then disconnects.
    
    Args:
        device_address: Bluetooth MAC address of Brady M511  
        hold_duration: How long to hold connection (seconds) for LED observation
        
    Returns:
        True if connection test was successful, False otherwise
    """
    logger.info(f"Starting Brady M511 connection test (hold for {hold_duration}s)")
    
    client, connected = await connect_to_brady(device_address)
    
    if not connected:
        return False
    
    try:
        # Hold connection for LED observation
        logger.info(f"Holding Brady M511 connection for {hold_duration}s (observe LED)")
        await asyncio.sleep(hold_duration)
        
        # Disconnect
        await disconnect_from_brady(client)
        
        logger.info("✅ Brady M511 connection test completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error during Brady M511 connection test: {e}")
        try:
            await disconnect_from_brady(client)
        except:
            pass
        return False

def test_brady_connection_sync(device_address: str, hold_duration: float = 5.0) -> bool:
    """
    Synchronous wrapper for Brady M511 connection test
    
    This function works in both sync and async contexts by using a thread-based approach
    when an event loop is already running.
    
    Args:
        device_address: Bluetooth MAC address of Brady M511
        hold_duration: How long to hold connection (seconds) for LED observation
        
    Returns:
        True if connection test was successful, False otherwise
    """
    try:
        # Check if there's already a running event loop
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, use a thread to run the connection test
            logger.info("Running Brady connection test in thread (async context detected)")
            
            import threading
            import concurrent.futures
            
            def run_in_thread():
                # Create new event loop in thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(test_brady_connection(device_address, hold_duration))
                finally:
                    new_loop.close()
            
            # Run in thread with timeout
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result(timeout=hold_duration + 30)  # Add buffer to hold_duration
                
        except RuntimeError:
            # No running loop, create new one (original behavior)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(test_brady_connection(device_address, hold_duration))
            finally:
                loop.close()
    except Exception as e:
        logger.error(f"Error in sync Brady connection test: {e}")
        return False

# Default Brady M511 for convenience
def test_default_brady_connection(hold_duration: float = 5.0) -> bool:
    """Test connection to the default Brady M511 device"""
    return test_brady_connection_sync(BRADY_MAC, hold_duration)