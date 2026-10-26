"""Double-click launcher: report startup failures in a native Windows dialog."""
import os
from pathlib import Path
import traceback

def main():
    try:
        from app import App
        App().mainloop()
    except Exception:
        folder = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PulsePlay'
        detail = traceback.format_exc()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / 'startup-error.log'
            path.write_text(detail, encoding='utf-8')
            message = 'Не удалось открыть PulsePlay. Подробности сохранены:\n' + str(path)
        except OSError:
            message = 'Не удалось открыть PulsePlay:\n' + detail[-1500:]
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'PulsePlay — ошибка запуска', 16)
        else:
            print(message)

if __name__ == '__main__':
    main()
