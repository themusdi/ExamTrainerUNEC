"""Revision (mistakes / unanswered / marked / difficult) and Bookmarks share one list screen."""
import tkinter as tk
from tkinter import messagebox, ttk

import revision
from exam_engine import ExamConfig
from ui import widgets
from ui.base import Screen
from ui.dialogs import QuestionViewer
from ui.theme import P
from ui.widgets import card, empty_state, label


class QuestionListScreen(Screen):
    TITLE = ''
    SUB = ''
    SOURCES = []                   # keys of revision.SOURCES shown as checkboxes
    DEFAULT = []                   # keys checked by default
    REVISION = True                # does the exam count as a revision session?
    EMPTY = ('✔', 'Nothing here yet', '')

    def build(self):
        self.pdfs = self.db.list_pdfs()
        self.bank = None
        self.rows = []
        if not self.pdfs:
            f = tk.Frame(self, bg=P['bg'])
            f.pack(fill='both', expand=True, padx=32, pady=24)
            widgets.heading(f, self.TITLE, self.SUB)
            empty_state(f, '📚', 'No PDF in the library yet', 'Add a PDF first.', 'Open the PDF Library',
                        lambda: self.app.navigate('library', add=True))
            return
        if not hasattr(self, 'checks'):
            self.checks = {k: tk.BooleanVar(value=k in self.DEFAULT) for k in self.SOURCES}
            self.v_missed = tk.BooleanVar(value=True)
        by_pdf = revision.counts_by_pdf(self.db)
        want = self.kw.get('pdf_id') or self.app.settings.get('last_pdf_id')
        names = ['All PDFs'] + [self._pdf_text(p, by_pdf.get(p['id'])) for p in self.pdfs]
        idx = 1 + next((i for i, p in enumerate(self.pdfs) if p['id'] == want), 0)
        top = tk.Frame(self, bg=P['bg'])
        top.pack(fill='x', padx=32, pady=(24, 0))
        widgets.heading(top, self.TITLE, self.SUB)
        c = card(top)
        r = tk.Frame(c, bg=P['card'])
        r.pack(fill='x')
        label(r, 'PDF', self.app.fonts.bold, bg=P['card']).pack(side='left', padx=(0, 10))
        self.cb = ttk.Combobox(r, state='readonly', values=names)
        self.cb.current(idx if getattr(self, '_pdf_idx', None) is None else self._pdf_idx)
        self.cb.pack(side='left', fill='x', expand=True)
        self.cb.bind('<<ComboboxSelected>>', lambda e: self.pdf_changed())
        r2 = tk.Frame(c, bg=P['card'])
        r2.pack(fill='x', pady=(10, 0))
        self.check_widgets = {}
        for k in self.SOURCES:
            cb = ttk.Checkbutton(r2, text=revision.SOURCES[k]['label'], variable=self.checks[k],
                                 style='Card.TCheckbutton', command=self.fill)
            cb.pack(side='left', padx=(0, 14))
            self.check_widgets[k] = cb
        if self.REVISION:
            ttk.Checkbutton(c, text='Most-missed questions first', variable=self.v_missed,
                            style='Card.TCheckbutton', command=self.fill).pack(anchor='w', pady=(8, 0))
        self.lbl_count = label(top, '', fg=P['muted'])
        self.lbl_count.pack(anchor='w')
        cols = [('pdf', 'PDF', 170, 'w'), ('num', '#', 60, 'center'), ('text', 'Question', 380, 'w'),
                ('flags', 'Flags', 90, 'center'), ('wrong', 'Wrong', 60, 'center'), ('right', 'Right', 60, 'center'),
                ('note', 'Note', 200, 'w')]
        self.table_holder = tk.Frame(self, bg=P['bg'])
        self.table_holder.pack(fill='both', expand=True, padx=32, pady=10)
        fr, self.tree = widgets.make_tree(self.table_holder, cols, height=12, selectmode='extended')
        fr.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.view())
        bar = tk.Frame(self, bg=P['bg'])
        bar.pack(fill='x', padx=32, pady=(0, 20))
        self.btn_start = ttk.Button(bar, text='▶  Practise these', style='Accent.TButton', command=self.start)
        self.btn_start.pack(side='left')
        ttk.Button(bar, text='View / edit…', command=self.view).pack(side='left', padx=8)
        self.extra_buttons(bar)
        self.pdf_changed()

    @staticmethod
    def _pdf_text(p, counts):
        n = sum((counts or {}).values())
        return f'{p["name"]}' + (f'   ({n} flagged)' if n else '')

    def extra_buttons(self, bar):
        pass

    def selected_pdf(self):
        i = self.cb.current()
        return None if i <= 0 else self.pdfs[i - 1]

    def pdf_changed(self):
        self._pdf_idx = self.cb.current()
        p = self.selected_pdf()
        self.bank = None
        self.fill()
        if p:
            def ready(bank):
                if self.winfo_exists() and self.selected_pdf() and self.selected_pdf()['id'] == p['id']:
                    self.bank = bank
                    self.fill()
            self.app.open_bank(p['id'], ready)

    def sources(self):
        return [k for k in self.SOURCES if self.checks[k].get()]

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        p = self.selected_pdf()
        src = self.sources()
        self.rows = []
        if src:
            where = ' OR '.join(revision.SOURCES[s]['where'] for s in src)
            order = 'q.times_wrong DESC, p.name COLLATE NOCASE, q.qnum' if (self.REVISION and self.v_missed.get()) \
                else 'p.name COLLATE NOCASE, q.qnum'
            self.rows = self.db.list_q(p['id'] if p else None, where, order=order)
        for r in self.rows:
            flags = ('★' if r['favorite'] else '') + ('🔥' if r['difficult'] else '') + ('⚑' if r['marked'] else '') \
                    + ('✘' if r['in_mistakes'] else '') + ('?' if r['in_skipped'] else '')
            text = self.bank.preview(r['qnum'], 70) if (self.bank and self.bank.pdf_id == r['pdf_id']) else '(select a PDF to see the text)'
            self.tree.insert('', 'end', iid=f'{r["pdf_id"]}:{r["qnum"]}',
                             values=(r['pdf_name'], r['qnum'], text, flags, r['times_wrong'], r['times_correct'],
                                     (r['note'] or '').replace('\n', ' ')[:60]))
        n = len(self.rows)
        self.lbl_count.configure(text=f'{n} question{"" if n == 1 else "s"}' if src else 'Tick at least one list above.')
        if not n:
            self.tree.insert('', 'end', iid='empty', values=('', '', self.EMPTY[1] + ('. ' + self.EMPTY[2] if self.EMPTY[2] else ''), '', '', '', ''))
        self.btn_start.configure(state='normal' if n else 'disabled')

    def _selected_rows(self):
        sel = set(self.tree.selection())
        return [r for r in self.rows if f'{r["pdf_id"]}:{r["qnum"]}' in sel]

    def view(self):
        rows = self._selected_rows() or self.rows[:1]
        if not rows:
            return
        r = rows[0]

        def show(bank):
            QuestionViewer(self.app, bank, r['qnum'], on_change=self.fill)
        self.app.open_bank(r['pdf_id'], show)

    def start(self):
        p = self.selected_pdf()
        if not p:
            messagebox.showinfo(self.TITLE, 'Please choose one PDF first - an exam uses the questions of a single PDF.')
            return
        sel = self._selected_rows() or self.rows
        nums = [r['qnum'] for r in sel]
        if not nums:
            return
        names = ', '.join(revision.SOURCES[s]['label'] for s in self.sources())
        label_txt = names + (' (selected rows)' if self._selected_rows() else '')
        preset = dict(pool=nums, source=self.sources()[0] if len(self.sources()) == 1 else 'revision',
                      source_label=label_txt, revision=self.REVISION)
        self.app.navigate('setup', pdf_id=p['id'], preset=preset)


class RevisionScreen(QuestionListScreen):
    TITLE = 'Revision'
    SUB = 'Practise the questions you got wrong, skipped or marked. A correct answer in a revision exam removes a question from the mistake list.'
    SOURCES = ['mistakes', 'skipped', 'marked', 'difficult']
    DEFAULT = ['mistakes', 'skipped']
    REVISION = True
    EMPTY = ('🎉', 'No questions on these lists', 'Mistakes and unanswered questions appear here after your exams')

    def extra_buttons(self, bar):
        ttk.Button(bar, text='Remove selected from mistake lists', command=self.clear_selected).pack(side='left')

    def clear_selected(self):
        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo('Revision', 'Select one or more questions first.')
            return
        if not messagebox.askyesno('Revision', f'Take {len(rows)} question(s) off the mistake and unanswered lists?\n'
                                               'Their statistics stay.'):
            return
        for r in rows:
            self.db.set_q_field(r['pdf_id'], r['fp'], r['qnum'], 'in_mistakes', 0)
            self.db.set_q_field(r['pdf_id'], r['fp'], r['qnum'], 'in_skipped', 0)
        self.fill()


class BookmarksScreen(QuestionListScreen):
    TITLE = 'Bookmarks & notes'
    SUB = 'Favourite and difficult questions and your personal notes. Create an exam from them with one click.'
    SOURCES = ['favorite', 'difficult', 'notes']
    DEFAULT = ['favorite', 'difficult', 'notes']
    REVISION = False
    EMPTY = ('⭐', 'No bookmarks yet', 'Use ★, 🔥 and 📝 during an exam or in the results')

    def extra_buttons(self, bar):
        ttk.Button(bar, text='Remove bookmarks of selected', command=self.unbookmark).pack(side='left')

    def unbookmark(self):
        rows = self._selected_rows()
        if not rows:
            messagebox.showinfo('Bookmarks', 'Select one or more questions first.')
            return
        if not messagebox.askyesno('Bookmarks', f'Remove the favourite / difficult flags of {len(rows)} question(s)?\n'
                                                'Notes are kept.'):
            return
        for r in rows:
            self.db.set_q_field(r['pdf_id'], r['fp'], r['qnum'], 'favorite', 0)
            self.db.set_q_field(r['pdf_id'], r['fp'], r['qnum'], 'difficult', 0)
        self.fill()
