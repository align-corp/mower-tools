#!/usr/bin/env python3
"""
USB Protocol Client for Mower Controller

Requirements:
    pip install pyserial

Serial port:
    set environment variable USB_PORT

Usage:
    python usb_protocol.py get <param_id>          # Get parameter value
    python usb_protocol.py set <param_id> <value>  # Set parameter value
    python usb_protocol.py version                 # Get firmware version
    python usb_protocol.py state                   # Get device state (voltage, RPM, engine)
    python usb_protocol.py reboot                  # Reboot device
"""

import usb_protocol as u
import sys
import time
import serial

PORT = '/dev/tty.usbmodem14101'  # Common for macOS

def main():
    """Command-line interface"""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nParameter IDs:")
        for pid, name in u.PARAM_NAMES.items():
            print(f"  {pid}: {name}")
        sys.exit(1)

    command = sys.argv[1].lower()

    # Allow port override via environment variable
    import os
    port = os.environ.get('USB_PORT', PORT)

    try:
        client = u.UsbProtocolClient(port)

        if command == 'get':
            if len(sys.argv) < 3:
                for p in u.PARAM_NAMES:
                    value = client.get_param(p)
                    param_name = u.PARAM_NAMES.get(p, f"PARAM_{p}")
                    print(f"{param_name} (ID {p}) = {value}")
                    time.sleep(0.1)
            else:
                param_id = int(sys.argv[2])
                value = client.get_param(param_id)
                param_name = u.PARAM_NAMES.get(param_id, f"PARAM_{param_id}")
                print(f"{param_name} (ID {param_id}) = {value}")

        elif command == 'set':
            if len(sys.argv) < 4:
                print("Usage: python usb_protocol.py set <param_id> <value>")
                sys.exit(1)

            param_id = int(sys.argv[2])
            value = int(sys.argv[3])
            client.set_param(param_id, value)
            param_name = u.PARAM_NAMES.get(param_id, f"PARAM_{param_id}")
            print(f"{param_name} (ID {param_id}) set to {value}")

        elif command == 'version':
            major, minor = client.get_version()
            print(f"Firmware version: {major}.{minor}")

        elif command == 'state':
            state = client.get_state()
            for i, s in u.STATUS_NAMES.items():
                print(f"{s}: {state[i]}")

        elif command == 'reboot':
            client.reboot()
            print("Device is rebooting...")

        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            sys.exit(1)

    except serial.SerialException as e:
        print(f"Serial port error: {e}")
        print(f"Make sure device is connected to {port}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        if 'client' in locals():
            client.close()


if __name__ == '__main__':
    main()
