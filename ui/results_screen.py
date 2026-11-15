"""Results of a finished exam (also used to review an exam from the history)."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import export
from exam_engine import mode_label
from exam_stats import fmt_clock
from ui import widgets
from ui.base import Screen
from ui.theme import P
from ui.widgets import label


class ResultsScreen(Screen):
    """kw: session, exam_id (optional), summary (optional, from the stored record), review (bool)."""

    def build(self):
        self.s = self.kw['session']
        self.exam_id = self.kw.get('exam_id')
        self.review = self.kw.get('review', False)
        s, F = self.s, self.app.fonts
        sm = self.kw.get('summary') or s.summary()
        n, ok, left, wrong, pct = sm['n'], sm['correct'], sm['unanswered'], sm['wrong'], sm['percent']
        self.pdf_name = (self.db.get_pdf(s.config.pdf_id) or {'name': s.bank.name})['name']
        if not hasattr(self, 'v_filter'):
            self.v_filter = tk.StringVar(value='all')

        head = tk.Frame(self, bg=P['bg'], padx=24, pady=16)
        head.pack(fill='x')
        self.ring(head, pct).pack(side='left', padx=(0, 22))
        col = tk.Frame(head, bg=P['bg'])
        col.pack(side='left', fill='x')
        title = f'{ok} / {n} correct'
        label(col, title, F.score).pack(anchor='w')
        label(col, f'{self.pdf_name}  ·  {mode_label(s.mode)} mode' + ('  ·  review' if self.review else ''),
              fg=P['muted']).pack(anchor='w')
        tiles = tk.Frame(col, bg=P['bg'])
        tiles.pack(anchor='w', pady=8)
        for val, cap, color in ((ok, 'Correct', P['okb']), (wrong, 'Wrong', P['badb']), (left, 'Unanswered', P['muted']),
                                (fmt_clock(sm['duration']), 'Time', P['accent'])):
            t = widgets.stat_card(tiles, str(val), cap, color)
            t.pack(side='left', padx=(0, 10))
        if getattr(s, 'missing', 0):
            label(col, f'{s.missing} question(s) of this exam no longer exist in the PDF and are not shown.',
                  fg=P['warn']).pack(anchor='w')

        r = tk.Frame(self, bg=P['bg'], padx=24)
        r.pack(fill='x')
        if self.review:
            ttk.Button(r, text='← History', command=lambda: self.app.navigate('history')).pack(side='left')
        ttk.Button(r, text='New exam', style='Accent.TButton', command=lambda: self.app.navigate('setup')).pack(
            side='left', padx=(0 if self.review else 0, 8))
        bad = bool(s.wrong_ids())
        ttk.Button(r, text='Retry wrong / unanswered', command=lambda: self.app.retry_session(s),
                   state='normal' if bad else 'disabled').pack(side='left')
        ttk.Button(r, text='Copy numbers', command=self.copy_wrong, state='normal' if bad else 'disabled').pack(side='left', padx=8)
        ttk.Button(r, text='Copy summary', command=self.copy_summary).pack(side='left')
        ttk.Button(r, text='Export PDF…', command=self.export_pdf).pack(side='left', padx=8)
        self.lbl_info = label(r, '', fg=P['okb'])
        self.lbl_info.pack(side='left', padx=8)

        counts = dict(all=len(s.ids), wrong=sum(s.status(i) == 'wrong' for i in range(len(s.ids))),
                      skipped=s.unanswered(), marked=len(s.flags))
        fr = tk.Frame(self, bg=P['bg'], padx=24, pady=10)
        fr.pack(fill='x')
        label(fr, 'Show:', fg=P['muted']).pack(side='left', padx=(0, 10))
        for key, text in (('all', 'All'), ('wrong', 'Wrong'), ('skipped', 'Unanswered'), ('marked', 'Marked ⚑')):
            ttk.Radiobutton(fr, text=f'{text} ({counts[key]})', value=key, variable=self.v_filter,
                            command=self.render_list).pack(side='left', padx=(0, 14))
        self.cv, self.area = widgets.make_scroll(self)
        self._render_w = 0
        self.render_list()

    def ring(self, parent, pct, size=130):
        c = tk.Canvas(parent, width=size, height=size, bg=P['bg'], highlightthickness=0)
        col = P['okb'] if pct >= 70 else (P['warn'] if pct >= 50 else P['badb'])
        c.create_oval(12, 12, size - 12, size - 12, outline=P['border'], width=12)
        if pct > 0:
            c.create_arc(12, 12, size - 12, size - 12, start=90, extent=-min(359.9, 3.6 * pct), style='arc',
                         outline=col, width=12)
        c.create_text(size / 2, size / 2, text=f'{pct:.0f}%', font=self.app.fonts.h2, fill=P['text'])
        return c

    # ------------------------------------------------------------------ list of questions
    def _selected(self):
        flt, s = self.v_filter.get(), self.s
        out = []
        for i in range(len(s.ids)):
            st = s.status(i)
            if flt == 'wrong' and st != 'wrong' or flt == 'skipped' and st != 'skipped' or flt == 'marked' and i not in s.flags:
                continue
            out.append(i)
        return out

    def render_list(self, keep_scroll=False):
        s = self.s
        pos = self.cv.yview()[0] if keep_scroll else 0
        for w in self.area.winfo_children():
            w.destroy()
        self.keep = []
        self.app.config(cursor='watch')
        self.update_idletasks()
        wrap = self.wrap()
        self._render_w = self.winfo_width()
        shown = self._selected()
        for i in shown:
            num = s.ids[i]
            st = s.status(i)
            stem, opts = s.bank.load(num)
            verdict = {'correct': '✔ correct', 'wrong': '✘ wrong', 'skipped': '– unanswered'}[st]
            hdr = widgets.question_card(self.area, stem, wrap, self.keep,
                                        header=f'{i + 1}.   (#{num})   {verdict}' + ('   ⚑ marked' if i in s.flags else ''),
                                        header_widgets=True)
            self._tools(hdr, num)
            for k, oi in enumerate(s.order[i]):
                is_ok, blocks = opts[oi]
                state = 'ok' if is_ok else ('bad' if s.ans[i] == oi else 'norm')
                widgets.option_row(self.area, 'ABCDEFGH'[k], blocks, wrap, state, self.keep)
            qs = self.db.get_q(s.config.pdf_id, s.bank.fp(num))
            if qs and qs['note']:
                label(self.area, '📝 ' + qs['note'], fg=P['muted'], wraplength=wrap, justify='left').pack(anchor='w', padx=14)
        if not shown:
            label(self.area, 'Nothing to show here.', fg=P['muted'], pady=40).pack()
        tk.Frame(self.area, height=16, bg=P['bg']).pack()
        self.app.config(cursor='')
        if keep_scroll and pos > 0:
            self.update_idletasks()
            self.cv.yview_moveto(pos)
        else:
            self.cv.yview_moveto(0)

    def _tools(self, row, num):
        s = self.s
        fp = s.bank.fp(num)
        qs = self.db.get_q(s.config.pdf_id, fp)

        def toggle(field, btn, on_text, off_text):
            cur = self.db.get_q(s.config.pdf_id, fp)
            new = not (cur and cur[field])
            self.db.set_q_field(s.config.pdf_id, fp, num, field, new)
            btn.configure(text=on_text if new else off_text)

        b1 = ttk.Button(row, style='Small.TButton', text='★' if (qs and qs['favorite']) else '☆')
        b1.configure(command=lambda: toggle('favorite', b1, '★', '☆'))
        b2 = ttk.Button(row, style='Small.TButton', text='🔥 hard ✓' if (qs and qs['difficult']) else '🔥 hard')
        b2.configure(command=lambda: toggle('difficult', b2, '🔥 hard ✓', '🔥 hard'))
        b3 = ttk.Button(row, style='Small.TButton', text='📝 note', command=lambda: self._note(num))
        for b in (b3, b2, b1):
            b.pack(side='right', padx=3)

    def _note(self, num):
        s = self.s
        fp = s.bank.fp(num)
        qs = self.db.get_q(s.config.pdf_id, fp)
        new = widgets.edit_note(self.app, f'Note for question #{num}', (qs['note'] if qs else '') or '')
        if new is not None:
            self.db.set_q_field(s.config.pdf_id, fp, num, 'note', new)
            self.render_list(keep_scroll=True)

    def on_resize(self, width):
        if abs(self.winfo_width() - self._render_w) >= 40:
            self.render_list(keep_scroll=True)

    # ------------------------------------------------------------------ clipboard / export
    def copy_wrong(self):
        self.app.clipboard_clear()
        self.app.clipboard_append(export.numbers_text(self.s.wrong_ids()))
        self.lbl_info.configure(text='Copied - paste it into "Which questions?" when starting an exam')

    def copy_summary(self):
        self.app.clipboard_clear()
        self.app.clipboard_append(export.results_text(self.s, self.pdf_name))
        self.lbl_info.configure(text='Result copied to the clipboard')

    def export_pdf(self):
        which = self.v_filter.get()
        which = {'all': 'all', 'wrong': 'wrong', 'skipped': 'wrong', 'marked': 'marked'}[which]
        path = filedialog.asksaveasfilename(title='Export results as PDF', defaultextension='.pdf',
                                            initialfile=export.default_filename('exam-results', 'pdf'),
                                            filetypes=[('PDF', '*.pdf')])
        if not path:
            return
        s = self.s
        notes = {r['qnum']: r['note'] for r in self.db.query(
            "SELECT qnum, note FROM qstate WHERE pdf_id=? AND stale=0 AND note<>''", (s.config.pdf_id,))}
        meta = dict(pdf_name=self.pdf_name, finished=s.started_at, summary=self.kw.get('summary') or s.summary())

        def work(progress):
            return export.export_results_pdf(path, s, meta, which, notes, progress)

        def done(pages):
            self.app.toast(f'Saved {os.path.basename(path)} ({pages} pages)')
            self.lbl_info.configure(text='PDF saved')
        self.app.run_task(work, done, 'Creating the PDF report…')
