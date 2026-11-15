"""Exports: formatted PDF report of an exam, CSV (history / statistics), JSON question bank, clipboard text.

The PDF report is drawn with Pillow (already required for the pictures), so no extra dependency is needed.
"""
import csv
import json
import os
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from exam_engine import mode_label
from exam_stats import fmt_clock, fmt_duration, fmt_pct

LETTERS = 'ABCDEFGH'

# ----------------------------------------------------------------------------- fonts
_FONT_CANDIDATES = {
    False: ['segoeui.ttf', 'arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf', 'LiberationSans-Regular.ttf',
            'FreeSans.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'],
    True: ['segoeuib.ttf', 'arialbd.ttf', 'Arial Bold.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf',
           'FreeSansBold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
           '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
}
_font_cache = {}


def get_font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        font = None
        for name in _FONT_CANDIDATES[bold]:
            try:
                font = ImageFont.truetype(name, size)
                break
            except (OSError, ValueError):
                continue
        if font is None:
            try:
                font = ImageFont.load_default(size)
            except TypeError:                         # very old Pillow
                font = ImageFont.load_default()
        _font_cache[key] = font
    return _font_cache[key]


# ----------------------------------------------------------------------------- PDF report
PAGE_W, PAGE_H, MARGIN, DPI = 1240, 1754, 90, 150           # A4 @150 dpi
INK, MUTED, LINE = (29, 35, 48), (102, 112, 133), (217, 221, 229)
GREEN, GREEN_BG = (26, 143, 76), (222, 245, 232)
RED, RED_BG = (211, 59, 59), (252, 226, 226)
BLUE, AMBER = (47, 111, 237), (217, 154, 26)


class _Pager:
    def __init__(self):
        self.pages = []
        self.draw = None
        self.y = MARGIN
        self.new_page()

    def new_page(self):
        im = Image.new('RGB', (PAGE_W, PAGE_H), 'white')
        self.pages.append(im)
        self.draw = ImageDraw.Draw(im)
        self.y = MARGIN

    def ensure(self, h):
        if self.y + h > PAGE_H - MARGIN and self.y > MARGIN + 5:
            self.new_page()

    def wrap(self, text, font, width):
        lines = []
        for para in str(text).split('\n'):
            cur = ''
            for word in para.split(' '):
                trial = (cur + ' ' + word).strip()
                if self.draw.textlength(trial, font=font) <= width:
                    cur = trial
                    continue
                if cur:
                    lines.append(cur)
                cur = word
                while self.draw.textlength(cur, font=font) > width and len(cur) > 1:     # very long word
                    k = len(cur)
                    while k > 1 and self.draw.textlength(cur[:k], font=font) > width:
                        k -= 1
                    lines.append(cur[:k])
                    cur = cur[k:]
            lines.append(cur)
        return lines

    def text(self, text, size=22, bold=False, color=INK, x=MARGIN, width=None, gap=6):
        font = get_font(size, bold)
        width = width or (PAGE_W - MARGIN - x)
        lh = int(size * 1.35)
        for line in self.wrap(text, font, width):
            self.ensure(lh)
            self.draw.text((x, self.y), line, font=font, fill=color)
            self.y += lh
        self.y += gap

    def rule(self, gap=14):
        self.ensure(gap * 2)
        self.draw.line([(MARGIN, self.y), (PAGE_W - MARGIN, self.y)], fill=LINE, width=2)
        self.y += gap


def _layout_blocks(pager, blocks, width, size=22):
    """-> list of ('t', [lines], font, height) / ('i', image, height)"""
    font, lh, out = get_font(size), int(size * 1.35), []
    for kind, val in blocks:
        if kind == 't':
            lines = pager.wrap(val, font, width)
            out.append(('t', lines, font, lh * len(lines) + 4))
        else:
            im = val
            if im.width > width:
                im = im.resize((int(width), max(1, int(im.height * width / im.width))), Image.LANCZOS)
            max_h = PAGE_H - 2 * MARGIN - 200
            if im.height > max_h:
                im = im.resize((max(1, int(im.width * max_h / im.height)), int(max_h)), Image.LANCZOS)
            out.append(('i', im, im.height + 6))
    return out


def _draw_laid(pager, laid, x, y, color=INK, lh=29):
    for item in laid:
        if item[0] == 't':
            for line in item[1]:
                pager.draw.text((x, y), line, font=item[2], fill=color)
                y += lh
            y += 4
        else:
            pager.pages[-1].paste(item[1], (int(x), int(y)))
            y += item[2]
    return y


def _selected(session, which):
    out = []
    for i, num in enumerate(session.ids):
        st = session.status(i)
        if which == 'wrong' and st == 'correct':
            continue
        if which == 'marked' and i not in session.flags:
            continue
        out.append(i)
    return out


def export_results_pdf(path, session, meta, which='all', notes=None, progress=None):
    """Write a formatted PDF report.

    meta: dict(pdf_name=, finished=, summary=dict(n, correct, wrong, unanswered, percent, duration))
    which: 'all' | 'wrong' (wrong + unanswered) | 'marked'
    notes: optional {question number: note text}
    Returns the number of pages."""
    pg = _Pager()
    s = meta.get('summary') or session.summary()
    pg.text('Exam results', 40, True, INK, gap=4)
    pg.text(meta.get('pdf_name', ''), 26, False, BLUE, gap=2)
    when = meta.get('finished') or datetime.now().isoformat(timespec='minutes')
    pg.text(f'{mode_label(session.mode)} mode   |   {str(when).replace("T", " ")[:16]}   |   '
            f'time {fmt_clock(s["duration"])}', 20, False, MUTED, gap=10)
    pg.rule()
    pg.text(f'{s["correct"]} / {s["n"]} correct   ({fmt_pct(s["percent"])})', 34, True,
            GREEN if s['percent'] >= 70 else (AMBER if s['percent'] >= 50 else RED), gap=2)
    pg.text(f'Correct {s["correct"]}     Wrong {s["wrong"]}     Unanswered {s["unanswered"]}', 22, False, MUTED, gap=6)
    if which != 'all':
        pg.text({'wrong': 'Showing only wrong and unanswered questions.',
                 'marked': 'Showing only questions marked for review.'}[which], 20, False, MUTED, gap=4)
    pg.rule(20)

    idx = _selected(session, which)
    if not idx:
        pg.text('No questions to show.', 24, False, MUTED)
    for n_done, i in enumerate(idx):
        if progress:
            progress(n_done / max(1, len(idx)), f'Question {n_done + 1} / {len(idx)}')
        num, st = session.ids[i], session.status(i)
        vcol = {'correct': GREEN, 'wrong': RED, 'skipped': AMBER}[st]
        vtxt = {'correct': 'Correct', 'wrong': 'Wrong', 'skipped': 'Unanswered'}[st]
        pg.ensure(120)
        pg.text(f'{i + 1}.   Question #{num}   -   {vtxt}' + ('   (marked)' if i in session.flags else ''),
                22, True, vcol, gap=2)
        stem, opts = session.bank.load(num)
        w = PAGE_W - 2 * MARGIN
        for item in _layout_blocks(pg, stem, w):
            pg.ensure(item[-1])
            pg.y = _draw_laid(pg, [item], MARGIN, pg.y)
        pg.y += 6
        for k, oi in enumerate(session.order[i]):
            ok, blocks = opts[oi]
            chosen = session.ans[i] == oi
            laid = _layout_blocks(pg, blocks, w - 110)
            h = max(sum(x[-1] for x in laid), 34) + 18
            pg.ensure(h)
            top = pg.y
            if ok:
                bg, edge = GREEN_BG, GREEN
            elif chosen:
                bg, edge = RED_BG, RED
            else:
                bg, edge = (255, 255, 255), LINE
            pg.draw.rounded_rectangle([MARGIN, top, PAGE_W - MARGIN, top + h], radius=10, fill=bg, outline=edge, width=2)
            pg.draw.text((MARGIN + 16, top + 9), LETTERS[k], font=get_font(22, True), fill=edge if edge != LINE else MUTED)
            _draw_laid(pg, laid, MARGIN + 64, top + 9)
            tag = ('your answer - correct' if (ok and chosen) else 'correct answer' if ok
                   else 'your answer' if chosen else '')
            if tag:
                f = get_font(16, True)
                tw = pg.draw.textlength(tag, font=f)
                pg.draw.text((PAGE_W - MARGIN - 14 - tw, top + 10), tag, font=f, fill=edge)
            pg.y = top + h + 8
        note = (notes or {}).get(num)
        if note:
            pg.text('Note: ' + note, 19, False, MUTED, x=MARGIN + 10, width=PAGE_W - 2 * MARGIN - 20, gap=4)
        pg.y += 14
    # footer on every page
    total = len(pg.pages)
    for n, im in enumerate(pg.pages, 1):
        d = ImageDraw.Draw(im)
        f = get_font(16)
        d.text((MARGIN, PAGE_H - MARGIN + 30), 'Exam Trainer', font=f, fill=MUTED)
        t = f'Page {n} / {total}'
        d.text((PAGE_W - MARGIN - d.textlength(t, font=f), PAGE_H - MARGIN + 30), t, font=f, fill=MUTED)
    first, rest = pg.pages[0], pg.pages[1:]
    first.save(path, 'PDF', resolution=float(DPI), save_all=True, append_images=rest)
    if progress:
        progress(1.0, 'Done')
    return total


# ----------------------------------------------------------------------------- CSV
def _csv(path, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:      # utf-8-sig: Excel opens it correctly
        csv.writer(f).writerows(rows)


def export_history_csv(path, exams):
    rows = [['Date', 'PDF', 'Mode', 'Kind', 'Questions', 'Correct', 'Wrong', 'Unanswered', 'Score %',
             'Time (seconds)', 'Time']]
    for e in exams:
        rows.append([str(e['finished_at']).replace('T', ' '), e['pdf_name'], mode_label(e['mode']), e['kind'],
                     e['n_questions'], e['correct'], e['wrong'], e['unanswered'], f'{e["score"]:.1f}',
                     int(e['duration'] or 0), fmt_clock(e['duration'] or 0)])
    _csv(path, rows)
    return len(exams)


def export_stats_csv(path, overall, last7, last30, per_pdf, daily):
    def block(title, d):
        return [[title], ['Exams', d['exams']], ['Questions answered', d['answered']],
                ['Correct', d['correct']], ['Wrong', d['wrong']],
                ['Accuracy %', '' if d['accuracy'] is None else f'{d["accuracy"]:.1f}'],
                ['Average score %', '' if d['avg_score'] is None else f'{d["avg_score"]:.1f}'],
                ['Best score %', '' if d['best'] is None else f'{d["best"]:.1f}'],
                ['Study time', fmt_duration(d['time'])], []]
    rows = [['Exam Trainer - statistics', datetime.now().strftime('%Y-%m-%d %H:%M')], []]
    rows += block('Overall', overall) + block('Last 7 days', last7) + block('Last 30 days', last30)
    rows.append(['Per PDF'])
    rows.append(['PDF', 'Exams', 'Answered', 'Accuracy %', 'Average score %', 'Best score %', 'Study time'])
    for d in per_pdf:
        rows.append([d['name'], d['exams'], d['answered'], '' if d['accuracy'] is None else f'{d["accuracy"]:.1f}',
                     '' if d['avg_score'] is None else f'{d["avg_score"]:.1f}',
                     '' if d['best'] is None else f'{d["best"]:.1f}', fmt_duration(d['time'])])
    rows += [[], ['Daily (last 30 days)'], ['Date', 'Exams', 'Questions answered', 'Correct', 'Average score %']]
    for d in daily:
        rows.append([d['date'], d['exams'], d['answered'], d['correct'],
                     '' if d['avg_score'] is None else f'{d["avg_score"]:.1f}'])
    _csv(path, rows)


# ----------------------------------------------------------------------------- JSON question bank
def export_bank_json(path, bank, name, qstates=None):
    """Text content of every question (pictures are only counted, not embedded)."""
    qs = []
    for n in bank.numbers:
        d = bank.plain(n)
        st = (qstates or {}).get(n)
        if st is not None:
            d['user'] = dict(favorite=bool(st['favorite']), difficult=bool(st['difficult']),
                             marked=bool(st['marked']), note=st['note'], times_wrong=st['times_wrong'],
                             times_correct=st['times_correct'])
        qs.append(d)
    data = dict(source=name, exported=datetime.now().isoformat(timespec='seconds'),
                question_count=len(qs), questions=qs)
    tmp = str(path) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return len(qs)


# ----------------------------------------------------------------------------- clipboard text
def numbers_text(numbers):
    return ','.join(str(n) for n in sorted(numbers))


def results_text(session, pdf_name):
    s = session.summary()
    lines = [f'Exam Trainer - {pdf_name}',
             f'{mode_label(session.mode)} mode   {fmt_clock(s["duration"])}',
             f'Score: {s["correct"]} / {s["n"]} ({fmt_pct(s["percent"])})',
             f'Correct {s["correct"]}   Wrong {s["wrong"]}   Unanswered {s["unanswered"]}']
    wrong = session.wrong_ids()
    if wrong:
        lines.append('Wrong / unanswered: ' + numbers_text(wrong))
    return '\n'.join(lines)


def default_filename(prefix, ext):
    return f'{prefix}-{datetime.now().strftime("%Y%m%d-%H%M")}.{ext}'
