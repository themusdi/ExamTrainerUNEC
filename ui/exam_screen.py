"""The exam itself. Works for every mode (standard, timed, practice, sequential, endless, survival)."""
import tkinter as tk
from tkinter import messagebox, ttk

from exam_engine import MODES
from exam_stats import fmt_clock
from ui import widgets
from ui.base import Screen
from ui.theme import P
from ui.widgets import label

LETTERS = 'ABCDEFGH'


class ExamScreen(Screen):
    """kw: session"""

    def build(self):
        self.s = self.kw['session']
        if not hasattr(self, 'cur'):
            self.cur = min(self.s.visited_max, len(self.s.ids) - 1)
            self._job = None
            self._saved_at = 0.0
            self._render_w = 0
            self._time_over = False
            self.ov_win = None
            self._resize_job = None
        self.render()
        if self._job is None:
            self._tick()

    # ------------------------------------------------------------------ helpers
    def on_close(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        if self.ov_win is not None:
            self.ov_win.destroy()
            self.ov_win = None

    def save(self, force=False):
        import time
        if not self.app.settings.get('autosave_sessions'):
            return
        if force or time.monotonic() - self._saved_at > 0.5:
            self._saved_at = time.monotonic()
            self.s.visit(self.cur)
            self.db.save_state(self.s.to_state())

    def _tick(self):
        s = self.s
        try:
            if self.lbl_time is not None:
                left = s.time_left()
                if left is not None:
                    self.lbl_time.configure(text='⏳ ' + fmt_clock(left),
                                            fg=P['badb'] if left < 60 else P['accent'])
                else:
                    self.lbl_time.configure(text='⏱ ' + fmt_clock(s.elapsed()))
        except tk.TclError:
            pass
        if s.time_up() and not self._time_over and not s.finalized:
            self._time_over = True
            self._job = None
            messagebox.showinfo('Time is up', 'The time limit has been reached. The exam will be finished now.')
            self.app.finish_exam(auto=True)
            return
        import time
        if time.monotonic() - self._saved_at > 15:
            self.save(force=True)
        self._job = self.after(1000, self._tick)

    def _qstate(self):
        s = self.s
        return self.db.get_q(s.config.pdf_id, s.bank.fp(s.ids[self.cur]))

    # ------------------------------------------------------------------ drawing
    def render(self, keep_scroll=False):
        pos = self.cv.yview()[0] if (keep_scroll and getattr(self, 'cv', None) is not None) else 0
        for w in self.winfo_children():
            w.destroy()
        self.keep = []
        s, i, F = self.s, self.cur, self.app.fonts
        num = s.ids[i]
        s.visit(i)
        flagged = i in s.flags
        qs = self._qstate()
        fav, hard = bool(qs and qs['favorite']), bool(qs and qs['difficult'])
        note = (qs['note'] if qs else '') or ''
        endless = s.mode == 'endless'
        total = len(s.ids) + (len(s.remaining) if endless else 0)
        last = i == len(s.ids) - 1
        finishing = s.game_over or (last and not (endless and s.remaining))

        top = tk.Frame(self, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        top.pack(fill='x')
        row = tk.Frame(top, bg=P['card'], padx=16, pady=10)
        row.pack(fill='x')
        label(row, f'Question {i + 1}' + ('' if endless else f' / {len(s.ids)}'), F.h2, bg=P['card']).pack(side='left')
        label(row, f'  {MODES[s.mode]["icon"]} {MODES[s.mode]["label"]}', fg=P['muted'], bg=P['card']).pack(side='left', padx=6)
        if flagged:
            tk.Label(row, text='⚑ marked', bg=P['flag'], fg=P['text'], padx=8, pady=2, font=F.bold).pack(side='left', padx=6)
        if s.mode == 'survival':
            lives = max(0, s.lives - s.wrong())
            tk.Label(row, text='❤' * lives + '♡' * (s.lives - lives), fg=P['badb'], bg=P['card'], font=F.h2).pack(side='left', padx=10)
        self.lbl_time = tk.Label(row, text='', bg=P['sel'], fg=P['accent'], padx=10, pady=3, font=F.bold)
        self.lbl_time.pack(side='right')
        done = s.answered()
        label(row, f'{done} answered' if endless else f'{done} / {len(s.ids)} answered', fg=P['muted'],
              bg=P['card']).pack(side='right', padx=14)
        ttk.Progressbar(top, maximum=max(1, total), value=done, mode='determinate').pack(fill='x', padx=16, pady=(0, 10))

        bottom = tk.Frame(self, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        bottom.pack(side='bottom', fill='x')
        bar = tk.Frame(bottom, bg=P['card'], padx=14, pady=10)
        bar.pack(fill='x')
        ttk.Button(bar, text='←  Previous', command=lambda: self.go(-1),
                   state='normal' if i > 0 else 'disabled').pack(side='left')
        ttk.Button(bar, text='Finish  ✔' if finishing else 'Next  →', style='Accent.TButton',
                   command=lambda: self.go(1)).pack(side='left', padx=8)
        ttk.Button(bar, text='⚑ Unmark' if flagged else '⚑ Mark (M)', command=self.toggle_flag).pack(side='left', padx=(14, 0))
        ttk.Button(bar, text='★ Favourite (S)' if not fav else '★ Favourite ✓', command=lambda: self.toggle_field('favorite')).pack(side='left', padx=4)
        ttk.Button(bar, text='🔥 Difficult (X)' if not hard else '🔥 Difficult ✓', command=lambda: self.toggle_field('difficult')).pack(side='left', padx=4)
        ttk.Button(bar, text='📝 Note (N)' if not note else '📝 Note ✓', command=self.edit_note).pack(side='left', padx=4)
        ttk.Button(bar, text='Finish exam', style='Danger.TButton', command=lambda: self.try_finish()).pack(side='right')
        ttk.Button(bar, text='✕ Exit', command=lambda: self.app.navigate('home')).pack(side='right', padx=8)
        ttk.Button(bar, text='▦ Overview (O)', command=self.show_overview).pack(side='right')

        self.cv, area = widgets.make_scroll(self)
        self.app.config(cursor='watch')
        self.update_idletasks()
        stem, opts = s.bank.load(num)
        self.app.config(cursor='')
        wrap = self.wrap()
        self._render_w = self.winfo_width()
        widgets.question_card(area, stem, wrap, self.keep)
        if note:
            nf = tk.Frame(area, bg=P['bg'])
            nf.pack(fill='x', padx=14, pady=(0, 2))
            label(nf, '📝 ' + note, fg=P['muted'], bg=P['bg'], wraplength=wrap, justify='left').pack(anchor='w')
        locked = s.locked(i)
        for k, oi in enumerate(s.order[i]):
            ok, blocks = opts[oi]
            state = 'sel' if s.ans[i] == oi else 'norm'
            if locked:
                state = 'ok' if ok else ('bad' if s.ans[i] == oi else 'norm')
            widgets.option_row(area, LETTERS[k], blocks, wrap, state, self.keep,
                               None if locked else (lambda oi=oi: self.pick(oi)))
        if s.game_over:
            b = tk.Frame(area, bg=P['bad'], highlightthickness=1, highlightbackground=P['badb'])
            b.pack(fill='x', padx=12, pady=10)
            tk.Label(b, text='Game over - that was your last life. Press Finish to see the result.',
                     bg=P['bad'], fg=P['text'], font=F.bold, pady=10).pack()
        tk.Frame(area, height=16, bg=P['bg']).pack()
        self._restore_scroll(pos)

    def _restore_scroll(self, pos):
        if pos <= 0:
            return
        cv = self.cv

        def go():
            try:
                cv.yview_moveto(pos)
            except tk.TclError:
                pass
        self.update_idletasks()
        go()
        self.after_idle(go)

    # ------------------------------------------------------------------ actions
    def pick(self, oi):
        if self.s.answer(self.cur, oi):
            self.save(force=True)
            self.render(keep_scroll=True)

    def go(self, d):
        s = self.s
        if d > 0 and (s.game_over or self.cur == len(s.ids) - 1):
            if not s.game_over and s.mode == 'endless' and s.extend():
                pass
            else:
                self.try_finish()
                return
        self.cur = max(0, min(len(s.ids) - 1, self.cur + d))
        self.save(force=True)
        self.render()

    def jump(self, i):
        self.cur = max(0, min(len(self.s.ids) - 1, i))
        self.save(force=True)
        self.render()

    def try_finish(self):
        s = self.s
        left = s.unanswered()
        if (self.app.settings.get('confirm_finish') and left and s.mode not in ('endless', 'survival')
                and not s.time_up()):
            if not messagebox.askyesno('Finish exam', f'{left} question(s) are unanswered.\nFinish anyway?'):
                return
        self.on_close()
        self.app.finish_exam()

    def toggle_flag(self):
        self.s.flags ^= {self.cur}
        self.save(force=True)
        self.render(keep_scroll=True)

    def toggle_field(self, field):
        s = self.s
        num = s.ids[self.cur]
        qs = self._qstate()
        self.db.set_q_field(s.config.pdf_id, s.bank.fp(num), num, field, not (qs and qs[field]))
        self.render(keep_scroll=True)

    def edit_note(self):
        s = self.s
        num = s.ids[self.cur]
        qs = self._qstate()
        new = widgets.edit_note(self.app, f'Note for question #{num}', (qs['note'] if qs else '') or '')
        if new is not None:
            self.db.set_q_field(s.config.pdf_id, s.bank.fp(num), num, 'note', new)
            self.render(keep_scroll=True)

    def show_overview(self):
        if self.ov_win is not None:
            self.ov_win.lift()
            return
        s = self.s
        win = tk.Toplevel(self.app)
        self.ov_win = win
        win.title('Overview')
        win.configure(bg=P['bg'])
        win.transient(self.app)

        def close(*_):
            self.ov_win = None
            win.destroy()
        win.protocol('WM_DELETE_WINDOW', close)
        for k in ('<Escape>', '<o>', '<O>'):
            win.bind(k, close)
        leg = tk.Frame(win, bg=P['bg'])
        leg.grid(row=0, column=0, columnspan=10, padx=12, pady=10)
        for txt, col in (('answered', P['ans']), ('marked ⚑', P['flag']), ('open', P['card'])):
            tk.Label(leg, text=f'  {txt}  ', bg=col, fg=P['text'], relief='groove').pack(side='left', padx=6)
        for i in range(len(s.ids)):
            bg = P['flag'] if i in s.flags else (P['ans'] if s.ans[i] is not None else P['card'])
            tk.Button(win, text=f'{i + 1}' + ('⚑' if i in s.flags else ''), width=5, bg=bg, fg=P['text'],
                      activebackground=P['hover'], activeforeground=P['text'], relief='groove',
                      font=self.app.fonts.bold if i == self.cur else None,
                      command=lambda i=i: (close(), self.jump(i))).grid(row=1 + i // 10, column=i % 10, padx=3, pady=3)
        tk.Frame(win, height=10, bg=P['bg']).grid(row=9999, column=0)
        win.focus_set()

    def on_resize(self, width):
        if abs(self.winfo_width() - self._render_w) < 40:
            return
        self.render(keep_scroll=True)

    # ------------------------------------------------------------------ keyboard
    def handle_key(self, e):
        s, i = self.s, self.cur
        if e.state & 0x4:                           # Ctrl held
            if e.keysym == 'Return':
                self.try_finish()
            return
        ch = e.char.upper() if len(e.char) == 1 else ''
        if e.keysym in ('Right', 'Return'):
            self.go(1)
        elif e.keysym == 'Left' and i > 0:
            self.go(-1)
        elif e.keysym == 'Home' and i > 0:
            self.jump(0)
        elif e.keysym == 'End' and i < len(s.ids) - 1:
            self.jump(len(s.ids) - 1)
        elif ch == 'M':
            self.toggle_flag()
        elif ch == 'O':
            self.show_overview()
        elif ch == 'S':
            self.toggle_field('favorite')
        elif ch == 'X':
            self.toggle_field('difficult')
        elif ch == 'N':
            self.edit_note()
        elif ch:
            k = LETTERS.index(ch) if ch in LETTERS else (int(ch) - 1 if ch in '12345678' else -1)
            if 0 <= k < len(s.order[i]):
                self.pick(s.order[i][k])
