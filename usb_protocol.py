#!/usr/bin/env python3

import serial
import struct
import time

# Serial port

# Protocol constants
USB_PROTO_HEADER = 0xA1

# Command codes
USB_CMD_GET_PARAM = 0x01
USB_CMD_SET_PARAM = 0x02
USB_CMD_GET_STATE = 0x03
USB_CMD_GET_VERSION = 0x04
USB_CMD_REBOOT = 0x05
USB_CMD_RESPONSE_OK = 0x80
USB_CMD_RESPONSE_ERR = 0x81

# Error codes
USB_ERR_INVALID_CMD = 0x01
USB_ERR_INVALID_CRC = 0x02
USB_ERR_INVALID_PARAM = 0x03
USB_ERR_PARAM_ACCESS = 0x04
USB_ERR_INVALID_LENGTH = 0x05

# Parameter names for reference
PARAM_NAMES = {
    0: "Blade encoder min",
    1: "Blade encoder max",
    2: "Blade encoder now",
    3: "Blade hysteresis start",
    4: "Blade hysteresis stop",
    5: "Blade setting bitmask",
    6: "Time engine [min]",
    7: "Time mower [min]",
    8: "Engine Choke CH"
}

STATUS_NAMES = {
    0: "Voltage",
    1: "RPM",
    2: "Engine ON",
    3: "Blade desired position",
    4: "Blade actual position"
}

# PARAM_BLADE_BITMASK bit definitions
BLADE_BITMASK_ENCODER_SELECT = 0x01  # bit 0: 0=Encoder A, 1=Encoder B

ERROR_NAMES = {
    USB_ERR_INVALID_CMD: "Invalid command",
    USB_ERR_INVALID_CRC: "Invalid checksum",
    USB_ERR_INVALID_PARAM: "Invalid parameter ID",
    USB_ERR_PARAM_ACCESS: "Parameter access failed",
    USB_ERR_INVALID_LENGTH: "Invalid payload length"
}


class UsbProtocolClient:
    def __init__(self, port, baudrate=115200, timeout=1.0):
        """
        Initialize USB protocol client

        Args:
            port: Serial port device
            baudrate: Baud rate (default 115200)
            timeout: Read timeout in seconds
        """
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        time.sleep(0.1)  # Wait for connection to stabilize

    def _calculate_checksum(self, cmd, payload):
        """Calculate protocol checksum (ABUS-style)"""
        crc = USB_PROTO_HEADER + cmd + len(payload)
        for b in payload:
            crc += b
        crc ^= 0xFFFF
        return crc & 0xFFFF

    def _send_packet(self, cmd, payload):
        """Send a protocol packet"""
        packet = bytearray([USB_PROTO_HEADER, cmd, len(payload)])
        packet.extend(payload)
        crc = self._calculate_checksum(cmd, payload)
        packet.extend(struct.pack('<H', crc))  # Little-endian 16-bit
        self.ser.write(packet)

    def _receive_packet(self, timeout=1.0):
        """Receive and parse a protocol packet"""
        start = time.time()

        # Wait for header
        while time.time() - start < timeout:
            b = self.ser.read(1)
            if len(b) == 1 and b[0] == USB_PROTO_HEADER:
                break
        else:
            raise TimeoutError("No response header received")

        # Read cmd and length
        data = self.ser.read(2)
        if len(data) != 2:
            raise RuntimeError("Incomplete packet (cmd/len)")

        cmd, length = data[0], data[1]

        # Read payload + checksum (2 bytes)
        data = self.ser.read(length + 2)
        if len(data) != length + 2:
            raise RuntimeError("Incomplete packet (payload/checksum)")

        payload = data[:length]
        crc_received = struct.unpack('<H', data[length:length+2])[0]

        # Validate checksum
        crc_calculated = self._calculate_checksum(cmd, payload)
        if crc_received != crc_calculated:
            raise RuntimeError(f"Checksum mismatch: expected {crc_calculated:04X}, got {crc_received:04X}")

        return cmd, payload

    def get_param(self, param_id):
        """
        Get parameter value

        Args:
            param_id: Parameter ID

        Returns:
            Parameter value (int32_t)
        """
        if param_id < 0 or param_id >= len(PARAM_NAMES):
            raise ValueError(f"Invalid parameter ID: {param_id}")

        # Send request
        self._send_packet(USB_CMD_GET_PARAM, [param_id])

        # Receive response
        cmd, payload = self._receive_packet()

        # Check for error
        if cmd == USB_CMD_RESPONSE_ERR:
            error_code = payload[0] if len(payload) > 0 else 0
            error_msg = ERROR_NAMES.get(error_code, f"Unknown error {error_code}")
            raise RuntimeError(f"Error: {error_msg}")

        # Validate response
        if cmd != USB_CMD_RESPONSE_OK or len(payload) != 5:
            raise RuntimeError(f"Invalid response: cmd={cmd:02X}, len={len(payload)}")

        # Parse response: [PARAM_ID] [VALUE_0] [VALUE_1] [VALUE_2] [VALUE_3]
        received_id = payload[0]
        if received_id != param_id:
            raise RuntimeError(f"Parameter ID mismatch: expected {param_id}, got {received_id}")

        value = struct.unpack('<i', payload[1:5])[0]  # int32_t little-endian
        return value

    def set_param(self, param_id, value):
        """
        Set parameter value

        Args:
            param_id: Parameter ID
            value: Parameter value (int32_t)

        Returns:
            True on success
        """
        if param_id < 0 or param_id >= len(PARAM_NAMES):
            raise ValueError(f"Invalid parameter ID: {param_id}")

        # Build payload: [PARAM_ID] [VALUE_0] [VALUE_1] [VALUE_2] [VALUE_3]
        payload = bytearray([param_id])
        payload.extend(struct.pack('<i', value))  # int32_t little-endian

        # Send request
        self._send_packet(USB_CMD_SET_PARAM, payload)

        # Receive response
        cmd, payload = self._receive_packet()

        # Check for error
        if cmd == USB_CMD_RESPONSE_ERR:
            error_code = payload[0] if len(payload) > 0 else 0
            error_msg = ERROR_NAMES.get(error_code, f"Unknown error {error_code}")
            raise RuntimeError(f"Error: {error_msg}")

        # Validate response
        if cmd != USB_CMD_RESPONSE_OK or len(payload) != 1:
            raise RuntimeError(f"Invalid response: cmd={cmd:02X}, len={len(payload)}")

        return True

    def get_version(self):
        """
        Get firmware version

        Returns:
            Tuple of (major, minor) version numbers
        """
        # Send request
        self._send_packet(USB_CMD_GET_VERSION, [])

        # Receive response
        cmd, payload = self._receive_packet()

        # Check for error
        if cmd == USB_CMD_RESPONSE_ERR:
            error_code = payload[0] if len(payload) > 0 else 0
            error_msg = ERROR_NAMES.get(error_code, f"Unknown error {error_code}")
            raise RuntimeError(f"Error: {error_msg}")

        # Validate response
        if cmd != USB_CMD_RESPONSE_OK or len(payload) != 2:
            raise RuntimeError(f"Invalid response: cmd={cmd:02X}, len={len(payload)}")

        major, minor = payload[0], payload[1]
        return (major, minor)

    def get_state(self):
        """
        Get device state (voltage, RPM, engine status)

        Returns:
            Dictionary with keys: 'voltage', 'rpm', 'engine_on'
        """
        # Send request
        self._send_packet(USB_CMD_GET_STATE, [])

        # Receive response
        cmd, payload = self._receive_packet()

        # Check for error
        if cmd == USB_CMD_RESPONSE_ERR:
            error_code = payload[0] if len(payload) > 0 else 0
            error_msg = ERROR_NAMES.get(error_code, f"Unknown error {error_code}")
            raise RuntimeError(f"Error: {error_msg}")

        # Validate response
        if cmd != USB_CMD_RESPONSE_OK or len(payload) != 9:
            raise RuntimeError(f"Invalid response: cmd={cmd:02X}, len={len(payload)}")

        # Parse response: [VOLT_L] [VOLT_H] [RPM_L] [RPM_H] [ENGINE_ON]
        shorts = struct.unpack('<HHBhh', payload) # H=unsigned short, h=signed short, B=unsigned byte
        voltage_mv = shorts[0]
        rpm = shorts[1]
        engine_on = shorts[2]
        blade_des_pos = shorts[3]
        blade_pos = shorts[4]

        return {
            0: voltage_mv / 1000.0,  # Convert to volts
            1: rpm,
            2: engine_on,
            3: blade_des_pos,
            4: blade_pos
        }

    def reboot(self):
        """
        Reboot device

        Note: Device will disconnect after this command
        """
        # Send request
        self._send_packet(USB_CMD_REBOOT, [])

        # Try to receive response (device will reboot quickly)
        try:
            cmd, payload = self._receive_packet(timeout=0.5)

            # Check for error
            if cmd == USB_CMD_RESPONSE_ERR:
                error_code = payload[0] if len(payload) > 0 else 0
                error_msg = ERROR_NAMES.get(error_code, f"Unknown error {error_code}")
                raise RuntimeError(f"Error: {error_msg}")

            # Validate response
            if cmd != USB_CMD_RESPONSE_OK:
                raise RuntimeError(f"Invalid response: cmd={cmd:02X}")

        except (TimeoutError, serial.SerialException):
            # Expected - device is rebooting
            pass

        return True

    def close(self):
        """Close serial connection"""
        if self.ser and self.ser.is_open:
            self.ser.close()

