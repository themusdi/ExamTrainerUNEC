"""A minimal fake of tkinter / ttk / tkinter.font / messagebox / filedialog / simpledialog.

It cannot show anything, but it lets the automated smoke tests execute every GUI code path (widget
creation, callbacks, state changes) on a machine without a display or without Tk installed.
Layout / drawing correctness still has to be checked by eye on a real screen.
"""
import sys
import time
import types

AFTER = []                  # pending after() callbacks: [id, fn, args]
_counter = [0]
CALLS = []                  # (function, title) of every messagebox call
ANSWERS = {}                # messagebox function name -> value to return
NEXT_PATHS = []             # values returned by filedialog functions
NEXT_STRINGS = []           # values returned by simpledialog.askstring


class TclError(Exception):
    pass


def _next_id():
    _counter[0] += 1
    return _counter[0]


class Misc:
    def __init__(self, master=None, cnf=None, **kw):
        self.master = master
        self._kw = dict(cnf or {})
        self._kw.update(kw)
        self._children = []
        self._binds = {}
        self._alive = True
        self._text = ''
        self._yview = (0.0, 1.0)
        if master is not None and hasattr(master, '_children'):
            master._children.append(self)
        self._init_extra()

    def _init_extra(self):
        pass

    # --- options
    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if kw:
            self._kw.update(kw)
            return None
        return dict(self._kw)
    config = configure

    def cget(self, key):
        return self._kw.get(key, '')

    def __getitem__(self, key):
        return self._kw.get(key, '#ffffff' if key in ('bg', 'background') else '')

    def __setitem__(self, key, value):
        self._kw[key] = value

    keys = lambda self: list(self._kw)

    # --- geometry / info
    def winfo_width(self):
        return int(self._kw.get('width', 1100)) if isinstance(self._kw.get('width'), int) and self._kw.get('width') > 5 else 1100

    def winfo_height(self):
        return 760

    winfo_reqwidth = winfo_reqheight = lambda self: 100
    winfo_rootx = winfo_rooty = lambda self: 0
    winfo_screenwidth = lambda self: 1920
    winfo_screenheight = lambda self: 1080
    winfo_pointerxy = lambda self: (0, 0)
    winfo_containing = lambda self, x, y: None
    winfo_ismapped = lambda self: True
    winfo_exists = lambda self: 1 if self._alive else 0
    winfo_children = lambda self: [c for c in self._children if c._alive]

    def winfo_id(self):
        return id(self)

    # --- events / timers
    def bind(self, seq=None, func=None, add=None):
        self._binds[seq] = func

    bind_all = bind_class = bind

    def after(self, ms, func=None, *args):
        i = _next_id()
        AFTER.append([i, func, args])
        return i

    after_idle = lambda self, func, *args: self.after(0, func, *args)

    def after_cancel(self, ident):
        AFTER[:] = [a for a in AFTER if a[0] != ident]

    def destroy(self):
        self._alive = False
        for c in list(self._children):
            c.destroy()
        if self.master is not None and hasattr(self.master, '_children') and self in self.master._children:
            self.master._children.remove(self)

    # --- clipboard
    clip = ''

    def clipboard_clear(self):
        Misc.clip = ''

    def clipboard_append(self, text):
        Misc.clip += text

    def clipboard_get(self):
        return Misc.clip

    # --- scrolling
    def yview(self, *a):
        return self._yview

    def yview_moveto(self, f):
        self._yview = (float(f), 1.0)

    # Tk methods that are safe to ignore. Anything else raises AttributeError like the real thing, so that
    # hasattr() / typos behave as in real Tk instead of being silently swallowed.
    _NOOP = {'focus_set', 'focus_force', 'focus', 'lift', 'lower', 'update', 'update_idletasks', 'transient',
             'title', 'geometry', 'minsize', 'maxsize', 'protocol', 'state', 'resizable', 'iconbitmap', 'withdraw',
             'deiconify', 'grab_set', 'grab_release', 'option_add', 'tk_popup', 'add_command', 'add_separator',
             'add_cascade', 'columnconfigure', 'rowconfigure', 'grid_columnconfigure', 'grid_rowconfigure',
             'pack_propagate', 'grid_propagate', 'tag_configure', 'tag_add', 'see', 'heading', 'column',
             'selection_clear', 'icursor', 'itemconfigure', 'itemconfig', 'coords', 'move', 'tag_bind',
             'yview_scroll', 'xview_scroll', 'xview', 'xview_moveto', 'bell', 'overrideredirect', 'start', 'stop',
             'step', 'select', 'deselect', 'add', 'forget', 'scan_mark', 'scan_dragto', 'identify_row',
             'event_generate', 'wm_attributes', 'iconphoto', 'tk', 'scale', 'delete_all', 'selection_range',
             'configure_scrollregion', 'tag_raise', 'insert_item', 'mark_set', 'edit_modified', 'focus_get',
             'theme_use', 'map', 'theme_names', 'unbind', 'grid_remove', 'grid_slaves', 'pack_slaves',
             'winfo_toplevel', 'wait_visibility', 'wait_window', 'mainloop', 'quit', 'activate'}

    def __getattr__(self, name):
        if name in Misc._NOOP or name.startswith('winfo_'):
            return lambda *a, **k: None
        raise AttributeError(name)


class Tk(Misc):
    def __init__(self, *a, **k):
        super().__init__(None)
        self._attrs = {}

    def mainloop(self, *a):
        pass

    def attributes(self, *a):
        if len(a) == 2:
            self._attrs[a[0]] = a[1]
        elif len(a) == 1:
            return self._attrs.get(a[0], False)

    def wait_window(self, w=None):
        pass


class Toplevel(Tk):
    def __init__(self, master=None, **kw):
        Misc.__init__(self, master, **kw)
        self._attrs = {}


class Widget(Misc):
    def _init_extra(self):
        self._items = {}
        self._order = []
        self._sel = []
        self._values = list(self._kw.get('values', []) or [])
        self._cur = -1
        self._var = self._kw.get('textvariable')

    # layout
    pack = grid = place = lambda self, *a, **k: None
    pack_forget = grid_forget = place_forget = lambda self, *a, **k: None

    # canvas
    def create_window(self, *a, **k):
        return _next_id()

    create_line = create_oval = create_arc = create_text = create_rectangle = create_polygon = create_window
    bbox = lambda self, *a: (0, 0, 100, 100)

    # entry / text
    def get(self, *a):
        if self._var is not None:
            return self._var.get()
        if a and a[0] == '1.0':
            return self._text + '\n'
        return self._text

    def set(self, v):
        if self._var is not None:
            self._var.set(v)
        self._text = v

    def insert(self, *a, **k):
        if len(a) >= 2 and isinstance(a[1], str) and a[0] in ('1.0', 'end', 0):
            self._text += a[1]
        elif len(a) >= 3 and self._items is not None and not isinstance(a[1], str):
            pass

    # treeview-ish
    def delete(self, *items):
        if items and items[0] == 'all':
            return
        for it in items:
            self._items.pop(it, None)
            if it in self._order:
                self._order.remove(it)

    def get_children(self, *a):
        return tuple(self._order)

    def selection(self):
        return tuple(self._sel)

    def selection_set(self, *items):
        self._sel = list(items[0] if items and isinstance(items[0], (list, tuple)) else items)

    def item(self, iid, option=None, **kw):
        row = self._items.get(iid, {})
        if option == 'values':
            return row.get('values', ())
        return row

    # combobox
    def current(self, i=None):
        if i is None:
            return self._cur
        self._cur = i
        if self._var is not None and 0 <= i < len(self._values):
            self._var.set(self._values[i])
        return None

    def invoke(self):
        cmd = self._kw.get('command')
        if cmd and self._kw.get('state') != 'disabled':
            cmd()


class Treeview(Widget):
    def insert(self, parent, index, iid=None, values=(), text='', **kw):
        iid = iid or f'I{_next_id()}'
        self._items[iid] = dict(values=tuple(values), text=text)
        self._order.append(iid)
        return iid


class Combobox(Widget):
    def _init_extra(self):
        Widget._init_extra(self)
        self._values = list(self._kw.get('values', []) or [])

    def __setitem__(self, k, v):
        if k == 'values':
            self._values = list(v)
        self._kw[k] = v

    def get(self, *a):
        if self._var is not None and self._var.get():
            return self._var.get()
        return self._values[self._cur] if 0 <= self._cur < len(self._values) else ''


class Variable:
    def __init__(self, master=None, value=None, name=None):
        self._v = value
        self._traces = []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for t in self._traces:
            t('v', '', 'write')

    def trace_add(self, mode, cb):
        self._traces.append(cb)
        return 't'


class StringVar(Variable):
    def __init__(self, master=None, value='', name=None):
        super().__init__(master, str(value))

    def set(self, v):
        super().set(str(v))


class IntVar(Variable):
    def __init__(self, master=None, value=0, name=None):
        super().__init__(master, int(value))

    def get(self):
        return int(self._v)


class DoubleVar(Variable):
    def get(self):
        return float(self._v)


class BooleanVar(Variable):
    def __init__(self, master=None, value=False, name=None):
        super().__init__(master, bool(value))

    def get(self):
        return bool(self._v)


# ---------------------------------------------------------------- font
class Font:
    def __init__(self, root=None, family='Arial', size=12, weight='normal', **kw):
        self.o = dict(family=family, size=size, weight=weight)

    def configure(self, **kw):
        self.o.update(kw)

    config = configure

    def cget(self, k):
        return self.o.get(k)

    def actual(self, k=None):
        return 'Arial' if k == 'family' else dict(self.o)

    def measure(self, text):
        return 7 * len(text)

    def metrics(self, *a):
        return 16

    def copy(self):
        return Font(**self.o)


_named = {}


def nametofont(name, root=None):
    return _named.setdefault(name, Font())


# ---------------------------------------------------------------- dialogs
def _mb(name, default):
    def f(title=None, message=None, **kw):
        CALLS.append((name, title, message))
        return ANSWERS.get(name, default)
    f.__name__ = name
    return f


messagebox = types.ModuleType('tkinter.messagebox')
for _n, _d in (('showinfo', 'ok'), ('showwarning', 'ok'), ('showerror', 'ok'), ('askyesno', True),
               ('askokcancel', True), ('askyesnocancel', True), ('askretrycancel', True)):
    setattr(messagebox, _n, _mb(_n, _d))


def _fd(name):
    def f(*a, **k):
        CALLS.append((name, k.get('title'), None))
        return NEXT_PATHS.pop(0) if NEXT_PATHS else ('' if name != 'askopenfilenames' else ())
    return f


filedialog = types.ModuleType('tkinter.filedialog')
for _n in ('askopenfilename', 'askopenfilenames', 'asksaveasfilename', 'askdirectory'):
    setattr(filedialog, _n, _fd(_n))

simpledialog = types.ModuleType('tkinter.simpledialog')
simpledialog.askstring = lambda *a, **k: NEXT_STRINGS.pop(0) if NEXT_STRINGS else None


# ---------------------------------------------------------------- modules
def install():
    tk = types.ModuleType('tkinter')
    ttk = types.ModuleType('tkinter.ttk')
    tkfont = types.ModuleType('tkinter.font')
    tk.TclError = TclError
    for n, c in (('Tk', Tk), ('Toplevel', Toplevel)):
        setattr(tk, n, c)
    for n in ('Frame', 'Label', 'Button', 'Canvas', 'Entry', 'Text', 'Menu', 'Scrollbar', 'Listbox', 'LabelFrame'):
        setattr(tk, n, type(n, (Widget,), {}))
    tk.StringVar, tk.IntVar, tk.DoubleVar, tk.BooleanVar = StringVar, IntVar, DoubleVar, BooleanVar
    for n in ('END', 'LEFT', 'RIGHT', 'TOP', 'BOTTOM', 'BOTH', 'X', 'Y', 'W', 'E', 'N', 'S', 'NW', 'WORD'):
        setattr(tk, n, n.lower())
    for n in ('Frame', 'Label', 'Button', 'Entry', 'Spinbox', 'Checkbutton', 'Radiobutton', 'Progressbar',
              'Scrollbar', 'Notebook', 'Scale', 'Separator'):
        setattr(ttk, n, type(n, (Widget,), {}))
    ttk.Combobox, ttk.Treeview = Combobox, Treeview

    class Style(Misc):
        def __init__(self, master=None):
            Misc.__init__(self, None)

        def lookup(self, *a):
            return ''
    ttk.Style = Style
    tkfont.Font, tkfont.nametofont = Font, nametofont
    tk.messagebox, tk.filedialog, tk.simpledialog, tk.ttk, tk.font = messagebox, filedialog, simpledialog, ttk, tkfont
    sys.modules.update({'tkinter': tk, 'tkinter.ttk': ttk, 'tkinter.font': tkfont, 'tkinter.messagebox': messagebox,
                        'tkinter.filedialog': filedialog, 'tkinter.simpledialog': simpledialog})
    # PIL.ImageTk needs a real Tk
    imagetk = types.ModuleType('PIL.ImageTk')
    imagetk.PhotoImage = lambda im=None, *a, **k: object()
    sys.modules['PIL.ImageTk'] = imagetk
    import PIL
    PIL.ImageTk = imagetk
    return tk


def pump(until=None, timeout=15.0, rounds=None):
    """Run pending after() callbacks (like the Tk main loop) until `until()` is true or time runs out."""
    end = time.time() + timeout
    n = 0
    while time.time() < end:
        batch = AFTER[:]
        AFTER.clear()
        for ident, fn, args in batch:
            if fn is not None:
                fn(*args)
        n += 1
        if until is not None and until():
            return True
        if rounds is not None and n >= rounds:
            return True
        time.sleep(0.02)
    return until is None


def reset():
    AFTER.clear()
    CALLS.clear()
    ANSWERS.clear()
    NEXT_PATHS.clear()
    NEXT_STRINGS.clear()
    Misc.clip = ''


class Event:
    def __init__(self, keysym='', char='', state=0):
        self.keysym, self.char, self.state = keysym, char, state
        self.widget = None
        self.x_root = self.y_root = 0
        self.delta = 0
        self.num = 0
