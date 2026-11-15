"""PDF parsing - the extraction logic of Exam Trainer 1.x, kept verbatim.

Format:  "12. question"  then variants  "• wrong"  /  "√ correct".
Everything between the markers below ("VERBATIM") is the original, tested parser; it must not be
changed without re-testing against real exam PDFs.  Around it this module adds: a content
fingerprint per question, file hashing, a gzip JSON parse cache and friendly errors.
"""
import gzip
import hashlib
import json
import os
import re
from pathlib import Path

from config import PARSER_VERSION


class PDFLoadError(Exception):
    """A problem with a PDF that can be shown to the user as is."""


class CancelledError(Exception):
    """Raised from a progress callback to abort a running parse."""


# ============================== VERBATIM (original parser) ==============================
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



# ============================== END VERBATIM ==============================

def _norm(s):
    return re.sub(r'\s+', ' ', s).strip().lower()


def _items_sig(items):
    parts = []
    for it in items:
        if it['k'] == 't':
            parts.append(_norm(it['text']))
        else:
            parts.append('IMG%dx%d' % (round(it['x1'] - it['x0']), round(it['bot'] - it['top'])))
    return '|'.join(p for p in parts if p)


def fingerprint(q):
    """Identity of a question that does not depend on its number or on which variant is correct."""
    sig = _items_sig(q['stem']) + '##' + '##'.join(_items_sig(o['items']) for o in q['opts'])
    return hashlib.sha1(sig.encode('utf-8')).hexdigest()[:16]


def file_sha256(path, progress=None, chunk=1 << 20):
    size = max(1, os.path.getsize(path))
    h, done = hashlib.sha256(), 0
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(min(done, size), size)
    return h.hexdigest()


def _cache_path(cache_dir, sha):
    return Path(cache_dir) / f'{sha}.v{PARSER_VERSION}.json.gz'


def _read_cache(p):
    try:
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list) and data and all('num' in q and 'opts' in q for q in data):
            return data
    except (OSError, ValueError, EOFError):
        pass
    return None


def _write_cache(p, qs):
    tmp = Path(str(p) + '.tmp')
    try:
        with gzip.open(tmp, 'wt', encoding='utf-8') as f:
            json.dump(qs, f, ensure_ascii=False)
        os.replace(tmp, p)
    except (OSError, TypeError, ValueError):
        try:
            tmp.unlink()
        except OSError:
            pass


def load_questions(path, sha, cache_dir, progress=None, use_cache=True):
    """Parse a PDF (or load the cached parse of exactly this file content). progress(done, total)."""
    cp = _cache_path(cache_dir, sha)
    if use_cache:
        qs = _read_cache(cp)
        if qs is not None:
            if progress:
                progress(1, 1)
            return qs
    try:
        with open(path, 'rb') as f:
            head = f.read(2048)
    except OSError as e:
        raise PDFLoadError(f'The file cannot be opened: {e.strerror or e}') from e
    if b'%PDF' not in head:
        raise PDFLoadError('This file is not a PDF document.')
    try:
        import pdfplumber
    except ImportError as e:
        raise PDFLoadError('The "pdfplumber" package is missing. Run:  pip install -r requirements.txt') from e
    try:
        with pdfplumber.open(path) as pdf:
            items = collect_items(pdf, progress)
    except CancelledError:
        raise
    except Exception as e:
        raise PDFLoadError('The PDF could not be read - it may be damaged, encrypted or unsupported '
                           f'({type(e).__name__}).') from e
    qs = group_questions(items)
    if not qs:
        raise PDFLoadError('No questions were found in this PDF.\n\nQuestions must start with a number '
                           '("12. text") and every variant with  \u2022  (wrong) or  \u221a  (correct).')
    _write_cache(cp, qs)
    return qs
