"""Home screen: resume banner, quick numbers, quick actions, recently opened PDFs."""
import tkinter as tk
from tkinter import ttk

import exam_stats
import revision
from exam_engine import mode_label
from ui import widgets
from ui.base import Screen
from ui.theme import P
from ui.widgets import card, empty_state, label, stat_card


class HomeScreen(Screen):
    def build(self):
        pdfs = self.db.list_pdfs()
        self.cv, inner = widgets.make_scroll(self)
        f = tk.Frame(inner, bg=P['bg'])
        f.pack(fill='both', expand=True, padx=32, pady=24)
        first_time = not self.db.one('SELECT 1 FROM exams LIMIT 1')
        widgets.heading(f, 'Welcome to Exam Trainer' if first_time else 'Welcome back',
                        'Practise multiple-choice exams from your own PDF files.')
        state = self.db.load_state()
        if state:
            c = card(f)
            row = tk.Frame(c, bg=P['card'])
            row.pack(fill='x')
            n = len(state.get('ids', []))
            done = sum(a is not None for a in state.get('ans', []))
            label(row, '⏸  You have an unfinished exam', self.app.fonts.h2, bg=P['card']).pack(side='left')
            ttk.Button(row, text='Discard', command=self._discard).pack(side='right')
            ttk.Button(row, text='Resume', style='Accent.TButton', command=self.app.resume_interrupted).pack(side='right', padx=8)
            label(c, f'{mode_label(state["config"].get("mode", "standard"))} mode - {done} of {n} answered.',
                  fg=P['muted'], bg=P['card']).pack(anchor='w', pady=(4, 0))
        if not pdfs:
            empty_state(f, '📚', 'Your library is empty',
                        'Add a PDF with exam questions to get started. Questions start with a number '
                        '("12. text") and each variant with • (wrong) or √ (correct).',
                        'Add your first PDF', lambda: self.app.navigate('library', add=True))
            return
        o = exam_stats.overview(self.db)
        c = revision.counts(self.db)
        flow = widgets.FlowFrame(f, 200)
        flow.pack(fill='x', pady=(0, 8))
        flow.add(stat_card(flow, str(o['exams']), 'Exams completed'))
        flow.add(stat_card(flow, exam_stats.fmt_pct(o['accuracy']), 'Overall accuracy', P['okb']))
        flow.add(stat_card(flow, str(c['mistakes']), 'Active mistakes', P['badb']))
        flow.add(stat_card(flow, exam_stats.fmt_duration(o['time']), 'Study time', P['accent']))

        a = card(f, pady=(8, 12))
        label(a, 'Quick actions', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 8))
        r = tk.Frame(a, bg=P['card'])
        r.pack(fill='x')
        ttk.Button(r, text='▶  New exam', style='Accent.TButton', command=lambda: self.app.navigate('setup')).pack(side='left')
        ttk.Button(r, text=f'🔁  Revise mistakes ({c["mistakes"] + c["skipped"]})',
                   command=lambda: self.app.navigate('revision')).pack(side='left', padx=8)
        ttk.Button(r, text='📊  Statistics', command=lambda: self.app.navigate('stats')).pack(side='left')

        recent = self.db.recent_pdfs(5) or pdfs[:5]
        b = card(f)
        label(b, 'Recent PDFs', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 8))
        for p in recent:
            r = tk.Frame(b, bg=P['card'])
            r.pack(fill='x', pady=3)
            label(r, p['name'], self.app.fonts.bold, bg=P['card']).pack(side='left')
            label(r, f'   {p["q_count"]} questions' + (f'  ·  {p["category"]}' if p['category'] else ''),
                  fg=P['muted'], bg=P['card']).pack(side='left')
            ttk.Button(r, text='Start', style='Small.TButton',
                       command=lambda pid=p['id']: self.app.navigate('setup', pdf_id=pid)).pack(side='right')
        last = self.db.list_exams(limit=1)
        if last:
            e = last[0]
            d = card(f)
            label(d, 'Last exam', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 4))
            label(d, f'{e["pdf_name"]}  ·  {mode_label(e["mode"])}  ·  {e["correct"]}/{e["n_questions"]} correct '
                     f'({e["score"]:.0f}%)  ·  {str(e["finished_at"]).replace("T", " ")[:16]}',
                  fg=P['muted'], bg=P['card']).pack(anchor='w')

    def _discard(self):
        from tkinter import messagebox
        if messagebox.askyesno('Discard exam', 'Discard the unfinished exam? Its answers will be lost.'):
            self.db.clear_state()
            self.rebuild()
