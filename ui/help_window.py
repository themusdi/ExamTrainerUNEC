"""'How to use' window: getting started, every shortcut, tips."""
import tkinter as tk
from tkinter import ttk

from ui import widgets
from ui.theme import P

KEYS = [
    ('During the exam', [
        (['A', 'B', 'C', 'D', 'E'], 'Choose that variant (press again to clear it)'),
        (['1', '2', '3', '4', '5'], 'Same as A - E'),
        (['→', 'Enter'], 'Next question (the last one: finish)'),
        (['←'], 'Previous question'),
        (['Home', 'End'], 'First / last question'),
        (['M'], 'Mark / unmark for review'),
        (['S'], 'Favourite (star) the question'),
        (['X'], 'Mark the question as difficult'),
        (['N'], 'Write / edit your note'),
        (['O'], 'Overview grid of all questions'),
        (['Ctrl', 'Enter'], 'Finish the exam'),
    ]),
    ('Everywhere', [
        (['F1'], 'Open this guide'),
        (['F2'], 'Switch light / dark theme'),
        (['F11'], 'Fullscreen on / off (Esc also leaves it)'),
        (['Ctrl', '+'], 'Bigger text'),
        (['Ctrl', '−'], 'Smaller text'),
        (['Esc'], 'Close this guide, the overview or a dialog'),
    ]),
    ('New exam screen', [(['Enter'], 'Start the exam')]),
    ('Mouse', [(['Click'], 'Choose a variant, press a button, jump in the overview'),
               (['Double-click'], 'Open a row in Revision, Bookmarks and History'),
               (['Wheel'], 'Scroll')]),
]

STEPS = [
    ('Add your PDF', 'Open PDF Library, press "Add PDF(s)…". Questions start with a number ("12. text"); each variant '
                     'starts with • (wrong) or √ (correct). Pictures and formulas are supported.'),
    ('Start an exam', 'Press "New exam", choose the PDF, a mode and its settings. Type which questions to use: 7, 5-61 or '
                      '1,5-61,69. Empty = all.'),
    ('Modes', 'Standard · Timed (whole-exam limit) · Practice (instant feedback) · Sequential (original order) · '
              'Endless (no repeats until the pool is empty) · Survival (ends after the first mistake).'),
    ('Answer and mark', 'Click a variant or press its key. Mark doubtful questions (M), star favourites (S), flag difficult '
                        'ones (X), write notes (N). Everything is saved on this computer.'),
    ('Review', 'After finishing, filter wrong / unanswered / marked, retry only your mistakes, copy their numbers or '
               'export the result as a PDF.'),
    ('Revision', 'Wrong and unanswered questions are remembered. Open "Revision" to practise them; a correct answer in '
                 'a revision exam removes the question from the mistake list (its history stays).'),
    ('Pause any time', 'Leave a running exam with ✕ Exit → Yes, and resume it from the Home page - even after closing the program.'),
]

TIPS = [
    'Statistics, history and exports (PDF report, CSV, JSON) are in their own pages in the sidebar.',
    'If you edit a PDF, Exam Trainer notices, re-reads it and keeps your notes and statistics with the right questions.',
    'Removing a PDF from the library never deletes the file - and your data returns if you add it again.',
    'In Practice and Survival mode an answer is locked once chosen. In the other modes you can change it until you finish.',
    'The window is resizable. Use F11 for a distraction-free fullscreen exam.',
    'A backup of your data is created automatically every day (Settings → Your data).',
]


class HelpWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title('How to use - Exam Trainer')
        self.geometry('760x680')
        self.minsize(520, 420)
        self.configure(bg=P['bg'])
        self.transient(app)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda e: self.close())
        F = app.fonts
        tk.Label(self, text='How to use Exam Trainer', font=F.title, bg=P['bg'], fg=P['text']).pack(anchor='w', padx=24, pady=(18, 10))
        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=16, pady=(0, 8))

        def tab(title):
            fr = tk.Frame(nb, bg=P['card'])
            nb.add(fr, text=title)
            cv, inner = widgets.make_scroll(fr, P['card'])
            body = tk.Frame(inner, bg=P['card'])
            body.pack(fill='x', padx=22, pady=16)
            return body

        b = tab('Getting started')
        for i, (title, text) in enumerate(STEPS, 1):
            r = tk.Frame(b, bg=P['card'])
            r.pack(fill='x', pady=7)
            widgets.badge(r, str(i)).pack(side='left', anchor='n', padx=(0, 12))
            col = tk.Frame(r, bg=P['card'])
            col.pack(side='left', fill='x', expand=True)
            tk.Label(col, text=title, font=F.bold, bg=P['card'], fg=P['text']).pack(anchor='w')
            tk.Label(col, text=text, wraplength=570, justify='left', bg=P['card'], fg=P['muted']).pack(anchor='w', pady=(2, 0))

        b = tab('Keyboard & mouse')
        for section, rows in KEYS:
            tk.Label(b, text=section, font=F.h2, bg=P['card'], fg=P['text']).pack(anchor='w', pady=(12, 4))
            for keys, what in rows:
                r = tk.Frame(b, bg=P['card'])
                r.pack(fill='x', pady=3)
                kf = tk.Frame(r, bg=P['card'], width=210, height=30)
                kf.pack(side='left', anchor='n')
                kf.pack_propagate(False)
                sep = '+' if keys[0] == 'Ctrl' else ('' if all(len(k) == 1 for k in keys) else 'or')
                for j, k in enumerate(keys):
                    if j and sep:
                        tk.Label(kf, text=sep, bg=P['card'], fg=P['muted']).pack(side='left', padx=4)
                    elif j:
                        tk.Frame(kf, width=4, bg=P['card']).pack(side='left')
                    tk.Label(kf, text=k, font=F.key, bg=P['sel'], fg=P['accent'], padx=7, pady=2,
                             highlightthickness=1, highlightbackground=P['border']).pack(side='left')
                tk.Label(r, text=what, wraplength=420, justify='left', bg=P['card'], fg=P['text']).pack(side='left', anchor='n', pady=3)

        b = tab('Tips')
        for t in TIPS:
            r = tk.Frame(b, bg=P['card'])
            r.pack(fill='x', pady=6)
            tk.Label(r, text='💡', bg=P['card']).pack(side='left', anchor='n', padx=(0, 10))
            tk.Label(r, text=t, wraplength=600, justify='left', bg=P['card'], fg=P['text']).pack(side='left')
        ttk.Button(self, text='Got it', style='Accent.TButton', command=self.close).pack(pady=(4, 16))
        self.focus_set()

    def close(self):
        self.app.help_win = None
        self.destroy()
