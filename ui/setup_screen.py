"""New exam: choose a PDF, a mode and configure it.  Also receives presets from Revision / Bookmarks."""
import tkinter as tk
from tkinter import messagebox, ttk

from exam_engine import MODES, MODE_ORDER, ExamConfig, build_pool
from ui import widgets
from ui.base import Screen
from ui.theme import P
from ui.widgets import card, chip, empty_state, label


class SetupScreen(Screen):
    """kw: pdf_id (preselect), preset = dict(pool=[numbers], source=, source_label=, revision=)."""

    def build(self):
        st = self.app.settings
        self.preset = self.kw.get('preset')
        self.pdfs = self.db.list_pdfs()
        self.bank = None
        self.pool = []
        cv, inner = widgets.make_scroll(self)
        f = tk.Frame(inner, bg=P['bg'])
        f.pack(fill='both', expand=True, padx=32, pady=24)
        widgets.heading(f, 'New exam', 'Choose a PDF, pick a mode and configure it.')
        if not self.pdfs:
            empty_state(f, '📚', 'No PDF in the library yet', 'Add a PDF first - then you can start an exam.',
                        'Open the PDF Library', lambda: self.app.navigate('library', add=True))
            return
        # variables survive mode switches
        self.v_mode = tk.StringVar(value=self.kw.get('mode') or st.get('default_mode'))
        self.v_range = tk.StringVar(value=st.get('last_range'))
        self.lbl_pool = None
        self.v_range.trace_add('write', lambda *a: self.update_pool())
        self.v_count = tk.StringVar(value=str(st.get('default_count')))
        self.v_shuffle = tk.BooleanVar(value=st.get('default_shuffle'))
        self.v_minutes = tk.StringVar(value='30')
        self.v_lives = tk.StringVar(value='1')

        c = card(f)
        self.step(c, '1', 'PDF')
        want = self.kw.get('pdf_id') or st.get('last_pdf_id')
        idx = next((i for i, p in enumerate(self.pdfs) if p['id'] == want), 0)
        self.cb = ttk.Combobox(c, state='readonly', values=[self._pdf_text(p) for p in self.pdfs])
        self.cb.current(idx)
        self.cb.pack(fill='x')
        self.cb.bind('<<ComboboxSelected>>', lambda e: self.load_selected())
        self.lbl_load = label(c, '', fg=P['muted'], bg=P['card'])
        self.lbl_load.pack(anchor='w', pady=(6, 0))

        c = card(f)
        self.step(c, '2', 'Mode')
        self.mode_flow = widgets.FlowFrame(c, 230, bg=P['card'])
        self.mode_flow.pack(fill='x')
        self.mode_cards = {}
        for m in MODE_ORDER:
            self.mode_flow.add(self._mode_card(self.mode_flow, m))
        self._paint_modes()

        self.cfg_outer = tk.Frame(f, bg=P['bg'])
        self.cfg_outer.pack(fill='x')
        self.load_selected()

    @staticmethod
    def _pdf_text(p):
        return f'{p["name"]}   ({p["q_count"]} questions)' + (f'   [{p["category"]}]' if p['category'] else '')

    def step(self, parent, n, text):
        r = tk.Frame(parent, bg=P['card'])
        r.pack(fill='x', pady=(0, 8))
        widgets.badge(r, n).pack(side='left')
        label(r, text, self.app.fonts.h2, bg=P['card']).pack(side='left', padx=10)

    # ------------------------------------------------------------ mode cards
    def _mode_card(self, parent, m):
        info = MODES[m]
        fr = tk.Frame(parent, bg=P['card'], highlightthickness=2, highlightbackground=P['border'], cursor='hand2')
        parts = [fr,
                 label(fr, f'{info["icon"]}  {info["label"]}', self.app.fonts.bold, bg=P['card']),
                 label(fr, info['desc'], fg=P['muted'], bg=P['card'], wraplength=210, justify='left', anchor='w')]
        parts[1].pack(anchor='w', padx=12, pady=(10, 2))
        parts[2].pack(anchor='w', padx=12, pady=(0, 10))
        for w in parts:
            w.bind('<Button-1>', lambda e, m=m: self.select_mode(m))
        self.mode_cards[m] = parts
        return fr

    def _paint_modes(self):
        for m, parts in self.mode_cards.items():
            sel = m == self.v_mode.get()
            bg = P['sel'] if sel else P['card']
            parts[0].configure(bg=bg, highlightbackground=P['accent'] if sel else P['border'])
            for w in parts[1:]:
                w.configure(bg=bg)

    def select_mode(self, m):
        self.v_mode.set(m)
        self._paint_modes()
        self.build_config()

    # ------------------------------------------------------------ bank loading
    def selected_pdf(self):
        i = self.cb.current()
        return self.pdfs[i] if 0 <= i < len(self.pdfs) else None

    def load_selected(self):
        p = self.selected_pdf()
        if not p:
            return
        self.bank = None
        self.lbl_load.configure(text='Reading the PDF…', fg=P['muted'])
        self.build_config()

        def ready(bank):
            if not self.winfo_exists() or self.selected_pdf()['id'] != p['id']:
                return
            self.bank = bank
            self.lbl_load.configure(text=f'✔  {len(bank.numbers)} questions  (#{bank.numbers[0]} – #{bank.numbers[-1]})',
                                    fg=P['okb'])
            self.build_config()
        self.app.open_bank(p['id'], ready)

    # ------------------------------------------------------------ configuration panel
    def build_config(self):
        for w in self.cfg_outer.winfo_children():
            w.destroy()
        mode = self.v_mode.get()
        info = MODES[mode]
        c = card(self.cfg_outer)
        r = tk.Frame(c, bg=P['card'])
        r.pack(fill='x', pady=(0, 8))
        widgets.badge(r, '3').pack(side='left')
        label(r, f'Configure: {info["icon"]} {info["label"]} mode', self.app.fonts.h2, bg=P['card']).pack(side='left', padx=10)
        label(c, info['desc'], fg=P['muted'], bg=P['card'], wraplength=700, justify='left').pack(anchor='w', pady=(0, 10))
        if self.bank is None:
            label(c, 'Waiting for the PDF…', fg=P['muted'], bg=P['card']).pack(anchor='w')
            return

        # --- which questions
        if self.preset:
            self.pool = [n for n in self.preset['pool'] if n in self.bank.q]
            label(c, 'Question pool', self.app.fonts.bold, bg=P['card']).pack(anchor='w')
            label(c, f'{self.preset.get("source_label", "Selected questions")}  -  {len(self.pool)} questions',
                  bg=P['card']).pack(anchor='w', pady=(2, 10))
            self.lbl_pool = None
        else:
            label(c, 'Which questions?', self.app.fonts.bold, bg=P['card']).pack(anchor='w')
            ttk.Entry(c, textvariable=self.v_range).pack(fill='x', pady=(4, 2))
            r = tk.Frame(c, bg=P['card'])
            r.pack(anchor='w', pady=(4, 0))
            label(r, 'Examples:', fg=P['muted'], bg=P['card']).pack(side='left', padx=(0, 6))
            for ex in ('7', '5-61', '1,5-61,69,73-152'):
                chip(r, ex).pack(side='left', padx=3)
            label(r, '  (empty = all)', fg=P['muted'], bg=P['card']).pack(side='left')
            self.lbl_pool = label(c, '', bg=P['card'], anchor='w')
            self.lbl_pool.pack(anchor='w', pady=(6, 10))
            self.update_pool()

        # --- mode specific options
        grid = tk.Frame(c, bg=P['card'])
        grid.pack(fill='x', pady=(0, 6))
        col = 0
        if mode != 'endless':
            label(grid, 'Number of questions' if mode != 'survival' else 'Maximum questions',
                  self.app.fonts.bold, bg=P['card']).grid(row=0, column=col, sticky='w', padx=(0, 24))
            r = tk.Frame(grid, bg=P['card'])
            r.grid(row=1, column=col, sticky='w', padx=(0, 24))
            ttk.Spinbox(r, from_=1, to=99999, textvariable=self.v_count, width=8).pack(side='left')
            ttk.Button(r, text='All', style='Small.TButton', command=self.use_all).pack(side='left', padx=8)
            col += 1
        if mode == 'timed':
            label(grid, 'Time limit (minutes)', self.app.fonts.bold, bg=P['card']).grid(row=0, column=col, sticky='w')
            ttk.Spinbox(grid, from_=1, to=1000, textvariable=self.v_minutes, width=8).grid(row=1, column=col, sticky='w')
            col += 1
        if mode == 'survival':
            label(grid, 'Lives', self.app.fonts.bold, bg=P['card']).grid(row=0, column=col, sticky='w')
            ttk.Spinbox(grid, from_=1, to=10, textvariable=self.v_lives, width=6).grid(row=1, column=col, sticky='w')
            col += 1
        notes = {'sequential': 'The first N questions of the pool are used, in their original order.',
                 'endless': 'No question limit - press Finish whenever you want to stop.',
                 'survival': 'The session ends when you have used up all lives.',
                 'timed': 'The exam ends automatically when the time is over.'}
        if mode in notes:
            label(c, notes[mode], fg=P['muted'], bg=P['card']).pack(anchor='w', pady=(4, 0))
        ttk.Checkbutton(c, text='Shuffle the variants (A–E) of each question', variable=self.v_shuffle,
                        style='Card.TCheckbutton').pack(anchor='w', pady=(10, 0))
        r = tk.Frame(self.cfg_outer, bg=P['bg'])
        r.pack(fill='x', pady=(4, 0))
        ttk.Button(r, text='▶   Start exam', style='Accent.TButton', command=self.start).pack(side='left', ipadx=18, ipady=4)
        label(r, 'or press Enter', fg=P['muted']).pack(side='left', padx=12)

    def update_pool(self):
        if self.bank is None or self.lbl_pool is None or self.preset:
            return
        ids, bad = build_pool(self.bank, self.v_range.get())
        self.pool = ids
        msg = f'Pool: {len(ids)} question' + ('' if len(ids) == 1 else 's')
        if bad:
            msg += '      (not understood / not in file: ' + ', '.join(bad[:8]) + ('…' if len(bad) > 8 else '') + ')'
        try:
            self.lbl_pool.configure(text=msg, fg=P['badb'] if (bad or not ids) else P['text'])
        except tk.TclError:
            self.lbl_pool = None

    def use_all(self):
        self.v_count.set(str(len(self.pool)))

    # ------------------------------------------------------------ start
    def start(self):
        if self.bank is None:
            return
        mode = self.v_mode.get()
        if not self.pool:
            messagebox.showwarning('New exam', 'The question pool is empty - check the question numbers.')
            return
        try:
            count = int(self.v_count.get()) if mode != 'endless' else 0
            if mode != 'endless' and count < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning('New exam', 'Please type a whole number (1 or more) for the number of questions.')
            return
        minutes = None
        if mode == 'timed':
            try:
                minutes = float(self.v_minutes.get().replace(',', '.'))
                if minutes <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning('New exam', 'Please type the time limit in minutes (a number above 0).')
                return
        lives = 1
        if mode == 'survival':
            try:
                lives = int(self.v_lives.get())
                if not 1 <= lives <= 10:
                    raise ValueError
            except ValueError:
                messagebox.showwarning('New exam', 'Lives must be a whole number between 1 and 10.')
                return
        if count > len(self.pool) and mode != 'endless':
            messagebox.showinfo('New exam', f'Only {len(self.pool)} questions in the pool - using all of them.')
            count = len(self.pool)
        pre = self.preset or {}
        cfg = ExamConfig(pdf_id=self.bank.pdf_id, mode=mode, pool=list(self.pool), count=count,
                         shuffle_options=self.v_shuffle.get(), time_limit_min=minutes, lives=lives,
                         revision=bool(pre.get('revision')), source=pre.get('source', 'pool'),
                         source_label=pre.get('source_label', ''))
        st = self.app.settings
        st.set('last_pdf_id', self.bank.pdf_id)
        st.set('default_mode', mode)
        st.set('default_shuffle', bool(self.v_shuffle.get()))
        if mode != 'endless':
            st.set('default_count', count)
        if not self.preset:
            st.set('last_range', self.v_range.get().strip())
        self.app.start_exam(self.bank, cfg)

    def handle_key(self, e):
        if e.keysym == 'Return' and self.bank is not None:
            self.start()
