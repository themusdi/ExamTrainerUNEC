"""Base class of all screens: a Frame that can rebuild itself (theme / font change)."""
import tkinter as tk

from ui.theme import P


class Screen(tk.Frame):
    def __init__(self, master, app, **kw):
        super().__init__(master, bg=P['bg'])
        self.app = app
        self.db = app.db
        self.kw = kw
        self.keep = []                 # PhotoImages must stay referenced
        self.build()

    def build(self):
        raise NotImplementedError

    def rebuild(self):
        self.configure(bg=P['bg'])
        for w in self.winfo_children():
            w.destroy()
        self.keep = []
        self.build()

    def wrap(self):
        return max(420, self.winfo_width() - 150)
