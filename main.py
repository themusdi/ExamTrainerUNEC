"""Exam Trainer - entry point."""
import sys


def main():
    if sys.platform == 'win32':                      # crisp text on high-DPI Windows screens
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    try:
        import tkinter  # noqa: F401
        import pdfplumber, pypdfium2, PIL  # noqa: F401,E401
    except ImportError as e:
        msg = f'A required package is missing: {e.name}\n\nInstall everything with:\n    pip install -r requirements.txt'
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror('Exam Trainer', msg)
        except Exception:
            print(msg)
        raise SystemExit(1)
    from ui.app import App
    App().mainloop()


if __name__ == '__main__':
    main()
