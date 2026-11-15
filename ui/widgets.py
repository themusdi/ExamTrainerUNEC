"""Reusable building blocks: cards, badges, stat tiles, flow layout, tables, question / option views."""
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from ui.theme import P

FONTS = None                      # set once by the App (ui.widgets.FONTS = fonts)


def init(fonts):
    global FONTS
    FONTS = fonts


# ------------------------------------------------------------------------------ layout helpers
def make_scroll(parent, bg=None):
    """Vertical scroll area. Returns (canvas, inner_frame). The canvas is wheel-scrollable."""
    bg = bg or P['bg']
    holder = tk.Frame(parent, bg=bg)
    holder.pack(fill='both', expand=True)
    cv = tk.Canvas(holder, highlightthickness=0, bg=bg)
    cv._scroll_me = True
    sb = ttk.Scrollbar(holder, orient='vertical', command=cv.yview)
    cv.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y')
    cv.pack(side='left', fill='both', expand=True)
    inner = tk.Frame(cv, bg=bg)
    win = cv.create_window((0, 0), window=inner, anchor='nw')
    inner.bind('<Configure>', lambda e: cv.configure(scrollregion=cv.bbox('all')))
    cv.bind('<Configure>', lambda e: cv.itemconfigure(win, width=e.width))
    return cv, inner


def card(parent, pady=(0, 12), padx=0, fill='x', expand=False):
    outer = tk.Frame(parent, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
    outer.pack(fill=fill, pady=pady, padx=padx, expand=expand)
    inner = tk.Frame(outer, bg=P['card'])
    inner.pack(fill='both', expand=True, padx=18, pady=14)
    return inner


def label(parent, text, font=None, fg=None, bg=None, **kw):
    return tk.Label(parent, text=text, font=font, fg=fg or P['text'], bg=bg or parent['bg'], **kw)


def heading(parent, text, sub=None):
    f = tk.Frame(parent, bg=P['bg'])
    f.pack(fill='x', pady=(0, 14))
    label(f, text, FONTS.title).pack(anchor='w')
    if sub:
        label(f, sub, fg=P['muted']).pack(anchor='w')
    return f


def badge(parent, text, fill=None, size=26):
    c = tk.Canvas(parent, width=size, height=size, bg=parent['bg'], highlightthickness=0)
    c.create_oval(1, 1, size - 1, size - 1, fill=fill or P['accent'], outline='')
    c.create_text(size / 2, size / 2, text=text, fill='#ffffff', font=FONTS.bold)
    return c


def chip(parent, text, bg=None, fg=None):
    return tk.Label(parent, text=text, font=FONTS.key, bg=bg or P['sel'], fg=fg or P['accent'], padx=7, pady=1)


def stat_card(parent, value, caption, color=None, sub=None):
    t = tk.Frame(parent, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
    tk.Label(t, text=value, font=FONTS.score, fg=color or P['accent'], bg=P['card']).pack(padx=16, pady=(10, 0), anchor='w')
    tk.Label(t, text=caption, fg=P['muted'], bg=P['card']).pack(padx=16, anchor='w', pady=(0, 0 if sub else 10))
    if sub:
        tk.Label(t, text=sub, fg=P['muted'], bg=P['card'], font=FONTS.small).pack(padx=16, anchor='w', pady=(0, 10))
    return t


class FlowFrame(tk.Frame):
    """Lays its children out in as many equal columns as fit (responsive card grid)."""

    def __init__(self, master, min_width=190, bg=None, **kw):
        super().__init__(master, bg=bg or P['bg'], **kw)
        self.min_width = min_width
        self.items = []
        self._cols = 0
        self.bind('<Configure>', lambda e: self.relayout())

    def add(self, widget):
        self.items.append(widget)
        self.relayout(force=True)
        return widget

    def relayout(self, force=False):
        cols = max(1, self.winfo_width() // self.min_width)
        cols = min(cols, max(1, len(self.items)))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for c in range(12):
            self.grid_columnconfigure(c, weight=1 if c < cols else 0, uniform='flow' if c < cols else '')
        for i, w in enumerate(self.items):
            w.grid(row=i // cols, column=i % cols, sticky='nsew', padx=5, pady=5)


def empty_state(parent, icon, title, text, button=None, command=None):
    f = tk.Frame(parent, bg=P['bg'])
    f.pack(fill='both', expand=True, pady=40)
    tk.Label(f, text=icon, font=(FONTS.default.actual('family'), 40), bg=P['bg'], fg=P['muted']).pack()
    tk.Label(f, text=title, font=FONTS.h2, bg=P['bg'], fg=P['text']).pack(pady=(6, 2))
    tk.Label(f, text=text, bg=P['bg'], fg=P['muted'], wraplength=460, justify='center').pack()
    if button:
        ttk.Button(f, text=button, style='Accent.TButton', command=command).pack(pady=16)
    return f


def make_tree(parent, columns, height=10, selectmode='browse'):
    """columns: [(id, title, width, anchor)].  Returns (frame, tree); the frame is not packed."""
    fr = tk.Frame(parent, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
    tree = ttk.Treeview(fr, columns=[c[0] for c in columns], show='headings', height=height, selectmode=selectmode)
    for cid, title, width, anchor in columns:
        tree.heading(cid, text=title)
        tree.column(cid, width=width, anchor=anchor, stretch=(anchor == 'w'))
    sb = ttk.Scrollbar(fr, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y')
    tree.pack(side='left', fill='both', expand=True)
    return fr, tree


# ------------------------------------------------------------------------------ question views
def add_blocks(parent, blocks, wrap, bg, keep):
    """Show text / picture blocks. `keep` is a list that holds the PhotoImages (so they are not freed)."""
    made = []
    for kind, val in blocks:
        if kind == 't':
            w = tk.Label(parent, text=val, wraplength=wrap, justify='left', anchor='w', bg=bg, fg=P['text'])
        else:
            im = val
            scale = 0.75                                  # crops are 2x PDF points; show ~1.5x
            if int(im.width * scale) > wrap:
                scale = wrap / im.width
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            keep.append(ph)
            w = tk.Label(parent, image=ph, bg=bg, bd=0)
        w.pack(anchor='w', pady=2)
        made.append(w)
    return made


def option_row(parent, letter, blocks, wrap, state, keep, on_click=None):
    """state: norm | sel | ok | bad.  Clickable rows highlight on hover."""
    bg = {'norm': P['card'], 'sel': P['sel'], 'ok': P['ok'], 'bad': P['bad']}[state]
    bd = {'norm': P['border'], 'sel': P['accent'], 'ok': P['okb'], 'bad': P['badb']}[state]
    bdg = {'norm': P['badge'], 'sel': P['accent'], 'ok': P['okb'], 'bad': P['badb']}[state]
    f = tk.Frame(parent, bg=bg, highlightthickness=2 if state != 'norm' else 1, highlightbackground=bd)
    f.pack(fill='x', pady=5, padx=10)
    tk.Label(f, text=letter, font=FONTS.bold, width=2, bg=bdg, fg='#ffffff', pady=4).pack(
        side='left', anchor='n', padx=(10, 8), pady=10)
    inner = tk.Frame(f, bg=bg)
    inner.pack(side='left', fill='x', expand=True, pady=8, padx=(0, 10))
    tint = [f, inner] + add_blocks(inner, blocks, wrap - 80, bg, keep)
    if state in ('ok', 'bad'):
        tk.Label(f, text='✔' if state == 'ok' else '✘', fg=bd, bg=bg, font=FONTS.bold).pack(side='right', padx=12)
    if on_click:
        def paint(col):
            for w in tint:
                try:
                    w.configure(bg=col)
                except tk.TclError:
                    pass

        def leave(e):
            w = f.winfo_containing(*f.winfo_pointerxy())
            if not (w is not None and str(w).startswith(str(f))):
                paint(bg)

        def bind_children(w):
            w.bind('<Button-1>', lambda e: on_click())
            try:
                w.configure(cursor='hand2')
            except tk.TclError:
                pass
            for c in w.winfo_children():
                bind_children(c)
        bind_children(f)
        f.bind('<Enter>', lambda e: paint(P['hover'] if state == 'norm' else bg))
        f.bind('<Leave>', leave)
    return f


def question_card(parent, stem, wrap, keep, header=None, header_widgets=None):
    """Card with the question stem. Returns the header row frame (so callers can add buttons)."""
    c = tk.Frame(parent, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
    c.pack(fill='x', pady=(14, 6), padx=10)
    pad = tk.Frame(c, bg=P['card'])
    pad.pack(fill='x', padx=18, pady=16)
    row = None
    if header or header_widgets:
        row = tk.Frame(pad, bg=P['card'])
        row.pack(fill='x', pady=(0, 6))
        if header:
            tk.Label(row, text=header, fg=P['muted'], bg=P['card'], font=FONTS.bold).pack(side='left')
    add_blocks(pad, stem, wrap, P['card'], keep)
    return row


class NoteDialog(tk.Toplevel):
    """Small modal editor for a personal note. `result` is the new text, or None if cancelled."""

    def __init__(self, master, title, text=''):
        super().__init__(master)
        self.title(title)
        self.configure(bg=P['bg'])
        self.transient(master)
        self.result = None
        self.geometry('520x320')
        tk.Label(self, text='Your note for this question (saved on this computer):', bg=P['bg'], fg=P['text']).pack(
            anchor='w', padx=16, pady=(14, 6))
        self.txt = tk.Text(self, wrap='word', height=8, bg=P['card'], fg=P['text'], insertbackground=P['text'],
                           relief='flat', highlightthickness=1, highlightbackground=P['border'], padx=8, pady=8,
                           font=FONTS.default)
        self.txt.pack(fill='both', expand=True, padx=16)
        self.txt.insert('1.0', text or '')
        row = tk.Frame(self, bg=P['bg'])
        row.pack(fill='x', padx=16, pady=12)
        ttk.Button(row, text='Save', style='Accent.TButton', command=self._save).pack(side='right')
        ttk.Button(row, text='Cancel', command=self.destroy).pack(side='right', padx=8)
        if text:
            ttk.Button(row, text='Delete note', command=self._delete).pack(side='left')
        self.bind('<Escape>', lambda e: self.destroy())
        self.txt.focus_set()
        self.grab_set()

    def _save(self):
        self.result = self.txt.get('1.0', 'end').strip()
        self.destroy()

    def _delete(self):
        self.result = ''
        self.destroy()


def edit_note(master, title, text=''):
    dlg = NoteDialog(master, title, text)
    master.wait_window(dlg)
    return dlg.result
