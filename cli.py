#!/usr/bin/env python3
"""
USB Protocol Client for Mower Controller

Requirements:
    pip install pyserial

Serial port:
    set environment variable USB_PORT

Usage:
    python cli.py get [param_id]          # Get parameter value (all if no ID)
    python cli.py set <param_id> <value>  # Set parameter value
    python cli.py version                 # Get firmware version
    python cli.py state                   # Get device state (voltage, RPM, engine)
    python cli.py reboot                  # Reboot device

Options:
    --fram <0|1>                          # Select FRAM revision (default: latest)
"""

import usb_protocol as u
import sys
import time
import serial

PORT = '/dev/tty.usbmodem14101'  # Common for macOS

def main():
    """Command-line interface"""
    # Parse optional --fram flag
    args = sys.argv[:]
    fram_revision = u.LATEST_REVISION
    if '--fram' in args:
        idx = args.index('--fram')
        fram_revision = int(args[idx + 1])
        del args[idx:idx + 2]

    if len(args) < 2:
        print(__doc__)
        print(f"\nParameter IDs (FRAM revision {fram_revision}):")
        for pid, name in u.PARAM_REVISIONS[fram_revision].items():
            print(f"  {pid}: {name}")
        sys.exit(1)

    command = args[1].lower()

    # Allow port override via environment variable
    import os
    port = os.environ.get('USB_PORT', PORT)

    try:
        client = u.UsbProtocolClient(port)
        client.param_revision = fram_revision

        if command == 'get':
            if len(args) < 3:
                for p in client.param_names:
                    value = client.get_param(p)
                    param_name = client.param_names.get(p, f"PARAM_{p}")
                    print(f"{param_name} (ID {p}) = {value}")
                    time.sleep(0.1)
            else:
                param_id = int(args[2])
                value = client.get_param(param_id)
                param_name = client.param_names.get(param_id, f"PARAM_{param_id}")
                print(f"{param_name} (ID {param_id}) = {value}")

        elif command == 'set':
            if len(args) < 4:
                print("Usage: python cli.py set <param_id> <value>")
                sys.exit(1)

            param_id = int(args[2])
            value = int(args[3])
            client.set_param(param_id, value)
            param_name = client.param_names.get(param_id, f"PARAM_{param_id}")
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
