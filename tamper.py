import psutil
import sys
import threading
import pydivert
import keyboard
import os
import time
import win32gui
import win32process

HOTKEY_FILE = "hotkey.txt"

class TamperController:
    def __init__(self):
        self.tamper_enabled = False
        self.main_port = 0
        self.filter_str = ""
        self.divert_handle = None
        self.tamper_thread = None
        self.thread_lock = threading.Lock()
        self.watchdog_timer = None
        self.hotkey = self._load_hotkey()
        self._setup_watchdog()

    def _get_udp_port(self):
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'].lower() == "robloxplayerbeta.exe":
                for conn in psutil.net_connections(kind='udp4'):
                    if conn.pid == proc.info['pid'] and conn.laddr.ip == '0.0.0.0':
                        return conn.laddr.port
        return 0

    def _tamper_packet(self, packet):
        data = bytearray(packet.payload)
        if data:
            patterns = [0x64, 0x13, 0x88, 0x40, 0x1F, 0xA0, 0xAA, 0x55]
            start, length = (0, len(data)) if len(data) <= 4 else (len(data) // 2 - len(data) // 8 + 1, len(data) // 4)
            for i, j in enumerate(range(start, min(start + length, len(data)))):
                data[j] ^= patterns[i % len(patterns)]
            packet.payload = bytes(data)
            return True
        return False

    def _tamper_loop(self):
        with self.thread_lock:
            if self.tamper_enabled and not self.divert_handle:
                self.divert_handle = pydivert.WinDivert(self.filter_str)
                self.divert_handle.open()
        try:
            while self.tamper_enabled:
                with self.thread_lock:
                    if not self.divert_handle or not self.divert_handle.is_open:
                        break
                packet = self.divert_handle.recv()
                self.divert_handle.send(packet if self._tamper_packet(packet) else packet)
        except OSError as e:
            if e.winerror not in (995, 6):
                print(f"Tamper loop error: {e}")
        finally:
            with self.thread_lock:
                if self.divert_handle and self.divert_handle.is_open:
                    self.divert_handle.close()
                self.divert_handle = None

    def start_tampering(self):
        with self.thread_lock:
            if self.main_port and not self.divert_handle:
                self.tamper_enabled = True
                self.tamper_thread = threading.Thread(target=self._tamper_loop, daemon=True)
                self.tamper_thread.start()

    def stop_tampering(self):
        with self.thread_lock:
            self.tamper_enabled = False
            if self.divert_handle and self.divert_handle.is_open:
                self.divert_handle.close()
                self.divert_handle = None
        if self.tamper_thread and self.tamper_thread.is_alive():
            self.tamper_thread.join(timeout=0.1)
        self.tamper_thread = None

    def toggle_tamper(self):
        if self.tamper_enabled:
            self.stop_tampering()
        else:
            self.start_tampering()

    def check_port(self):
        current_port = self._get_udp_port()
        if current_port and current_port != self.main_port:
            self.stop_tampering()
            self.main_port = current_port
            self.filter_str = f"udp and (udp.DstPort == {self.main_port} or udp.SrcPort == {self.main_port})"
            if self.tamper_enabled:
                self.start_tampering()
        self._setup_watchdog()

    def _setup_watchdog(self):
        if self.watchdog_timer:
            self.watchdog_timer.cancel()
        self.watchdog_timer = threading.Timer(5.0, self.check_port)
        self.watchdog_timer.daemon = True
        self.watchdog_timer.start()

    def _is_roblox_active(self):
        try:
            hwnd = win32gui.GetForegroundWindow()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name().lower() == "robloxplayerbeta.exe"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _load_hotkey(self):
        try:
            with open(HOTKEY_FILE) as file:
                if hotkey := file.readline().strip():
                    return hotkey
        except FileNotFoundError:
            pass
        hotkey = input("No hotkey found. Enter a key to bind (e.g., 't', 'f1', 'ctrl'): ").strip().lower()
        while not hotkey:
            hotkey = input("Input cannot be empty. Enter a key: ").strip().lower()
        with open(HOTKEY_FILE, "w") as file:
            file.write(hotkey)
        print(f"Hotkey set to '{hotkey}' and saved to {HOTKEY_FILE}")
        return hotkey

    def cleanup(self):
        self.stop_tampering()
        if self.watchdog_timer:
            self.watchdog_timer.cancel()

def main():
    controller = TamperController()
    controller.check_port()
    print(f"Press '{controller.hotkey}' to toggle tamper (Roblox must be active)")
    keyboard.on_press(lambda e: (
        print(f"Key pressed: {e.name}, Roblox active: {controller._is_roblox_active()}"),
        controller.toggle_tamper()
    ) if e.name.lower() == controller.hotkey and e.event_type == keyboard.KEY_DOWN and controller._is_roblox_active() else None)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.cleanup()
        print("Program terminated")
        sys.exit(0)

if __name__ == "__main__":
    main()