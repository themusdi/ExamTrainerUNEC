"""Dialogs: question viewer (read a question, toggle bookmarks, edit the note)."""
import tkinter as tk
from tkinter import ttk

from ui import widgets
from ui.theme import P

LETTERS = 'ABCDEFGH'


class QuestionViewer(tk.Toplevel):
    def __init__(self, app, bank, num, on_change=None):
        super().__init__(app)
        self.app, self.bank, self.num, self.on_change = app, bank, num, on_change
        self.keep = []
        self.title(f'Question #{num}')
        self.geometry('760x640')
        self.configure(bg=P['bg'])
        self.transient(app)
        self.bind('<Escape>', lambda e: self.destroy())
        self.build()

    def build(self):
        for w in self.winfo_children():
            w.destroy()
        self.keep = []
        db, bank, num = self.app.db, self.bank, self.num
        qs = db.get_q(bank.pdf_id, bank.fp(num))
        bar = tk.Frame(self, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        bar.pack(side='bottom', fill='x')
        row = tk.Frame(bar, bg=P['card'], padx=12, pady=10)
        row.pack(fill='x')
        fav, hard = bool(qs and qs['favorite']), bool(qs and qs['difficult'])
        note = (qs['note'] if qs else '') or ''
        ttk.Button(row, text='★ Favourite ✓' if fav else '★ Favourite', command=lambda: self.toggle('favorite')).pack(side='left')
        ttk.Button(row, text='🔥 Difficult ✓' if hard else '🔥 Difficult', command=lambda: self.toggle('difficult')).pack(side='left', padx=6)
        ttk.Button(row, text='📝 Edit note' if note else '📝 Add note', command=self.edit_note).pack(side='left')
        ttk.Button(row, text='Close', command=self.destroy).pack(side='right')
        cv, area = widgets.make_scroll(self)
        stem, opts = bank.load(num)
        wrap = 640
        widgets.question_card(area, stem, wrap, self.keep, header=f'#{num}')
        if note:
            tk.Label(area, text='📝 ' + note, bg=P['bg'], fg=P['muted'], wraplength=wrap, justify='left').pack(anchor='w', padx=14)
        for k, (ok, blocks) in enumerate(opts):
            widgets.option_row(area, LETTERS[k], blocks, wrap, 'ok' if ok else 'norm', self.keep)

    def toggle(self, field):
        db, bank = self.app.db, self.bank
        qs = db.get_q(bank.pdf_id, bank.fp(self.num))
        db.set_q_field(bank.pdf_id, bank.fp(self.num), self.num, field, not (qs and qs[field]))
        self.build()
        if self.on_change:
            self.on_change()

    def edit_note(self):
        db, bank = self.app.db, self.bank
        qs = db.get_q(bank.pdf_id, bank.fp(self.num))
        new = widgets.edit_note(self, f'Note for question #{self.num}', (qs['note'] if qs else '') or '')
        if new is not None:
            db.set_q_field(bank.pdf_id, bank.fp(self.num), self.num, 'note', new)
            self.build()
            if self.on_change:
                self.on_change()
