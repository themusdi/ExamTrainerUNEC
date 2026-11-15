"""PDF Library: import, rename, categorise, re-read, re-locate, export and remove PDFs."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import export
from library import describe_report
from ui import widgets
from ui.base import Screen
from ui.theme import P
from ui.widgets import card, empty_state, label


def _size_text(n):
    n = n or 0
    return f'{n / 1048576:.1f} MB' if n >= 1048576 else f'{max(1, n // 1024)} KB'


class LibraryScreen(Screen):
    """kw: add=True opens the file dialog right away."""

    def build(self):
        if not hasattr(self, 'v_cat'):
            self.v_cat = tk.StringVar(value='All categories')
            self.v_search = tk.StringVar(value='')
            self.v_search.trace_add('write', lambda *a: self._schedule_list())
            self._job = None
        self.cats = self.db.list_categories()
        top = tk.Frame(self, bg=P['bg'])
        top.pack(fill='x', padx=32, pady=(24, 0))
        widgets.heading(top, 'PDF Library', 'Your question files. Removing a PDF here never deletes the file itself.')
        bar = tk.Frame(top, bg=P['bg'])
        bar.pack(fill='x', pady=(0, 10))
        ttk.Button(bar, text='＋  Add PDF(s)…', style='Accent.TButton', command=self.add).pack(side='left')
        ttk.Button(bar, text='Categories…', command=self.manage_categories).pack(side='left', padx=8)
        names = ['All categories', 'Uncategorised'] + [c['name'] for c in self.cats]
        cb = ttk.Combobox(bar, state='readonly', values=names, textvariable=self.v_cat, width=22)
        cb.pack(side='right')
        cb.bind('<<ComboboxSelected>>', lambda e: self.fill())
        ttk.Entry(bar, textvariable=self.v_search, width=24).pack(side='right', padx=8)
        label(bar, 'Search:', fg=P['muted']).pack(side='right')
        self.cv, self.area = widgets.make_scroll(self)
        self.fill()
        if self.kw.get('add') and not getattr(self, '_asked', False):
            self._asked = True
            self.after(150, self.add)

    def _schedule_list(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(250, self.fill)

    def _cat_filter(self):
        v = self.v_cat.get()
        if v == 'Uncategorised':
            return 0
        for c in self.cats:
            if c['name'] == v:
                return c['id']
        return None

    # ------------------------------------------------------------------ list
    def fill(self):
        for w in self.area.winfo_children():
            w.destroy()
        wrap = tk.Frame(self.area, bg=P['bg'])
        wrap.pack(fill='both', expand=True, padx=32, pady=(0, 24))
        rows = self.db.list_pdfs(category_id=self._cat_filter(), search=self.v_search.get().strip() or None)
        if not rows:
            if self.db.list_pdfs():
                empty_state(wrap, '🔍', 'Nothing matches', 'Try another category or search text.')
            else:
                empty_state(wrap, '📚', 'Your library is empty',
                            'Add one or more PDF files with exam questions.', '＋  Add PDF(s)…', self.add)
            return
        recent = self.db.recent_pdfs(4)
        if recent and not self.v_search.get().strip() and self._cat_filter() is None:
            c = card(wrap, pady=(0, 14))
            label(c, 'Recently opened', self.app.fonts.h2, bg=P['card']).pack(anchor='w', pady=(0, 6))
            r = tk.Frame(c, bg=P['card'])
            r.pack(fill='x')
            for p in recent:
                ttk.Button(r, text=f'▶  {p["name"]}', command=lambda pid=p['id']: self.start(pid)).pack(side='left', padx=(0, 8))
        for p in rows:
            self.row(wrap, p)

    def row(self, parent, p):
        status = self.app.library.status(p)
        c = card(parent, pady=(0, 10))
        top = tk.Frame(c, bg=P['card'])
        top.pack(fill='x')
        label(top, p['name'], self.app.fonts.h2, bg=P['card']).pack(side='left')
        if p['category']:
            widgets.chip(top, p['category']).pack(side='left', padx=10)
        st_txt, st_col = {'ok': ('✔ file OK', P['okb']), 'missing': ('✘ file not found', P['badb']),
                          'modified': ('⚠ changed on disk - re-checked when opened', P['warn'])}[status]
        label(top, st_txt, fg=st_col, bg=P['card']).pack(side='right')
        last = (p['last_opened'] or '').replace('T', ' ')[:16] or 'never'
        label(c, f'{p["q_count"]} questions   ·   {_size_text(p["size"])}   ·   last opened: {last}',
              fg=P['muted'], bg=P['card']).pack(anchor='w', pady=(2, 0))
        label(c, p['path'], fg=P['muted'], bg=P['card'], font=self.app.fonts.small).pack(anchor='w')
        r = tk.Frame(c, bg=P['card'])
        r.pack(fill='x', pady=(10, 0))
        ttk.Button(r, text='▶  New exam', style='Accent.TButton',
                   command=lambda: self.start(p['id']), state='disabled' if status == 'missing' else 'normal').pack(side='left')
        ttk.Button(r, text='Rename', command=lambda: self.rename(p)).pack(side='left', padx=6)
        mb = ttk.Button(r, text='Category ▾')
        mb.configure(command=lambda b=mb: self.category_menu(p, b))
        mb.pack(side='left')
        if status == 'missing':
            ttk.Button(r, text='Locate file…', style='Accent.TButton', command=lambda: self.locate(p)).pack(side='left', padx=6)
        else:
            ttk.Button(r, text='Re-read', command=lambda: self.reread(p)).pack(side='left', padx=6)
        ttk.Button(r, text='Export JSON', command=lambda: self.export_json(p)).pack(side='left')
        ttk.Button(r, text='Remove', command=lambda: self.remove(p)).pack(side='right')

    # ------------------------------------------------------------------ actions
    def start(self, pid):
        self.app.navigate('setup', pdf_id=pid)

    def add(self):
        paths = filedialog.askopenfilenames(title='Choose PDF file(s) with questions',
                                            filetypes=[('PDF files', '*.pdf'), ('All files', '*.*')])
        if not paths:
            return
        self.app.import_pdfs(paths, category_id=self._cat_filter() or None, on_done=lambda pid: self._refresh())

    def _refresh(self, *_):
        try:
            self.rebuild()
        except tk.TclError:
            pass

    def rename(self, p):
        name = simpledialog.askstring('Rename PDF', 'Name shown in the library:', initialvalue=p['name'], parent=self.app)
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning('Rename PDF', 'The name cannot be empty.')
            return
        self.db.update_pdf(p['id'], name=name[:120])
        self.app.library.forget(p['id'])
        self.fill()

    def category_menu(self, p, button):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label='No category', command=lambda: self.set_cat(p, None))
        for c in self.cats:
            m.add_command(label=c['name'], command=lambda cid=c['id']: self.set_cat(p, cid))
        m.add_separator()
        m.add_command(label='New category…', command=lambda: self.new_cat_for(p))
        m.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    def set_cat(self, p, cid):
        self.db.update_pdf(p['id'], category_id=cid)
        self.rebuild()

    def new_cat_for(self, p):
        name = simpledialog.askstring('New category', 'Category name:', parent=self.app)
        if name:
            try:
                self.db.update_pdf(p['id'], category_id=self.db.add_category(name))
            except ValueError as e:
                messagebox.showwarning('Category', str(e))
            self.rebuild()

    def manage_categories(self):
        CategoryDialog(self.app, self.db, on_change=self._refresh)

    def reread(self, p):
        """Force a fresh parse (ignores the cache) - e.g. after the parser was improved."""
        def work(progress):
            return self.app.library.prepare(p['path'], known=None, progress=progress, use_cache=False)

        def done(data):
            bank, report = self.app.library.complete_open(p['id'], data)
            msg = describe_report(report) or f'Done - {len(bank.numbers)} questions found.'
            messagebox.showinfo(p['name'], msg)
            self.rebuild()
        self.app.run_task(work, done, f'Re-reading "{p["name"]}"…', lambda e: self.app.show_error(e, 'Re-read failed'))

    def locate(self, p):
        path = filedialog.askopenfilename(title=f'Where is "{p["name"]}" now?', filetypes=[('PDF files', '*.pdf')])
        if not path:
            return

        def work(progress):
            return self.app.library.prepare(path, progress=progress)

        def done(data):
            try:
                report = self.app.library.relink(p['id'], path, data)
            except ValueError as e:
                messagebox.showwarning('Locate file', str(e))
                return
            messagebox.showinfo(p['name'], describe_report(report) or 'The file was found again.')
            self.rebuild()
        self.app.run_task(work, done, 'Checking the file…', lambda e: self.app.show_error(e, 'Locate file'))

    def export_json(self, p):
        path = filedialog.asksaveasfilename(title='Export questions as JSON', defaultextension='.json',
                                            initialfile=f'{p["name"]}.json'.replace('/', '-'),
                                            filetypes=[('JSON', '*.json')])
        if not path:
            return

        def go(bank):
            try:
                n = export.export_bank_json(path, bank, p['name'], self.db.qstates(p['id']))
                self.app.toast(f'Exported {n} questions to {os.path.basename(path)}')
            except OSError as e:
                messagebox.showerror('Export', f'The file could not be written:\n{e}')
        self.app.open_bank(p['id'], go)

    def remove(self, p):
        if messagebox.askyesno('Remove from library',
                               f'Remove "{p["name"]}" from the library?\n\nThe PDF file is NOT deleted. Your history, '
                               'notes and statistics are kept and come back if you add the file again.'):
            self.db.remove_pdf(p['id'])
            self.app.library.forget(p['id'])
            self.rebuild()


class CategoryDialog(tk.Toplevel):
    def __init__(self, app, db, on_change=None):
        super().__init__(app)
        self.db, self.on_change = db, on_change
        self.title('Categories')
        self.geometry('420x380')
        self.configure(bg=P['bg'])
        self.transient(app)
        self.bind('<Escape>', lambda e: self.destroy())
        fr, self.tree = widgets.make_tree(self, [('name', 'Category', 260, 'w'), ('n', 'PDFs', 60, 'center')], height=10)
        fr.pack(fill='both', expand=True, padx=16, pady=(16, 8))
        r = tk.Frame(self, bg=P['bg'])
        r.pack(fill='x', padx=16, pady=(0, 14))
        ttk.Button(r, text='New…', command=self.new).pack(side='left')
        ttk.Button(r, text='Rename…', command=self.rename).pack(side='left', padx=6)
        ttk.Button(r, text='Delete', command=self.delete).pack(side='left')
        ttk.Button(r, text='Close', command=self.destroy).pack(side='right')
        self.fill()

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        for c in self.db.list_categories():
            self.tree.insert('', 'end', iid=str(c['id']), values=(c['name'], c['n']))

    def _sel(self):
        s = self.tree.selection()
        return int(s[0]) if s else None

    def _changed(self):
        self.fill()
        if self.on_change:
            self.on_change()

    def new(self):
        name = simpledialog.askstring('New category', 'Category name:', parent=self)
        if name:
            try:
                self.db.add_category(name)
            except ValueError as e:
                messagebox.showwarning('Category', str(e), parent=self)
            self._changed()

    def rename(self):
        cid = self._sel()
        if cid is None:
            return
        cur = self.tree.item(str(cid), 'values')[0]
        name = simpledialog.askstring('Rename category', 'New name:', initialvalue=cur, parent=self)
        if name:
            try:
                self.db.rename_category(cid, name)
            except ValueError as e:
                messagebox.showwarning('Category', str(e), parent=self)
            self._changed()

    def delete(self):
        cid = self._sel()
        if cid is not None and messagebox.askyesno(
                'Delete category', 'Delete this category? Its PDFs are kept and become uncategorised.', parent=self):
            self.db.delete_category(cid)
            self._changed()
