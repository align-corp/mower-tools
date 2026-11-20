# Mower Tools

A desktop application for configuring and monitoring a lawn mower robot controller via USB serial connection. Provides both a graphical interface (Tkinter) and a command-line interface.

## Features

- Auto-detection of Mower controllers on available serial ports
- Read and write configuration parameters (blade encoder, hysteresis, choke, etc.)
- Real-time status monitoring (voltage, RPM, engine state, blade position)
- Track engine and mower runtime statistics
- Firmware version check and device reboot

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.11 and the dependencies automatically)

```
uv sync
```

## Usage

### GUI

```
uv run gui.py
```

### CLI

```
uv run cli.py version          # Get firmware version
uv run cli.py state            # Get device state
uv run cli.py get              # Read all parameters
uv run cli.py get 0            # Read a specific parameter
uv run cli.py set 0 100        # Write a parameter value
uv run cli.py reboot           # Reboot the device
```

By default, the CLI uses `/dev/tty.usbmodem14101`. Override with the `USB_PORT` environment variable:

```
USB_PORT=/dev/ttyUSB0 uv run cli.py get
```

## Generate installer
```
uv run pyinstaller gui.py --onedir --windowed --noconfirm --name "Mower Tools" --add-data "pyproject.toml:." --icon=icon/icon.icns
```
