# Mower Tools

A desktop application for configuring and monitoring a lawn mower robot controller via USB serial connection. Provides both a graphical interface (Tkinter) and a command-line interface.

## Features

- Auto-detection of Mower controllers on available serial ports
- Read and write configuration parameters (blade encoder, hysteresis, choke, etc.)
- Real-time status monitoring (voltage, RPM, engine state, blade position)
- Track engine and mower runtime statistics
- Firmware version check and device reboot

## Requirements

- Python 3
- [pyserial](https://pypi.org/project/pyserial/)

```
pip install pyserial
```

## Usage

### GUI

```
python gui.py
```

### CLI

```
python cli.py version          # Get firmware version
python cli.py state            # Get device state
python cli.py get              # Read all parameters
python cli.py get 0            # Read a specific parameter
python cli.py set 0 100        # Write a parameter value
python cli.py reboot           # Reboot the device
```

By default, the CLI uses `/dev/tty.usbmodem14101`. Override with the `USB_PORT` environment variable:

```
USB_PORT=/dev/ttyUSB0 python cli.py get
```

## Generate installer
```
pyinstaller gui.py --onedir --windowed --noconfirm --name "Mower Tools" --icon=icon/icon.icns
```
