#!/usr/bin/env python3
"""
STM32G0B0CE Bootloader Firmware Uploader

Uploads firmware to the bootloader via USB CDC.

Usage:
    python bootloader_uploader.py <port> <firmware.bin>

Example:
    python bootloader_uploader.py /dev/tty.usbmodem14101 .pio/build/align/firmware.bin
    python bootloader_uploader.py COM3 firmware.bin
"""

import sys
import time
import struct
import argparse
from pathlib import Path

try:
    import serial
except ImportError:
    print("Error: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

# ============================================================
# Protocol Constants
# ============================================================

SYNC_WORD = 0xAA55
FLASH_PAGE_SIZE = 2048

# Application memory layout
APPLICATION_START = 0x08008000
APPLICATION_MAX_SIZE = 0x00037800  # 222KB (BANK1 only)
METADATA_ADDR = 0x0803F800

# Metadata magic
METADATA_MAGIC = 0x4D4F5745  # "MOWE"
METADATA_VERSION = 1

# Application protocol constants (for entering bootloader from running app)
APP_PROTO_HEADER = 0xA1
APP_CMD_ENTER_BOOTLOADER = 0x06

# Bootloader command codes
CMD_PING = 0x00
CMD_GET_VERSION = 0x01
CMD_GET_APP_INFO = 0x02
CMD_ERASE_APP = 0x10
CMD_WRITE_PAGE = 0x11
CMD_VERIFY_APP = 0x12
CMD_START_APP = 0x20
CMD_STAY_IN_BOOT = 0x21
CMD_RESET = 0xFE
CMD_GET_STATUS = 0xFF

# Status codes
STATUS_OK = 0x00
STATUS_ERROR = 0x01
STATUS_BUSY = 0x02
STATUS_INVALID_CMD = 0x03
STATUS_INVALID_CRC = 0x04
STATUS_FLASH_ERROR = 0x05
STATUS_VERIFY_ERROR = 0x06
STATUS_INVALID_ADDR = 0x07
STATUS_INVALID_SIZE = 0x08
STATUS_NO_APP = 0x09

STATUS_NAMES = {
    STATUS_OK: "OK",
    STATUS_ERROR: "Error",
    STATUS_BUSY: "Busy",
    STATUS_INVALID_CMD: "Invalid Command",
    STATUS_INVALID_CRC: "CRC Mismatch",
    STATUS_FLASH_ERROR: "Flash Error",
    STATUS_VERIFY_ERROR: "Verification Failed",
    STATUS_INVALID_ADDR: "Invalid Address",
    STATUS_INVALID_SIZE: "Invalid Size",
    STATUS_NO_APP: "No Application"
}


# ============================================================
# CRC Functions
# ============================================================

def crc16_ccitt(data: bytes) -> int:
    """Calculate CRC-16-CCITT"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def crc32(data: bytes) -> int:
    """Calculate CRC-32 (standard, same as STM32 hardware CRC with config)"""
    import binascii
    return binascii.crc32(data) & 0xFFFFFFFF


# ============================================================
# Bootloader Uploader Class
# ============================================================

class BootloaderUploader:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 5.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def connect(self) -> bool:
        """Connect to bootloader"""
        print(f"Connecting to {self.port}...")
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout
            )
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            print("Connected!")
            return True
        except serial.SerialException as e:
            print(f"Error connecting: {e}")
            return False

    def disconnect(self):
        """Disconnect from bootloader"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Disconnected")

    def send_packet(self, cmd: int, data: bytes = b''):
        """Send a command packet"""
        packet = bytearray()

        # Sync word (big-endian)
        packet.extend(struct.pack('>H', SYNC_WORD))

        # Command
        packet.append(cmd)

        # Length (little-endian)
        packet.extend(struct.pack('<H', len(data)))

        # Data
        if data:
            packet.extend(data)

        # CRC16 over cmd + len + data
        crc_data = bytearray([cmd])
        crc_data.extend(struct.pack('<H', len(data)))
        crc_data.extend(data)
        crc = crc16_ccitt(bytes(crc_data))
        packet.extend(struct.pack('<H', crc))

        self.ser.write(packet)

    def receive_response(self, timeout: float = None) -> tuple:
        """Receive a response packet. Returns (cmd, status, data) or (None, None, None)"""
        if timeout is None:
            timeout = self.timeout

        old_timeout = self.ser.timeout
        self.ser.timeout = timeout

        try:
            # Read sync word
            sync_bytes = self.ser.read(2)
            if len(sync_bytes) != 2:
                return None, None, None

            sync = struct.unpack('>H', sync_bytes)[0]
            if sync != SYNC_WORD:
                print(f"Warning: Invalid sync word: 0x{sync:04X}")
                return None, None, None

            # Read command
            cmd_byte = self.ser.read(1)
            if len(cmd_byte) != 1:
                return None, None, None
            cmd = cmd_byte[0]

            # Read status
            status_byte = self.ser.read(1)
            if len(status_byte) != 1:
                return None, None, None
            status = status_byte[0]

            # Read length
            len_bytes = self.ser.read(2)
            if len(len_bytes) != 2:
                return None, None, None
            data_len = struct.unpack('<H', len_bytes)[0]

            # Read data
            data = b''
            if data_len > 0:
                data = self.ser.read(data_len)
                if len(data) != data_len:
                    return None, None, None

            # Read and verify CRC
            crc_bytes = self.ser.read(2)
            if len(crc_bytes) != 2:
                return None, None, None
            received_crc = struct.unpack('<H', crc_bytes)[0]

            # Verify CRC
            crc_data = bytearray([cmd, status])
            crc_data.extend(len_bytes)
            crc_data.extend(data)
            calculated_crc = crc16_ccitt(bytes(crc_data))

            if received_crc != calculated_crc:
                print(f"Warning: CRC mismatch (rx=0x{received_crc:04X}, calc=0x{calculated_crc:04X})")
                return None, None, None

            return cmd, status, data
        finally:
            self.ser.timeout = old_timeout

    def send_app_enter_bootloader(self):
        """Send enter bootloader command to running application (different protocol)"""
        # App protocol: header(1) + cmd(1) + len(1) + payload + checksum(2)
        cmd = APP_CMD_ENTER_BOOTLOADER
        length = 0

        # App uses additive checksum XOR 0xFFFF (not CRC16)
        checksum = (APP_PROTO_HEADER + cmd + length) ^ 0xFFFF

        # Build packet
        packet = bytearray([APP_PROTO_HEADER, cmd, length])
        packet.extend(struct.pack('<H', checksum))

        self.ser.write(packet)
        # Don't wait for response - device will reboot

    def ping(self) -> bool:
        """Send ping to check bootloader is alive"""
        self.send_packet(CMD_PING)
        cmd, status, _ = self.receive_response(timeout=2.0)
        return cmd == CMD_PING and status == STATUS_OK

    def get_version(self) -> tuple:
        """Get bootloader version. Returns (major, minor) or None"""
        self.send_packet(CMD_GET_VERSION)
        cmd, status, data = self.receive_response()
        if cmd == CMD_GET_VERSION and status == STATUS_OK and len(data) >= 2:
            return data[0], data[1]
        return None

    def stay_in_boot(self) -> bool:
        """Tell bootloader to stay in boot mode (disable auto-boot)"""
        self.send_packet(CMD_STAY_IN_BOOT)
        cmd, status, _ = self.receive_response()
        return cmd == CMD_STAY_IN_BOOT and status == STATUS_OK

    def erase_app(self) -> bool:
        """Erase application area"""
        self.send_packet(CMD_ERASE_APP)
        # Erase takes time, use longer timeout
        cmd, status, _ = self.receive_response(timeout=30.0)
        return cmd == CMD_ERASE_APP and status == STATUS_OK

    def write_page(self, address: int, data: bytes) -> bool:
        """Write a flash page"""
        if len(data) != FLASH_PAGE_SIZE:
            print(f"Error: Page data must be {FLASH_PAGE_SIZE} bytes")
            return False

        # Pack address + data
        payload = struct.pack('<I', address) + data
        self.send_packet(CMD_WRITE_PAGE, payload)

        cmd, status, _ = self.receive_response(timeout=5.0)
        if cmd != CMD_WRITE_PAGE:
            return False
        if status != STATUS_OK:
            print(f"Write failed at 0x{address:08X}: {STATUS_NAMES.get(status, 'Unknown')}")
            return False
        return True

    def verify_app(self) -> bool:
        """Verify application CRC"""
        self.send_packet(CMD_VERIFY_APP)
        cmd, status, _ = self.receive_response(timeout=30.0)
        return cmd == CMD_VERIFY_APP and status == STATUS_OK

    def start_app(self) -> bool:
        """Start application"""
        self.send_packet(CMD_START_APP)
        cmd, status, _ = self.receive_response(timeout=2.0)
        return cmd == CMD_START_APP and status == STATUS_OK

    def upload_firmware(self, firmware_path: str, app_version: tuple = (0, 1)) -> bool:
        """Upload firmware file to bootloader"""

        # Read firmware file
        path = Path(firmware_path)
        if not path.exists():
            print(f"Error: File not found: {firmware_path}")
            return False

        firmware_data = path.read_bytes()
        firmware_size = len(firmware_data)

        print(f"Firmware: {firmware_path}")
        print(f"Size: {firmware_size} bytes ({firmware_size / 1024:.1f} KB)")

        if firmware_size > APPLICATION_MAX_SIZE:
            print(f"Error: Firmware too large (max {APPLICATION_MAX_SIZE} bytes)")
            return False

        # Calculate CRC32 of firmware
        firmware_crc = crc32(firmware_data)
        print(f"CRC32: 0x{firmware_crc:08X}")

        # Ping bootloader with retry logic
        print("\nChecking bootloader...")
        if not self.ping():
            print("Bootloader not responding, requesting app to enter bootloader...")
            self.send_app_enter_bootloader()

            # Retry with timeout
            start_time = time.time()
            timeout_seconds = 10.0
            retry_interval = 1.0

            while time.time() - start_time < timeout_seconds:
                time.sleep(retry_interval)

                # Reconnect (device may have re-enumerated)
                try:
                    self.ser.close()
                    self.ser = serial.Serial(
                        port=self.port,
                        baudrate=self.baudrate,
                        timeout=self.timeout,
                        write_timeout=self.timeout
                    )
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except serial.SerialException:
                    print(".", end='', flush=True)
                    continue

                if self.ping():
                    print("\nBootloader ready!")
                    break
                print(".", end='', flush=True)
            else:
                print("\nError: Bootloader not responding after 10 seconds")
                return False

        # Get version
        version = self.get_version()
        if version:
            print(f"Bootloader version: {version[0]}.{version[1]}")

        # Stay in boot mode
        print("Staying in bootloader mode...")
        if not self.stay_in_boot():
            print("Warning: Could not set stay-in-boot flag")

        # Erase application
        print("Erasing application area...")
        if not self.erase_app():
            print("Error: Failed to erase application")
            return False
        print("Erase complete")

        # Pad firmware to page boundary
        padded_size = ((firmware_size + FLASH_PAGE_SIZE - 1) // FLASH_PAGE_SIZE) * FLASH_PAGE_SIZE
        padded_data = firmware_data + (b'\xFF' * (padded_size - firmware_size))

        # Write firmware pages
        num_pages = padded_size // FLASH_PAGE_SIZE
        print(f"\nWriting {num_pages} pages...")

        for i in range(num_pages):
            address = APPLICATION_START + (i * FLASH_PAGE_SIZE)
            page_data = padded_data[i * FLASH_PAGE_SIZE:(i + 1) * FLASH_PAGE_SIZE]

            if not self.write_page(address, page_data):
                print(f"\nError: Failed to write page {i + 1}/{num_pages}")
                return False

            # Progress bar
            progress = (i + 1) / num_pages
            bar_width = 40
            filled = int(bar_width * progress)
            bar = '=' * filled + '-' * (bar_width - filled)
            print(f"\r[{bar}] {progress * 100:.0f}% ({i + 1}/{num_pages})", end='', flush=True)

        print("\nFirmware written successfully!")

        # Write metadata
        print("\nWriting metadata...")
        metadata = self._create_metadata(firmware_size, firmware_crc, app_version)

        # Pad metadata to page size
        metadata_padded = metadata + (b'\xFF' * (FLASH_PAGE_SIZE - len(metadata)))

        if not self.write_page(METADATA_ADDR, metadata_padded):
            print("Error: Failed to write metadata")
            return False
        print("Metadata written")

        # Verify
        print("\nVerifying CRC...")
        if not self.verify_app():
            print("Error: CRC verification failed!")
            return False
        print("Verification successful!")

        return True

    def _create_metadata(self, app_size: int, app_crc: int, version: tuple) -> bytes:
        """Create metadata structure"""
        # AppMetadata structure (64 bytes)
        metadata = struct.pack('<I', METADATA_MAGIC)       # magic
        metadata += struct.pack('<I', METADATA_VERSION)    # metadata_version
        metadata += struct.pack('<I', version[0])          # app_version_major
        metadata += struct.pack('<I', version[1])          # app_version_minor
        metadata += struct.pack('<I', app_size)            # app_size
        metadata += struct.pack('<I', app_crc)             # app_crc32
        metadata += struct.pack('<I', int(time.time()))    # build_timestamp
        metadata += b'\x00' * 8                            # git_hash (placeholder)
        metadata += b'\x00' * 28                           # reserved

        assert len(metadata) == 64, f"Metadata size mismatch: {len(metadata)}"
        return metadata


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Upload firmware to STM32G0B0CE bootloader via USB CDC'
    )
    parser.add_argument('port', help='Serial port (e.g., /dev/tty.usbmodem14101, COM3)')
    parser.add_argument('firmware', help='Firmware binary file (.bin)')
    parser.add_argument('--version', '-v', default='0.1',
                        help='Application version (e.g., 1.2)')
    parser.add_argument('--start', '-s', action='store_true',
                        help='Start application after upload')
    parser.add_argument('--baudrate', '-b', type=int, default=115200,
                        help='Serial baudrate (default: 115200)')

    args = parser.parse_args()

    # Parse version
    try:
        version_parts = args.version.split('.')
        version = (int(version_parts[0]),
                   int(version_parts[1]) if len(version_parts) > 1 else 0)
    except ValueError:
        print(f"Error: Invalid version format: {args.version}")
        return 1

    # Create uploader
    uploader = BootloaderUploader(args.port, args.baudrate)

    if not uploader.connect():
        return 1

    try:
        # Upload firmware
        if not uploader.upload_firmware(args.firmware, version):
            return 1

        # Start application if requested
        if args.start:
            print("\nStarting application...")
            if uploader.start_app():
                print("Application started!")
            else:
                print("Warning: Could not start application (might have started anyway)")
        else:
            print("\nUpload complete! Reset device or use --start to launch application.")

        return 0
    finally:
        uploader.disconnect()


if __name__ == '__main__':
    sys.exit(main())
