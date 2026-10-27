"""PulsePlay 0.8 — desktop launcher for separately installed Moonlight/Sunshine."""
import os
import ctypes
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

from help_ui import help_label
from network import diagnose, host_profile, own_address
from core import PRESETS, find_moonlight, find_sunshine, load_settings, save_settings, stream_args, validate_host, make_invite, parse_invite


def copy_text_to_clipboard(widget, text):
    """Copy Unicode text reliably on Windows, including PyInstaller builds."""
    if os.name != 'nt':
        widget.clipboard_clear()
        widget.clipboard_append(text)
        widget.update_idletasks()
        return

    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p

    opened = False
    for _ in range(20):
        if user32.OpenClipboard(wintypes.HWND(widget.winfo_id())):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        raise tk.TclError('Не удалось открыть буфер обмена Windows.')

    memory = None
    transferred = False
    try:
        if not user32.EmptyClipboard():
            raise tk.TclError('Не удалось очистить буфер обмена Windows.')
        payload = (str(text) + '\0').encode('utf-16le')
        memory = kernel32.GlobalAlloc(0x0002, len(payload))  # GMEM_MOVEABLE
        if not memory:
            raise tk.TclError('Не удалось выделить память для буфера обмена.')
        pointer = kernel32.GlobalLock(memory)
        if not pointer:
            raise tk.TclError('Не удалось записать буфер обмена.')
        try:
            ctypes.memmove(pointer, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(memory)
        if not user32.SetClipboardData(13, memory):  # CF_UNICODETEXT
            raise tk.TclError('Windows не приняла текст в буфер обмена.')
        transferred = True  # Windows owns the memory after SetClipboardData.
    finally:
        if memory and not transferred:
            kernel32.GlobalFree(memory)
        user32.CloseClipboard()


def read_clipboard_text(widget):
    """Read Unicode clipboard text without relying on Tcl's STRING target."""
    if os.name != 'nt':
        return widget.clipboard_get()

    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL

    opened = False
    for _ in range(20):
        if user32.OpenClipboard(wintypes.HWND(widget.winfo_id())):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        raise tk.TclError('Не удалось открыть буфер обмена Windows.')
    try:
        if not user32.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
            raise tk.TclError('В буфере обмена нет текста.')
        memory = user32.GetClipboardData(13)
        if not memory:
            raise tk.TclError('Не удалось получить текст из буфера обмена.')
        pointer = kernel32.GlobalLock(memory)
        if not pointer:
            raise tk.TclError('Не удалось прочитать текст из буфера обмена.')
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(memory)
    finally:
        user32.CloseClipboard()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PulsePlay • Играй там, где ты')
        self.geometry('1160x820')
        self.minsize(920, 620)
        self.configure(bg='#0b1020')
        self.events = queue.Queue()
        self.process = None
        self.process_kind = ''
        self.stopping = False
        self.pairing_context = None
        self.settings = load_settings()
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#141d2d', foreground='#edf2fc')
        style.configure('TFrame', background='#141d2d')
        style.configure('Page.TFrame', background='#0b1020')
        style.configure('TLabel', background='#141d2d', foreground='#edf2fc')
        style.configure('Muted.TLabel', background='#141d2d', foreground='#9aaac1')
        style.configure('TButton', padding=(16, 11), background='#25334b', borderwidth=0, foreground='#e1e9f7', font=('Segoe UI', 10))
        style.map('TButton', background=[('pressed','#1c2940'),('active','#34445f'),('disabled','#1a2435')], foreground=[('disabled','#74839b')])
        style.configure('Accent.TButton', background='#83e4b1', foreground='#092116', font=('Segoe UI',11,'bold'), padding=(22,14))
        style.map('Accent.TButton', background=[('pressed','#65c895'),('active','#a0f0c5'),('disabled','#253c32')], foreground=[('disabled','#789585'),('active','#092116')])
        style.configure('TEntry', fieldbackground='#0e1626', foreground='#f3f6fd', bordercolor='#2b3a53', lightcolor='#2b3a53', darkcolor='#2b3a53', padding=10, insertcolor='#f3f6fd')
        style.map('TEntry', bordercolor=[('focus','#83e4b1')], fieldbackground=[('readonly','#101a2c')])
        style.configure('TCombobox', fieldbackground='#0e1626', foreground='#f3f6fd', bordercolor='#2b3a53', arrowcolor='#83e4b1', padding=10)
        style.map('TCombobox', fieldbackground=[('readonly','#101a2c'),('active','#17233a')], foreground=[('readonly','#f3f6fd')])
        style.configure('TCheckbutton', background='#141d2d', padding=(0,6), indicatorbackground='#0e1626', foreground='#dce5f4')
        style.map('TCheckbutton', background=[('active','#141d2d')], indicatorbackground=[('selected','#83e4b1')], foreground=[('disabled','#74839b')])
        style.configure('TRadiobutton', background='#141d2d', padding=(0,5), indicatorbackground='#0e1626', foreground='#dce5f4')
        style.map('TRadiobutton', background=[('active','#141d2d')], indicatorbackground=[('selected','#83e4b1')])
        style.configure('Horizontal.TScale', background='#141d2d', troughcolor='#0e1626',
                        bordercolor='#2b3a53', lightcolor='#83e4b1', darkcolor='#83e4b1',
                        sliderlength=18, sliderthickness=18)
        style.map('Horizontal.TScale', background=[('active','#141d2d')])
        style.configure('TNotebook', background='#0b1020', borderwidth=0, tabmargins=0)
        style.layout('TNotebook.Tab', [])
        style.configure('Vertical.TScrollbar', background='#2b3a53', troughcolor='#0b1020', borderwidth=0, arrowsize=12, width=11)
        self.option_add('*TCombobox*Listbox.background','#141d2d')
        self.option_add('*TCombobox*Listbox.foreground','#edf2fc')
        self.option_add('*TCombobox*Listbox.selectBackground','#34445f')
        sidebar = tk.Frame(self, bg='#101827', width=210)
        sidebar.pack(side='left',fill='y')
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text='P / P', bg='#101827', fg='#83e4b1', font=('Segoe UI',28,'bold')).pack(anchor='w',padx=24,pady=(28,2))
        tk.Label(sidebar, text='PULSEPLAY', bg='#101827', fg='#f3f6fd', font=('Segoe UI',13,'bold')).pack(anchor='w',padx=24)
        tk.Label(sidebar, text='ИГРАЙТЕ ВМЕСТЕ', bg='#101827', fg='#8494ae', font=('Segoe UI',8,'bold')).pack(anchor='w',padx=24,pady=(6,36))
        self.nav_buttons=[]
        for index,label in enumerate(['01   Подключиться','02   Мой компьютер','03   Интернет','04   Права хоста']):
            button=tk.Button(sidebar,text=label,anchor='w',bg='#101827',fg='#9aaac1',activebackground='#1c2b38',activeforeground='#83e4b1',relief='flat',bd=0,font=('Segoe UI',10),padx=16,pady=13,cursor='hand2',command=lambda i=index:self.navigate(i))
            button.pack(fill='x',padx=10,pady=3)
            self.nav_buttons.append(button)
        tk.Label(sidebar,text='PULSEPLAY  /  0.8\nНа базе Sunshine + Moonlight',justify='left',bg='#101827',fg='#8494ae',font=('Segoe UI',9)).pack(side='bottom',anchor='w',padx=24,pady=24)
        viewport = tk.Canvas(self, bg='#0b1020', highlightthickness=0)
        self.viewport = viewport
        scrollbar = ttk.Scrollbar(self, orient='vertical', command=viewport.yview)
        scrollbar.pack(side='right', fill='y')
        viewport.pack(side='left', fill='both', expand=True)
        viewport.configure(yscrollcommand=scrollbar.set)
        root = ttk.Frame(viewport, padding=28, style='Page.TFrame')
        root_window = viewport.create_window((0, 0), window=root, anchor='nw')
        root.bind('<Configure>', lambda e: viewport.configure(scrollregion=viewport.bbox('all')))
        viewport.bind('<Configure>', lambda e: viewport.itemconfigure(root_window, width=e.width))
        hero=tk.Frame(root,bg='#141f31',highlightbackground='#26364f',highlightthickness=1,padx=24,pady=20)
        hero.pack(fill='x',pady=(0,20))
        tk.Label(hero,text='PULSEPLAY  /  ИГРОВОЙ СТРИМИНГ',bg='#141f31',fg='#83e4b1',font=('Segoe UI',9,'bold')).pack(anchor='w')
        self.page_title=tk.Label(hero,text='Играй там, где ты.',bg='#141f31',fg='#f3f6fd',font=('Segoe UI',27,'bold'))
        self.page_title.pack(anchor='w',pady=(8,4))
        self.page_subtitle=tk.Label(hero,text='Подключись к игровому ПК — настройка займёт всего пару минут.',bg='#141f31',fg='#a8b6cb',font=('Segoe UI',11))
        self.page_subtitle.pack(anchor='w')
        self.setup_pairing_card(root)
        self.setup_address(root)
        book = ttk.Notebook(root)
        self.book = book
        book.pack(fill='x')
        client = ttk.Frame(book, padding=24)
        host = ttk.Frame(book, padding=24)
        book.add(client, text='Подключиться')
        book.add(host, text='Мой компьютер')
        internet = ttk.Frame(book, padding=24)
        permissions = ttk.Frame(book, padding=24)
        book.add(internet, text='Интернет')
        book.add(permissions, text='Права хоста')
        self.setup_internet(internet)
        self.setup_permissions(permissions)
        self.navigate(0)
        self.vars = {}
        ttk.Label(client,text='НОВОЕ ПОДКЛЮЧЕНИЕ',foreground='#83e4b1',font=('Segoe UI',10,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,18))
        advanced = ttk.Frame(client)
        advanced.grid(row=12, column=0, columnspan=3, sticky='ew', pady=8)
        advanced.columnconfigure(1, weight=1)
        moonlight_path = self.settings.get('moonlight', '')
        if not Path(moonlight_path).is_file():
            moonlight_path = find_moonlight()
        self.field(advanced, 'moonlight', 'Moonlight.exe', moonlight_path, 0)
        ttk.Button(advanced, text='Выбрать…', command=self.select_exe).grid(row=0, column=2, padx=(8,0))
        self.advanced = advanced
        advanced.grid_remove()
        ttk.Button(client, text='Дополнительные настройки ▾', command=self.toggle_advanced).grid(row=11, column=0, columnspan=3, sticky='w', pady=8)
        self.field(client, 'host', 'Адрес игрового ПК', self.settings.get('host', ''), 1)
        ttk.Button(client, text='Вставить IP', command=self.paste_host).grid(row=1, column=2, padx=(8,0))
        self.field(client, 'app', 'Игра в Sunshine', self.settings.get('app', 'Desktop'), 2)
        ttk.Button(client, text='Подключиться по приглашению хоста', command=self.paste_invite).grid(
            row=9, column=0, columnspan=3, sticky='w', pady=(8, 0))
        help_label(client, 'Профиль', 'preset').grid(row=3, column=0, sticky='w', pady=7)
        preset = ttk.Combobox(client, values=list(PRESETS), state='readonly')
        preset.set('Мои настройки' if self.settings.get('resolution') else 'Баланс • 1080p / 60')
        self.preset_box = preset
        preset.grid(row=3, column=1, columnspan=2, sticky='ew', pady=7)
        preset.bind('<<ComboboxSelected>>', lambda e: self.preset(preset.get()))
        quality = ttk.Frame(advanced)
        quality.grid(row=1, column=0, columnspan=3, sticky='ew', pady=8)
        for col, (key, label, values, default) in enumerate([
            ('resolution', 'Разрешение', ['1280x720','1920x1080','2560x1440','3840x2160'], '1920x1080'),
            ('fps', 'FPS', ['30','60','90','120','144','165','240'], '60'),
            ('bitrate', 'Мбит/с', None, '20'),
            ('codec', 'Кодек', ['auto','H.264','HEVC','AV1'], 'auto')]):
            frame = ttk.Frame(quality)
            frame.grid(row=0, column=col, sticky='ew', padx=(0,10))
            quality.columnconfigure(col, weight=1)
            help_label(frame, label, key).pack(anchor='w')
            self.vars[key] = tk.StringVar(value=str(self.settings.get(key, default)))
            self.vars[key].trace_add('write', lambda *args: self.preset_box.set('Мои настройки'))
            if values:
                widget = ttk.Combobox(frame, values=values, textvariable=self.vars[key], state='readonly', width=12)
            else:
                widget = ttk.Entry(frame, textvariable=self.vars[key], width=8)
            widget.pack(fill='x', pady=5)
        self.low_latency = tk.BooleanVar(value=self.settings.get('low_latency', True) is True)
        self.overlay = tk.BooleanVar(value=self.settings.get('overlay', False) is True)
        self.help_check(advanced, 'Приоритет низкой задержки', 'latency', self.low_latency).grid(row=2,column=0,columnspan=3,sticky='w',pady=4)
        self.help_check(advanced, 'Статистика поверх игры', 'overlay', self.overlay).grid(row=3,column=0,columnspan=3,sticky='w',pady=4)
        self.fullscreen = tk.BooleanVar(value=self.settings.get('fullscreen', True) is True)
        self.help_check(client, 'Открывать игру на весь экран', 'fullscreen', self.fullscreen).grid(row=4, column=0, columnspan=3, sticky='w', pady=8)
        volume_frame = ttk.Frame(client)
        volume_frame.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(5, 2))
        volume_frame.columnconfigure(1, weight=1)
        help_label(volume_frame, 'Громкость у гостя', 'volume').grid(row=0, column=0, sticky='w', padx=(0, 14))
        self.volume = tk.IntVar(value=max(0, min(100, int(self.settings.get('volume', 100)))))
        self.volume_value = tk.StringVar(value=f'{self.volume.get()}%')
        self.volume_scale = ttk.Scale(volume_frame, from_=0, to=100, variable=self.volume,
                                      command=self.update_volume_label)
        self.volume_scale.grid(row=0, column=1, sticky='ew')
        self.volume_scale.bind('<MouseWheel>', self.volume_wheel)
        self.volume_scale.bind('<Button-4>', lambda _event: self.volume_wheel_step(5))
        self.volume_scale.bind('<Button-5>', lambda _event: self.volume_wheel_step(-5))
        ttk.Label(volume_frame, textvariable=self.volume_value, width=5, anchor='e').grid(row=0, column=2, padx=(8, 0))
        ttk.Label(client, text='Меняется сразу. Колесо мыши над ползунком регулирует по 5%.',
                  foreground='#9daac2').grid(row=6, column=0, columnspan=3, sticky='w', pady=(0, 2))
        ttk.Label(client, text='В игре: Ctrl+Alt+Shift+X — полный экран / окно\nCtrl+Alt+Shift+Q — отключиться, оставив игру запущенной', foreground='#9daac2').grid(row=7, column=0, columnspan=3, sticky='w', pady=6)
        help_label(client, 'Как подключиться впервые', 'connect').grid(row=8,column=0,columnspan=3,sticky='w',pady=6)
        buttons = ttk.Frame(client)
        buttons.grid(row=10,column=0,columnspan=3,sticky='ew',pady=(10,0))
        self.pair_button = ttk.Button(buttons, text='Сопряжение · PIN', command=self.pair)
        self.pair_button.pack(side='left')
        ttk.Button(buttons, text='Куда вводить PIN?', command=self.show_pairing_help).pack(side='left', padx=(8, 0))
        self.play_button = ttk.Button(buttons, text='Играть  →', style='Accent.TButton', command=self.play)
        self.play_button.pack(side='left',padx=12,fill='x',expand=True)
        self.stop_button = ttk.Button(buttons, text='Отключиться', command=self.stop, state='disabled')
        self.stop_button.pack(side='right')
        client.columnconfigure(1,weight=1)
        ttk.Label(host, text='Компьютер, на котором запущена игра', font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(0,12))
        steps = ('1. Установи Sunshine на игровой ПК и запусти его.\n\n'
                 '2. Открой настройки, создай учётную запись и добавь игры.\n'
                 '    Для NVIDIA проверь аппаратный кодировщик NVENC.\n\n'
                 '3. На втором устройстве нажми «Сопряжение». Введи показанный\n'
                 '    PIN в разделе PIN панели Sunshine на игровом ПК.\n\n'
                 '4. Для интернета включи UPnP в Sunshine и в роутере.\n'
                 '    Если UPnP недоступен, открой порты вручную (вкладка «Интернет»).\n'
                 '    При CGNAT нужен публичный IP от провайдера.\n\n'
                 'Доступ сохраняется после сопряжения. Удаляй ненужные устройства\n'
                 'в Sunshine. Для прекращения всех подключений останови Sunshine\n'
                 'на игровом ПК. Закрытие PulsePlay на хосте поток не останавливает.')
        ttk.Label(host,text=steps,justify='left',wraplength=720).pack(anchor='w')
        ttk.Label(host, text='Что увидит гость', font=('Segoe UI',12,'bold')).pack(anchor='w', pady=(18,6))
        self.host_scope = tk.StringVar(value='desktop')
        ttk.Radiobutton(host, text='Весь экран компьютера', variable=self.host_scope,
                        value='desktop').pack(anchor='w')
        ttk.Radiobutton(host, text='Только выбранное окно — пока недоступно',
                        variable=self.host_scope, value='window', state='disabled').pack(anchor='w')
        ttk.Label(host, text='Sunshine передаёт дисплей целиком даже при запуске одной игры.\n'
                  'Для скрытия остальных окон нужен отдельный механизм захвата.',
                  foreground='#e6bd8a', wraplength=720).pack(anchor='w', pady=(4,12))
        ttk.Label(host, text='Название приложения в Sunshine (обычно Desktop)').pack(anchor='w')
        self.host_app = tk.StringVar(value='Desktop')
        ttk.Entry(host, textvariable=self.host_app, width=38).pack(anchor='w', pady=6)
        ttk.Label(host, text='Как гость подключится', font=('Segoe UI',12,'bold')).pack(anchor='w', pady=(12,6))
        self.invite_route = tk.StringVar(value='direct')
        ttk.Radiobutton(host, text='Напрямую: публичный IP роутера',
                        variable=self.invite_route, value='direct').pack(anchor='w')
        ttk.Radiobutton(host, text='Через Radmin VPN: адрес хоста из Radmin VPN',
                        variable=self.invite_route, value='radmin').pack(anchor='w')
        ttk.Label(host, text='Для Radmin VPN установи программу на оба ПК, создай сеть и пригласи гостя.\n'
                  'Скопируй адрес своего ПК из окна Radmin VPN и вставь ниже.').pack(anchor='w', pady=(6,2))
        self.radmin_ip = tk.StringVar(value='')
        ttk.Entry(host, textvariable=self.radmin_ip, width=38).pack(anchor='w', pady=4)
        ttk.Button(host, text='Открыть сайт Radmin VPN',
                   command=lambda: webbrowser.open('https://www.radmin-vpn.com/')).pack(anchor='w', pady=4)
        ttk.Button(host, text='Скопировать приглашение для гостя',
                   command=self.copy_invite).pack(anchor='w', pady=6)
        ttk.Label(host, text='Приглашение содержит адрес и название приложения. Это не пароль.\n'
                  'Гость вставляет его на вкладке «Подключиться», затем проходит PIN-сопряжение.',
                  wraplength=720).pack(anchor='w', pady=(0,10))
        ttk.Button(host,text='Открыть панель Sunshine на этом ПК',command=lambda: webbrowser.open('https://localhost:47990')).pack(anchor='w',pady=15)
        links=ttk.Frame(host)
        links.pack(anchor='w')
        ttk.Button(links,text='Скачать Sunshine',command=lambda:webbrowser.open('https://github.com/LizardByte/Sunshine/releases')).pack(side='left')
        ttk.Button(links,text='Скачать Moonlight',command=lambda:webbrowser.open('https://moonlight-stream.org/')).pack(side='left',padx=10)
        self.status=tk.StringVar(value='Готов к настройке • поток ещё не запущен')
        tk.Label(root,textvariable=self.status,bg='#0b1020',fg='#9aaac1',font=('Segoe UI',9),anchor='w',wraplength=800).pack(fill='x',pady=(18,8))
        self.log_toggle=ttk.Button(root,text='Показать журнал подключения',command=self.toggle_log)
        self.log_toggle.pack(anchor='w',pady=(0,8))
        self.log=tk.Text(root,height=5,bg='#0b0e15',fg='#aebbd1',relief='flat',font=('Consolas',10),wrap='word',state='disabled')
        # Log stays collapsed until needed; content is preserved.

        if not self.vars['moonlight'].get():
            self.advanced.grid()
        self.write('PulsePlay 0.8 • Требуются отдельно установленные Moonlight и Sunshine.\nКлиент запускается отдельным окном. Реальная задержка здесь не измерена.')
        self.after(100,self.poll)
        self.after(200,self.refresh_address)
        self.after(500,self.maybe_setup_wizard)
        self.protocol('WM_DELETE_WINDOW',self.close)

    def maybe_setup_wizard(self):
        if not self.settings.get('setup_wizard_completed'):
            self.show_setup_wizard()

    def show_setup_wizard(self):
        dialog = tk.Toplevel(self)
        dialog.title('Первый запуск PulsePlay')
        dialog.geometry('690x600')
        dialog.minsize(600, 480)
        dialog.transient(self)
        dialog.configure(bg='#0b1020')
        body = ttk.Frame(dialog, padding=24, style='Page.TFrame')
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Подготовим подключение', font=('Segoe UI', 20, 'bold'),
                  style='TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(body, text='PulsePlay — оболочка управления подключением. Нужны Sunshine '
                  'на игровом ПК и Moonlight на ПК гостя. Выбери роль для этого компьютера, '
                  'затем нажми установку. Для хоста и гостя понадобится настроить оба ПК.',
                  wraplength=620, justify='left').pack(anchor='w', pady=(0, 14))

        role = tk.StringVar(value='guest')
        ttk.Label(body, text='Какую роль выполняет этот компьютер?',
                  font=('Segoe UI', 12, 'bold')).pack(anchor='w', pady=(0, 4))
        ttk.Radiobutton(body, text='Хост — на этом ПК запускается игра (Sunshine)',
                        variable=role, value='host').pack(anchor='w', pady=3)
        ttk.Radiobutton(body, text='Гость — с этого ПК играют удалённо (Moonlight)',
                        variable=role, value='guest').pack(anchor='w', pady=3)

        status = tk.StringVar()
        ttk.Label(body, textvariable=status, wraplength=590, justify='left').pack(anchor='w', pady=14)

        def refresh():
            sunshine = find_sunshine()
            moonlight = find_moonlight()
            found = sunshine if role.get() == 'host' else moonlight
            requirement = 'Sunshine' if role.get() == 'host' else 'Moonlight'
            def describe(name, path):
                return f'{name}: найдено на этом компьютере.\n  {path}' if path else f'{name}: не найдено.'
            status.set('PulsePlay проверил установленные программы на этом ПК. Искать их в интернете вручную не нужно.\n\n' +
                       describe('Sunshine', sunshine) + '\n' + describe('Moonlight', moonlight) +
                       ('\n\nКнопка ниже установит или переустановит выбранную среду через Winget.' if shutil.which('winget') else
                        '\n\nWinget не найден. Кнопка ниже откроет официальный источник загрузки выбранной среды.'))
            install_button.configure(state='normal',
                                     text=f'Установить / переустановить {requirement}')
            host_help.pack_forget()
            if role.get() == 'host':
                host_help.pack(anchor='w', pady=(6, 0))

        def install():
            if not shutil.which('winget'):
                webbrowser.open('https://apps.microsoft.com/detail/9nblggh4nns1')
                status.set('Открыл страницу Microsoft Store для Установщика приложений. '
                           'Установи его, закрой это окно и нажми «Проверить ещё раз».')
                return
            package = 'LizardByte.Sunshine' if role.get() == 'host' else 'MoonlightGameStreamingProject.Moonlight'
            try:
                subprocess.Popen(['winget', 'install', '--exact', '--force', '--id', package],
                                 creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
                status.set('Открылось окно Winget для установки или переустановки ' + package +
                           '. Следуй запросам в чёрном окне и подтверди установку Windows, если появится запрос. '
                           'После завершения нажми «Проверить программы на ПК». Настройки Sunshine хранятся '
                           'отдельно; переустановка программы может не удалить их.')
            except OSError as exc:
                status.set('Не удалось запустить Winget: ' + str(exc))

        role.trace_add('write', lambda *_: refresh())
        buttons = ttk.Frame(body)
        buttons.pack(side='bottom', fill='x', pady=(18, 0))
        ttk.Button(buttons, text='Проверить программы на ПК', command=refresh).pack(side='left')
        install_button = ttk.Button(buttons, command=install)
        install_button.pack(side='left', padx=8)
        ttk.Button(buttons, text='Куда вводить PIN?', command=self.show_pairing_help).pack(side='left')

        def finish():
            
            self.settings['setup_wizard_completed'] = True
            save_settings(self.settings)
            dialog.destroy()

        ttk.Button(buttons, text='Перейти к подключению', command=lambda: (finish(), self.navigate(0))).pack(side='right')
        host_help = ttk.Label(body, text='После установки нажми «Настройки Sunshine» во вкладке '
                              '«Мой компьютер», создай учётную запись и добавь Desktop. '
                              'Затем подключи гостевой ПК по PIN.', wraplength=590, justify='left')
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        refresh()
        dialog.grab_set()
        dialog.focus_set()

    def help_check(self, parent, text, key, variable):
        row = ttk.Frame(parent)
        ttk.Checkbutton(row, text=text, variable=variable).pack(side='left')
        help_label(row, '', key).pack(side='left')
        return row

    def show_pairing_help(self, parent=None):
        messagebox.showinfo(
            'Куда вводить PIN',
            'PIN вводится на ИГРОВОМ компьютере (хосте), где запущен Sunshine.\n\n'
            '1. Оставь открытым окно Moonlight/PulsePlay на компьютере гостя.\n'
            '2. На игровом ПК открой панель Sunshine: https://localhost:47990\n'
            '3. В меню Sunshine открой PIN и введи код, показанный в окне Moonlight.\n'
            '4. Подтверди сопряжение. После этого вернись к гостю и нажми «Играть».\n\n'
            'Не вводи этот PIN в PulsePlay или в поле адреса. Если игровой ПК другой, '
            'адрес localhost нужно открыть именно на игровом ПК.',
            parent=parent or self,
        )

    def setup_pairing_card(self, parent):
        """Create a persistent PIN card in the main PulsePlay screen."""
        card = ttk.Frame(parent, padding=18, style='Page.TFrame')
        card.pack(fill='x', pady=(0, 14))
        self.pairing_card = card
        ttk.Label(card, text='КОД ДЛЯ ПОДКЛЮЧЕНИЯ', foreground='#83e4b1',
                  font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        ttk.Label(card, text='Передай его хозяину игрового компьютера',
                  font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(4, 2))
        self.pairing_host_text = tk.StringVar(value='')
        ttk.Label(card, textvariable=self.pairing_host_text, foreground='#9aaac1').pack(anchor='w')
        self.pairing_code = tk.StringVar(value='')
        code = tk.Entry(card, textvariable=self.pairing_code, justify='center',
                        font=('Consolas', 40, 'bold'), readonlybackground='#101827',
                        foreground='#83e4b1', relief='flat', state='readonly')
        code.pack(fill='x', pady=(8, 4), ipady=4)
        self.pairing_countdown = tk.StringVar(value='')
        ttk.Label(card, textvariable=self.pairing_countdown, foreground='#83e4b1',
                  font=('Segoe UI', 11, 'bold')).pack(anchor='center', pady=(0, 4))
        self.pairing_instructions = ttk.Label(card, text='', wraplength=760, justify='left')
        self.pairing_instructions.pack(anchor='w', pady=(2, 8))
        buttons = ttk.Frame(card)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Скопировать PIN', style='Accent.TButton',
                   command=lambda: self.copy_pairing_pin(self.pairing_code.get())).pack(side='left')
        ttk.Button(buttons, text='Как ввести PIN?', command=self.show_pairing_help).pack(side='left', padx=8)
        self.pairing_cancel_button = ttk.Button(buttons, text='Отменить сопряжение',
                                                command=self.cancel_pairing)
        self.pairing_cancel_button.pack(side='right')
        card.pack_forget()

    def show_pairing_card(self, host, pin):
        """Show the PIN and its timer in the main window, not a floating dialog."""
        clipboard_status = 'PIN скопирован автоматически.'
        try:
            copy_text_to_clipboard(self, pin)
        except tk.TclError:
            clipboard_status = 'Нажми «Скопировать PIN».'
        self.pairing_host_text.set(f'Игровой компьютер: {host}')
        self.pairing_code.set(pin)
        self.pairing_countdown.set('Осталось 20:00')
        self.pairing_instructions.configure(
            text=clipboard_status + ' На игровом ПК открой Sunshine → PIN и введи этот код. '
                 'Если вы в разных городах — отправь PIN хозяину в чат или продиктуй по звонку. '
                 'Оставь PulsePlay открытой: запрос будет обновляться с тем же кодом.'
        )
        self.pairing_cancel_button.configure(text='Отменить сопряжение', command=self.cancel_pairing)
        self.pairing_card.pack(fill='x', pady=(0, 14), before=self.setup_address_frame)
        self.viewport.yview_moveto(0)
        if self.pairing_context:
            self.pairing_context.update(countdown=self.pairing_countdown,
                                        cancel_button=self.pairing_cancel_button)
            self.update_pairing_countdown()

    def update_pairing_countdown(self):
        context = self.pairing_context
        if not context or not self.pairing_card.winfo_manager():
            return
        remaining = max(0, int(context['deadline'] - time.monotonic()))
        context['countdown'].set(f'Осталось {remaining // 60:02d}:{remaining % 60:02d}')
        if remaining:
            self.after(1000, self.update_pairing_countdown)
        else:
            context['countdown'].set('Время истекло. Создай новый PIN кнопкой «Сопряжение · PIN».')
            context['cancel_button'].configure(text='Скрыть код', command=self.hide_pairing_card)
            self.pairing_context = None
            self.pair_button.configure(state='normal')
            if self.process is None:
                self.play_button.configure(state='normal')
            if self.process is not None and self.process_kind == 'сопряжение':
                self.stop()

    def cancel_pairing(self):
        context, self.pairing_context = self.pairing_context, None
        if self.process is not None and self.process_kind == 'сопряжение':
            self.stop()
        self.hide_pairing_card()
        if self.process is None:
            self.pair_button.configure(state='normal')
            self.play_button.configure(state='normal')

    def hide_pairing_card(self):
        self.pairing_card.pack_forget()

    def retry_pairing(self):
        context = self.pairing_context
        if not context or time.monotonic() >= context['deadline']:
            return
        if self.process is None:
            try:
                context['attempt'] += 1
                self.launch(['pair', context['host'], '--pin', context['pin']], 'сопряжение')
                self.status.set(f'Ожидаю подтверждение на игровом ПК • попытка {context["attempt"]}')
            except (ValueError, OSError) as exc:
                self.write('Не удалось повторить сопряжение: ' + str(exc))
                self.after(3000, self.retry_pairing)

    def finish_pairing(self, result):
        context = self.pairing_context
        if not context:
            return
        if result == 0:
            self.pairing_context = None
            self.status.set('Сопряжение подтверждено • теперь нажми «Играть»')
            context['countdown'].set('Готово! Хост подтвердил подключение. Теперь нажми «Играть».')
            self.pairing_instructions.configure(text='Сопряжение готово. PIN сохранён в Moonlight; нажми «Играть».')
            context['cancel_button'].configure(text='Скрыть код', command=self.hide_pairing_card)
        elif time.monotonic() < context['deadline']:
            self.play_button.configure(state='disabled')
            self.pair_button.configure(state='disabled')
            self.stop_button.configure(state='disabled')
            context['countdown'].set('Запрос обновляется автоматически • тот же PIN остаётся на экране')
            self.status.set('Жду ввод PIN на игровом ПК • PulsePlay повторяет запрос')
            self.after(1500, self.retry_pairing)

    def copy_pairing_pin(self, pin):
        try:
            copy_text_to_clipboard(self, pin)
            self.status.set('PIN скопирован. Введи его на игровом ПК в Sunshine → PIN.')
        except tk.TclError:
            messagebox.showerror('Буфер обмена', 'Не удалось скопировать PIN.')

    def navigate(self, index):
        self.book.select(index)
        titles=['Играй там, где ты.','Твой ПК. Твои игры.','Ближе, чем кажется.','Контроль у тебя.']
        subtitles=['Подключись к игровому ПК. Всё остальное подождёт.',
                    'Подготовь компьютер, который будет запускать игру.',
                    'Настрой доступ между устройствами и проверь маршрут.',
                    'Подготовь общие ограничения ввода на игровом ПК.']
        self.page_title.configure(text=titles[index])
        self.page_subtitle.configure(text=subtitles[index])
        for i,button in enumerate(self.nav_buttons):
            button.configure(bg='#1c2b38' if i==index else '#101827',fg='#83e4b1' if i==index else '#9aaac1')

    def show_log(self):
        self.log.pack(fill='both',expand=True)
        self.log_toggle.configure(text='Скрыть журнал подключения')

    def toggle_log(self):
        if self.log.winfo_ismapped():
            self.log.pack_forget()
            self.log_toggle.configure(text='Показать журнал подключения')
        else:
            self.show_log()

    def toggle_advanced(self):
        if self.advanced.winfo_ismapped():
            self.advanced.grid_remove()
        else:
            self.advanced.grid()

    def paste_host(self):
        try:
            address = validate_host(read_clipboard_text(self))
            self.vars['host'].set(address)
        except (tk.TclError, ValueError):
            messagebox.showerror('Вставить IP', 'Скопируй только IP или имя игрового ПК, без другого текста.')

    def paste_invite(self):
        try:
            host, app = parse_invite(read_clipboard_text(self))
            self.vars['host'].set(host)
            self.vars['app'].set(app)
            moonlight_path = self.vars['moonlight'].get().strip()
            if not Path(moonlight_path).is_file():
                moonlight_path = find_moonlight() or ''
                self.vars['moonlight'].set(moonlight_path)
            self.settings.update(host=host, app=app, moonlight=moonlight_path)
            save_settings(self.settings)
            if moonlight_path:
                self.status.set('Приглашение заполнено • Moonlight найден • нажми «Сопряжение · PIN»')
            else:
                self.status.set('Приглашение заполнено • открываю настройку Moonlight')
                self.after(100, self.show_setup_wizard)
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror('Приглашение', str(exc))

    def copy_invite(self):
        try:
            if self.invite_route.get() == 'radmin':
                address = self.radmin_ip.get()
                if not address.strip():
                    raise ValueError('Введи VPN-адрес своего ПК из окна Radmin VPN.')
            else:
                address = self.own_ip.get()
                if not address:
                    raise ValueError('Сначала получи публичный IPv4 роутера кнопкой «Обновить».')
            invite = make_invite(address, self.host_app.get())
            copy_text_to_clipboard(self, invite)
            self.address_status.set('Приглашение скопировано. Передай его гостю и подтверди PIN в Sunshine.')
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror('Приглашение', str(exc) or 'Сначала получи публичный IP роутера.')

    def persist_settings(self):
        values = {key:var.get() for key,var in self.vars.items()}
        values.update(fullscreen=self.fullscreen.get(), low_latency=self.low_latency.get(), overlay=self.overlay.get(), volume=self.volume.get())
        values['setup_wizard_completed'] = bool(self.settings.get('setup_wizard_completed'))
        self.settings.update(values)
        save_settings(values)

    def update_volume_label(self, value):
        volume = max(0, min(100, int(float(value))))
        self.volume.set(volume)
        self.volume_value.set(f'{volume}%')
        if hasattr(self, '_volume_apply_job'):
            self.after_cancel(self._volume_apply_job)
        self._volume_apply_job = self.after(150, self.apply_guest_volume)

    def volume_wheel(self, event):
        if event.delta:
            self.volume_wheel_step(5 if event.delta > 0 else -5)
        return 'break'

    def volume_wheel_step(self, amount):
        self.volume.set(max(0, min(100, int(self.volume.get()) + amount)))
        self.update_volume_label(self.volume.get())
        return 'break'

    def apply_guest_volume(self):
        self._volume_apply_job = None
        if self.process is None or self.process_kind != 'игровой сеанс' or self.process.poll() is not None:
            return
        try:
            from audio_control import set_process_volume
            if set_process_volume(self.process.pid, self.volume.get()):
                self.status.set(f'Громкость Moonlight: {self.volume.get()}%')
            else:
                # Windows creates the audio session after the stream starts.
                self._volume_apply_job = self.after(700, self.apply_guest_volume)
        except Exception as exc:
            self.status.set('Не удалось изменить громкость Moonlight: ' + str(exc))

    def setup_address(self, parent):
        card = ttk.Frame(parent,padding=18)
        self.setup_address_frame = card
        card.pack(fill='x', pady=(0, 14))
        help_label(card, 'МОЙ КОМПЬЮТЕР / IP ДЛЯ ПОДКЛЮЧЕНИЯ', 'own_ip').grid(row=0, column=0, columnspan=3, sticky='w')
        self.own_ip = tk.StringVar(value='')
        self.address_status = tk.StringVar(value='Получаю адрес…')
        self.address_busy = False
        ttk.Entry(card, textvariable=self.own_ip, state='readonly', width=30,font=('Consolas',17,'bold')).grid(row=1, column=0, sticky='ew', pady=6)
        self.copy_ip_button = ttk.Button(card, text='Копировать IP', command=self.copy_address, state='disabled')
        self.copy_ip_button.grid(row=1, column=1, padx=8)
        self.refresh_ip_button = ttk.Button(card, text='Обновить', command=self.refresh_address)
        self.refresh_ip_button.grid(row=1, column=2)
        ttk.Label(card, textvariable=self.address_status, wraplength=740, foreground='#9daac2').grid(row=2, column=0, columnspan=3, sticky='w')
        card.columnconfigure(0, weight=1)

    def refresh_address(self):
        if self.address_busy:
            return
        self.address_busy = True
        self.own_ip.set('')
        self.copy_ip_button.configure(state='disabled')
        self.refresh_ip_button.configure(state='disabled')
        self.address_status.set('Запрашиваю публичный IPv4 у домашнего роутера…')
        def worker():
            try:
                self.events.put(('own_ip', (own_address(), None)))
            except Exception as exc:
                self.events.put(('own_ip', ('', str(exc)[:200])))
        threading.Thread(target=worker, daemon=True).start()

    def copy_address(self):
        address = self.own_ip.get()
        if not address:
            return
        try:
            copy_text_to_clipboard(self, address)
            self.address_status.set('IP скопирован. Отправь его доверенному человеку; для подключения нужны открытые порты и PIN Sunshine.')
        except tk.TclError:
            self.address_status.set('Не удалось скопировать. Выдели адрес в поле и нажми Ctrl+C.')

    def setup_internet(self, frame):
        text = ('Прямое подключение через интернет — без VPN и сервера PulsePlay\n\n'
                '1. На игровом ПК запусти Sunshine. В его панели открой Network\n'
                '    и включи UPnP. На домашнем роутере тоже должен работать UPnP.\n'
                '2. Нажми «Обновить» в карточке IP. Если показан публичный адрес,\n'
                '    скопируй его и передай доверенному человеку.\n'
                '3. На втором ПК, в другой сети, введи этот IP в «Подключиться»,\n'
                '    нажми «Проверить», затем выполни сопряжение по PIN и играй.\n\n'
                'Если UPnP не работает, направь на игровой ПК порты вручную:\n'
                'TCP 47984, 47989, 48010; UDP 47998, 47999, 48000, 48002, 48010.\n'
                'Закрепи локальный IP игрового ПК в DHCP роутера.\n'
                'Если WAN IP роутера непубличный (CGNAT/двойной NAT), попроси\n'
                'публичный IPv4 у провайдера. Без него этот прямой способ не работает.\n\n'
                'Не открывай веб-панель Sunshine (TCP 47990) в интернет.\n'
                'Проверка TCP не проверяет UDP и видеопоток; проверяй из другой сети.\n'
                'После теста отключи UPnP или убери правила роутера, если доступ\n'
                'больше не нужен. Удаляй ненужные сопряжённые клиенты в Sunshine.')
        help_label(frame, 'Подключение через интернет', 'network').pack(anchor='w',pady=(0,12))
        ttk.Label(frame, text=text, wraplength=720, justify='left').pack(anchor='w')
        ttk.Button(frame, text='Настройки Sunshine на этом ПК', command=lambda: webbrowser.open('https://localhost:47990')).pack(anchor='w', pady=8)
        ttk.Label(frame, text='Если провайдер — Ростелеком и нет публичного IP:',
                  foreground='#e6bd8a').pack(anchor='w', pady=(16,4))
        ttk.Button(frame, text='Скопировать запрос в Ростелеком',
                   command=self.copy_provider_request).pack(anchor='w', pady=4)
        self.diagnostic_button = ttk.Button(frame, text='Проверить указанный игровой ПК', command=self.check_network)
        self.diagnostic_button.pack(anchor='w', pady=8)
        ttk.Label(frame, text='Сначала введи IP или имя игрового ПК во вкладке «01 Подключиться» → «Адрес игрового ПК». '
                  'Затем нажми эту кнопку. Результат появится в журнале PulsePlay ниже.',
                  wraplength=720, justify='left', foreground='#9aaac1').pack(anchor='w', padx=(2, 0))
        ttk.Label(frame, text='Звук игры передаёт Sunshine вместе с изображением.',
                  font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(16, 4))
        ttk.Label(frame, text='Если у гостя нет звука: в Sunshine → Audio/Video проверь '
                  '«Stream Audio» (включено), на хосте выбери работающий аудиовыход, '
                  'а на ПК гостя проверь громкость Moonlight и устройство вывода Windows. '
                  'При необходимости укажи Audio Sink в Sunshine.',
                  wraplength=720, justify='left').pack(anchor='w')

    def copy_provider_request(self):
        request = ('Здравствуйте! У меня домашний интернет Ростелекома. Для прямого '
                   'подключения к моему игровому ПК из другой сети нужен публичный '
                   'IPv4-адрес без CGNAT и возможность входящих TCP/UDP-соединений. '
                   'Есть ли такая услуга по моему адресу (например, «Фиксированный IP»)? '
                   'Сколько стоит подключение и ежемесячная плата? '
                   'Будет ли публичный адрес назначен моему роутеру и смогу ли я '
                   'настроить проброс портов или UPnP?')
        try:
            copy_text_to_clipboard(self, request)
            self.show_log()
            self.write('Запрос Ростелекому скопирован. Отправь его через официальный '
                       'личный кабинет или задай оператору по телефону.')
        except tk.TclError:
            messagebox.showerror('Буфер обмена', 'Не удалось скопировать запрос.')

    def check_network(self):
        try:
            host = validate_host(self.vars['host'].get())
        except ValueError as exc:
            messagebox.showerror('Адрес ПК', str(exc))
            return
        self.diagnostic_button.configure(state='disabled')
        self.write('Проверяю TCP-порты Sunshine; это может занять до 10 секунд…')
        def worker():
            try:
                result = diagnose(host)
            except Exception as exc:
                result = 'Не удалось выполнить проверку: ' + str(exc)
            self.events.put(('diagnostic', result))
        threading.Thread(target=worker, daemon=True).start()

    def setup_permissions(self, frame):
        help_label(frame, 'Общие ограничения Sunshine', 'permissions').pack(anchor='w')
        ttk.Label(frame, text='Профиль применяется ко ВСЕМ клиентам. Персональных прав пока нет.\n'
            'Галочки ниже готовят настройки; сами по себе они не блокируют ввод.\n'
            'Примени значения на хосте в Sunshine → Configuration → Input,\n'
            'сохрани, перезапусти Sunshine и проверь запреты со второго ПК.',
            wraplength=720, justify='left').pack(anchor='w', pady=12)
        self.host_rights = {}
        for key, label in [('keyboard', 'Разрешить клавиатуру'), ('mouse', 'Разрешить мышь'), ('controller', 'Разрешить геймпад')]:
            value = tk.BooleanVar(value=False)
            self.host_rights[key] = value
            self.help_check(frame, label, key, value).pack(anchor='w', pady=6)
        ttk.Label(frame, text='Все выключено = просмотр. Native pen/touch также нужно выключить.\n'
            'Видимость рабочего стола этими настройками не ограничивается.\n'
            'Срочно прекратить доступ: останови Sunshine на игровом ПК.').pack(anchor='w', pady=14)
        ttk.Button(frame, text='Показать / скопировать значения', command=self.copy_profile).pack(anchor='w', pady=6)
        ttk.Button(frame, text='Настроить Sunshine на этом ПК', command=lambda: webbrowser.open('https://localhost:47990')).pack(anchor='w', pady=6)

    def copy_profile(self):
        profile = host_profile(**{key:value.get() for key,value in self.host_rights.items()})
        copy_text_to_clipboard(self, profile)
        self.show_log()
        self.write(profile + 'Профиль скопирован, но ещё НЕ применён. Внеси значения в Sunshine на хосте.')

    def field(self,parent,key,label,default,row):
        help_label(parent,label,key).grid(row=row,column=0,sticky='w',padx=(0,14),pady=7)
        self.vars[key]=tk.StringVar(value=default if isinstance(default,str) else '')
        ttk.Entry(parent,textvariable=self.vars[key]).grid(row=row,column=1,sticky='ew',pady=7)

    def select_exe(self):
        path=filedialog.askopenfilename(title='Выберите установленный Moonlight.exe',filetypes=[('Moonlight','*.exe'),('Все файлы','*')])
        if path:
            self.vars['moonlight'].set(path)

    def preset(self,name):
        for key,value in zip(('resolution','fps','bitrate'),PRESETS[name]):
            self.vars[key].set(str(value))
        self.preset_box.set(name)

    def write(self,text):
        self.log.configure(state='normal')
        self.log.insert('end',text+'\n')
        if int(self.log.index('end-1c').split('.')[0]) > 300:
            self.log.delete('1.0','101.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def executable(self):
        path=Path(self.vars['moonlight'].get().strip())
        if not path.is_file() or (os.name=='nt' and path.suffix.lower()!='.exe'):
            raise ValueError('Установи Moonlight и выбери его исполняемый файл.')
        return str(path.resolve())

    def launch(self,args,kind):
        if self.process is not None:
            raise ValueError('Сначала заверши текущее действие.')
        executable=self.executable()
        self.persist_settings()
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        self.process=subprocess.Popen([executable,*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,creationflags=flags,shell=False)
        self.process_kind=kind
        self.stopping=False
        self.status.set('Moonlight запущен • '+kind+' • подключение проверяй в окне Moonlight')
        self.play_button.configure(state='disabled')
        self.pair_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        process=self.process
        def reader():
            # Stream output without touching Tk from the worker thread.
            for line in iter(process.stdout.readline,b''):
                self.events.put(('log',line.decode('utf-8',errors='replace').rstrip()))
            process.stdout.close()
            self.events.put(('exit',process.wait()))
        threading.Thread(target=reader,daemon=True).start()

    def pair(self):
        try:
            if self.pairing_context:
                self.pairing_card.pack(fill='x', pady=(0, 14), before=self.setup_address_frame)
                self.viewport.yview_moveto(0)
                return
            host=validate_host(self.vars['host'].get())
            pin=f'{secrets.randbelow(10000):04d}'
            self.pairing_context = {
                'host': host, 'pin': pin, 'deadline': time.monotonic() + 20 * 60,
                'attempt': 1,
            }
            self.launch(['pair',host,'--pin',pin],'сопряжение')
            self.status.set('Ожидаю подтверждение PIN на игровом компьютере')
            self.show_pairing_card(host, pin)
        except (ValueError,OSError) as exc:
            self.pairing_context = None
            messagebox.showerror('Сопряжение',str(exc))

    def play(self):
        try:
            values={key:self.vars[key].get() for key in ('host','app','resolution','fps','bitrate','codec')}
            self.launch(stream_args(**values,low_latency=self.low_latency.get(),overlay=self.overlay.get(),fullscreen=self.fullscreen.get()),'игровой сеанс')
            self.apply_guest_volume()
        except (ValueError,OSError) as exc:
            messagebox.showerror('Запуск',str(exc))

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.stopping=True
                self.process.terminate()
                self.status.set('Отключение локального клиента…')
            except OSError as exc:
                self.write(str(exc))

    def poll(self):
        for _ in range(100):
            try:
                kind,value=self.events.get_nowait()
            except queue.Empty:
                break
            if kind=='own_ip':
                address, error = value
                self.address_busy = False
                self.refresh_ip_button.configure(state='normal')
                self.own_ip.set(address)
                self.copy_ip_button.configure(state='normal' if address else 'disabled')
                self.address_status.set(error or 'На игровом ПК скопируй IP. Для подключения нужны открытые порты и PIN Sunshine.')
            elif kind=='diagnostic':
                self.show_log()
                self.write(value)
                self.diagnostic_button.configure(state='normal')
            elif kind=='log':
                if self.process_kind != 'сопряжение':
                    self.write(value)
            else:
                finished_kind = self.process_kind
                label='Действие отменено' if self.stopping else ('Moonlight завершён' if value==0 else 'Ошибка Moonlight')
                self.status.set(f'{label} • код {value}')
                if value != 0 and not self.stopping:
                    self.show_log()
                self.write(f'{label} ({self.process_kind}), код {value}.')
                self.process=None
                self.play_button.configure(state='normal')
                self.pair_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                if finished_kind == 'сопряжение' and self.pairing_context:
                    self.finish_pairing(value)
        self.after(100,self.poll)

    def close(self):
        if self.process is not None and self.process.poll() is None:
            if not messagebox.askyesno('Выход','Отключить запущенный клиент Moonlight и закрыть PulsePlay?'):
                return
            self.stop()
        try:
            self.persist_settings()
        except OSError:
            pass
        self.destroy()

if __name__=='__main__':
    App().mainloop()
