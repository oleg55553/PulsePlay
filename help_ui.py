"""Accessible, local-only contextual help for the desktop UI."""
import tkinter as tk
from tkinter import ttk

HELP = {
    'host': 'На игровом ПК скопируй IP из блока «Мой компьютер» и вставь сюда. Для интернета обоим устройствам нужен Tailscale, а другу — доступ Share к этому ПК.',
    'app': 'Введи точное имя приложения из Sunshine → Applications. Desktop показывает рабочий стол. Для отдельной игры сначала добавь её в Sunshine.',
    'moonlight': 'Это программа, которая показывает игру. Установи Moonlight на принимающем ПК. Если путь не найден, нажми «Выбрать» и укажи Moonlight.exe.',
    'preset': 'Начни с «Баланс»: 1080p, 60 FPS. Если картинка зависает — попробуй «Быстрый». 120 FPS имеет смысл проверять на быстром экране и стабильной сети.',
    'resolution': 'Размер передаваемой картинки. Больше разрешение — выше детализация и нагрузка на сеть. Для начала выбери 1920×1080; при проблемах — 1280×720.',
    'fps': 'Сколько кадров в секунду передаётся. Начни с 60. Повышай до 120, если экран и оба компьютера справляются. Большее число не гарантирует меньшую задержку.',
    'bitrate': 'Количество данных в секунду, Мбит/с. Начни с 20 для 1080p/60. При потере кадров попробуй снизить. Слишком высокий битрейт может ухудшить плавность.',
    'codec': 'Способ сжатия видео. Оставь auto. Если нет изображения или аппаратный декодер не поддерживается, попробуй H.264. HEVC/AV1 требуют поддержки устройств.',
    'fullscreen': 'Включено — Moonlight открывает игру на весь экран. Во время игры Ctrl+Alt+Shift+X переключает окно и полный экран. Ctrl+Alt+Shift+Q завершает подключение.',
    'latency': 'Отключает V-Sync и выравнивание подачи кадров для уменьшения ожидания. Возможны разрывы изображения. Если картинка неприятно дёргается, отключи этот режим.',
    'overlay': 'Показывает статистику Moonlight поверх игры: сеть, декодирование и потери кадров. Помогает найти причину задержки; это не измерение полной задержки управления.',
    'own_ip': 'Это публичный IPv4 домашнего роутера, полученный через UPnP без внешнего сервиса. На игровом ПК скопируй адрес и передай доверенному человеку. Если адрес пустой, проверь UPnP или узнай WAN IP в роутере. Один IP не даёт доступ без открытых портов и сопряжения.',
    'connect': 'PIN вводится на игровом ПК (хосте), где работает Sunshine: открой https://localhost:47990 именно на игровом ПК → раздел PIN → введи код из окна Moonlight на гостевом ПК. Не вводи код в PulsePlay. После подтверждения на хосте нажми «Играть» у гостя. Повторно вводить PIN обычно не нужно.',
    'network': 'Для прямого подключения включи UPnP в Sunshine и роутере или открой нужные порты вручную. Нужен публичный IPv4; при CGNAT обратись к провайдеру. Проверка TCP не подтверждает работу UDP и игры.',
    'permissions': 'Эти настройки общие для всех клиентов Sunshine. Здесь создаётся текст профиля — его нужно применить вручную в Sunshine → Configuration → Input, сохранить и перезапустить Sunshine.',
    'keyboard': 'Разрешает гостям нажатия клавиш. Запрет действует только после применения профиля на хосте. Это общее разрешение, не персональное право одного гостя.',
    'mouse': 'Разрешает гостям двигать мышь и нажимать её кнопки. Не ограничивает управление одной игрой. Примени профиль на хосте и проверь запрет со второго ПК.',
    'controller': 'Разрешает виртуальные геймпады. Для игры вдвоём нужны поддержка локального кооператива и настроенный драйвер геймпада в Sunshine. Примени профиль на хосте.',
}

class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.window = None
        self.pending = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<FocusIn>', self.show, add='+')
        widget.bind('<FocusOut>', self.hide, add='+')
        widget.bind('<Button-1>', self.show, add='+')
        widget.bind('<Return>', self.show, add='+')
        widget.bind('<space>', self.show, add='+')
        widget.bind('<Escape>', self.hide, add='+')
        widget.bind('<Destroy>', self.hide, add='+')
        widget.bind('<Unmap>', self.hide, add='+')
        widget.winfo_toplevel().bind('<Configure>', self.on_move, add='+')

    def on_move(self, event):
        if event.widget == self.widget.winfo_toplevel():
            self.hide()

    def schedule(self, event=None):
        self.hide()
        self.pending = self.widget.after(350, self.show)

    def show(self, event=None):
        self.hide()
        if not self.widget.winfo_ismapped():
            return
        window = self.window = tk.Toplevel(self.widget)
        window.overrideredirect(True)
        window.configure(bg='#506449', padx=1, pady=1)
        label = tk.Label(window, text=self.text, bg='#202c26', fg='#edf7ee',
            font=('Segoe UI',10), wraplength=340, justify='left', padx=15, pady=12)
        label.pack()
        window.update_idletasks()
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        x = min(self.widget.winfo_rootx(), self.widget.winfo_screenwidth()-width-12)
        y = self.widget.winfo_rooty()+self.widget.winfo_height()+8
        if y+height > self.widget.winfo_screenheight()-12:
            y = self.widget.winfo_rooty()-height-8
        window.geometry(f'+{max(0,x)}+{max(0,y)}')

    def hide(self, event=None):
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None

def help_label(parent, text, key):
    row = ttk.Frame(parent)
    ttk.Label(row, text=text).pack(side='left')
    marker = tk.Label(row, text='?', bg='#263b31', fg='#a3edba',
        font=('Segoe UI',9,'bold'), width=2, cursor='question_arrow',
        takefocus=True, highlightthickness=1, highlightbackground='#395444',
        highlightcolor='#a3edba')
    marker.pack(side='left', padx=(8,0))
    marker.tooltip = Tooltip(marker, HELP[key])
    return row
