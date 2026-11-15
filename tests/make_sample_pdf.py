"""Creates a small exam PDF in the format Exam Trainer expects (used by the automated tests)."""
import sys
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw

FONT_PATHS = ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf']


def _font():
    for p in FONT_PATHS:
        try:
            pdfmetrics.registerFont(TTFont('Body', p))
            return 'Body'
        except Exception:
            continue
    raise SystemExit('no TTF font with the bullet / check-mark glyphs found')


def picture(w, h, label):
    im = Image.new('RGB', (w, h), (230, 240, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([2, 2, w - 3, h - 3], outline=(47, 111, 237), width=3)
    d.text((10, h // 2 - 6), label, fill=(0, 0, 0))
    return im


def make(path, n_questions=40, edit=None):
    """edit: optional {number: replacement stem} to simulate a changed PDF."""
    font = _font()
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    y = 800

    def line(text, x, size=11):
        nonlocal y
        c.setFont(font, size)
        c.drawString(x, y, text)
        y -= 16

    for n in range(1, n_questions + 1):
        need = 150 if n % 7 == 0 else 100
        if y < need + 40:
            c.showPage()
            y = 800
        line(f'{n}. {(edit or {}).get(n, f"What is {n} + {n}? Choose the right result.")}', 12)
        if n % 7 == 0:
            c.drawImage(ImageReader(picture(160, 50, f'figure {n}')), 40, y - 54, width=160, height=50)
            y -= 62
        for val in [n + n + 1, n + n, n + n - 1, n * n + 100]:
            line(f'{"√" if val == n + n else "•"} {val}', 30)
        y -= 14
    c.save()


if __name__ == '__main__':
    make(sys.argv[1] if len(sys.argv) > 1 else 'sample_exam.pdf')
