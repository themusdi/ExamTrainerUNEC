"""Exam history: browse, review, export and delete saved exams."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import export
from exam_engine import Session, mode_label
from exam_stats import fmt_clock
from ui import widgets
from ui.base import Screen
from ui.theme import P
from ui.widgets import empty_state


class HistoryScreen(Screen):
    def build(self):
        self.pdfs = self.db.list_pdfs(include_removed=True)
        top = tk.Frame(self, bg=P['bg'])
        top.pack(fill='x', padx=32, pady=(24, 0))
        widgets.heading(top, 'Exam history', 'Every finished exam. Open one to review your answers.')
        if not self.db.one('SELECT 1 FROM exams LIMIT 1'):
            empty_state(top, '🕘', 'No exams yet', 'Finished exams are saved here automatically.',
                        'Start an exam', lambda: self.app.navigate('setup'))
            return
        bar = tk.Frame(top, bg=P['bg'])
        bar.pack(fill='x', pady=(0, 8))
        names = ['All PDFs'] + [p['name'] for p in self.pdfs]
        self.cb = ttk.Combobox(bar, state='readonly', values=names, width=34)
        self.cb.current(0 if not hasattr(self, '_idx') else self._idx)
        self.cb.pack(side='left')
        self.cb.bind('<<ComboboxSelected>>', lambda e: self.fill())
        cols = [('date', 'Date', 130, 'w'), ('pdf', 'PDF', 190, 'w'), ('mode', 'Mode', 90, 'w'),
                ('n', 'Questions', 80, 'center'), ('ok', 'Correct', 70, 'center'), ('bad', 'Wrong', 70, 'center'),
                ('skip', 'Unanswered', 90, 'center'), ('score', 'Score', 70, 'center'), ('time', 'Time', 80, 'center')]
        holder = tk.Frame(self, bg=P['bg'])
        holder.pack(fill='both', expand=True, padx=32, pady=6)
        fr, self.tree = widgets.make_tree(holder, cols, height=14)
        fr.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.open())
        b = tk.Frame(self, bg=P['bg'])
        b.pack(fill='x', padx=32, pady=(4, 20))
        ttk.Button(b, text='Open / review', style='Accent.TButton', command=self.open).pack(side='left')
        ttk.Button(b, text='Export history (CSV)…', command=self.export_csv).pack(side='left', padx=8)
        ttk.Button(b, text='Delete selected', command=self.delete).pack(side='left')
        self.fill()

    def _pdf_id(self):
        i = self.cb.current()
        return None if i <= 0 else self.pdfs[i - 1]['id']

    def fill(self):
        self._idx = self.cb.current()
        self.tree.delete(*self.tree.get_children())
        self.exams = self.db.list_exams(pdf_id=self._pdf_id())
        for e in self.exams:
            self.tree.insert('', 'end', iid=str(e['id']), values=(
                str(e['finished_at']).replace('T', ' ')[:16], e['pdf_name'], mode_label(e['mode']) + (' ↻' if e['kind'] == 'revision' else ''),
                e['n_questions'], e['correct'], e['wrong'], e['unanswered'], f'{e["score"]:.0f}%', fmt_clock(e['duration'] or 0)))

    def _selected(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

    def open(self):
        eid = self._selected()
        if eid is None:
            messagebox.showinfo('History', 'Select an exam first.')
            return
        exam = self.db.get_exam(eid)
        if not exam or not exam['pdf_id'] or not self.db.get_pdf(exam['pdf_id']):
            messagebox.showwarning('History', 'The PDF of this exam is not in the library any more, '
                                              'so its questions cannot be shown. Add the file again to review it.')
            return

        def show(bank):
            s = Session.from_record(bank, exam, self.db.exam_answers(eid))
            if not s.ids:
                messagebox.showwarning('History', 'None of the questions of this exam exist in the PDF any more.')
                return
            summary = dict(n=exam['n_questions'], correct=exam['correct'], wrong=exam['wrong'],
                           unanswered=exam['unanswered'], percent=exam['score'], duration=exam['duration'])
            self.app.session = s
            self.app.navigate('results', session=s, exam_id=eid, summary=summary, review=True)
        self.app.open_bank(exam['pdf_id'], show)

    def export_csv(self):
        path = filedialog.asksaveasfilename(title='Export exam history', defaultextension='.csv',
                                            initialfile=export.default_filename('exam-history', 'csv'),
                                            filetypes=[('CSV (Excel)', '*.csv')])
        if not path:
            return
        try:
            n = export.export_history_csv(path, self.exams)
            self.app.toast(f'Exported {n} exams to {os.path.basename(path)}')
        except OSError as e:
            messagebox.showerror('Export', f'The file could not be written:\n{e}')

    def delete(self):
        eid = self._selected()
        if eid is None:
            return
        if messagebox.askyesno('Delete exam', 'Delete this exam from the history?\n\nStatistics are calculated from '
                                              'the history, so they will change. Mistake lists and notes are not affected.'):
            self.db.delete_exam(eid)
            self.fill()
