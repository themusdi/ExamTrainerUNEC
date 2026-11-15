"""Colours, fonts and ttk styling (light / dark, adjustable font size)."""
import tkinter.font as tkfont
from tkinter import ttk

LIGHT = dict(bg='#f3f4f7', card='#ffffff', border='#d9dde5', text='#1d2330', muted='#667085',
             accent='#2f6fed', accent_dk='#2459c4', sel='#dbe8ff', hover='#f0f5ff',
             ok='#d5f3df', okb='#1a8f4c', bad='#fbd9d9', badb='#d33b3b', warn='#d99a1a',
             ans='#cfe0ff', flag='#ffe08a', badge='#98a2b3', header='#1b2540', chip='#2c3a63',
             side='#ffffff', side_sel='#e7efff')
DARK = dict(bg='#12151c', card='#1c212b', border='#323a48', text='#e6e9ef', muted='#98a2b3',
            accent='#5b8cff', accent_dk='#7aa0ff', sel='#22335c', hover='#252c3a',
            ok='#173a28', okb='#34c274', bad='#43201f', badb='#f0646b', warn='#e0a93a',
            ans='#2a3d6b', flag='#6b5412', badge='#4a5365', header='#0b0e14', chip='#1d2433',
            side='#171b24', side_sel='#22335c')
P = dict(LIGHT)                       # the active palette; updated in place by set_theme()


def set_theme(name):
    P.clear()
    P.update(DARK if name == 'dark' else LIGHT)


class Fonts:
    """Named fonts derived from one base size, so the whole UI scales together."""

    def __init__(self, root, size=12):
        self.root = root
        self.default = tkfont.nametofont('TkDefaultFont')
        family = self.default.actual('family')
        mk = lambda w='normal': tkfont.Font(root=root, family=family, size=size, weight=w)
        self.bold, self.h2, self.title, self.score, self.small = mk('bold'), mk('bold'), mk('bold'), mk('bold'), mk()
        self.key = tkfont.Font(root=root, family=tkfont.nametofont('TkFixedFont').actual('family'), size=size, weight='bold')
        self.apply(size)

    def apply(self, size):
        self.size = size
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont'):
            try:
                tkfont.nametofont(name).configure(size=size)
            except Exception:
                pass
        self.bold.configure(size=size)
        self.h2.configure(size=size + 2)
        self.title.configure(size=size + 10)
        self.score.configure(size=size + 14)
        self.small.configure(size=max(8, size - 3))
        self.key.configure(size=max(8, size - 1))


def apply_style(root, fonts):
    root.configure(bg=P['bg'])
    st = ttk.Style(root)
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
                     lightcolor=col, darkcolor=col, font=fonts.bold)
        st.map(f'{name}.TButton', background=[('active', hov), ('disabled', P['border'])],
               foreground=[('disabled', P['muted'])], bordercolor=[('disabled', P['border'])],
               lightcolor=[('disabled', P['border'])], darkcolor=[('disabled', P['border'])])
    st.configure('Small.TButton', padding=(8, 3))
    st.configure('TEntry', padding=7, fieldbackground=P['card'], foreground=P['text'],
                 bordercolor=P['border'], lightcolor=P['border'], darkcolor=P['border'])
    st.map('TEntry', fieldbackground=[('readonly', P['card'])], bordercolor=[('focus', P['accent'])],
           lightcolor=[('focus', P['accent'])], darkcolor=[('focus', P['accent'])])
    st.configure('TSpinbox', padding=6, fieldbackground=P['card'], foreground=P['text'], arrowcolor=P['text'],
                 bordercolor=P['border'], background=P['card'], lightcolor=P['border'], darkcolor=P['border'])
    st.configure('TCombobox', padding=6, fieldbackground=P['card'], foreground=P['text'], arrowcolor=P['text'],
                 background=P['card'], bordercolor=P['border'], lightcolor=P['border'], darkcolor=P['border'],
                 selectbackground=P['card'], selectforeground=P['text'])
    st.map('TCombobox', fieldbackground=[('readonly', P['card'])], selectbackground=[('readonly', P['card'])],
           selectforeground=[('readonly', P['text'])])
    root.option_add('*TCombobox*Listbox.background', P['card'])
    root.option_add('*TCombobox*Listbox.foreground', P['text'])
    root.option_add('*TCombobox*Listbox.selectBackground', P['accent'])
    root.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')
    st.configure('Card.TCheckbutton', background=P['card'], foreground=P['text'])
    st.map('Card.TCheckbutton', background=[('active', P['card'])],
           indicatorcolor=[('selected', P['accent']), ('!selected', P['card'])])
    st.configure('Card.TRadiobutton', background=P['card'], foreground=P['text'])
    st.map('Card.TRadiobutton', background=[('active', P['card'])],
           indicatorcolor=[('selected', P['accent']), ('!selected', P['card'])])
    st.configure('TRadiobutton', background=P['bg'], foreground=P['text'])
    st.map('TRadiobutton', background=[('active', P['bg'])],
           indicatorcolor=[('selected', P['accent']), ('!selected', P['card'])])
    st.configure('Horizontal.TProgressbar', troughcolor=P['border'], background=P['accent'],
                 bordercolor=P['border'], lightcolor=P['accent'], darkcolor=P['accent'], thickness=10)
    st.configure('Vertical.TScrollbar', background=P['border'], troughcolor=P['bg'], bordercolor=P['bg'],
                 arrowcolor=P['muted'], lightcolor=P['border'], darkcolor=P['border'])
    st.configure('TNotebook', background=P['bg'], bordercolor=P['border'])
    st.configure('TNotebook.Tab', padding=(18, 9), background=P['bg'], foreground=P['muted'])
    st.map('TNotebook.Tab', background=[('selected', P['card'])], foreground=[('selected', P['text'])])
    st.configure('Treeview', background=P['card'], fieldbackground=P['card'], foreground=P['text'],
                 bordercolor=P['border'], lightcolor=P['card'], darkcolor=P['card'],
                 rowheight=int(fonts.size * 2.3))
    st.map('Treeview', background=[('selected', P['accent'])], foreground=[('selected', '#ffffff')])
    st.configure('Treeview.Heading', background=P['bg'], foreground=P['muted'], relief='flat',
                 font=fonts.bold, padding=(8, 6))
    st.map('Treeview.Heading', background=[('active', P['hover'])])
    st.configure('TScale', background=P['card'], troughcolor=P['border'])
