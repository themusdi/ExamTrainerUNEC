"""One PDF's questions.  Pictures / formulas are cropped lazily, only when a question is shown.

The rendering code (_render_page / _crop / _blocks) is the original one; additions are: releasing the
PDF handle (close), tolerance for missing / unreadable pages, text previews and fingerprints.
"""
import threading

from pdf_parser import SCALE, JUNK_RE, join_lines, fingerprint

MISSING_IMAGE_TEXT = '[picture not available]'


class Bank:
    def __init__(self, path, questions, pdf_id=None, name=''):
        self.path = path
        self.pdf_id = pdf_id
        self.name = name
        self.q = {}
        for q in questions:
            self.q.setdefault(q['num'], q)
        self.numbers = sorted(self.q)
        self._doc = None
        self._pages = {}
        self._blocks_cache = {}
        self._fps = {}
        self._fp_to_num = None
        self._lock = threading.RLock()          # rendering may happen in an export thread

    # ---------------------------------------------------------------- identity
    def fp(self, num):
        f = self._fps.get(num)
        if f is None:
            f = self._fps[num] = fingerprint(self.q[num])
        return f

    def fingerprints(self):
        return {n: self.fp(n) for n in self.numbers}

    def num_for_fp(self, fp):
        if self._fp_to_num is None:
            self._fp_to_num = {}
            for n in self.numbers:
                self._fp_to_num.setdefault(self.fp(n), n)
        return self._fp_to_num.get(fp)

    # ---------------------------------------------------------------- text only (no rendering)
    def preview(self, num, limit=110):
        q = self.q.get(num)
        if not q:
            return ''
        txt = ' '.join(it['text'] for it in q['stem'] if it['k'] == 't').strip()
        txt = ' '.join(txt.split())
        if not txt:
            return '[question with pictures]'
        return txt if len(txt) <= limit else txt[:limit - 1].rstrip() + '…'

    def plain(self, num):
        """{'text': str, 'options': [{'text':, 'correct':}], 'images': int}  - for JSON export / reports."""
        q = self.q[num]

        def text_of(items):
            lines = [it for it in items if it['k'] == 't']
            return join_lines(lines).strip() if lines else ''
        return dict(
            number=num,
            text=text_of(q['stem']),
            options=[dict(text=text_of(o['items']), correct=bool(o['correct']),
                          has_image=any(it['k'] == 'i' for it in o['items'])) for o in q['opts']],
            images=sum(1 for it in q['stem'] if it['k'] == 'i'))

    # ---------------------------------------------------------------- rendering (original logic)
    def _render_page(self, p):
        if self._doc is None:
            import pypdfium2 as pdfium
            self._doc = pdfium.PdfDocument(self.path)
        if p not in self._pages:
            if len(self._pages) > 3:
                self._pages.pop(next(iter(self._pages)))
            page = self._doc[p]
            try:
                self._pages[p] = page.render(scale=SCALE).to_pil().convert('RGB')
            finally:
                try:
                    page.close()
                except Exception:
                    pass
        return self._pages[p]

    def _crop(self, p, x0, top, x1, bot):
        try:
            im = self._render_page(p)
            box = (max(0, int(x0 * SCALE)), max(0, int(top * SCALE)),
                   min(im.width, int(x1 * SCALE) + 1), min(im.height, int(bot * SCALE) + 1))
            if box[2] <= box[0] or box[3] <= box[1]:
                return None
            return im.crop(box)
        except Exception:                      # file moved / damaged / page missing -> placeholder
            return None

    def _img_block(self, *args):
        im = self._crop(*args)
        return ('i', im) if im is not None else ('t', MISSING_IMAGE_TEXT)

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
                out.append(self._img_block(it['p'], it['x0'] - 2, it['top'] - 2, it['x1'] + 2, it['bot'] + 2))
                continue
            h = it['bot'] - it['top']
            hit = [im for im in imgs if im['p'] == it['p']
                   and min(it['bot'], im['bot']) - max(it['top'], im['top']) > 0.5 * h]
            if hit:                                   # formula sitting inside the text line
                flush()
                left = 44 if it.get('opt') else it['x0'] - 1
                out.append(self._img_block(it['p'], left, it['top'] - 1,
                                           max([it['x1']] + [im['x1'] for im in hit]) + 2, it['bot'] + 1))
            else:
                buf.append(it)
        flush()
        if any(b[0] == 'i' for b in out):
            out = [b for b in out if not (b[0] == 't' and JUNK_RE.match(b[1]))]
        return out

    def load(self, num):
        """-> (stem_blocks, [(is_correct, option_blocks), ...]); cached."""
        with self._lock:
            c = self._blocks_cache.get(num)
            if c is None:
                q = self.q[num]
                c = (self._blocks(q['stem']), [(o['correct'], self._blocks(o['items'])) for o in q['opts']])
                self._blocks_cache[num] = c
            return c

    def close(self):
        """Release the PDF handle and rendered pages (the question text stays usable)."""
        with self._lock:
            self._pages.clear()
            if self._doc is not None:
                try:
                    self._doc.close()
                except Exception:
                    pass
                self._doc = None
            if len(self._blocks_cache) > 150:          # bound memory on huge banks
                self._blocks_cache.clear()
