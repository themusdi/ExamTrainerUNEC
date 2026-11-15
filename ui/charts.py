"""Small canvas charts (no matplotlib): bar chart and line chart with grid, labels and an empty state."""
import math
import tkinter as tk

from ui.theme import P


class ChartCanvas(tk.Canvas):
    def __init__(self, master, height=200, **kw):
        super().__init__(master, height=height, bg=P['card'], highlightthickness=0, **kw)
        self.kind = 'bar'
        self.labels, self.values, self.ymax, self.unit = [], [], None, ''
        self.colors = None
        self.empty_text = 'No data yet'
        self.bind('<Configure>', lambda e: self.redraw())

    def set_data(self, kind, labels, values, ymax=None, unit='', colors=None, empty_text=None):
        """values may contain None (= no data for that point). ymax=None -> automatic scale."""
        self.kind, self.labels, self.values, self.ymax, self.unit = kind, list(labels), list(values), ymax, unit
        self.colors = colors
        if empty_text:
            self.empty_text = empty_text
        self.configure(bg=P['card'])
        self.redraw()

    @staticmethod
    def _nice(v):
        if v <= 0:
            return 1
        mag = 10 ** math.floor(math.log10(v))
        for m in (1, 2, 5, 10):
            if v <= m * mag:
                return m * mag
        return 10 * mag

    def redraw(self):
        self.delete('all')
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 100)
        real = [v for v in self.values if v is not None]
        if not real:
            self.create_text(w / 2, h / 2, text=self.empty_text, fill=P['muted'])
            return
        left, right, top, bottom = 46, 14, 12, 28
        ymax = self.ymax or self._nice(max(real))
        if ymax <= 0:
            ymax = 1
        for k in range(5):
            y = top + (h - top - bottom) * (1 - k / 4)
            self.create_line(left, y, w - right, y, fill=P['border'])
            val = ymax * k / 4
            self.create_text(left - 6, y, text=f'{val:g}{self.unit}', anchor='e', fill=P['muted'], font=('TkDefaultFont', 8))
        n = len(self.values)
        span = w - left - right
        slot = span / max(1, n)
        step = max(1, math.ceil(n * 46 / max(1, span)))
        for i, lab in enumerate(self.labels):
            if i % step == 0:
                self.create_text(left + slot * (i + 0.5), h - bottom + 12, text=lab, fill=P['muted'], font=('TkDefaultFont', 8))
        pts = []
        for i, v in enumerate(self.values):
            cx = left + slot * (i + 0.5)
            if v is None:
                continue
            y = top + (h - top - bottom) * (1 - min(v, ymax) / ymax)
            col = (self.colors[i] if self.colors else P['accent'])
            if self.kind == 'bar':
                bw = max(2, slot * 0.62)
                self.create_rectangle(cx - bw / 2, y, cx + bw / 2, h - bottom, fill=col, outline='')
            else:
                pts.append((cx, y, col))
        if self.kind == 'line' and pts:
            if len(pts) > 1:
                self.create_line(*[c for p in pts for c in p[:2]], fill=P['accent'], width=2, smooth=False)
            for x, y, col in pts:
                self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=col, outline=P['card'], width=1)
