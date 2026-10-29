"""First in-app Windows UI for PulsePlay's native stream engine."""
from __future__ import annotations

import ctypes
import queue
import tkinter as tk
from tkinter import ttk, messagebox

from network import radmin_vpn_address
from native_stream import NativeStream, StreamEvent, list_windows


VERSION = "0.9.0-alpha1"
BG = "#0b1020"
PANEL = "#141d2d"
ACCENT = "#83e4b1"


def virtual_key(event):
    special = {
        "BackSpace": 0x08, "Tab": 0x09, "Return": 0x0D, "Escape": 0x1B,
        "space": 0x20, "Prior": 0x21, "Next": 0x22, "End": 0x23,
        "Home": 0x24, "Left": 0x25, "Up": 0x26, "Right": 0x27,
        "Down": 0x28, "Insert": 0x2D, "Delete": 0x2E,
        "Shift_L": 0xA0, "Shift_R": 0xA1, "Control_L": 0xA2,
        "Control_R": 0xA3, "Alt_L": 0xA4, "Alt_R": 0xA5,
        "Caps_Lock": 0x14,
    }
    if event.keysym in special:
        return special[event.keysym]
    if event.keysym.startswith("F") and event.keysym[1:].isdigit():
        number = int(event.keysym[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    if event.char and len(event.char) == 1:
        try:
            value = ctypes.windll.user32.VkKeyScanW(ord(event.char))
            if value != -1:
                return value & 0xFF
        except (AttributeError, OSError):
            pass
    return None


class StreamWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Трансляция PulsePlay")
        self.geometry("1100x720")
        self.minsize(640, 400)
        self.configure(bg="#080b12")
        self.image_label = tk.Label(self, bg="#080b12", fg="#dce5f4",
                                    text="Подключаемся к компьютеру…",
                                    font=("Segoe UI", 14))
        self.image_label.pack(fill="both", expand=True)
        controls = ttk.Frame(self, padding=8)
        controls.pack(fill="x")
        self.volume = tk.IntVar(value=100)
        ttk.Label(controls, text="Звук у вас").pack(side="left", padx=5)
        ttk.Scale(controls, from_=0, to=100, variable=self.volume,
                  command=self.on_volume).pack(side="left", fill="x", expand=True, padx=8)
        self.mute = ttk.Button(controls, text="Выключить звук", command=self.toggle_mute)
        self.mute.pack(side="left", padx=5)
        ttk.Button(controls, text="Отключиться", command=self.disconnect).pack(side="right", padx=5)
        self._photo = None
        self._display_box = (0, 0, 1, 1)
        self._pressed = set()
        self.image_label.bind("<Motion>", self.on_motion)
        self.image_label.bind("<MouseWheel>", self.on_wheel)
        for button, name in ((1, "left"), (2, "middle"), (3, "right")):
            self.image_label.bind(f"<ButtonPress-{button}>", lambda e, n=name: self.on_button(e, n, True))
            self.image_label.bind(f"<ButtonRelease-{button}>", lambda e, n=name: self.on_button(e, n, False))
        self.bind("<KeyPress>", self.on_key_down)
        self.bind("<KeyRelease>", self.on_key_up)
        self.protocol("WM_DELETE_WINDOW", self.disconnect)
        self.focus_force()
        self.after(30, self.draw_frame)

    def draw_frame(self):
        if not self.winfo_exists():
            return
        frame = self.app.stream.latest_video()
        if frame is not None:
            width = max(1, self.image_label.winfo_width())
            height = max(1, self.image_label.winfo_height())
            frame.thumbnail((width, height))
            from PIL import ImageTk
            self._photo = ImageTk.PhotoImage(frame)
            x = max(0, (width - frame.width) / 2)
            y = max(0, (height - frame.height) / 2)
            self._display_box = (x, y, frame.width, frame.height)
            self.image_label.configure(image=self._photo, text="")
        self.after(30, self.draw_frame)

    def _relative(self, event):
        left, top, width, height = self._display_box
        return (max(0.0, min(1.0, (event.x - left) / max(1, width))),
                max(0.0, min(1.0, (event.y - top) / max(1, height))))

    def on_motion(self, event):
        x, y = self._relative(event)
        self.app.stream.send_input({"type": "mouse", "x": x, "y": y})

    def on_button(self, event, button, down):
        x, y = self._relative(event)
        self.app.stream.send_input({"type": "mouse", "x": x, "y": y,
                                    "button": f"{button}-{'down' if down else 'up'}"})

    def on_wheel(self, event):
        x, y = self._relative(event)
        self.app.stream.send_input({"type": "mouse", "x": x, "y": y,
                                    "button": "wheel-up" if event.delta > 0 else "wheel-down"})

    def on_key_down(self, event):
        if event.keysym in ("Escape",) and event.state & 0x4:
            return self.disconnect()
        vk = virtual_key(event)
        if vk is not None and vk not in self._pressed:
            self._pressed.add(vk)
            self.app.stream.send_input({"type": "key", "vk": vk, "down": True})

    def on_key_up(self, event):
        vk = virtual_key(event)
        if vk is not None:
            self._pressed.discard(vk)
            self.app.stream.send_input({"type": "key", "vk": vk, "down": False})

    def on_volume(self, value):
        self.app.stream.set_volume(float(value) / 100.0)
        self.mute.configure(text="Включить звук" if float(value) <= 0 else "Выключить звук")

    def toggle_mute(self):
        if self.volume.get() > 0:
            self._previous_volume = self.volume.get()
            self.volume.set(0)
        else:
            self.volume.set(getattr(self, "_previous_volume", 80))
        self.on_volume(self.volume.get())

    def disconnect(self):
        for vk in tuple(self._pressed):
            self.app.stream.send_input({"type": "key", "vk": vk, "down": False})
        self._pressed.clear()
        self.app.disconnect()
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PulsePlay • трансляция внутри приложения")
        self.geometry("940x700")
        self.minsize(760, 560)
        self.configure(bg=BG)
        self.events = queue.Queue()
        self.stream = NativeStream(self.events)
        self.viewer = None
        self.host_running = False
        self._build_style()
        self._build_ui()
        self.refresh_address()
        self.refresh_windows()
        self.after(100, self.poll_events)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=PANEL, foreground="#edf2fc")
        style.configure("TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL, foreground="#edf2fc")
        style.configure("Muted.TLabel", background=PANEL, foreground="#9aaac1")
        style.configure("TButton", padding=(14, 10), background="#25334b",
                        foreground="#e1e9f7", borderwidth=0)
        style.map("TButton", background=[("active", "#34445f")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#092116",
                        font=("Segoe UI", 11, "bold"), padding=(18, 12))
        style.configure("TEntry", fieldbackground="#0e1626", foreground="#f3f6fd",
                        bordercolor="#2b3a53", padding=9)
        style.configure("Horizontal.TScale", background=PANEL, troughcolor="#0e1626")

    def _build_ui(self):
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="PULSEPLAY", foreground=ACCENT,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Играй вместе — всё в одном приложении",
                  font=("Segoe UI", 23, "bold")).pack(anchor="w", pady=(5, 3))
        ttk.Label(outer, text="Встроенная трансляция через одну сеть Radmin VPN.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 18))

        book = ttk.Notebook(outer)
        book.pack(fill="both", expand=True)
        host = ttk.Frame(book, padding=22)
        guest = ttk.Frame(book, padding=22)
        book.add(host, text="Мой компьютер")
        book.add(guest, text="Подключиться")
        self._build_host(host)
        self._build_guest(guest)
        self.status = tk.StringVar(value="Готово. Откройте PulsePlay на обоих компьютерах.")
        ttk.Label(outer, textvariable=self.status, style="Muted.TLabel",
                  wraplength=850).pack(fill="x", pady=(12, 0))

    def _build_host(self, parent):
        ttk.Label(parent, text="Запусти трансляцию", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Подключи оба компьютера к одной сети Radmin VPN. "
                  "Разреши PulsePlay доступ в брандмауэре Windows, если появится запрос.",
                  wraplength=780).pack(anchor="w", pady=(5, 16))
        ttk.Label(parent, text="Адрес Radmin VPN этого компьютера").pack(anchor="w")
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=6)
        self.address = tk.StringVar()
        ttk.Entry(row, textvariable=self.address).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Найти IP", command=self.refresh_address).pack(side="left", padx=(8, 0))
        ttk.Label(parent, text="Что показывать гостю").pack(anchor="w", pady=(12, 0))
        source_row = ttk.Frame(parent)
        source_row.pack(fill="x", pady=6)
        self.capture_source = tk.StringVar(value="Весь экран")
        self.capture_targets = {"Весь экран": None}
        self.capture_box = ttk.Combobox(source_row, textvariable=self.capture_source,
                                        values=["Весь экран"], state="readonly")
        self.capture_box.pack(side="left", fill="x", expand=True)
        ttk.Button(source_row, text="Обновить окна", command=self.refresh_windows).pack(side="left", padx=(8, 0))
        ttk.Label(parent, text="При выборе окна гостю передаётся только его содержимое. "
                  "При выборе экрана виден весь рабочий стол.", style="Muted.TLabel",
                  wraplength=780).pack(anchor="w")
        self.host_button = ttk.Button(parent, text="Начать трансляцию",
                                      style="Accent.TButton", command=self.toggle_host)
        self.host_button.pack(anchor="w", pady=(10, 14))
        ttk.Label(parent, text="Приглашение для гостя").pack(anchor="w")
        self.invite = tk.StringVar()
        ttk.Entry(parent, textvariable=self.invite, state="readonly").pack(fill="x", pady=6)
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Button(row, text="Скопировать приглашение",
                   command=self.copy_invite).pack(side="left")
        ttk.Label(parent, text="Передавай приглашение только человеку, которому разрешаешь "
                  "управлять этим компьютером. При остановке трансляции код отзывается.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", pady=(12, 0))

    def _build_guest(self, parent):
        ttk.Label(parent, text="Подключись к хосту", font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(parent, text="Сначала подключись к той же сети Radmin VPN. Попроси у хоста "
                  "приглашение PulsePlay целиком.", wraplength=780).pack(anchor="w", pady=(5, 16))
        ttk.Label(parent, text="Вставь приглашение (начинается с PP2:)").pack(anchor="w")
        self.invite_input = tk.Text(parent, height=5, bg="#0e1626", fg="#f3f6fd",
                                    insertbackground="#f3f6fd", relief="flat", wrap="word")
        self.invite_input.pack(fill="x", pady=6)
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Вставить из буфера",
                   command=self.paste_invite).pack(side="left")
        ttk.Button(row, text="Подключиться", style="Accent.TButton",
                   command=self.connect).pack(side="right")

    def refresh_address(self):
        self.address.set(radmin_vpn_address())
        if self.address.get():
            self.status.set("IP Radmin VPN найден. Подключи гостя к той же VPN-сети.")
        else:
            self.status.set("IP не найден. Запусти Radmin VPN и подключись к общей сети.")

    def toggle_host(self):
        if self.host_running:
            self.disconnect()
            return
        address = self.address.get().strip()
        if not address:
            return messagebox.showinfo("Нет адреса", "Сначала найди IP Radmin VPN.")
        capture_target = self.capture_targets.get(self.capture_source.get(), None)
        try:
            self.invite.set(self.stream.start_host(address, fps=30,
                                                   window_hwnd=capture_target))
        except Exception as exc:
            return messagebox.showerror("Не удалось начать трансляцию", str(exc))
        self.host_running = True
        self.host_button.configure(text="Остановить трансляцию")
        self.status.set("Запускаю захват экрана и звука…")

    def refresh_windows(self):
        try:
            windows = list_windows()
        except Exception as exc:
            self.status.set("Не удалось получить список окон: " + str(exc))
            windows = []
        current = self.capture_source.get() if hasattr(self, "capture_source") else "Весь экран"
        self.capture_targets = {"Весь экран": None}
        for hwnd, label in windows:
            self.capture_targets[label] = hwnd
        values = list(self.capture_targets)
        if hasattr(self, "capture_box"):
            self.capture_box.configure(values=values)
            self.capture_source.set(current if current in self.capture_targets else "Весь экран")

    def connect(self):
        invite = self.invite_input.get("1.0", "end").strip()
        try:
            self.stream.connect_guest(invite)
        except Exception as exc:
            return messagebox.showerror("Подключение", str(exc))
        self.status.set("Соединяюсь с хостом…")
        self.viewer = StreamWindow(self)

    def paste_invite(self):
        try:
            self.invite_input.delete("1.0", "end")
            self.invite_input.insert("1.0", self.clipboard_get())
        except tk.TclError:
            messagebox.showinfo("Буфер обмена", "Скопируй приглашение хоста и попробуй снова.")

    def copy_invite(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.invite.get())
            self.update_idletasks()
            self.status.set("Приглашение скопировано. Отправь его гостю.")
        except tk.TclError:
            messagebox.showerror("Буфер обмена", "Windows не дала доступ к буферу обмена.")

    def poll_events(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if not isinstance(event, StreamEvent):
                continue
            if event.kind == "host_started":
                self.status.set(f"Трансляция запущена • адрес {event.value} • ожидание гостя")
            elif event.kind == "guest_signaling":
                self.status.set("Хост принял приглашение. Устанавливаем медиасвязь…")
            elif event.kind == "connection" and event.value == "connected":
                self.status.set("Гость подключён • изображение, звук и управление работают")
            elif event.kind == "connection":
                self.status.set(f"Состояние соединения: {event.value}")
            elif event.kind == "error":
                self.status.set(str(event.value))
                messagebox.showerror("PulsePlay", str(event.value))
            elif event.kind == "loop_timeout":
                self.status.set("Сетевой модуль запускается дольше обычного. Подключение станет доступно через несколько секунд.")
            elif event.kind == "audio_error":
                self.status.set("Соединение установлено, но звук не запустился: " + str(event.value))
            elif event.kind == "stopped":
                self.host_running = False
                self.host_button.configure(text="Начать трансляцию")
                self.invite.set("")
                self.status.set("Трансляция остановлена. Старое приглашение отозвано.")
        self.after(100, self.poll_events)

    def disconnect(self):
        self.stream.stop()
        if self.viewer and self.viewer.winfo_exists():
            self.viewer.destroy()
        self.viewer = None

    def close(self):
        self.disconnect()
        self.after(100, self.destroy)


if __name__ == "__main__":
    App().mainloop()

