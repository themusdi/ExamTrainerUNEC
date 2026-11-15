"""The main window: sidebar navigation, services, theme / font handling and the exam lifecycle."""
import json
import os
import tkinter as tk
from tkinter import messagebox, ttk
import tkinter.font as tkfont

import config
import exam_stats
import revision
from database import Database, DatabaseError
from exam_engine import ExamConfig, Session, retry_config
from library import Library, describe_report
from pdf_parser import PDFLoadError
from tasks import TaskRunner
from ui import theme, widgets
from ui.theme import P

NAV = [('home', '🏠', 'Home'), ('setup', '▶', 'New exam'), ('revision', '🔁', 'Revision'),
       ('library', '📚', 'PDF Library'), ('bookmarks', '⭐', 'Bookmarks'), ('history', '🕘', 'History'),
       ('stats', '📊', 'Statistics'), ('settings', '⚙', 'Settings')]


class Settings:
    """Typed access to the preferences stored in the database."""

    def __init__(self, db):
        self.db = db
        self.cache = dict(config.DEFAULT_SETTINGS)
        self.cache.update(db.all_settings())

    def get(self, key):
        return self.cache.get(key, config.DEFAULT_SETTINGS.get(key))

    def set(self, key, value):
        self.cache[key] = value
        self.db.set_setting(key, value)


class App(tk.Tk):
    def __init__(self, base_dir=None):
        super().__init__()
        self.title(config.APP_NAME)
        self.geometry('1180x800')
        self.minsize(760, 560)
        try:
            self.paths = config.Paths(base_dir)
            self.db = Database(self.paths.db, self.paths.backups)
        except (DatabaseError, OSError) as e:
            messagebox.showerror(config.APP_NAME, f'The data could not be opened:\n\n{e}')
            raise SystemExit(1)
        self.settings = Settings(self.db)
        self._legacy_file = None
        self._import_legacy_settings()
        self.library = Library(self.db, self.paths.cache)
        self.tasks = TaskRunner(self)
        self.db.auto_backup()

        theme.set_theme(self.settings.get('theme'))
        self.fonts = theme.Fonts(self, self.settings.get('font_size'))
        widgets.init(self.fonts)
        theme.apply_style(self, self.fonts)

        self.screen = None
        self.screen_name = None
        self.session = None
        self.help_win = None
        self.fullscreen = False
        self._busy_task = None
        self._toast_job = None
        self._nav_buttons = {}
        self._compact = None
        self._resize_job = None

        self._build_shell()
        self.bind_all('<MouseWheel>', self._wheel)
        self.bind_all('<Button-4>', self._wheel)
        self.bind_all('<Button-5>', self._wheel)
        self.bind('<Key>', self._key)
        self.bind('<Configure>', self._on_configure)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.navigate('home')
        if self._legacy_file and os.path.isfile(self._legacy_file):      # last PDF of version 1 -> library
            self.after(900, lambda: self.import_pdfs([self._legacy_file]))
        if not self.settings.get('seen_help'):
            self.settings.set('seen_help', True)
            self.after(500, self.show_help)

    # ------------------------------------------------------------------ settings migration from v1
    def _import_legacy_settings(self):
        """Version 1 kept its settings in ~/.exam_trainer.json - copy them over once (file is left alone)."""
        if self.settings.get('legacy_imported'):
            return
        try:
            old = json.loads(config.LEGACY_CONFIG.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            old = None
        if isinstance(old, dict):
            mapping = {'dark': ('theme', lambda v: 'dark' if v else 'light'), 'count': ('default_count', int),
                       'shuffle': ('default_shuffle', bool), 'range': ('last_range', str),
                       'seen_help': ('seen_help', bool)}
            for k, (new, conv) in mapping.items():
                if k in old:
                    try:
                        self.settings.set(new, conv(old[k]))
                    except (TypeError, ValueError):
                        pass
            if old.get('practice'):
                self.settings.set('default_mode', 'practice')
            self._legacy_file = old.get('file')
        self.settings.set('legacy_imported', True)

    # ------------------------------------------------------------------ shell
    def _build_shell(self):
        self.header = tk.Frame(self, bg=P['header'])
        self.header.pack(fill='x')
        self.status = tk.Frame(self, bg=P['card'], highlightthickness=1, highlightbackground=P['border'])
        self.status.pack(side='bottom', fill='x')
        self.lbl_status = tk.Label(self.status, text='', bg=P['card'], fg=P['muted'], anchor='w', padx=12, pady=4)
        self.lbl_status.pack(side='left', fill='x', expand=True)
        self.pbar = ttk.Progressbar(self.status, mode='determinate', length=180, maximum=1.0)
        self.btn_cancel = ttk.Button(self.status, text='Cancel', style='Small.TButton', command=self.cancel_busy)
        self.middle = tk.Frame(self, bg=P['bg'])
        self.middle.pack(fill='both', expand=True)
        self.sidebar = tk.Frame(self.middle, bg=P['side'], highlightthickness=1, highlightbackground=P['border'])
        self.sidebar.pack(side='left', fill='y')
        self.content = tk.Frame(self.middle, bg=P['bg'])
        self.content.pack(side='left', fill='both', expand=True, padx=(0, 0))
        self.build_header()
        self.build_sidebar()

    def build_header(self):
        for w in self.header.winfo_children():
            w.destroy()
        self.header.configure(bg=P['header'])
        tk.Label(self.header, text='📝  Exam Trainer', font=self.fonts.h2, fg='#ffffff',
                 bg=P['header']).pack(side='left', padx=18, pady=10)
        self._chip(self.header, 'Fullscreen   F11', self.toggle_fullscreen).pack(side='right', padx=(0, 14))
        self._chip(self.header, 'Dark / Light   F2', self.toggle_theme).pack(side='right', padx=8)
        self._chip(self.header, '?  How to use   F1', self.show_help).pack(side='right', padx=8)

    def _chip(self, parent, text, cmd):
        lb = tk.Label(parent, text=text, bg=P['chip'], fg='#ffffff', padx=12, pady=5, cursor='hand2')
        lb.bind('<Button-1>', lambda e: cmd())
        lb.bind('<Enter>', lambda e: lb.configure(bg=P['accent']))
        lb.bind('<Leave>', lambda e: lb.configure(bg=P['chip']))
        return lb

    def build_sidebar(self):
        for w in self.sidebar.winfo_children():
            w.destroy()
        self._nav_buttons = {}
        self.sidebar.configure(bg=P['side'], highlightbackground=P['border'])
        compact = self.winfo_width() < 940 and self.winfo_width() > 1
        self._compact = compact
        for key, icon, text in NAV:
            btn = tk.Label(self.sidebar, text=icon if compact else f'  {icon}   {text}', anchor='w',
                           bg=P['side'], fg=P['text'], padx=16 if not compact else 14, pady=11, cursor='hand2',
                           font=self.fonts.bold, width=2 if compact else 16)
            btn.pack(fill='x', pady=(8 if key == 'home' else 0, 0))
            btn.bind('<Button-1>', lambda e, k=key: self.navigate(k))
            btn.bind('<Enter>', lambda e, b=btn, k=key: b.configure(bg=P['hover'] if k != self.screen_name else P['side_sel']))
            btn.bind('<Leave>', lambda e, k=key: self._paint_nav())
            self._nav_buttons[key] = btn
        self._paint_nav()

    def _paint_nav(self):
        for k, b in self._nav_buttons.items():
            sel = (k == self.screen_name) or (k == 'setup' and self.screen_name == 'setup')
            b.configure(bg=P['side_sel'] if sel else P['side'], fg=P['accent'] if sel else P['text'])

    def set_chrome(self, visible):
        """Hide / show header + sidebar (used by the exam screen and fullscreen)."""
        for w, kw in ((self.header, dict(fill='x', before=self.middle)),
                      (self.sidebar, dict(side='left', fill='y', before=self.content))):
            w.pack_forget()
            if visible:
                w.pack(**kw)

    # ------------------------------------------------------------------ navigation
    def navigate(self, name, **kw):
        force = kw.pop('_force', False)
        if self.screen_name == 'exam' and name != 'exam' and not force:
            if not self.leave_exam():
                return
        self._close_screen()
        from ui.screens import SCREENS
        cls = SCREENS[name]
        self.screen_name = name
        self.set_chrome(name != 'exam')
        self.screen = cls(self.content, self, **kw)
        self.screen.pack(fill='both', expand=True)
        self._paint_nav()
        self.clear_toast()

    def _close_screen(self):
        if self.screen is not None:
            try:
                if hasattr(self.screen, 'on_close'):
                    self.screen.on_close()
            finally:
                self.screen.destroy()
            self.screen = None

    def refresh(self):
        """Rebuild the current screen (after a theme / font change)."""
        if self.screen is not None:
            self.screen.rebuild()

    def _on_configure(self, e):
        if e.widget is not self:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(200, self._after_resize)

    def _after_resize(self):
        self._resize_job = None
        compact = self.winfo_width() < 940
        if compact != self._compact and self.sidebar.winfo_ismapped():
            self.build_sidebar()
        if self.screen is not None and hasattr(self.screen, 'on_resize'):
            self.screen.on_resize(self.winfo_width())

    # ------------------------------------------------------------------ status bar / background work
    def toast(self, text, ms=6000, error=False):
        self.lbl_status.configure(text=text, fg=P['badb'] if error else P['muted'])
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(ms, self.clear_toast)

    def clear_toast(self):
        self._toast_job = None
        if self._busy_task is None:
            self.lbl_status.configure(text='', fg=P['muted'])

    def run_task(self, fn, on_done, text='Working…', on_error=None, cancellable=True):
        """Run fn(progress) in a thread; show a progress bar in the status bar; callbacks run on the Tk thread."""
        if self._busy_task is not None:
            self.toast('Please wait until the current task has finished.')
            return None
        self.lbl_status.configure(text=text, fg=P['text'])
        self.pbar.configure(value=0)
        self.pbar.pack(side='right', padx=8, pady=4)
        if cancellable:
            self.btn_cancel.pack(side='right', padx=4)
        self.config(cursor='watch')

        def finish():
            self._busy_task = None
            self.pbar.pack_forget()
            self.btn_cancel.pack_forget()
            self.config(cursor='')
            self.lbl_status.configure(text='', fg=P['muted'])

        def done(res):
            finish()
            on_done(res)

        def err(exc):
            finish()
            if on_error:
                on_error(exc)
            else:
                self.show_error(exc)

        def prog(frac, msg=''):
            self.pbar.configure(value=frac)
            if msg:
                self.lbl_status.configure(text=msg)

        self._busy_task = self.tasks.run(fn, done, err, prog)
        return self._busy_task

    def cancel_busy(self):
        if self._busy_task is not None:
            self._busy_task.cancel()
            self._busy_task = None
            self.pbar.pack_forget()
            self.btn_cancel.pack_forget()
            self.config(cursor='')
            self.toast('Cancelled.')

    def show_error(self, exc, title='Something went wrong'):
        if isinstance(exc, PDFLoadError):
            messagebox.showerror(title, str(exc))
        else:
            messagebox.showerror(title, f'{type(exc).__name__}: {exc}')

    # ------------------------------------------------------------------ importing PDFs
    def import_pdfs(self, paths, category_id=None, on_done=None):
        paths = [p for p in paths if p]
        if not paths:
            return

        def work(progress):
            out = []
            for i, p in enumerate(paths):
                def sub(f, t, i=i, p=p):
                    progress((i + f) / len(paths), f'{os.path.basename(p)}: {t}')
                try:
                    out.append((p, self.library.prepare(p, progress=sub), None))
                except PDFLoadError as e:
                    out.append((p, None, str(e)))
            return out

        def done(results):
            lines, errors, new_id = [], [], None
            for p, data, err in results:
                if err:
                    errors.append(f'{os.path.basename(p)}:\n{err}')
                    continue
                pid, status, msg = self.library.register(data, category_id=category_id)
                lines.append(msg)
                new_id = pid
            if errors:
                messagebox.showerror('Import', '\n\n'.join(errors + lines))
            elif len(lines) > 1:
                messagebox.showinfo('Import finished', '\n'.join(lines))
            elif lines:
                self.toast(lines[0])
            if on_done:
                on_done(new_id)

        self.run_task(work, done, 'Importing…')

    # ------------------------------------------------------------------ opening banks
    def open_bank(self, pdf_id, callback):
        """Get the Bank of a library PDF (cached when possible, otherwise read in the background)."""
        bank = self.library.cached_bank(pdf_id)
        if bank is not None:
            callback(bank)
            return
        row = self.db.get_pdf(pdf_id)
        if row is None:
            messagebox.showerror('PDF Library', 'This PDF is not in the library any more.')
            return

        def work(progress):
            return self.library.prepare(row['path'], known=row, progress=progress)

        def done(data):
            bank, report = self.library.complete_open(pdf_id, data)
            msg = describe_report(report)
            if msg:
                messagebox.showinfo(f'"{row["name"]}" has changed', msg)
            callback(bank)

        def error(exc):
            self.show_error(exc, f'Cannot open "{row["name"]}"')

        self.run_task(work, done, f'Opening "{row["name"]}"…', error)

    # ------------------------------------------------------------------ exam lifecycle
    def start_exam(self, bank, cfg):
        marked = [r['qnum'] for r in self.db.list_q(cfg.pdf_id, 'q.marked=1')]
        try:
            session = Session.create(bank, cfg, marked_numbers=marked)
        except ValueError as e:
            messagebox.showwarning('New exam', str(e))
            return
        self.session = session
        self.db.save_state(session.to_state()) if self.settings.get('autosave_sessions') else None
        if self.settings.get('fullscreen_exams') and not self.fullscreen:
            self.toggle_fullscreen(auto=True)
        self.navigate('exam', session=session, _force=True)

    def resume_interrupted(self):
        state = self.db.load_state()
        if not state:
            return
        pid = state.get('pdf_id')
        if not self.db.get_pdf(pid):
            self.db.clear_state()
            self.toast('The interrupted exam belonged to a PDF that is no longer in the library.', error=True)
            return

        def go(bank):
            try:
                s = Session.from_state(bank, state)
            except (ValueError, KeyError, IndexError) as e:
                self.db.clear_state()
                messagebox.showwarning('Resume exam', f'The interrupted exam could not be restored:\n\n{e}')
                return
            self.session = s
            self.navigate('exam', session=s, _force=True)
        self.open_bank(pid, go)

    def leave_exam(self):
        """Ask before leaving a running exam. True = go ahead."""
        s = self.session
        if s is None or s.finalized or self.screen_name != 'exam':
            return True
        ans = messagebox.askyesnocancel(
            'Leave the exam?', 'Yes = pause: you can resume this exam later from the Home page.\n'
                               'No = discard the exam.\nCancel = stay in the exam.')
        if ans is None:
            return False
        if ans:
            s.pause()
            self.db.save_state(s.to_state())
        else:
            self.db.clear_state()
            self.session = None
        self._leave_fullscreen_if_auto()
        return True

    def finish_exam(self, auto=False):
        s = self.session
        if s is None:
            return
        s.finalize()
        name = (self.db.get_pdf(s.config.pdf_id) or {'name': s.bank.name})['name']
        eid = self.db.save_exam(s.exam_record(name), s.answer_records())
        self.db.record_results(s.config.pdf_id, s.config.revision, s.results())
        self.db.clear_state()
        self._leave_fullscreen_if_auto()
        self.navigate('results', session=s, exam_id=eid, _force=True)

    def retry_session(self, session):
        cfg = retry_config(session)
        self.start_exam(session.bank, cfg)

    # ------------------------------------------------------------------ fullscreen / theme / fonts
    def toggle_fullscreen(self, auto=False):
        self.fullscreen = not self.fullscreen
        self._auto_fullscreen = bool(auto and self.fullscreen)
        try:
            self.attributes('-fullscreen', self.fullscreen)
        except tk.TclError:
            self.fullscreen = False
            return
        self.set_chrome(self.screen_name != 'exam')
        if self.screen is not None and hasattr(self.screen, 'on_fullscreen'):
            self.screen.on_fullscreen(self.fullscreen)

    def _leave_fullscreen_if_auto(self):
        if self.fullscreen and getattr(self, '_auto_fullscreen', False):
            self.toggle_fullscreen()

    def toggle_theme(self):
        self.apply_theme('light' if self.settings.get('theme') == 'dark' else 'dark')

    def apply_theme(self, name):
        self.settings.set('theme', name)
        theme.set_theme(name)
        theme.apply_style(self, self.fonts)
        self.middle.configure(bg=P['bg'])
        self.content.configure(bg=P['bg'])
        self.status.configure(bg=P['card'], highlightbackground=P['border'])
        self.lbl_status.configure(bg=P['card'], fg=P['muted'])
        self.build_header()
        self.build_sidebar()
        was_help = self.help_win is not None
        if was_help:
            self.help_win.destroy()
            self.help_win = None
        self.refresh()
        if was_help:
            self.show_help()

    def set_font_size(self, size):
        lo, hi = config.FONT_SIZE_RANGE
        size = max(lo, min(hi, int(size)))
        if size == self.fonts.size:
            return
        self.settings.set('font_size', size)
        self.fonts.apply(size)
        theme.apply_style(self, self.fonts)
        self.build_header()
        self.build_sidebar()
        self.refresh()

    # ------------------------------------------------------------------ help / keys / wheel
    def show_help(self):
        from ui.help_window import HelpWindow
        if self.help_win is not None:
            self.help_win.lift()
            return
        self.help_win = HelpWindow(self)

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

    def _key(self, e):
        ks = e.keysym
        if ks == 'F1':
            self.show_help()
        elif ks == 'F2':
            self.toggle_theme()
        elif ks == 'F11':
            self.toggle_fullscreen()
        elif ks == 'Escape' and self.fullscreen:
            self.toggle_fullscreen()
        elif (e.state & 0x4) and ks in ('plus', 'equal', 'KP_Add'):
            self.set_font_size(self.fonts.size + 1)
        elif (e.state & 0x4) and ks in ('minus', 'KP_Subtract'):
            self.set_font_size(self.fonts.size - 1)
        elif self.screen is not None and hasattr(self.screen, 'handle_key'):
            self.screen.handle_key(e)

    def on_close(self):
        if self.session is not None and not self.session.finalized and self.screen_name == 'exam':
            self.session.pause()
            self.db.save_state(self.session.to_state())          # an unfinished exam can be resumed
        self.tasks.active = 0
        self.library.close_all()
        self.db.close()
        self.destroy()
