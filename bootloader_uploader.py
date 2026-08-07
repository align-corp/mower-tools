#!/usr/bin/env python3
"""
STM32G0B0CE Bootloader Firmware Uploader

Uploads firmware to the bootloader via USB CDC.

Usage:
    python bootloader_uploader.py <port> <firmware.bin>

Example:
    python bootloader_uploader.py /dev/tty.usbmodem14101 build/firmware.bin
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
APPLICATION_MAX_SIZE = 0x00037800        # 222KB application region (BANK1 only)
METADATA_OFFSET = APPLICATION_MAX_SIZE   # metadata page lands at 0x0803F800
METADATA_SIZE = 64
IMAGE_MAX_SIZE = APPLICATION_MAX_SIZE + FLASH_PAGE_SIZE

# Metadata magic. Used to recognise and read a descriptor
METADATA_MAGIC = 0x4D4F5745  # "MOWE"

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


# ============================================================
# Metadata
# ============================================================

def decode_metadata(blob: bytes) -> dict:
    """Decode the 64-byte descriptor produced by the firmware build.

    Mirrors app_metadata_t in the firmware's include/app_metadata.h. Read-only:
    this is for showing what an image or a device contains. Authoring the
    descriptor is the build's job, so that what gets flashed can be traced back
    to a commit no matter which tool wrote it.
    """
    magic, meta_version, major, minor, size, crc, timestamp = struct.unpack_from(
        '<7I', blob, 0)

    return {
        'magic': magic,
        'metadata_version': meta_version,
        'version': f"{major}.{minor}",
        'size': size,
        'crc32': crc,
        'timestamp': timestamp,
        # 8 ASCII hex chars, not NUL-terminated.
        'git_hash': blob[28:36].decode('ascii', errors='replace'),
    }


def print_metadata(meta: dict, prefix: str = ''):
    """Print a decoded descriptor as two aligned lines"""
    when = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(meta['timestamp']))
    print(f"{prefix}Version: {meta['version']}  "
          f"Commit: {meta['git_hash']}  Built: {when}")
    print(f"{prefix}Size: {meta['size']} bytes  CRC32: 0x{meta['crc32']:08X}")


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

        deadline = time.time() + timeout

        # Wait for sync word (device may be busy processing, e.g. erasing flash)
        sync_bytes = b''
        while len(sync_bytes) < 2 and time.time() < deadline:
            chunk = self.ser.read(2 - len(sync_bytes))
            if chunk:
                sync_bytes += chunk
        if len(sync_bytes) != 2:
            return None, None, None

        sync = struct.unpack('>H', sync_bytes)[0]
        if sync != SYNC_WORD:
            print(f"Warning: Invalid sync word: 0x{sync:04X}")
            return None, None, None

        # Response started - remaining reads use default serial timeout
        cmd_byte = self.ser.read(1)
        if len(cmd_byte) != 1:
            return None, None, None
        cmd = cmd_byte[0]

        status_byte = self.ser.read(1)
        if len(status_byte) != 1:
            return None, None, None
        status = status_byte[0]

        len_bytes = self.ser.read(2)
        if len(len_bytes) != 2:
            return None, None, None
        data_len = struct.unpack('<H', len_bytes)[0]

        data = b''
        if data_len > 0:
            data = self.ser.read(data_len)
            if len(data) != data_len:
                return None, None, None

        crc_bytes = self.ser.read(2)
        if len(crc_bytes) != 2:
            return None, None, None
        received_crc = struct.unpack('<H', crc_bytes)[0]

        crc_data = bytearray([cmd, status])
        crc_data.extend(len_bytes)
        crc_data.extend(data)
        calculated_crc = crc16_ccitt(bytes(crc_data))

        if received_crc != calculated_crc:
            print(f"Warning: CRC mismatch (rx=0x{received_crc:04X}, calc=0x{calculated_crc:04X})")
            return None, None, None

        return cmd, status, data

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

    def get_app_info(self) -> dict:
        """Read the descriptor of the application currently in flash.

        Returns None if the bootloader reports no valid application.
        """
        self.send_packet(CMD_GET_APP_INFO)
        cmd, status, data = self.receive_response()
        if (cmd != CMD_GET_APP_INFO or status != STATUS_OK
                or len(data) < METADATA_SIZE):
            return None
        return decode_metadata(data)

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

    def reset_mcu(self) -> bool:
        """Reset MCU (device will reboot and boot to app if valid)"""
        self.send_packet(CMD_RESET)
        # Device resets immediately; response may or may not arrive
        cmd, status, _ = self.receive_response(timeout=2.0)
        return cmd is None or (cmd == CMD_RESET and status == STATUS_OK)

    def upload_firmware(self, firmware_path: str) -> bool:
        """Upload a firmware image to the bootloader.

        The image is written verbatim. Everything the bootloader needs to
        validate it — size, CRC, version, provenance — is already inside the
        image, put there by the firmware build.
        """

        # Read firmware file
        path = Path(firmware_path)
        if not path.exists():
            print(f"Error: File not found: {firmware_path}")
            return False

        image = path.read_bytes()

        print(f"Firmware: {firmware_path}")
        print(f"Size: {len(image)} bytes ({len(image) / 1024:.1f} KB)")

        meta = self._read_image_metadata(image)
        if meta is None:
            return False
        print_metadata(meta)

        # Ping bootloader with retry logic
        print("\nChecking bootloader...")
        try:
            bootloader_ready = self.ping()
        except (serial.SerialException, PermissionError):
            bootloader_ready = False

        if not bootloader_ready:
            print("Bootloader not responding, requesting app to enter bootloader...")
            try:
                self.send_app_enter_bootloader()
            except (serial.SerialException, PermissionError):
                pass  # Device may already be rebooting

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
                except (serial.SerialException, PermissionError):
                    print(".", end='', flush=True)
                    continue

                try:
                    if self.ping():
                        print("\nBootloader ready!")
                        break
                except (serial.SerialException, PermissionError):
                    pass
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

        # Pad the tail of the image out to a whole page. Only the last page is
        # ever short: the metadata is 64 bytes at the start of it.
        padded = image + (b'\xFF' * (-len(image) % FLASH_PAGE_SIZE))
        num_pages = len(padded) // FLASH_PAGE_SIZE

        # Most of the image is the gap between the application and the metadata
        # page, filled with 0xFF by the build. Those pages already read 0xFF
        # after the erase above, so skipping them is a no-op that keeps upload
        # time proportional to the firmware rather than to the 224 KB image.
        blank_page = b'\xFF' * FLASH_PAGE_SIZE
        pages = [i for i in range(num_pages)
                 if padded[i * FLASH_PAGE_SIZE:(i + 1) * FLASH_PAGE_SIZE] != blank_page]

        skipped = num_pages - len(pages)
        print(f"\nWriting {len(pages)} pages ({skipped} blank pages skipped)...")

        # Ascending order matters: the metadata page is the last page of the
        # image, and it has to be written last. It is what the bootloader checks
        # to decide the application is complete, so an upload that dies partway
        # must leave it erased and the device refusing to boot a half-written
        # application.
        for count, i in enumerate(pages, start=1):
            address = APPLICATION_START + (i * FLASH_PAGE_SIZE)
            page_data = padded[i * FLASH_PAGE_SIZE:(i + 1) * FLASH_PAGE_SIZE]

            if not self.write_page(address, page_data):
                print(f"\nError: Failed to write page {count}/{len(pages)} "
                      f"at 0x{address:08X}")
                return False

            # Progress bar
            progress = count / len(pages)
            bar_width = 40
            filled = int(bar_width * progress)
            bar = '=' * filled + '-' * (bar_width - filled)
            print(f"\r[{bar}] {progress * 100:.0f}% ({count}/{len(pages)})",
                  end='', flush=True)

        print("\nFirmware written successfully!")

        # Verify
        print("\nVerifying CRC...")
        if not self.verify_app():
            print("Error: CRC verification failed!")
            return False
        print("Verification successful!")

        return True

    def _read_image_metadata(self, image: bytes) -> dict:
        """Validate the image carries a metadata page, and return it decoded.

        Rejecting the image here rather than after the erase matters: a build
        without the metadata page would flash cleanly and then fail to boot,
        leaving the device in the bootloader with no application.
        """
        if len(image) > IMAGE_MAX_SIZE:
            print(f"Error: Image too large: {len(image)} bytes "
                  f"(max {IMAGE_MAX_SIZE})")
            return None

        if len(image) < METADATA_OFFSET + METADATA_SIZE:
            print(f"Error: Image is {len(image)} bytes, too short to contain a "
                  f"metadata page at offset 0x{METADATA_OFFSET:X}.")
            print("       Expected a firmware.bin from a build that emits the "
                  ".app_metadata section.")
            return None

        meta = decode_metadata(image[METADATA_OFFSET:])
        if meta['magic'] != METADATA_MAGIC:
            print(f"Error: No metadata found at offset 0x{METADATA_OFFSET:X} "
                  f"(magic 0x{meta['magic']:08X}).")
            print("       This image was not produced by a build that embeds "
                  "application metadata.")
            return None

        if meta['size'] == 0 or meta['size'] > APPLICATION_MAX_SIZE:
            print(f"Error: Metadata reports an implausible size "
                  f"({meta['size']} bytes); the image looks unpatched.")
            return None

        return meta


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Upload firmware to STM32G0B0CE bootloader via USB CDC'
    )
    parser.add_argument('port', help='Serial port (e.g., /dev/tty.usbmodem14101, COM3)')
    parser.add_argument('firmware', help='Firmware binary file (.bin)')
    parser.add_argument('--no-reset', action='store_true',
                        help='Do not reset MCU after upload')
    parser.add_argument('--baudrate', '-b', type=int, default=115200,
                        help='Serial baudrate (default: 115200)')

    args = parser.parse_args()

    # Create uploader
    uploader = BootloaderUploader(args.port, args.baudrate)

    if not uploader.connect():
        return 1

    try:
        # Upload firmware
        if not uploader.upload_firmware(args.firmware):
            return 1

        # Report what the bootloader now sees, read back from the device
        # rather than from the file we just sent.
        info = uploader.get_app_info()
        if info:
            print("\nApplication on device:")
            print_metadata(info, prefix='  ')

        # Reset MCU to boot into app
        if not args.no_reset:
            print("\nResetting MCU...")
            uploader.reset_mcu()
            print("Reset sent. Device booting to application.")
        else:
            print("\nUpload complete! Reset device to launch application.")

        return 0
    finally:
        uploader.disconnect()


if __name__ == '__main__':
    sys.exit(main())
