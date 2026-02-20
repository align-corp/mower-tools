import tkinter as tk
from tkinter import ttk, filedialog
import threading
import queue
import serial.tools.list_ports
import usb_protocol as u
import bootloader_uploader as bl

VERSION = 0.1

class _QueueWriter:
    """File-like object that captures print output into a queue for GUI display."""
    def __init__(self, q):
        self._queue = q
        self._line = ""
        self._cr = False

    def write(self, text):
        for ch in text:
            if ch == '\r':
                self._cr = True
                self._line = ""
            elif ch == '\n':
                self._queue.put((self._line, self._cr))
                self._line = ""
                self._cr = False
            else:
                self._line += ch

    def flush(self):
        if self._line:
            self._queue.put((self._line, self._cr))
            self._line = ""


class MowerGUI:
    def __init__(self, root):
        self.client = None
        self.read_ok = False
        self.root = root
        self.root.title(f"Mower Tools v{VERSION}")
        self.root.resizable(False, False)

        # Styles
        style = ttk.Style()
        style.configure("Title.TLabel", font=(None, 14, "bold"))

        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Serial port selection
        serial_frame = ttk.Frame(main_frame)
        serial_frame.grid(row=0, column=0, pady=0)
        self.port_label = ttk.Label(serial_frame, style="Title.TLabel", text="Serial Port")
        self.port_label.grid(row=1, column=0, pady=5)
        port_frame = ttk.Frame(serial_frame)
        port_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(port_frame, textvariable=self.port_var, width=30)
        self.port_combo.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        self.refresh_btn = ttk.Button(port_frame, text="Refresh", command=self.refresh_ports)
        self.refresh_btn.grid(row=0, column=1)

        # Buttons Frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=1, column=0, pady=5)
        self.connect_btn = ttk.Button(button_frame, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=0, padx=10, pady=2)
        self.read_btn = ttk.Button(button_frame, text="Read", command=self.read)
        self.read_btn.grid(row=0, column=1, padx=10, pady=2)
        self.write_btn = ttk.Button(button_frame, text="Write", command=self.write)
        self.write_btn.grid(row=0, column=2, padx=10, pady=2)

        # Params frame
        self.param_frame = ttk.Frame(main_frame)
        self.param_frame.grid(row=2, column=0, pady=5)
        self.param_label = ttk.Label(self.param_frame, text="Parameters", style="Title.TLabel")
        self.param_label.grid(columnspan=2, pady=5)
        self.params = {}
        self.current_param_names = {}
            
        # Status frame
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=3, column=0, pady=5)
        self.status_label = ttk.Label(status_frame, text="Status", style="Title.TLabel")
        self.status_label.grid(columnspan=2, pady=5)
        self.status = {}
        for i, name  in u.STATUS_NAMES.items():
            ttk.Label(status_frame, text=name).grid(row=i+1, sticky=tk.W)
            self.status[i] = ttk.Entry(status_frame, width=10, state="readonly")
            self.status[i].grid(row=i+1, column=1, padx=5)

        # Firmware upgrade frame
        fw_frame = ttk.Frame(main_frame)
        fw_frame.grid(row=4, column=0, pady=5)
        ttk.Label(fw_frame, text="Firmware Upgrade", style="Title.TLabel").grid(
            row=0, columnspan=3, pady=5
        )
        self.fw_path_var = tk.StringVar()
        ttk.Entry(fw_frame, textvariable=self.fw_path_var, width=30).grid(
            row=1, column=0, padx=(0, 5)
        )
        ttk.Button(fw_frame, text="Browse", command=self.browse_firmware).grid(
            row=1, column=1, padx=(0, 5)
        )
        self.upgrade_btn = ttk.Button(fw_frame, text="Upgrade", command=self.start_upgrade)
        self.upgrade_btn.grid(row=2, columnspan=2)

        # Log frame
        self.log_frame = ttk.LabelFrame(main_frame, text="Log")
        self.log_frame.grid(row=5, pady=5)
        self.log_text = tk.Text(self.log_frame, height=10, width=50)
        scrollbar = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # Refresh serial port at startup
        self.refresh_ports()

    # === UI heper functions ===
    def refresh_ports(self):
        """Update serial ports list and select APx devices"""
        ports = serial.tools.list_ports.comports()
        self.port_combo['values'] = [p.device for p in ports]
        if ports:
            port_to_select = ports[0]
            for p in ports:
                if "Mower" in p.description or "2A58" in p.hwid:
                    port_to_select = p
                    self.log(f"Mower controller found\nPort: {port_to_select}")
                    break
            self.port_combo.set(port_to_select.device)

    def log(self, message):
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)

    def _build_params(self, param_names):
        """Build parameter widgets based on param names dict"""
        self._clear_params()
        self.current_param_names = param_names
        for i, name in param_names.items():
            ttk.Label(self.param_frame, text=name).grid(row=i+1, sticky=tk.W)
            state = "readonly" if self.is_readonly(i) else "normal"
            self.params[i] = ttk.Entry(self.param_frame, width=10, state=state)
            self.params[i].grid(row=i+1, column=1, padx=5)

    def _clear_params(self):
        """Remove all parameter widgets"""
        for widget in self.param_frame.winfo_children():
            if widget != self.param_label:
                widget.destroy()
        self.params = {}
        self.current_param_names = {}

    def connect(self):
        try:
            self.client = u.UsbProtocolClient(self.port_combo.get())
        except Exception as e:
            self.log(f"Connection error: {e}")
            self.client = None
            return
        try:
            major, minor = self.client.get_version()
            self.log(f"Version {major}.{minor}")
            self._build_params(self.client.param_names)
        except Exception as e:
            self.log(f"Controller is not answering: {e}")
            self.client.close()
            self.client = None
            return
        self.connect_btn.config(text="Disconnect", command=self.disconnect)
        self.read()
            

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
        self.connect_btn.config(text="Connect", command=self.connect)
        self.log("Disconnected")
        self.read_ok = False

        self._clear_params()

        # Reset status
        for s in u.STATUS_NAMES:
            self.status[s].config(state="normal")
            self.status[s].delete(0, tk.END)
            self.status[s].config(state="readonly")

    def is_readonly(self, param_id):
        return "Time" in self.current_param_names.get(param_id, "")

    def read(self):
        if self.client is None:
            self.log("Connect first")
            return

        for p in self.current_param_names:
            try:
                value = self.client.get_param(p)
            except Exception as e:
                self.log(f"Error: {e}")
                self.disconnect()
                return
            self.params[p].config(state="normal")
            self.params[p].delete(0, tk.END)
            self.params[p].insert(0, value)
            if self.is_readonly(p):
                self.params[p].config(state="readonly")
                
        try:
            state = self.client.get_state()
        except Exception as e:
            self.log(f"Error: {e}")
            self.disconnect()
            return
        for s in u.STATUS_NAMES:
            self.status[s].config(state="normal")
            self.status[s].delete(0, tk.END)
            self.status[s].insert(0, state.get(s))
            self.status[s].config(state="readonly")

        self.read_ok = True
        self.log("Params read successful")

    def write(self):
        if self.client is None:
            self.log("Connect first")
            return

        if not self.read_ok:
            self.log("Read parameters first")
            return

        for i in self.current_param_names:
            if self.is_readonly(i):
                continue
            try:
                value = int(self.params[i].get())
            except Exception as e:
                self.log(f"Wrong input: {e}")
                return

            try:
                self.client.set_param(i, value)
            except Exception as e:
                self.log(f"Param write error: {e}")
                self.disconnect()
                return

        self.log("Params write successful")

    def browse_firmware(self):
        path = filedialog.askopenfilename(
            filetypes=[("Binary files", "*.bin"), ("All files", "*.*")]
        )
        if path:
            self.fw_path_var.set(path)

    def start_upgrade(self):
        fw_path = self.fw_path_var.get()
        if not fw_path:
            self.log("Select a firmware file first")
            return

        port = self.port_combo.get()
        if not port:
            self.log("Select a serial port first")
            return

        if self.client:
            self.disconnect()

        self.upgrade_btn.config(state="disabled")
        self._upgrade_queue = queue.Queue()
        self._last_was_progress = False

        thread = threading.Thread(
            target=self._upgrade_worker, args=(port, fw_path), daemon=True
        )
        thread.start()
        self._poll_upgrade()

    def _upgrade_worker(self, port, fw_path):
        import sys
        old_stdout = sys.stdout
        sys.stdout = _QueueWriter(self._upgrade_queue)
        try:
            uploader = bl.BootloaderUploader(port)
            if not uploader.connect():
                return
            try:
                uploader.upload_firmware(fw_path)
            finally:
                uploader.disconnect()
        except Exception as e:
            print(f"Upgrade error: {e}")
        finally:
            sys.stdout = old_stdout
            self._upgrade_queue.put(None)

    def _poll_upgrade(self):
        try:
            while True:
                msg = self._upgrade_queue.get_nowait()
                if msg is None:
                    self.upgrade_btn.config(state="normal")
                    return
                text, is_progress = msg
                if not text:
                    continue
                if is_progress and self._last_was_progress:
                    self.log_text.delete("end-2l", "end-1c")
                self.log(text)
                self._last_was_progress = is_progress
        except queue.Empty:
            pass
        self.root.after(100, self._poll_upgrade)


def main():
    root = tk.Tk()
    app = MowerGUI(root)

    def on_closing():
        app.disconnect()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
