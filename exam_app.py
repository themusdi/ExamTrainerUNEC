#!/usr/bin/env python3
"""
Exam Trainer - desktop app (Python + Tkinter)

1. Pick the PDF  (format:  "12. question"  then variants:  "• wrong"  /  "√ correct")
2. Type which questions to use:   5   |   5-61   |   1,5-61,69,73-152     (empty = all)
3. Type how many questions you want  ->  N random ones are picked from that pool.

Install once:   pip install pdfplumber pypdfium2 pillow
Run:            python exam_app.py
Make an .exe:   pip install pyinstaller  &&  pyinstaller --onefile --windowed exam_app.py
"""
import os
import re
import sys
import random
import queue
import threading

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageTk

# ----------------------------------------------------------------------------
#  PART 1 - PDF parsing (no GUI code in here)
# ----------------------------------------------------------------------------
SCALE = 2.0                      # render quality of image crops
GAP_NEW_Q = 10                   # vertical gap (pt) after a variant => new question starts
NUM_RE = re.compile(r'^(\d{1,5})\.\s*(.*)$', re.S)
JUNK_RE = re.compile(r'^[\s.,;:\/…_\-]*$')   # placeholder text the PDF leaves next to pictures
MARKS = ('•', '√')


def collect_items(pdf, progress=None):
    """Flatten the PDF to a reading-order stream of text lines and images."""
    items = []
    for pi, page in enumerate(pdf.pages):
        page_items = []
        lines = page.extract_text_lines(strip=True)
        maxx = max([l['x1'] for l in lines], default=0)
        for l in lines:
            page_items.append(dict(k='t', p=pi, top=l['top'], bot=l['bottom'],
                                   x0=l['x0'], x1=l['x1'], text=l['text'], maxx=maxx))
        for im in page.images:
            if (im['x1'] - im['x0']) < 3 or (im['bottom'] - im['top']) < 3:
                continue
            page_items.append(dict(k='i', p=pi, top=im['top'], bot=im['bottom'],
                                   x0=im['x0'], x1=im['x1']))
        # a bullet drawn on a slightly different baseline than its text -> glue them together
        for m in [d for d in page_items if d['k'] == 't' and d['x0'] < 45 and d['text'] in MARKS]:
            cy = (m['top'] + m['bot']) / 2
            cand = [d for d in page_items if d['k'] == 't' and d is not m and 45 > m['x0'] and d['x0'] > m['x0']
                    and d['x0'] < 80 and d['text'][:1] not in MARKS
                    and abs((d['top'] + d['bot']) / 2 - cy) < 9]
            if cand:
                t = min(cand, key=lambda d: abs((d['top'] + d['bot']) / 2 - cy))
                m['text'] += ' ' + t['text']
                m['x1'] = max(m['x1'], t['x1'])
                page_items.remove(t)
        page_items.sort(key=lambda d: (round(d['top']), d['x0']))
        items += page_items
        if progress:
            progress(pi + 1, len(pdf.pages))
    return items


def is_marker(it):
    return it['k'] == 't' and it['x0'] < 45 and it['text'][:1] in MARKS


def group_questions(items):
    qs, cur, state, prev = [], None, None, None

    def start():
        nonlocal cur, state
        cur = dict(num=None, stem=[], opts=[])
        qs.append(cur)
        state = 'stem'

    for it in items:
        mk = is_marker(it)
        num = None
        if it['k'] == 't' and not mk and it['x0'] < 20:
            m = NUM_RE.match(it['text'])
            if m:
                num = int(m.group(1))
        new_q = False
        if num is not None:
            # number arriving after its own stem text (detached number) -> same question
            if not (cur is not None and cur['num'] is None and state == 'stem' and cur['stem']):
                new_q = True
        elif cur is not None and state == 'options' and not mk:
            if prev is not None and prev['p'] == it['p'] and it['top'] - prev['bot'] > GAP_NEW_Q:
                new_q = True               # number-less stem start
        if cur is None and not mk and not new_q:
            prev = it                       # title / preamble before the first question
            continue
        if new_q:
            start()
        if cur is None:
            prev = it
            continue
        if num is not None and cur['num'] is None:
            cur['num'] = num
            rest = NUM_RE.match(it['text']).group(2)
            it = dict(it, text=rest)
            if not rest:
                prev = it
                continue
        if mk:
            state = 'options'
            cur['opts'].append(dict(correct=it['text'][0] == '√',
                                    items=[dict(it, text=it['text'][1:].strip(), opt=True)]))
        elif state == 'options':
            cur['opts'][-1]['items'].append(it)
        else:
            cur['stem'].append(it)
        prev = it
    return [q for q in qs if q['num'] is not None]


def join_lines(lines):
    """Join wrapped lines into paragraphs; keep a break after short lines / list items."""
    out = ''
    for i, l in enumerate(lines):
        if i == 0:
            out = l['text']
            continue
        prev = lines[i - 1]
        hard = prev['x1'] < prev['maxx'] - 25 or re.match(r'^\d+\s*[\.\)]', l['text'])
        out += ('\n' if hard else ' ') + l['text']
    return out


def parse_ranges(text, available):
    """'1,5-61,69' -> (sorted unique ids that exist in `available`, list of unknown tokens)."""
    text = re.sub(r'\s*([-–—])\s*', r'\1', text.strip())
    ids, bad = set(), []
    for tok in re.split(r'[,;\s]+', text):
        if not tok:
            continue
        m = re.fullmatch(r'(\d+)[-–—](\d+)', tok)
        if m:
            a, b = sorted((int(m.group(1)), int(m.group(2))))
            ids.update(i for i in range(a, b + 1) if i in available)
        elif tok.isdigit():
            (ids.add(int(tok)) if int(tok) in available else bad.append(tok))
        else:
            bad.append(tok)
    return sorted(ids), bad


class Bank:
    """All questions of one PDF. Pictures are cropped lazily, only when a question is shown."""

    def __init__(self, path, questions):
        self.path = path
        self.q = {}
        for q in questions:
            self.q.setdefault(q['num'], q)
        self.numbers = sorted(self.q)
        self._doc = None
        self._pages = {}

    def _render_page(self, p):
        if self._doc is None:
            self._doc = pdfium.PdfDocument(self.path)
        if p not in self._pages:
            if len(self._pages) > 3:
                self._pages.pop(next(iter(self._pages)))
            self._pages[p] = self._doc[p].render(scale=SCALE).to_pil().convert('RGB')
        return self._pages[p]

    def _crop(self, p, x0, top, x1, bot):
        im = self._render_page(p)
        box = (max(0, int(x0 * SCALE)), max(0, int(top * SCALE)),
               min(im.width, int(x1 * SCALE) + 1), min(im.height, int(bot * SCALE) + 1))
        return im.crop(box)

    def _blocks(self, items):
        """items -> [('t', text) | ('i', PIL.Image)]  (a line that holds a picture becomes a picture)."""
        imgs = [x for x in items if x['k'] == 'i']
        out, buf = [], []

        def flush():
            nonlocal buf
            if buf:
                txt = join_lines(buf).strip()
                if txt:
                    out.append(('t', txt))
                buf = []

        for it in items:
            if it['k'] == 'i':
                flush()
                out.append(('i', self._crop(it['p'], it['x0'] - 2, it['top'] - 2, it['x1'] + 2, it['bot'] + 2)))
                continue
            h = it['bot'] - it['top']
            hit = [im for im in imgs if im['p'] == it['p']
                   and min(it['bot'], im['bot']) - max(it['top'], im['top']) > 0.5 * h]
            if hit:                                   # formula sitting inside the text line
                flush()
                left = 44 if it.get('opt') else it['x0'] - 1
                out.append(('i', self._crop(it['p'], left, it['top'] - 1,
                                            max([it['x1']] + [im['x1'] for im in hit]) + 2, it['bot'] + 1)))
            else:
                buf.append(it)
        flush()
        if any(b[0] == 'i' for b in out):
            out = [b for b in out if not (b[0] == 't' and JUNK_RE.match(b[1]))]
        return out

    def load(self, num):
        """-> (stem_blocks, [(is_correct, option_blocks), ...]); cached."""
        q = self.q[num]
        if 'cache' not in q:
            q['cache'] = (self._blocks(q['stem']),
                          [(o['correct'], self._blocks(o['items'])) for o in q['opts']])
        return q['cache']


class Session:
    """One running exam (pure logic)."""

    def __init__(self, bank, ids, shuffle_options=False):
        self.bank = bank
        self.ids = list(ids)
        self.order = []
        for n in self.ids:
            idx = list(range(len(bank.q[n]['opts'])))
            if shuffle_options:
                random.shuffle(idx)
            self.order.append(idx)
        self.ans = [None] * len(self.ids)          # chosen ORIGINAL option index

    def is_correct(self, i):
        a = self.ans[i]
        return a is not None and self.bank.q[self.ids[i]]['opts'][a]['correct']

    def score(self):
        return sum(self.is_correct(i) for i in range(len(self.ids)))

    def wrong_ids(self):
        return [self.ids[i] for i in range(len(self.ids)) if not self.is_correct(i)]


# ----------------------------------------------------------------------------
#  PART 2 - GUI
# ----------------------------------------------------------------------------
C_BG, C_SEL, C_OK, C_BAD = '#ffffff', '#dbe8ff', '#d5f3df', '#fbd9d9'
B_NORM, B_SEL, B_OK, B_BAD = '#c9ced6', '#2f6fed', '#1a8f4c', '#d33b3b'
LETTERS = 'ABCDEFGH'


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Exam Trainer')
        self.geometry('960x760')
        self.minsize(640, 520)
        tkfont.nametofont('TkDefaultFont').configure(size=12)
        tkfont.nametofont('TkTextFont').configure(size=12)
        self.bold = ('TkDefaultFont', 12, 'bold')
        self.bank = None
        self.sess = None
        self.cur = 0
        self.practice = False
        self.shuffle_opts = False
        self.photos = []
        self.canvas = None
        self.msgs = queue.Queue()
        self.bind_all('<MouseWheel>', self._wheel)
        self.bind_all('<Button-4>', self._wheel)
        self.bind_all('<Button-5>', self._wheel)
        self.bind('<Key>', self._key)
        self.body = tk.Frame(self)
        self.body.pack(fill='both', expand=True)
        self.show_setup()

    # ---------- helpers ----------
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.canvas = None
        self.photos = []

    def _wheel(self, e):
        if self.canvas is None:
            return
        d = -1 if (getattr(e, 'num', 0) == 4 or getattr(e, 'delta', 0) > 0) else 1
        try:
            self.canvas.yview_scroll(d * 2, 'units')
        except tk.TclError:
            pass

    def scroll_area(self, parent):
        holder = tk.Frame(parent)
        holder.pack(fill='both', expand=True)
        cv = tk.Canvas(holder, highlightthickness=0, bg='#f3f4f7')
        sb = ttk.Scrollbar(holder, orient='vertical', command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        cv.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(cv, bg='#f3f4f7')
        win = cv.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: cv.configure(scrollregion=cv.bbox('all')))
        cv.bind('<Configure>', lambda e: cv.itemconfigure(win, width=e.width))
        self.canvas = cv
        return inner

    def add_blocks(self, parent, blocks, wrap, bg):
        """Show text / picture blocks. Returns every widget created (for click binding)."""
        made = []
        for kind, val in blocks:
            if kind == 't':
                w = tk.Label(parent, text=val, wraplength=wrap, justify='left', anchor='w', bg=bg)
            else:
                im = val
                scale = 0.75                         # crops are 2x PDF points; show ~1.5x
                nw = max(1, int(im.width * scale))
                if nw > wrap:
                    scale = wrap / im.width
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
                ph = ImageTk.PhotoImage(im)
                self.photos.append(ph)
                w = tk.Label(parent, image=ph, bg=bg, bd=0)
            w.pack(anchor='w', pady=2)
            made.append(w)
        return made

    def option_row(self, parent, letter, blocks, wrap, state, on_click=None):
        bg = {'norm': C_BG, 'sel': C_SEL, 'ok': C_OK, 'bad': C_BAD}[state]
        bd = {'norm': B_NORM, 'sel': B_SEL, 'ok': B_OK, 'bad': B_BAD}[state]
        f = tk.Frame(parent, bg=bg, highlightthickness=2 if state != 'norm' else 1, highlightbackground=bd)
        f.pack(fill='x', pady=4, padx=2)
        tk.Label(f, text=letter, font=self.bold, width=2, bg=bg).pack(side='left', anchor='n', padx=(8, 4), pady=8)
        inner = tk.Frame(f, bg=bg)
        inner.pack(side='left', fill='x', expand=True, pady=6, padx=(0, 8))
        self.add_blocks(inner, blocks, wrap - 70, bg)
        if on_click:
            def bind_all_children(w):
                w.bind('<Button-1>', lambda e: on_click())
                try:
                    w.configure(cursor='hand2')
                except tk.TclError:
                    pass
                for c in w.winfo_children():
                    bind_all_children(c)
            bind_all_children(f)
        return f

    def question_card(self, parent, stem, header=None):
        card = tk.Frame(parent, bg=C_BG, highlightthickness=1, highlightbackground=B_NORM)
        card.pack(fill='x', pady=(10, 6), padx=10)
        pad = tk.Frame(card, bg=C_BG)
        pad.pack(fill='x', padx=14, pady=12)
        if header:
            tk.Label(pad, text=header, fg='#667085', bg=C_BG).pack(anchor='w')
        self.add_blocks(pad, stem, self.wrap(), C_BG)

    def wrap(self):
        return max(420, self.winfo_width() - 110)

    # ---------- screen 1: setup ----------
    def show_setup(self):
        self._clear()
        f = tk.Frame(self.body, padx=28, pady=22)
        f.pack(fill='both', expand=True)
        tk.Label(f, text='Exam Trainer', font=('TkDefaultFont', 20, 'bold')).pack(anchor='w')
        tk.Label(f, text='Fill in the three fields and press Start.', fg='#667085').pack(anchor='w', pady=(0, 14))

        # 1 - file
        tk.Label(f, text='1.  PDF file with the questions', font=self.bold).pack(anchor='w')
        r = tk.Frame(f)
        r.pack(fill='x', pady=(4, 2))
        self.v_file = tk.StringVar(value=self.bank.path if self.bank else '')
        ttk.Entry(r, textvariable=self.v_file, state='readonly').pack(side='left', fill='x', expand=True)
        ttk.Button(r, text='Browse…', command=self.browse).pack(side='left', padx=(8, 0))
        self.lbl_file = tk.Label(f, text='', fg='#667085', anchor='w')
        self.lbl_file.pack(anchor='w')
        self.pbar = ttk.Progressbar(f, mode='determinate', length=300)

        # 2 - which questions
        tk.Label(f, text='2.  Which questions?', font=self.bold).pack(anchor='w', pady=(16, 0))
        self.v_range = tk.StringVar()
        ttk.Entry(f, textvariable=self.v_range).pack(fill='x', pady=(4, 2))
        tk.Label(f, text='Examples:   7     |     5-61     |     1,5-61,69,73-152      (leave empty = all questions)',
                 fg='#667085').pack(anchor='w')
        self.lbl_pool = tk.Label(f, text='', anchor='w')
        self.lbl_pool.pack(anchor='w')

        # 3 - count
        tk.Label(f, text='3.  How many questions in the exam?', font=self.bold).pack(anchor='w', pady=(16, 0))
        r = tk.Frame(f)
        r.pack(anchor='w', pady=4)
        self.v_count = tk.StringVar(value='30')
        ttk.Spinbox(r, from_=1, to=9999, textvariable=self.v_count, width=8).pack(side='left')
        ttk.Button(r, text='All from the pool', command=self.use_all).pack(side='left', padx=8)
        tk.Label(f, text='They are picked randomly from the questions chosen above.', fg='#667085').pack(anchor='w')

        # options
        self.v_practice = tk.BooleanVar(value=False)
        self.v_shuffle = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text='Practice mode: show right / wrong right after each answer',
                        variable=self.v_practice).pack(anchor='w', pady=(14, 0))
        ttk.Checkbutton(f, text='Shuffle the variants (A–E) of each question',
                        variable=self.v_shuffle).pack(anchor='w')

        self.btn_start = ttk.Button(f, text='Start exam', command=self.start_from_setup, state='disabled')
        self.btn_start.pack(anchor='w', pady=18, ipadx=18, ipady=4)

        tk.Label(f, text='© Exam Trainer  |  Instagram: the.musdi',
             fg='#667085', font=('TkDefaultFont', 9)).pack(side='bottom', anchor='e', pady=(12, 0))

        self.v_range.trace_add('write', lambda *a: self.update_pool())
        if self.bank:
            self.file_ready()

    def browse(self):
        path = filedialog.askopenfilename(title='Choose the question PDF',
                                          filetypes=[('PDF files', '*.pdf'), ('All files', '*.*')])
        if not path:
            return
        self.bank = None
        self.v_file.set(path)
        self.btn_start.configure(state='disabled')
        self.lbl_pool.configure(text='')
        self.lbl_file.configure(text='Reading the PDF…', fg='#667085')
        self.pbar.pack(anchor='w', pady=2)
        self.pbar['value'] = 0
        threading.Thread(target=self._load_thread, args=(path,), daemon=True).start()
        self.after(100, self._poll)

    def _load_thread(self, path):
        try:
            pdf = pdfplumber.open(path)
            items = collect_items(pdf, lambda i, n: self.msgs.put(('prog', i, n)))
            qs = group_questions(items)
            if not qs:
                raise ValueError('No questions found in this PDF.')
            self.msgs.put(('done', Bank(path, qs)))
        except Exception as e:                      # show any problem to the user
            self.msgs.put(('err', str(e)))

    def _poll(self):
        try:
            while True:
                m = self.msgs.get_nowait()
                if m[0] == 'prog':
                    self.pbar['maximum'] = m[2]
                    self.pbar['value'] = m[1]
                    self.lbl_file.configure(text=f'Reading the PDF…  page {m[1]} / {m[2]}')
                elif m[0] == 'done':
                    self.bank = m[1]
                    self.file_ready()
                    return
                else:
                    self.pbar.pack_forget()
                    self.lbl_file.configure(text='Could not read the file: ' + m[1], fg=B_BAD)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def file_ready(self):
        self.pbar.pack_forget()
        n = self.bank.numbers
        self.lbl_file.configure(text=f'✔  {len(n)} questions found  (#{n[0]} – #{n[-1]})', fg=B_OK)
        self.btn_start.configure(state='normal')
        self.update_pool()

    def update_pool(self):
        if not self.bank:
            return
        txt = self.v_range.get().strip()
        if txt:
            ids, bad = parse_ranges(txt, set(self.bank.numbers))
        else:
            ids, bad = self.bank.numbers, []
        self.pool = ids
        msg = f'Pool: {len(ids)} question' + ('' if len(ids) == 1 else 's')
        if bad:
            msg += '      (not understood / not in file: ' + ', '.join(bad[:8]) + ('…' if len(bad) > 8 else '') + ')'
        self.lbl_pool.configure(text=msg, fg=B_BAD if (bad or not ids) else '#1d2330')

    def use_all(self):
        if self.bank:
            self.v_count.set(str(len(self.pool)))

    def start_from_setup(self):
        if not self.pool:
            messagebox.showwarning('Exam Trainer', 'The pool is empty - check the question numbers.')
            return
        try:
            n = int(self.v_count.get())
            if n < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning('Exam Trainer', 'Please type a whole number for the question count.')
            return
        self.practice = self.v_practice.get()
        self.shuffle_opts = self.v_shuffle.get()
        if n > len(self.pool):
            messagebox.showinfo('Exam Trainer', f'Only {len(self.pool)} questions in the pool - using all of them.')
            n = len(self.pool)
        self.start_exam(random.sample(self.pool, n))

    # ---------- screen 2: exam ----------
    def start_exam(self, ids):
        self.sess = Session(self.bank, ids, self.shuffle_opts)
        self.cur = 0
        self.show_question()

    def show_question(self):
        self._clear()
        s, i = self.sess, self.cur
        num = s.ids[i]
        top = tk.Frame(self.body, padx=14, pady=8)
        top.pack(fill='x')
        tk.Label(top, text=f'Question {i + 1} / {len(s.ids)}', font=self.bold).pack(side='left')
        done = sum(a is not None for a in s.ans)
        tk.Label(top, text=f'answered {done} / {len(s.ids)}', fg='#667085').pack(side='right')

        bottom = tk.Frame(self.body, padx=14, pady=10)
        bottom.pack(side='bottom', fill='x')
        ttk.Button(bottom, text='← Previous', command=lambda: self.go(-1),
                   state='normal' if i > 0 else 'disabled').pack(side='left')
        ttk.Button(bottom, text='Next →', command=lambda: self.go(1),
                   state='normal' if i < len(s.ids) - 1 else 'disabled').pack(side='left', padx=8)
        ttk.Button(bottom, text='Finish exam', command=self.finish).pack(side='right')

        area = self.scroll_area(self.body)
        self.config(cursor='watch')
        self.update_idletasks()
        stem, opts = s.bank.load(num)
        self.config(cursor='')
        self.question_card(area, stem)
        locked = self.practice and s.ans[i] is not None
        wrap = self.wrap()
        for k, oi in enumerate(s.order[i]):
            ok, blocks = opts[oi]
            state = 'sel' if s.ans[i] == oi else 'norm'
            if locked:
                state = 'ok' if ok else ('bad' if s.ans[i] == oi else 'norm')
            self.option_row(area, LETTERS[k], blocks, wrap, state,
                            None if locked else (lambda oi=oi: self.pick(oi)))
        tk.Frame(area, height=12, bg='#f3f4f7').pack()

    def pick(self, oi):
        self.sess.ans[self.cur] = oi
        self.show_question()

    def go(self, d):
        self.cur = max(0, min(len(self.sess.ids) - 1, self.cur + d))
        self.show_question()

    def _key(self, e):
        if self.sess is None or self.canvas is None or self.sess_done:
            return
        s, i = self.sess, self.cur
        if e.keysym == 'Right' and i < len(s.ids) - 1:
            self.go(1)
        elif e.keysym == 'Left' and i > 0:
            self.go(-1)
        elif len(e.char) == 1 and e.char.upper() in LETTERS:
            k = LETTERS.index(e.char.upper())
            if k < len(s.order[i]) and not (self.practice and s.ans[i] is not None):
                self.pick(s.order[i][k])

    sess_done = False

    # ---------- screen 3: result ----------
    def finish(self):
        s = self.sess
        left = sum(a is None for a in s.ans)
        if left and not messagebox.askyesno('Finish exam', f'{left} question(s) are unanswered.\nFinish anyway?'):
            return
        self.sess_done = True
        self._clear()
        n, ok = len(s.ids), s.score()
        wrong = n - ok - left
        head = tk.Frame(self.body, padx=20, pady=12)
        head.pack(fill='x')
        tk.Label(head, text=f'{ok} / {n}   ({ok / n * 100:.1f} %)', font=('TkDefaultFont', 26, 'bold')).pack(anchor='w')
        tk.Label(head, text=f'Correct: {ok}     Wrong: {wrong}     Unanswered: {left}', fg='#667085').pack(anchor='w')
        r = tk.Frame(head)
        r.pack(anchor='w', pady=8)
        ttk.Button(r, text='New exam', command=self.new_exam).pack(side='left')
        ttk.Button(r, text='Retry the wrong / unanswered ones', command=self.retry,
                   state='normal' if ok < n else 'disabled').pack(side='left', padx=8)

        area = self.scroll_area(self.body)
        self.config(cursor='watch')
        self.update_idletasks()
        wrap = self.wrap()
        for i, num in enumerate(s.ids):
            stem, opts = s.bank.load(num)
            verdict = '✔ correct' if s.is_correct(i) else ('– unanswered' if s.ans[i] is None else '✘ wrong')
            self.question_card(area, stem, header=f'{i + 1}.   (#{num})   {verdict}')
            for k, oi in enumerate(s.order[i]):
                is_ok, blocks = opts[oi]
                state = 'ok' if is_ok else ('bad' if s.ans[i] == oi else 'norm')
                self.option_row(area, LETTERS[k], blocks, wrap, state)
        tk.Frame(area, height=14, bg='#f3f4f7').pack()
        self.config(cursor='')

    def new_exam(self):
        self.sess_done = False
        self.sess = None
        self.show_setup()

    def retry(self):
        ids = self.sess.wrong_ids()
        self.sess_done = False
        self.start_exam(ids)


if __name__ == '__main__':
    App().mainloop()
