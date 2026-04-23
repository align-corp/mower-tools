import tkinter as tk
from tkinter import ttk, filedialog
import threading
import queue
import serial.tools.list_ports
import locale
import os
import usb_protocol as u
import bootloader_uploader as bl

VERSION = 0.2

TRANSLATIONS = {
    "en": {
        "serial_port": "Serial Port",
        "refresh": "Refresh",
        "connect": "Connect",
        "disconnect": "Disconnect",
        "parameters": "Parameters",
        "status": "Status",
        "fw_upgrade": "Firmware Upgrade",
        "browse": "Browse",
        "upgrade": "Upgrade",
        "log": "Log",
        "lang_btn": "中文",
        # messages
        "connected": "Version {major}.{minor}",
        "connect_error": "Connection error: {e}",
        "no_answer": "Controller is not answering: {e}",
        "disconnected": "Disconnected",
        "connect_first": "Connect first",
        "read_first": "Read parameters first",
        "params_read_ok": "Params read successful",
        "params_write_ok": "Params write successful",
        "wrong_input": "Wrong input: {e}",
        "param_write_err": "Param write error: {e}",
        "mower_found": "Mower controller found\nPort: {port}",
        "select_fw_first": "Select a firmware file first",
        "select_port_first": "Select a serial port first",
        "resetting": "Resetting MCU...",
        "reset_sent": "Reset sent. Device booting to application.",
        "upgrade_error": "Upgrade error: {e}",
        "error": "Error: {e}",
        "param_title": "Parameters",
        "read": "Read",
        "write": "Write",
    },
    "zh_TW": {
        "serial_port": "序列埠",
        "refresh": "重新整理",
        "connect": "連線",
        "disconnect": "中斷連線",
        "parameters": "參數",
        "status": "狀態",
        "fw_upgrade": "韌體更新",
        "browse": "瀏覽...",
        "upgrade": "更新",
        "log": "日誌",
        "lang_btn": "English",
        # messages
        "connected": "版本 {major}.{minor}",
        "connect_error": "連線錯誤：{e}",
        "no_answer": "控制器未回應：{e}",
        "disconnected": "已中斷連線",
        "connect_first": "請先連線",
        "read_first": "請先讀取參數",
        "params_read_ok": "參數讀取成功",
        "params_write_ok": "參數寫入成功",
        "wrong_input": "輸入錯誤：{e}",
        "param_write_err": "參數寫入錯誤：{e}",
        "mower_found": "找到割草機控制器\n序列埠：{port}",
        "select_fw_first": "請先選擇韌體檔案",
        "select_port_first": "請先選擇序列埠",
        "resetting": "重置 MCU...",
        "reset_sent": "已送出重置指令，裝置正在啟動應用程式。",
        "upgrade_error": "更新錯誤：{e}",
        "error": "錯誤：{e}",
        "param_title": "參數",
        "read": "讀取",
        "write": "寫入",
    },
}


def get_system_language():
    try:
        system_locale = locale.getlocale()[0]
        if not system_locale:
            system_locale = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
        if system_locale and system_locale.lower().startswith("zh"):
            return "zh_TW"
    except Exception:
        pass
    return "en"


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


class ParameterWindow:
    def __init__(self, parent, mower_gui):
        self.mower_gui = mower_gui
        self.win = tk.Toplevel(parent)
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = ttk.Frame(self.win, padding="10")
        frame.grid(row=0, column=0)

        self.title_label = ttk.Label(frame, font=(None, 14, "bold"))
        self.title_label.grid(row=0, columnspan=2, pady=5)

        self.param_frame = ttk.Frame(frame)
        self.param_frame.grid(row=1, column=0, columnspan=2)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=8)
        self.read_btn = ttk.Button(btn_frame, command=self.mower_gui.read_params)
        self.read_btn.grid(row=0, column=0, padx=10)
        self.write_btn = ttk.Button(btn_frame, command=self.mower_gui.write)
        self.write_btn.grid(row=0, column=1, padx=10)

        self.update_texts()

        # Build widgets for any already-known params
        if mower_gui.current_param_names:
            self._build(mower_gui.current_param_names)

        self.mower_gui.read_params()

        # Center over parent
        self.win.withdraw()
        self.win.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.win.winfo_reqwidth()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.win.winfo_reqheight()) // 2
        self.win.geometry(f"+{x}+{y}")
        self.win.deiconify()

    def update_texts(self):
        t = self.mower_gui.tr
        self.win.title(t("param_title"))
        self.title_label.config(text=t("param_title"))
        self.read_btn.config(text=t("read"))
        self.write_btn.config(text=t("write"))

    def _build(self, param_names):
        for widget in self.param_frame.winfo_children():
            widget.destroy()
        mower_gui = self.mower_gui
        mower_gui.params = {}
        for i, name in param_names.items():
            ttk.Label(self.param_frame, text=name).grid(row=i, column=0, sticky=tk.W)
            state = "readonly" if mower_gui.is_readonly(i) else "normal"
            mower_gui.params[i] = ttk.Entry(self.param_frame, width=10, state=state)
            mower_gui.params[i].grid(row=i, column=1, padx=5)

    def clear(self):
        for widget in self.param_frame.winfo_children():
            widget.destroy()
        self.mower_gui.params = {}

    def _on_close(self):
        self.mower_gui.param_window = None
        self.win.destroy()


class MowerGUI:
    def __init__(self, root):
        self.client = None
        self.read_ok = False
        self.root = root
        self.root.resizable(False, False)
        self.param_window = None
        self.params = {}
        self.current_param_names = {}
        self.lang = get_system_language()

        self.root.title(f"Mower Tools v{VERSION}")

        # Styles
        style = ttk.Style()
        style.configure("Title.TLabel", font=(None, 14, "bold"))

        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Serial port selection
        serial_frame = ttk.Frame(main_frame)
        serial_frame.grid(row=0, column=0, pady=0)
        self.port_label = ttk.Label(serial_frame, style="Title.TLabel")
        self.port_label.grid(row=1, column=0, pady=5)
        port_frame = ttk.Frame(serial_frame)
        port_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(port_frame, textvariable=self.port_var, width=30)
        self.port_combo.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        self.refresh_btn = ttk.Button(port_frame, command=self.refresh_ports)
        self.refresh_btn.grid(row=0, column=1)

        # Buttons Frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=1, column=0, pady=5)
        self.connect_btn = ttk.Button(button_frame, command=self.connect)
        self.connect_btn.grid(row=0, column=0, padx=10, pady=2)
        self.param_btn = ttk.Button(button_frame, command=self.open_param_window, state="disabled")
        self.param_btn.grid(row=0, column=1, padx=10, pady=2)
        self.lang_btn = ttk.Button(button_frame, command=self.toggle_language)
        self.lang_btn.grid(row=0, column=2, padx=10, pady=2)

        # Status frame
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=2, column=0, pady=5)
        self.status_label = ttk.Label(status_frame, style="Title.TLabel")
        self.status_label.grid(columnspan=2, pady=5)
        self.status = {}
        for i, name in u.STATUS_NAMES.items():
            ttk.Label(status_frame, text=name).grid(row=i+1, sticky=tk.W)
            self.status[i] = ttk.Entry(status_frame, width=10, state="readonly")
            self.status[i].grid(row=i+1, column=1, padx=5)

        # Firmware upgrade frame
        fw_frame = ttk.Frame(main_frame)
        fw_frame.grid(row=3, column=0, pady=5)
        self.fw_label = ttk.Label(fw_frame, style="Title.TLabel")
        self.fw_label.grid(row=0, columnspan=3, pady=5)
        self.fw_path_var = tk.StringVar()
        ttk.Entry(fw_frame, textvariable=self.fw_path_var, width=30).grid(
            row=1, column=0, padx=(0, 5)
        )
        self.browse_btn = ttk.Button(fw_frame, command=self.browse_firmware)
        self.browse_btn.grid(row=1, column=1, padx=(0, 5))
        self.upgrade_btn = ttk.Button(fw_frame, command=self.start_upgrade)
        self.upgrade_btn.grid(row=2, columnspan=2)

        # Log frame
        self.log_frame = ttk.LabelFrame(main_frame)
        self.log_frame.grid(row=4, pady=5)
        self.log_text = tk.Text(self.log_frame, height=10, width=50)
        scrollbar = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        self._update_texts()
        self.refresh_ports()

    def tr(self, key, **kwargs):
        text = TRANSLATIONS.get(self.lang, {}).get(key, key)
        return text.format(**kwargs) if kwargs else text

    def toggle_language(self):
        self.lang = "zh_TW" if self.lang == "en" else "en"
        self._update_texts()
        if self.param_window is not None:
            self.param_window.update_texts()

    def _update_texts(self):
        self.port_label.config(text=self.tr("serial_port"))
        self.refresh_btn.config(text=self.tr("refresh"))
        self.connect_btn.config(text=self.tr("connect") if self.client is None else self.tr("disconnect"))
        self.param_btn.config(text=self.tr("parameters"))
        self.lang_btn.config(text=self.tr("lang_btn"))
        self.status_label.config(text=self.tr("status"))
        self.fw_label.config(text=self.tr("fw_upgrade"))
        self.browse_btn.config(text=self.tr("browse"))
        self.upgrade_btn.config(text=self.tr("upgrade"))
        self.log_frame.config(text=self.tr("log"))

    # === UI helper functions ===
    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        self.port_combo['values'] = [p.device for p in ports]
        if ports:
            port_to_select = ports[0]
            for p in ports:
                if "Mower" in p.description or "2A58" in p.hwid:
                    port_to_select = p
                    self.log(self.tr("mower_found", port=port_to_select))
                    break
            self.port_combo.set(port_to_select.device)

    def log(self, message):
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)

    def open_param_window(self):
        if self.param_window is not None:
            self.param_window.win.lift()
            return
        self.param_window = ParameterWindow(self.root, self)

    def is_readonly(self, param_id):
        return "Time" in self.current_param_names.get(param_id, "")

    def connect(self):
        try:
            self.client = u.UsbProtocolClient(self.port_combo.get())
        except Exception as e:
            self.log(self.tr("connect_error", e=e))
            self.client = None
            return
        try:
            major, minor = self.client.get_version()
            self.log(self.tr("connected", major=major, minor=minor))
            self.current_param_names = self.client.param_names
        except Exception as e:
            self.log(self.tr("no_answer", e=e))
            self.client.close()
            self.client = None
            return
        self.connect_btn.config(text=self.tr("disconnect"), command=self.disconnect)
        self.param_btn.config(state="enabled")
        if self.param_window is not None:
            self.param_window._build(self.current_param_names)
        self._poll_state()

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
        self.connect_btn.config(text=self.tr("connect"), command=self.connect)
        self.param_btn.config(state="disabled")
        self.log(self.tr("disconnected"))
        self.read_ok = False
        self.current_param_names = {}

        if self.param_window is not None:
            self.param_window.clear()

        for s in u.STATUS_NAMES:
            self.status[s].config(state="normal")
            self.status[s].delete(0, tk.END)
            self.status[s].config(state="readonly")

    def read_params(self):
        if self.client is None:
            self.log(self.tr("connect_first"))
            return

        for p in self.current_param_names:
            try:
                value = self.client.get_param(p)
            except Exception as e:
                self.log(self.tr("error", e=e))
                self.disconnect()
                return
            self.params[p].config(state="normal")
            self.params[p].delete(0, tk.END)
            self.params[p].insert(0, value)
            if self.is_readonly(p):
                self.params[p].config(state="readonly")

        self.read_ok = True
        self.log(self.tr("params_read_ok"))

    def _read_state(self):
        try:
            state = self.client.get_state()
        except Exception as e:
            self.log(self.tr("error", e=e))
            self.disconnect()
            return False
        for s in u.STATUS_NAMES:
            self.status[s].config(state="normal")
            self.status[s].delete(0, tk.END)
            self.status[s].insert(0, state.get(s))
            self.status[s].config(state="readonly")
        return True

    def _poll_state(self):
        if self.client is None:
            return
        if self.param_window is None:
            self._read_state()
        self.root.after(1000, self._poll_state)

    def write(self):
        if self.client is None:
            self.log(self.tr("connect_first"))
            return

        if not self.read_ok:
            self.log(self.tr("read_first"))
            return

        for i in self.current_param_names:
            if self.is_readonly(i):
                continue
            try:
                value = int(self.params[i].get())
            except Exception as e:
                self.log(self.tr("wrong_input", e=e))
                return

            try:
                self.client.set_param(i, value)
            except Exception as e:
                self.log(self.tr("param_write_err", e=e))
                self.disconnect()
                return

        self.log(self.tr("params_write_ok"))

    def browse_firmware(self):
        path = filedialog.askopenfilename(
            filetypes=[("Binary files", "*.bin"), ("All files", "*.*")]
        )
        if path:
            self.fw_path_var.set(path)

    def start_upgrade(self):
        fw_path = self.fw_path_var.get()
        if not fw_path:
            self.log(self.tr("select_fw_first"))
            return

        port = self.port_combo.get()
        if not port:
            self.log(self.tr("select_port_first"))
            return

        if self.client:
            self.disconnect()

        self.upgrade_btn.config(state="disabled")
        self.connect_btn.config(state="disabled")
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
                if uploader.upload_firmware(fw_path):
                    print(self.tr("resetting"))
                    uploader.reset_mcu()
                    print(self.tr("reset_sent"))
            finally:
                uploader.disconnect()
        except Exception as e:
            print(self.tr("upgrade_error", e=e))
        finally:
            sys.stdout = old_stdout
            # Signal update finished putting None
            self._upgrade_queue.put(None)

    def _poll_upgrade(self):
        try:
            while True:
                msg = self._upgrade_queue.get_nowait()
                if msg is None:
                    # Update finished, restore state
                    self.upgrade_btn.config(state="normal")
                    self.connect_btn.config(state="normal")
                    return
                text, is_progress = msg
                if not text:
                    continue
                if is_progress and self._last_was_progress:
                    # Delete for progress bar
                    self.log_text.delete("end-2l", "end-1c")
                self.log(text)
                self._last_was_progress = is_progress
        except queue.Empty:
            # Empty queue means we consumed all messages: reschedule the loop in 100 ms,
            # so GUI remains responsive
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
