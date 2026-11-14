#!/usr/bin/env python3
"""
Exam Trainer - desktop app (Python + Tkinter)

1. Pick the PDF  (format:  "12. question"  then variants:  "• wrong"  /  "√ correct")
2. Type which questions to use:   5   |   5-61   |   1,5-61,69,73-152     (empty = all)
3. Type how many questions you want  ->  N random ones are picked from that pool.

Extras: timer, mark-for-review (M), overview grid, keyboard answers (A-E or 1-5, arrows),
filterable results (wrong / unanswered / marked), settings remembered between runs.

Install once:   pip install pdfplumber pypdfium2 pillow
Run:            python exam_app.py
Make an .exe:   pip install pyinstaller  &&  pyinstaller --onefile --windowed exam_app.py
"""
import os
import re
import sys
import random
import json
import time
import queue
import threading
from pathlib import Path

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
            hit = [i for i in range(a, b + 1) if i in available]
            ids.update(hit)
            if not hit:
                bad.append(tok)
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
        self.flags = set()                         # positions marked for review

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
LIGHT = dict(bg='#f3f4f7', card='#ffffff', border='#d9dde5', text='#1d2330', muted='#667085',
             accent='#2f6fed', accent_dk='#2459c4', sel='#dbe8ff', hover='#f0f5ff',
             ok='#d5f3df', okb='#1a8f4c', bad='#fbd9d9', badb='#d33b3b', warn='#d99a1a',
             ans='#cfe0ff', flag='#ffe08a', badge='#98a2b3', header='#1b2540', chip='#2c3a63')
DARK = dict(bg='#12151c', card='#1c212b', border='#323a48', text='#e6e9ef', muted='#98a2b3',
            accent='#5b8cff', accent_dk='#7aa0ff', sel='#22335c', hover='#252c3a',
            ok='#173a28', okb='#34c274', bad='#43201f', badb='#f0646b', warn='#e0a93a',
            ans='#2a3d6b', flag='#6b5412', badge='#4a5365', header='#0b0e14', chip='#1d2433')
P = dict(LIGHT)                    # the active palette (updated in place when the theme changes)
LETTERS = 'ABCDEFGH'
CONFIG = Path.home() / '.exam_trainer.json'

# (keys, what it does) - shown in the "How to use" window
HELP_KEYS = [
    ('During the exam', [
        (['A', 'B', 'C', 'D', 'E'], 'Choose that variant (press again to un-choose it)'),
        (['1', '2', '3', '4', '5'], 'Same as A - E'),
        (['→', 'Enter'], 'Next question'),
        (['←'], 'Previous question'),
        (['Home', 'End'], 'Jump to the first / last question'),
        (['M'], 'Mark / unmark the question for review'),
        (['O'], 'Open the overview grid of all questions'),
        (['Ctrl', 'Enter'], 'Finish the exam'),
    ]),
    ('Everywhere', [
        (['F1'], 'Open this guide'),
        (['F2'], 'Switch between light and dark theme'),
        (['Esc'], 'Close the guide / overview window'),
    ]),
    ('Start screen', [
        (['Enter'], 'Start the exam (once the PDF is loaded)'),
    ]),
    ('Mouse', [
        (['Click'], 'Choose a variant, press a button, or jump to a question in the overview'),
        (['Wheel'], 'Scroll long questions and long result lists'),
    ]),
]

HELP_STEPS = [
    ('Choose your PDF',
     'Press Browse… and pick the file. Every question must start with its number ("12. question text"). '
     'Each variant starts with • (wrong answer) or √ (correct answer). Pictures and formulas are supported.'),
    ('Pick which questions',
     'Type  7  for one question,  5-61  for a range, or mix them:  1,5-61,69,73-152.  '
     'Leave the field empty to use every question in the file.'),
    ('Choose how many',
     'The app picks that many questions at random from your pool. "All from the pool" uses every one of them.'),
    ('Optional settings',
     'Practice mode shows right / wrong straight after each answer. '
     'Shuffle variants mixes the order of the answers (A - E) in every question.'),
    ('Take the exam',
     'Click a variant (or press its key) to answer. Use Next / Previous, mark doubtful questions with M, '
     'and open the Overview to see what is still open. Press Finish exam when you are done.'),
    ('Review your result',
     'See your score and time, filter the list (wrong / unanswered / marked), retry only your mistakes, '
     'or copy their numbers and paste them into step 2 for a focused re-run later.'),
]

HELP_TIPS = [
    'Your last PDF, question range, count and options are remembered. The file reopens by itself next time.',
    'Wrong answers are easy to drill: finish an exam, press "Retry the wrong / unanswered ones" and repeat until it is empty.',
    'In practice mode an answer is locked once you choose it. In normal mode you can change it any time.',
    'Click the variant you already chose to clear it again.',
    'The window can be resized. Text and pictures re-flow automatically.',
    'Settings are stored in  ~/.exam_trainer.json  - delete that file to reset everything.',
]


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        CONFIG.write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    except OSError:
        pass


def fmt_time(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Exam Trainer')
        self.geometry('1000x780')
        self.minsize(700, 560)
        for name in ('TkDefaultFont', 'TkTextFont'):
            tkfont.nametofont(name).configure(size=12)
        self.bold = self._font(12, True)
        self.f_title = self._font(22, True)
        self.f_h2 = self._font(14, True)
        self.f_score = self._font(26, True)
        self.f_ring = self._font(22, True)
        self.f_small = self._font(9)
        self.f_key = tkfont.nametofont('TkFixedFont').copy()
        self.f_key.configure(size=11, weight='bold')

        self.cfg = load_config()
        if self.cfg.get('dark'):
            P.update(DARK)
        self.bank = None
        self.sess = None
        self.cur = 0
        self.pool = []
        self.screen = 'setup'          # 'setup' | 'exam' | 'result'
        self.practice = False
        self.shuffle_opts = False
        self.photos = []
        self.canvas = None
        self.res_area = None
        self.help_win = None
        self.ov_win = None
        self.msgs = queue.Queue()
        self._load_id = 0              # lets us ignore results of an older, superseded load
        self._polling = False
        self.t0 = 0.0
        self.elapsed = 0.0
        self.lbl_time = None
        self._tick_job = None
        self._resize_job = None
        self._render_w = 0
        self.v_filter = None

        self.apply_style()
        self.header = tk.Frame(self, bg=P['header'])
        self.header.pack(fill='x')
        self.build_header()
        self.body = tk.Frame(self, bg=P['bg'])
        self.body.pack(fill='both', expand=True)

        self.bind_all('<MouseWheel>', self._wheel)
        self.bind_all('<Button-4>', self._wheel)
        self.bind_all('<Button-5>', self._wheel)
        self.bind('<Key>', self._key)
        self.bind('<Configure>', self._on_configure)
        self.show_setup()

        last = self.cfg.get('file')
        if last and os.path.isfile(last):          # reopen the last PDF automatically
            self.load_path(last)
        if not self.cfg.get('seen_help'):          # first run: show the guide
            self.cfg['seen_help'] = True
            save_config(self.cfg)
            self.after(400, self.show_help)

    # ---------- theme / style ----------
    @staticmethod
    def _font(size, bold=False):
        f = tkfont.nametofont('TkDefaultFont').copy()
        f.configure(size=size, weight='bold' if bold else 'normal')
        return f

    def apply_style(self):
        self.configure(bg=P['bg'])
        st = ttk.Style(self)
        st.theme_use('clam')
        st.configure('.', background=P['bg'], foreground=P['text'], fieldbackground=P['card'],
                     bordercolor=P['border'], lightcolor=P['card'], darkcolor=P['card'],
                     troughcolor=P['border'], focuscolor=P['bg'], insertcolor=P['text'])
        st.configure('TButton', padding=(14, 7), background=P['card'], foreground=P['text'],
                     bordercolor=P['border'], lightcolor=P['card'], darkcolor=P['card'], relief='flat')
        st.map('TButton', background=[('active', P['hover']), ('disabled', P['bg'])],
               foreground=[('disabled', P['muted'])])
        for name, col, hov in (('Accent', P['accent'], P['accent_dk']), ('Danger', P['badb'], P['badb'])):
            st.configure(f'{name}.TButton', background=col, foreground='#ffffff', bordercolor=col,
                         lightcolor=col, darkcolor=col, font=self.bold)
            st.map(f'{name}.TButton', background=[('active', hov), ('disabled', P['border'])],
                   foreground=[('disabled', P['muted'])], bordercolor=[('disabled', P['border'])],
                   lightcolor=[('disabled', P['border'])], darkcolor=[('disabled', P['border'])])
        st.configure('TEntry', padding=7, fieldbackground=P['card'], foreground=P['text'],
                     bordercolor=P['border'], lightcolor=P['border'], darkcolor=P['border'])
        st.map('TEntry', fieldbackground=[('readonly', P['card'])], bordercolor=[('focus', P['accent'])],
               lightcolor=[('focus', P['accent'])], darkcolor=[('focus', P['accent'])])
        st.configure('TSpinbox', padding=6, fieldbackground=P['card'], foreground=P['text'],
                     arrowcolor=P['text'], bordercolor=P['border'], background=P['card'],
                     lightcolor=P['border'], darkcolor=P['border'])
        st.configure('Card.TCheckbutton', background=P['card'], foreground=P['text'])
        st.map('Card.TCheckbutton', background=[('active', P['card'])],
               indicatorcolor=[('selected', P['accent']), ('!selected', P['card'])])
        st.configure('TRadiobutton', background=P['bg'], foreground=P['text'])
        st.map('TRadiobutton', background=[('active', P['bg'])],
               indicatorcolor=[('selected', P['accent']), ('!selected', P['card'])])
        st.configure('Horizontal.TProgressbar', troughcolor=P['border'], background=P['accent'],
                     bordercolor=P['border'], lightcolor=P['accent'], darkcolor=P['accent'], thickness=10)
        st.configure('Vertical.TScrollbar', background=P['border'], troughcolor=P['bg'],
                     bordercolor=P['bg'], arrowcolor=P['muted'], lightcolor=P['border'], darkcolor=P['border'])
        st.configure('TNotebook', background=P['bg'], bordercolor=P['border'])
        st.configure('TNotebook.Tab', padding=(18, 9), background=P['bg'], foreground=P['muted'])
        st.map('TNotebook.Tab', background=[('selected', P['card'])], foreground=[('selected', P['text'])])

    def build_header(self):
        for w in self.header.winfo_children():
            w.destroy()
        self.header.configure(bg=P['header'])
        tk.Label(self.header, text='📝  Exam Trainer', font=self.f_h2, fg='#ffffff',
                 bg=P['header']).pack(side='left', padx=18, pady=10)
        self._chip(self.header, 'Dark / Light   F2', self.toggle_theme).pack(side='right', padx=(0, 14))
        self._chip(self.header, '?  How to use   F1', self.show_help).pack(side='right', padx=8)

    def _chip(self, parent, text, cmd):
        lb = tk.Label(parent, text=text, bg=P['chip'], fg='#ffffff', padx=12, pady=5, cursor='hand2')
        lb.bind('<Button-1>', lambda e: cmd())
        lb.bind('<Enter>', lambda e: lb.configure(bg=P['accent']))
        lb.bind('<Leave>', lambda e: lb.configure(bg=P['chip']))
        return lb

    def toggle_theme(self):
        dark = not self.cfg.get('dark', False)
        self.cfg['dark'] = dark
        self._remember_setup_values()
        save_config(self.cfg)
        P.update(DARK if dark else LIGHT)
        reopen_help = self.help_win is not None
        for w in (self.help_win, self.ov_win):
            if w is not None:
                w.destroy()
        self.help_win = self.ov_win = None
        self.apply_style()
        self.build_header()
        self.body.configure(bg=P['bg'])
        if self.screen == 'setup':
            self.show_setup()
        elif self.screen == 'exam':
            self.show_question(keep_scroll=True)
        else:
            self.build_results(self.v_filter.get() if self.v_filter else 'all')
        if reopen_help:
            self.show_help()

    def _remember_setup_values(self):
        if self.screen == 'setup' and hasattr(self, 'v_range'):
            try:
                self.cfg.update(range=self.v_range.get().strip(), count=int(self.v_count.get()),
                                practice=self.v_practice.get(), shuffle=self.v_shuffle.get())
            except (ValueError, tk.TclError):
                pass

    # ---------- generic widgets ----------
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.canvas = None
        self.res_area = None
        self.lbl_time = None
        self.photos = []

    def _wheel(self, e):
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
        except (KeyError, tk.TclError):
            return
        while w is not None:
            if isinstance(w, tk.Canvas) and getattr(w, '_scroll_me', False):
                d = -1 if (getattr(e, 'num', 0) == 4 or getattr(e, 'delta', 0) > 0) else 1
                try:
                    w.yview_scroll(d * 2, 'units')
                except tk.TclError:
                    pass
                return
            w = w.master

    def _restore_scroll(self, pos):
        if self.canvas is None or pos <= 0:
            return
        cv = self.canvas

        def go():
            try:
                cv.yview_moveto(pos)
            except tk.TclError:
                pass
        self.update_idletasks()
        go()
        self.after_idle(go)

    def make_scroll(self, parent, bg):
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

    def scroll_area(self, parent):
        self.canvas, inner = self.make_scroll(parent, P['bg'])
        return inner

    def card(self, parent, pady=(0, 12)):
        outer = tk.Frame(parent, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        outer.pack(fill='x', pady=pady)
        inner = tk.Frame(outer, bg=P['card'])
        inner.pack(fill='x', padx=18, pady=14)
        return inner

    def badge(self, parent, text, fill=None, size=26):
        c = tk.Canvas(parent, width=size, height=size, bg=parent['bg'], highlightthickness=0)
        c.create_oval(1, 1, size - 1, size - 1, fill=fill or P['accent'], outline='')
        c.create_text(size / 2, size / 2, text=text, fill='#ffffff', font=self.bold)
        return c

    def step_header(self, parent, n, text):
        r = tk.Frame(parent, bg=P['card'])
        r.pack(fill='x', pady=(0, 8))
        self.badge(r, n).pack(side='left')
        tk.Label(r, text=text, font=self.f_h2, bg=P['card'], fg=P['text']).pack(side='left', padx=10)

    def add_blocks(self, parent, blocks, wrap, bg):
        """Show text / picture blocks. Returns every widget created."""
        made = []
        for kind, val in blocks:
            if kind == 't':
                w = tk.Label(parent, text=val, wraplength=wrap, justify='left', anchor='w',
                             bg=bg, fg=P['text'])
            else:
                im = val
                scale = 0.75                         # crops are 2x PDF points; show ~1.5x
                if int(im.width * scale) > wrap:
                    scale = wrap / im.width
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
                ph = ImageTk.PhotoImage(im)
                self.photos.append(ph)
                w = tk.Label(parent, image=ph, bg=bg, bd=0)
            w.pack(anchor='w', pady=2)
            made.append(w)
        return made

    def option_row(self, parent, letter, blocks, wrap, state, on_click=None):
        bg = {'norm': P['card'], 'sel': P['sel'], 'ok': P['ok'], 'bad': P['bad']}[state]
        bd = {'norm': P['border'], 'sel': P['accent'], 'ok': P['okb'], 'bad': P['badb']}[state]
        bdg = {'norm': P['badge'], 'sel': P['accent'], 'ok': P['okb'], 'bad': P['badb']}[state]
        f = tk.Frame(parent, bg=bg, highlightthickness=2 if state != 'norm' else 1, highlightbackground=bd)
        f.pack(fill='x', pady=5, padx=10)
        tk.Label(f, text=letter, font=self.bold, width=2, bg=bdg, fg='#ffffff',
                 pady=4).pack(side='left', anchor='n', padx=(10, 8), pady=10)
        inner = tk.Frame(f, bg=bg)
        inner.pack(side='left', fill='x', expand=True, pady=8, padx=(0, 10))
        tint = [f, inner] + self.add_blocks(inner, blocks, wrap - 80, bg)
        if state == 'ok':
            tk.Label(f, text='✔', fg=P['okb'], bg=bg, font=self.bold).pack(side='right', padx=12)
        elif state == 'bad':
            tk.Label(f, text='✘', fg=P['badb'], bg=bg, font=self.bold).pack(side='right', padx=12)
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

    def question_card(self, parent, stem, header=None):
        card = tk.Frame(parent, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        card.pack(fill='x', pady=(14, 6), padx=10)
        pad = tk.Frame(card, bg=P['card'])
        pad.pack(fill='x', padx=18, pady=16)
        if header:
            tk.Label(pad, text=header, fg=P['muted'], bg=P['card'], font=self.bold).pack(anchor='w', pady=(0, 4))
        self.add_blocks(pad, stem, self.wrap(), P['card'])

    def wrap(self):
        self._render_w = self.winfo_width()
        return max(420, self._render_w - 120)

    def _on_configure(self, e):
        """Re-flow text / pictures after the window was resized (debounced)."""
        if e.widget is not self or self.screen not in ('exam', 'result'):
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(250, self._reflow)

    def _reflow(self):
        self._resize_job = None
        if abs(self.winfo_width() - self._render_w) < 40:
            return
        if self.screen == 'exam':
            self.show_question(keep_scroll=True)
        elif self.screen == 'result':
            self.render_results(keep_scroll=True)

    # ---------- help window ----------
    def show_help(self):
        if self.help_win is not None:
            self.help_win.lift()
            self.help_win.focus_set()
            return
        win = tk.Toplevel(self)
        self.help_win = win
        win.title('How to use - Exam Trainer')
        win.geometry('720x640')
        win.minsize(520, 420)
        win.configure(bg=P['bg'])
        win.transient(self)

        def close(*_):
            self.help_win = None
            win.destroy()
        win.protocol('WM_DELETE_WINDOW', close)
        win.bind('<Escape>', close)
        tk.Label(win, text='How to use Exam Trainer', font=self.f_title, bg=P['bg'],
                 fg=P['text']).pack(anchor='w', padx=24, pady=(18, 10))
        nb = ttk.Notebook(win)
        nb.pack(fill='both', expand=True, padx=16, pady=(0, 8))

        def tab(title):
            fr = tk.Frame(nb, bg=P['card'])
            nb.add(fr, text=title)
            cv, inner = self.make_scroll(fr, P['card'])
            body = tk.Frame(inner, bg=P['card'])
            body.pack(fill='x', padx=22, pady=16)
            return body

        # --- getting started
        b = tab('Getting started')
        for i, (title, text) in enumerate(HELP_STEPS, 1):
            r = tk.Frame(b, bg=P['card'])
            r.pack(fill='x', pady=7)
            self.badge(r, str(i)).pack(side='left', anchor='n', padx=(0, 12))
            col = tk.Frame(r, bg=P['card'])
            col.pack(side='left', fill='x', expand=True)
            tk.Label(col, text=title, font=self.bold, bg=P['card'], fg=P['text']).pack(anchor='w')
            tk.Label(col, text=text, wraplength=560, justify='left', bg=P['card'],
                     fg=P['muted']).pack(anchor='w', pady=(2, 0))

        # --- keys
        b = tab('Keyboard & mouse')
        for section, rows in HELP_KEYS:
            tk.Label(b, text=section, font=self.f_h2, bg=P['card'], fg=P['text']).pack(anchor='w', pady=(12, 4))
            for keys, what in rows:
                r = tk.Frame(b, bg=P['card'])
                r.pack(fill='x', pady=3)
                kf = tk.Frame(r, bg=P['card'], width=190)
                kf.pack(side='left', anchor='n')
                kf.pack_propagate(False)
                kf.configure(height=30)
                sep = '+' if keys[0] == 'Ctrl' else ('' if all(len(k) == 1 for k in keys) else 'or')
                for j, k in enumerate(keys):
                    if j and sep:
                        tk.Label(kf, text=sep, bg=P['card'], fg=P['muted']).pack(side='left', padx=4)
                    elif j:
                        tk.Frame(kf, width=4, bg=P['card']).pack(side='left')
                    tk.Label(kf, text=k, font=self.f_key, bg=P['sel'], fg=P['accent'], padx=7, pady=2,
                             highlightthickness=1, highlightbackground=P['border']).pack(side='left')
                tk.Label(r, text=what, wraplength=400, justify='left', bg=P['card'],
                         fg=P['text']).pack(side='left', anchor='n', pady=3)

        # --- tips
        b = tab('Tips')
        for t in HELP_TIPS:
            r = tk.Frame(b, bg=P['card'])
            r.pack(fill='x', pady=6)
            tk.Label(r, text='💡', bg=P['card']).pack(side='left', anchor='n', padx=(0, 10))
            tk.Label(r, text=t, wraplength=580, justify='left', bg=P['card'], fg=P['text']).pack(side='left')

        ttk.Button(win, text='Got it', style='Accent.TButton', command=close).pack(pady=(4, 16))
        win.focus_set()

    # ---------- screen 1: setup ----------
    def show_setup(self):
        self.screen = 'setup'
        self._clear()
        area = self.scroll_area(self.body)
        f = tk.Frame(area, bg=P['bg'])
        f.pack(fill='x', padx=44, pady=(24, 16))
        tk.Label(f, text='Set up your exam', font=self.f_title, bg=P['bg'], fg=P['text']).pack(anchor='w')
        tk.Label(f, text='Three quick steps, then press Start.   Need help?  Press F1.',
                 fg=P['muted'], bg=P['bg']).pack(anchor='w', pady=(0, 16))

        # 1 - file
        c = self.card(f)
        self.step_header(c, '1', 'Question PDF')
        r = tk.Frame(c, bg=P['card'])
        r.pack(fill='x')
        self.v_file = tk.StringVar(value=self.bank.path if self.bank else '')
        ttk.Entry(r, textvariable=self.v_file, state='readonly').pack(side='left', fill='x', expand=True)
        ttk.Button(r, text='Browse…', command=self.browse).pack(side='left', padx=(10, 0))
        self.lbl_file = tk.Label(c, text='No file chosen yet.', fg=P['muted'], bg=P['card'], anchor='w')
        self.lbl_file.pack(anchor='w', pady=(8, 0))
        self.pbar = ttk.Progressbar(c, mode='determinate', length=320)   # packed (after lbl_file) while loading

        # 2 - which questions
        c = self.card(f)
        self.step_header(c, '2', 'Which questions?')
        self.v_range = tk.StringVar(value=self.cfg.get('range', ''))
        ttk.Entry(c, textvariable=self.v_range).pack(fill='x')
        r = tk.Frame(c, bg=P['card'])
        r.pack(anchor='w', pady=(8, 0))
        tk.Label(r, text='Examples:', fg=P['muted'], bg=P['card']).pack(side='left', padx=(0, 6))
        for ex in ('7', '5-61', '1,5-61,69,73-152'):
            tk.Label(r, text=ex, font=self.f_key, bg=P['sel'], fg=P['accent'], padx=7, pady=1).pack(side='left', padx=3)
        tk.Label(r, text='  (empty = all)', fg=P['muted'], bg=P['card']).pack(side='left')
        self.lbl_pool = tk.Label(c, text='', anchor='w', bg=P['card'], fg=P['text'])
        self.lbl_pool.pack(anchor='w', pady=(8, 0))

        # 3 - count + options
        c = self.card(f)
        self.step_header(c, '3', 'How many questions?')
        r = tk.Frame(c, bg=P['card'])
        r.pack(anchor='w')
        self.v_count = tk.StringVar(value=str(self.cfg.get('count', 30)))
        ttk.Spinbox(r, from_=1, to=9999, textvariable=self.v_count, width=8).pack(side='left')
        ttk.Button(r, text='All from the pool', command=self.use_all).pack(side='left', padx=10)
        tk.Label(c, text='They are picked randomly from the questions chosen in step 2.',
                 fg=P['muted'], bg=P['card']).pack(anchor='w', pady=(6, 10))
        self.v_practice = tk.BooleanVar(value=self.cfg.get('practice', False))
        self.v_shuffle = tk.BooleanVar(value=self.cfg.get('shuffle', False))
        ttk.Checkbutton(c, text='Practice mode: show right / wrong right after each answer',
                        variable=self.v_practice, style='Card.TCheckbutton').pack(anchor='w')
        ttk.Checkbutton(c, text='Shuffle the variants (A–E) of each question',
                        variable=self.v_shuffle, style='Card.TCheckbutton').pack(anchor='w', pady=(4, 0))

        r = tk.Frame(f, bg=P['bg'])
        r.pack(fill='x', pady=(6, 0))
        self.btn_start = ttk.Button(r, text='▶   Start exam', style='Accent.TButton',
                                    command=self.start_from_setup, state='disabled')
        self.btn_start.pack(side='left', ipadx=18, ipady=4)
        tk.Label(r, text='or press Enter', fg=P['muted'], bg=P['bg']).pack(side='left', padx=12)

        tk.Label(f, text='© Exam Trainer  |  Instagram: the.musdi', fg=P['muted'], bg=P['bg'],
                 font=self.f_small).pack(anchor='e', pady=(22, 0))

        self.v_range.trace_add('write', lambda *a: self.update_pool())
        if self.bank:
            self.file_ready()

    def browse(self):
        start = os.path.dirname(self.cfg.get('file', '')) or None
        path = filedialog.askopenfilename(title='Choose the question PDF', initialdir=start,
                                          filetypes=[('PDF files', '*.pdf'), ('All files', '*.*')])
        if path:
            self.load_path(path)

    def load_path(self, path):
        self.bank = None
        self._load_id += 1
        self.v_file.set(path)
        self.btn_start.configure(state='disabled')
        self.lbl_pool.configure(text='')
        self.lbl_file.configure(text='Reading the PDF…', fg=P['muted'])
        self.pbar.pack(anchor='w', pady=(6, 0), after=self.lbl_file)
        self.pbar['value'] = 0
        threading.Thread(target=self._load_thread, args=(path, self._load_id), daemon=True).start()
        if not self._polling:
            self._polling = True
            self.after(100, self._poll)

    def _load_thread(self, path, lid):
        try:
            with pdfplumber.open(path) as pdf:
                items = collect_items(pdf, lambda i, n: self.msgs.put(('prog', lid, i, n)))
            qs = group_questions(items)
            if not qs:
                raise ValueError('No questions found in this PDF.')
            self.msgs.put(('done', lid, Bank(path, qs)))
        except Exception as e:                      # show any problem to the user
            self.msgs.put(('err', lid, str(e)))

    def _poll(self):
        try:
            while True:
                m = self.msgs.get_nowait()
                if m[1] != self._load_id:           # stale message from an older load
                    continue
                if m[0] == 'prog':
                    self.pbar['maximum'] = m[3]
                    self.pbar['value'] = m[2]
                    self.lbl_file.configure(text=f'Reading the PDF…  page {m[2]} / {m[3]}')
                elif m[0] == 'done':
                    self._polling = False
                    self.bank = m[2]
                    self.file_ready()
                    return
                else:
                    self._polling = False
                    self.pbar.pack_forget()
                    self.lbl_file.configure(text='Could not read the file: ' + m[2], fg=P['badb'])
                    return
        except queue.Empty:
            pass
        except tk.TclError:                         # setup screen was replaced meanwhile
            self._polling = False
            return
        self.after(100, self._poll)

    def file_ready(self):
        self.pbar.pack_forget()
        n = self.bank.numbers
        self.lbl_file.configure(text=f'✔  {len(n)} questions found  (#{n[0]} – #{n[-1]})', fg=P['okb'])
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
        self.lbl_pool.configure(text=msg, fg=P['badb'] if (bad or not ids) else P['text'])

    def use_all(self):
        if self.bank:
            self.v_count.set(str(len(self.pool)))

    def start_from_setup(self):
        if not self.bank:
            return
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
        self.cfg.update(file=self.bank.path, range=self.v_range.get().strip(), count=n,
                        practice=self.practice, shuffle=self.shuffle_opts)
        save_config(self.cfg)
        if n > len(self.pool):
            messagebox.showinfo('Exam Trainer', f'Only {len(self.pool)} questions in the pool - using all of them.')
            n = len(self.pool)
        self.start_exam(random.sample(self.pool, n))

    # ---------- screen 2: exam ----------
    def start_exam(self, ids):
        self.sess = Session(self.bank, ids, self.shuffle_opts)
        self.cur = 0
        self.t0 = time.time()
        self.elapsed = 0.0
        self._stop_timer()
        self._tick()
        self.show_question()

    def _tick(self):
        self.elapsed = time.time() - self.t0
        if self.lbl_time is not None:
            try:
                self.lbl_time.configure(text='⏱ ' + fmt_time(self.elapsed))
            except tk.TclError:
                pass
        self._tick_job = self.after(1000, self._tick)

    def _stop_timer(self):
        if self._tick_job:
            self.after_cancel(self._tick_job)
            self._tick_job = None

    def show_question(self, keep_scroll=False):
        pos = self.canvas.yview()[0] if (keep_scroll and self.canvas) else 0
        self.screen = 'exam'
        self._clear()
        s, i = self.sess, self.cur
        num = s.ids[i]
        flagged = i in s.flags
        done = sum(a is not None for a in s.ans)

        top = tk.Frame(self.body, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        top.pack(fill='x')
        row = tk.Frame(top, bg=P['card'], padx=16, pady=10)
        row.pack(fill='x')
        tk.Label(row, text=f'Question {i + 1} / {len(s.ids)}', font=self.f_h2,
                 bg=P['card'], fg=P['text']).pack(side='left')
        if flagged:
            tk.Label(row, text='⚑ marked', bg=P['flag'], fg=P['text'], padx=8, pady=2,
                     font=self.bold).pack(side='left', padx=12)
        self.lbl_time = tk.Label(row, text='⏱ ' + fmt_time(self.elapsed), bg=P['sel'], fg=P['accent'],
                                 padx=10, pady=3, font=self.bold)
        self.lbl_time.pack(side='right')
        tk.Label(row, text=f'{done} / {len(s.ids)} answered', fg=P['muted'],
                 bg=P['card']).pack(side='right', padx=14)
        ttk.Progressbar(top, maximum=len(s.ids), value=done, mode='determinate').pack(fill='x', padx=16, pady=(0, 10))

        bottom = tk.Frame(self.body, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        bottom.pack(side='bottom', fill='x')
        bar = tk.Frame(bottom, bg=P['card'], padx=14, pady=10)
        bar.pack(fill='x')
        ttk.Button(bar, text='←  Previous', command=lambda: self.go(-1),
                   state='normal' if i > 0 else 'disabled').pack(side='left')
        ttk.Button(bar, text='Next  →', style='Accent.TButton', command=lambda: self.go(1),
                   state='normal' if i < len(s.ids) - 1 else 'disabled').pack(side='left', padx=8)
        ttk.Button(bar, text='⚑  Unmark' if flagged else '⚑  Mark  (M)',
                   command=self.toggle_flag).pack(side='left', padx=(18, 0))
        ttk.Button(bar, text='▦  Overview  (O)', command=self.show_overview).pack(side='left', padx=8)
        ttk.Button(bar, text='Finish exam', style='Danger.TButton', command=self.finish).pack(side='right')

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
        tk.Frame(area, height=16, bg=P['bg']).pack()
        self._restore_scroll(pos)

    def pick(self, oi):
        s = self.sess
        # clicking the chosen answer again clears it (only when answers aren't locked by practice mode)
        s.ans[self.cur] = None if s.ans[self.cur] == oi else oi
        self.show_question(keep_scroll=True)

    def go(self, d):
        self.cur = max(0, min(len(self.sess.ids) - 1, self.cur + d))
        self.show_question()

    def toggle_flag(self):
        self.sess.flags ^= {self.cur}
        self.show_question(keep_scroll=True)

    def show_overview(self):
        """Grid with every question: blue = answered, yellow = marked. Click to jump."""
        if self.ov_win is not None:
            self.ov_win.lift()
            return
        s = self.sess
        win = tk.Toplevel(self)
        self.ov_win = win
        win.title('Overview')
        win.configure(bg=P['bg'])
        win.transient(self)

        def close(*_):
            self.ov_win = None
            win.destroy()
        win.protocol('WM_DELETE_WINDOW', close)
        win.bind('<Escape>', close)
        win.bind('<o>', close)
        win.bind('<O>', close)
        leg = tk.Frame(win, bg=P['bg'])
        leg.grid(row=0, column=0, columnspan=10, padx=12, pady=10)
        for txt, col in (('answered', P['ans']), ('marked ⚑', P['flag']), ('open', P['card'])):
            tk.Label(leg, text=f'  {txt}  ', bg=col, fg=P['text'], relief='groove').pack(side='left', padx=6)
        for i in range(len(s.ids)):
            bg = P['flag'] if i in s.flags else (P['ans'] if s.ans[i] is not None else P['card'])
            tk.Button(win, text=f'{i + 1}' + ('⚑' if i in s.flags else ''), width=5, bg=bg, fg=P['text'],
                      activebackground=P['hover'], activeforeground=P['text'], relief='groove',
                      font=self.bold if i == self.cur else None,
                      command=lambda i=i: (close(), self.jump(i))
                      ).grid(row=1 + i // 10, column=i % 10, padx=3, pady=3)
        tk.Frame(win, height=10, bg=P['bg']).grid(row=999, column=0)
        win.focus_set()

    def jump(self, i):
        self.cur = i
        self.show_question()

    def _key(self, e):
        if e.keysym == 'F1':
            self.show_help()
            return
        if e.keysym == 'F2':
            self.toggle_theme()
            return
        if self.screen == 'setup':
            if e.keysym == 'Return' and self.bank and str(self.btn_start.cget('state')) == 'normal':
                self.start_from_setup()
            return
        if self.screen != 'exam' or self.canvas is None:
            return
        s, i = self.sess, self.cur
        if e.state & 0x4:                           # Ctrl held
            if e.keysym == 'Return':
                self.finish()
            return
        if e.keysym in ('Right', 'Return') and i < len(s.ids) - 1:
            self.go(1)
        elif e.keysym == 'Left' and i > 0:
            self.go(-1)
        elif e.keysym == 'Home' and i > 0:
            self.jump(0)
        elif e.keysym == 'End' and i < len(s.ids) - 1:
            self.jump(len(s.ids) - 1)
        elif len(e.char) == 1 and e.char.upper() == 'M':
            self.toggle_flag()
        elif len(e.char) == 1 and e.char.upper() == 'O':
            self.show_overview()
        elif len(e.char) == 1:
            ch = e.char.upper()
            k = LETTERS.index(ch) if ch in LETTERS else (int(ch) - 1 if ch in '12345678' else -1)
            if 0 <= k < len(s.order[i]) and not (self.practice and s.ans[i] is not None):
                self.pick(s.order[i][k])

    # ---------- screen 3: result ----------
    def finish(self):
        s = self.sess
        left = sum(a is None for a in s.ans)
        if left and not messagebox.askyesno('Finish exam', f'{left} question(s) are unanswered.\nFinish anyway?'):
            return
        self._stop_timer()
        self.elapsed = time.time() - self.t0
        if self.ov_win is not None:
            self.ov_win.destroy()
            self.ov_win = None
        self.build_results('all')

    def score_ring(self, parent, pct, size=130):
        c = tk.Canvas(parent, width=size, height=size, bg=P['bg'], highlightthickness=0)
        col = P['okb'] if pct >= 70 else (P['warn'] if pct >= 50 else P['badb'])
        c.create_oval(12, 12, size - 12, size - 12, outline=P['border'], width=12)
        if pct > 0:
            c.create_arc(12, 12, size - 12, size - 12, start=90, extent=-min(359.9, 3.6 * pct),
                         style='arc', outline=col, width=12)
        c.create_text(size / 2, size / 2, text=f'{pct:.0f}%', font=self.f_ring, fill=P['text'])
        return c

    def stat_tile(self, parent, value, label, color):
        t = tk.Frame(parent, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        t.pack(side='left', padx=(0, 10))
        tk.Label(t, text=value, font=self.f_score, fg=color, bg=P['card']).pack(padx=18, pady=(8, 0))
        tk.Label(t, text=label, fg=P['muted'], bg=P['card']).pack(padx=18, pady=(0, 8))

    def build_results(self, flt='all'):
        s = self.sess
        self.screen = 'result'
        self._clear()
        n, ok = len(s.ids), s.score()
        left = sum(a is None for a in s.ans)
        wrong = n - ok - left
        pct = ok / n * 100

        head = tk.Frame(self.body, bg=P['bg'], padx=24, pady=16)
        head.pack(fill='x')
        self.score_ring(head, pct).pack(side='left', padx=(0, 22))
        col = tk.Frame(head, bg=P['bg'])
        col.pack(side='left', fill='x')
        tk.Label(col, text=f'{ok} / {n} correct', font=self.f_score, bg=P['bg'], fg=P['text']).pack(anchor='w')
        tiles = tk.Frame(col, bg=P['bg'])
        tiles.pack(anchor='w', pady=8)
        self.stat_tile(tiles, str(ok), 'Correct', P['okb'])
        self.stat_tile(tiles, str(wrong), 'Wrong', P['badb'])
        self.stat_tile(tiles, str(left), 'Unanswered', P['muted'])
        self.stat_tile(tiles, fmt_time(self.elapsed), 'Time', P['accent'])

        r = tk.Frame(self.body, bg=P['bg'], padx=24)
        r.pack(fill='x')
        ttk.Button(r, text='New exam', style='Accent.TButton', command=self.new_exam).pack(side='left')
        ttk.Button(r, text='Retry the wrong / unanswered ones', command=self.retry,
                   state='normal' if ok < n else 'disabled').pack(side='left', padx=8)
        ttk.Button(r, text='Copy their numbers', command=self.copy_wrong,
                   state='normal' if ok < n else 'disabled').pack(side='left')
        self.lbl_copied = tk.Label(r, text='', fg=P['okb'], bg=P['bg'])
        self.lbl_copied.pack(side='left', padx=10)

        counts = dict(all=n, wrong=wrong, unanswered=left, marked=len(s.flags))
        self.v_filter = tk.StringVar(value=flt)
        fr = tk.Frame(self.body, bg=P['bg'], padx=24, pady=10)
        fr.pack(fill='x')
        tk.Label(fr, text='Show:', fg=P['muted'], bg=P['bg']).pack(side='left', padx=(0, 10))
        for key, label in (('all', 'All'), ('wrong', 'Wrong'), ('unanswered', 'Unanswered'), ('marked', 'Marked ⚑')):
            ttk.Radiobutton(fr, text=f'{label} ({counts[key]})', value=key, variable=self.v_filter,
                            command=self.render_results).pack(side='left', padx=(0, 14))

        self.res_area = self.scroll_area(self.body)
        self.render_results()

    def render_results(self, keep_scroll=False):
        s = self.sess
        pos = self.canvas.yview()[0] if (keep_scroll and self.canvas) else 0
        for w in self.res_area.winfo_children():
            w.destroy()
        self.photos = []
        flt = self.v_filter.get()
        self.config(cursor='watch')
        self.update_idletasks()
        wrap = self.wrap()
        shown = 0
        for i, num in enumerate(s.ids):
            correct, blank = s.is_correct(i), s.ans[i] is None
            if ((flt == 'wrong' and (correct or blank)) or (flt == 'unanswered' and not blank)
                    or (flt == 'marked' and i not in s.flags)):
                continue
            shown += 1
            stem, opts = s.bank.load(num)
            verdict = '✔ correct' if correct else ('– unanswered' if blank else '✘ wrong')
            flag = '   ⚑ marked' if i in s.flags else ''
            self.question_card(self.res_area, stem, header=f'{i + 1}.   (#{num})   {verdict}{flag}')
            for k, oi in enumerate(s.order[i]):
                is_ok, blocks = opts[oi]
                state = 'ok' if is_ok else ('bad' if s.ans[i] == oi else 'norm')
                self.option_row(self.res_area, LETTERS[k], blocks, wrap, state)
        if not shown:
            tk.Label(self.res_area, text='Nothing to show here.', fg=P['muted'], bg=P['bg'], pady=40).pack()
        tk.Frame(self.res_area, height=16, bg=P['bg']).pack()
        self.config(cursor='')
        if keep_scroll:
            self._restore_scroll(pos)
        else:
            self.canvas.yview_moveto(0)

    def copy_wrong(self):
        ids = sorted(self.sess.wrong_ids())
        self.clipboard_clear()
        self.clipboard_append(','.join(map(str, ids)))
        self.lbl_copied.configure(text='Copied - paste it into step 2 on the start screen')

    def new_exam(self):
        self.sess = None
        self.show_setup()

    def retry(self):
        self.start_exam(self.sess.wrong_ids())


if __name__ == '__main__':
    if sys.platform == 'win32':                     # crisp text on high-DPI Windows screens
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()
