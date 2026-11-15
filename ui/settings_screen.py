"""Preferences: theme, font size, exam defaults, backups and data management."""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import config
from exam_engine import MODES, MODE_ORDER
from ui import widgets
from ui.base import Screen
from ui.theme import P
from ui.widgets import card, label


class SettingsScreen(Screen):
    def build(self):
        st = self.app.settings
        cv, inner = widgets.make_scroll(self)
        f = tk.Frame(inner, bg=P['bg'])
        f.pack(fill='both', expand=True, padx=32, pady=24)
        widgets.heading(f, 'Settings', f'{config.APP_NAME} {config.APP_VERSION}')

        c = card(f)
        label(c, 'Appearance', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 8))
        self.v_theme = tk.StringVar(value=st.get('theme'))
        r = tk.Frame(c, bg=P['card'])
        r.pack(anchor='w')
        for val, txt in (('light', '☀  Light'), ('dark', '🌙  Dark')):
            ttk.Radiobutton(r, text=txt, value=val, variable=self.v_theme, style='Card.TRadiobutton',
                            command=lambda: self.app.apply_theme(self.v_theme.get())).pack(side='left', padx=(0, 16))
        r = tk.Frame(c, bg=P['card'])
        r.pack(anchor='w', pady=(12, 0))
        label(r, 'Font size', bg=P['card']).pack(side='left', padx=(0, 10))
        ttk.Button(r, text='−', style='Small.TButton', command=lambda: self.app.set_font_size(self.app.fonts.size - 1)).pack(side='left')
        label(r, f'  {st.get("font_size")} pt  ', self.app.fonts.bold, bg=P['card']).pack(side='left')
        ttk.Button(r, text='+', style='Small.TButton', command=lambda: self.app.set_font_size(self.app.fonts.size + 1)).pack(side='left')
        label(r, '    (Ctrl + / Ctrl − works everywhere)', fg=P['muted'], bg=P['card']).pack(side='left')

        c = card(f)
        label(c, 'Exams', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 8))
        self.v_full = tk.BooleanVar(value=st.get('fullscreen_exams'))
        self.v_conf = tk.BooleanVar(value=st.get('confirm_finish'))
        self.v_auto = tk.BooleanVar(value=st.get('autosave_sessions'))
        self.v_shuf = tk.BooleanVar(value=st.get('default_shuffle'))
        for var, key, text in ((self.v_full, 'fullscreen_exams', 'Start exams in fullscreen mode (F11 / Esc to leave)'),
                               (self.v_conf, 'confirm_finish', 'Ask before finishing an exam with unanswered questions'),
                               (self.v_auto, 'autosave_sessions', 'Save the running exam automatically so it can be resumed after a crash'),
                               (self.v_shuf, 'default_shuffle', 'Shuffle the variants by default')):
            ttk.Checkbutton(c, text=text, variable=var, style='Card.TCheckbutton',
                            command=lambda v=var, k=key: st.set(k, bool(v.get()))).pack(anchor='w', pady=2)
        r = tk.Frame(c, bg=P['card'])
        r.pack(anchor='w', pady=(10, 0))
        label(r, 'Default mode', bg=P['card']).pack(side='left', padx=(0, 10))
        self.cb_mode = ttk.Combobox(r, state='readonly', width=14, values=[MODES[m]['label'] for m in MODE_ORDER])
        self.cb_mode.current(MODE_ORDER.index(st.get('default_mode')) if st.get('default_mode') in MODE_ORDER else 0)
        self.cb_mode.pack(side='left')
        self.cb_mode.bind('<<ComboboxSelected>>', lambda e: st.set('default_mode', MODE_ORDER[self.cb_mode.current()]))
        label(r, '     Default number of questions', bg=P['card']).pack(side='left', padx=(0, 10))
        self.v_count = tk.StringVar(value=str(st.get('default_count')))
        sp = ttk.Spinbox(r, from_=1, to=9999, textvariable=self.v_count, width=7, command=self._count)
        sp.pack(side='left')
        sp.bind('<FocusOut>', lambda e: self._count())

        c = card(f)
        label(c, 'Your data', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 4))
        label(c, f'Stored in: {self.app.paths.base}', fg=P['muted'], bg=P['card'], wraplength=760, justify='left').pack(anchor='w')
        label(c, 'History, bookmarks, notes and statistics are kept in one database file. A backup is made automatically '
                 'once a day and before any update of the data format.', fg=P['muted'], bg=P['card'], wraplength=760,
              justify='left').pack(anchor='w', pady=(4, 8))
        r = tk.Frame(c, bg=P['card'])
        r.pack(anchor='w')
        ttk.Button(r, text='Back up now', command=self.backup).pack(side='left')
        ttk.Button(r, text='Open data folder', command=self.open_folder).pack(side='left', padx=8)
        ttk.Button(r, text='Clear exam history…', command=self.clear_history).pack(side='left')
        self.lbl = label(c, '', fg=P['okb'], bg=P['card'])
        self.lbl.pack(anchor='w', pady=(8, 0))

    def _count(self):
        try:
            n = int(self.v_count.get())
            if n < 1:
                raise ValueError
            self.app.settings.set('default_count', n)
        except ValueError:
            self.v_count.set(str(self.app.settings.get('default_count')))

    def backup(self):
        try:
            p = self.db.backup('manual')
            self.lbl.configure(text=f'Backup saved: {p.name}', fg=P['okb'])
        except Exception as e:
            self.lbl.configure(text=f'Backup failed: {e}', fg=P['badb'])

    def open_folder(self):
        path = str(self.app.paths.base)
        try:
            if sys.platform == 'win32':
                os.startfile(path)                       # noqa
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            messagebox.showinfo('Data folder', f'{path}\n\n({e})')

    def clear_history(self):
        if not messagebox.askyesno('Clear exam history', 'Delete ALL saved exams and their statistics?\n\n'
                                   'A backup is created first. Notes, bookmarks and mistake lists are kept.'):
            return
        if not messagebox.askyesno('Clear exam history', 'Are you really sure? This cannot be undone '
                                   '(except by restoring the backup).', icon='warning'):
            return
        self.db.clear_history()
        self.lbl.configure(text='Exam history cleared. A backup was saved in the backup folder.', fg=P['okb'])
