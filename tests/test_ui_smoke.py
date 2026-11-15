"""GUI smoke tests: drives the real screens through a fake Tk (no display needed).
Run:  python -m unittest tests.test_ui_smoke -v     (or python -m unittest discover -s tests)"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_tk
fake_tk.install()

from make_sample_pdf import make                      # noqa: E402
from ui import widgets                                # noqa: E402
from ui.app import App                                # noqa: E402
from ui.screens import SCREENS                        # noqa: E402

E = fake_tk.Event


def key(app, ks, ch='', state=0):
    app._key(E(ks, ch, state))


class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_tk.reset()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdf = cls.tmp / 'exam.pdf'
        make(cls.pdf, 40)
        cls.app = App(base_dir=cls.tmp / 'data')
        widgets.edit_note = lambda master, title, text='': 'a note'

    @classmethod
    def tearDownClass(cls):
        cls.app.on_close()

    # ---------------------------------------------------------------- helpers
    def pump(self, until=None, timeout=20):
        self.assertTrue(fake_tk.pump(until, timeout), 'timed out waiting for background task')

    def start(self, mode, count='6', **extra):
        app = self.app
        app.navigate('setup', **extra.pop('nav', {}))
        self.pump(lambda: app.screen.bank is not None)
        sc = app.screen
        sc.select_mode(mode)
        sc.v_count.set(count)
        sc.v_minutes.set(extra.get('minutes', '30'))
        sc.v_lives.set(extra.get('lives', '1'))
        sc.v_shuffle.set(extra.get('shuffle', False))
        if 'range' in extra:
            sc.v_range.set(extra['range'])
        sc.start()
        self.assertEqual(app.screen_name, 'exam')
        return app.screen

    def answer_all(self, ex, correct=True):
        s = ex.s
        for _ in range(len(s.ids)):
            i = ex.cur
            want = 1 if correct else 0
            ex.pick(s.order[i].index(want) and want or want)        # original option index
            if i < len(s.ids) - 1:
                ex.go(1)

    # ---------------------------------------------------------------- tests
    def test_01_all_static_screens_open(self):
        for name in ('home', 'setup', 'revision', 'bookmarks', 'history', 'stats', 'settings', 'library'):
            self.app.navigate(name)
            self.assertEqual(self.app.screen_name, name)

    def test_02_import_and_library(self):
        app = self.app
        app.import_pdfs([str(self.pdf)])
        self.pump(lambda: app.db.list_pdfs())
        pdfs = app.db.list_pdfs()
        self.assertEqual((len(pdfs), pdfs[0]['q_count']), (1, 40))
        # duplicate import -> no second record
        app.import_pdfs([str(self.pdf)])
        self.pump(lambda: app._busy_task is None)
        self.assertEqual(len(app.db.list_pdfs()), 1)
        app.navigate('library')
        lib = app.screen
        fake_tk.NEXT_STRINGS.append('My Exam')
        lib.rename(pdfs[0])
        self.assertEqual(app.db.get_pdf(pdfs[0]['id'])['name'], 'My Exam')
        fake_tk.NEXT_STRINGS.append('Maths')
        lib.new_cat_for(app.db.get_pdf(pdfs[0]['id']))
        self.assertEqual(app.db.get_pdf(pdfs[0]['id'])['category'], 'Maths')
        app.navigate('library')
        app.screen.v_cat.set('Maths')
        app.screen.fill()
        app.screen.v_cat.set('Uncategorised')
        app.screen.fill()
        app.screen.v_cat.set('All categories')
        # re-read + export json
        app.screen.reread(app.db.get_pdf(pdfs[0]['id']))
        self.pump(lambda: app._busy_task is None)
        fake_tk.NEXT_PATHS.append(str(self.tmp / 'bank.json'))
        app.screen.export_json(app.db.get_pdf(pdfs[0]['id']))
        self.pump(lambda: app._busy_task is None, 5)
        self.assertTrue((self.tmp / 'bank.json').exists())
        CategoryDlg = __import__('ui.library_screen', fromlist=['x']).CategoryDialog
        d = CategoryDlg(app, app.db)
        d.tree.selection_set(d.tree.get_children()[0])
        fake_tk.NEXT_STRINGS.append('Math2')
        d.rename()
        d.delete()

    def test_03_every_mode(self):
        app = self.app
        before = len(app.db.list_exams())
        # standard
        ex = self.start('standard', '6', shuffle=True)
        self.answer_all(ex)
        ex.try_finish()
        self.assertEqual(app.screen_name, 'results')
        # timed (time limit ends the exam by itself)
        ex = self.start('timed', '5', minutes='0.001')
        import time
        time.sleep(0.2)
        self.pump(lambda: app.screen_name == 'results', 5)
        # practice: answers lock
        ex = self.start('practice', '4')
        s = ex.s
        ex.pick(0)
        self.assertEqual(s.ans[0], 0)
        ex.pick(1)
        self.assertEqual(s.ans[0], 0)
        ex.try_finish()
        # sequential
        ex = self.start('sequential', '5')
        self.assertEqual(ex.s.ids, [1, 2, 3, 4, 5])
        self.answer_all(ex)
        ex.try_finish()
        # endless
        ex = self.start('endless', range='1-4')
        for _ in range(10):
            ex.pick(1)
            ex.go(1)
            if app.screen_name == 'results':
                break
        self.assertEqual(app.screen_name, 'results')
        self.assertEqual(sorted(app.session.ids), [1, 2, 3, 4])
        # survival
        ex = self.start('survival', '10', lives='1')
        ex.pick(1)
        ex.go(1)
        ex.pick(0)                                   # wrong -> game over
        self.assertTrue(ex.s.game_over)
        ex.render()
        ex.go(1)
        self.assertEqual(app.screen_name, 'results')
        self.assertEqual(app.session.summary()['n'], 2)
        self.assertEqual(len(app.db.list_exams()) - before, 6)

    def test_04_keys_notes_bookmarks(self):
        app = self.app
        ex = self.start('sequential', '8')
        key(app, 'a', 'a')
        self.assertEqual(ex.s.ans[0], ex.s.order[0][0])
        key(app, '2', '2')
        key(app, 'm', 'm')
        self.assertIn(0, ex.s.flags)
        key(app, 's', 's'); key(app, 'x', 'x'); key(app, 'n', 'n')
        q = app.db.get_q(ex.s.config.pdf_id, ex.s.bank.fp(1))
        self.assertEqual((q['favorite'], q['difficult'], q['note']), (1, 1, 'a note'))
        key(app, 'Right'); key(app, 'Return'); key(app, 'Left'); key(app, 'End'); key(app, 'Home')
        key(app, 'o', 'o')
        self.assertIsNotNone(ex.ov_win)
        ex.ov_win.destroy(); ex.ov_win = None
        ex.show_overview()
        key(app, 'Return', '\r', 0x4)               # Ctrl+Enter = finish
        self.assertEqual(app.screen_name, 'results')
        # the marked question is remembered and pre-marked in the next exam
        ex = self.start('sequential', '3')
        self.assertIn(0, ex.s.flags)
        app.navigate('home')                         # leave -> pause (askyesnocancel = True)
        self.assertIsNotNone(app.db.load_state())

    def test_05_resume(self):
        app = self.app
        app.navigate('home')
        self.assertIsNotNone(app.db.load_state())
        app.resume_interrupted()
        self.pump(lambda: app.screen_name == 'exam', 5)
        ex = app.screen
        ex.pick(1)
        key(app, 'Return', '\r', 0x4)
        self.assertEqual(app.screen_name, 'results')
        self.assertIsNone(app.db.load_state())
        # discard path
        self.start('standard', '3')
        fake_tk.ANSWERS['askyesnocancel'] = False
        app.navigate('home')
        fake_tk.ANSWERS.clear()
        self.assertIsNone(app.db.load_state())

    def test_06_results_actions(self):
        app = self.app
        ex = self.start('sequential', '10')
        for i in range(10):
            ex.pick(1 if i % 2 else 0)
            ex.go(1) if i < 9 else None
        ex.try_finish()
        res = app.screen
        for flt in ('all', 'wrong', 'skipped', 'marked'):
            res.v_filter.set(flt)
            res.render_list()
        res.copy_wrong()
        self.assertTrue(fake_tk.Misc.clip)
        res.copy_summary()
        self.assertIn('Score:', fake_tk.Misc.clip)
        fake_tk.NEXT_PATHS.append(str(self.tmp / 'report.pdf'))
        res.export_pdf()
        self.pump(lambda: (self.tmp / 'report.pdf').exists(), 20)
        self.pump(lambda: app._busy_task is None, 20)
        self.assertTrue((self.tmp / 'report.pdf').read_bytes().startswith(b'%PDF'))
        res._tools(fake_tk.Widget(None), 1)
        res._note(2)
        res.on_resize(900)
        app.retry_session(res.s)
        self.assertEqual(app.screen_name, 'exam')
        self.assertTrue(app.session.config.revision)

    def test_07_revision_flow(self):
        app = self.app
        app.session = None
        app.navigate('home') if app.screen_name != 'exam' else None
        app.db.clear_state()
        app.navigate('revision', _force=True) if False else None
        if app.screen_name == 'exam':
            app.leave_exam = lambda: True
        app.navigate('revision')
        rv = app.screen
        self.pump(lambda: rv.bank is not None)
        self.assertGreater(len(rv.rows), 0)
        pid = rv.selected_pdf()['id']
        n_before = len(app.db.list_q(pid, 'q.in_mistakes=1'))
        rv.tree.selection_set(*[f'{r["pdf_id"]}:{r["qnum"]}' for r in rv.rows[:2]])
        rv.view()
        rv.start()
        self.assertEqual(app.screen_name, 'setup')
        self.pump(lambda: app.screen.bank is not None)
        sc = app.screen
        sc.select_mode('standard')
        sc.v_count.set('2')
        sc.start()
        ex = app.screen
        self.assertTrue(ex.s.config.revision)
        for i in range(len(ex.s.ids)):
            ex.pick(1)                                # the correct option of the sample PDF
            if i < len(ex.s.ids) - 1:
                ex.go(1)
        ex.try_finish()
        self.assertLess(len(app.db.list_q(pid, 'q.in_mistakes=1')), n_before)
        app.navigate('revision')
        app.screen.clear_selected()
        # bookmarks page
        app.navigate('bookmarks')
        bk = app.screen
        self.pump(lambda: bk.bank is not None)
        self.assertGreater(len(bk.rows), 0)
        bk.tree.selection_set(f'{bk.rows[0]["pdf_id"]}:{bk.rows[0]["qnum"]}')
        bk.view()
        bk.start()
        self.assertEqual(app.screen_name, 'setup')
        app.navigate('bookmarks')
        app.screen.unbookmark()

    def test_08_history_and_stats(self):
        app = self.app
        app.navigate('history')
        h = app.screen
        self.assertGreater(len(h.exams), 3)
        h.tree.selection_set(str(h.exams[0]['id']))
        h.open()
        self.pump(lambda: app.screen_name == 'results', 10)
        self.assertTrue(app.screen.review)
        app.navigate('history')
        h = app.screen
        fake_tk.NEXT_PATHS.append(str(self.tmp / 'h.csv'))
        h.export_csv()
        self.assertTrue((self.tmp / 'h.csv').exists())
        h.cb.current(1)
        h.fill()
        h.tree.selection_set(str(h.exams[0]['id']))
        n = len(app.db.list_exams())
        h.delete()
        self.assertEqual(len(app.db.list_exams()), n - 1)
        app.navigate('stats')
        st = app.screen
        st.v_days.set(7)
        st.draw_daily()
        fake_tk.NEXT_PATHS.append(str(self.tmp / 's.csv'))
        st.export_csv()
        self.assertTrue((self.tmp / 's.csv').exists())

    def test_09_settings_theme_fonts_fullscreen_help(self):
        app = self.app
        app.navigate('settings')
        st = app.screen
        for name in ('dark', 'light'):
            app.apply_theme(name)
            self.assertEqual(app.settings.get('theme'), name)
            for scr in ('home', 'stats', 'library', 'history', 'setup'):
                app.navigate(scr)
        app.toggle_theme(); app.toggle_theme()
        size = app.fonts.size
        app.set_font_size(size + 2)
        self.assertEqual(app.fonts.size, size + 2)
        app.set_font_size(2)
        self.assertEqual(app.fonts.size, 9)
        key(app, 'plus', '+', 0x4); key(app, 'minus', '-', 0x4)
        app.set_font_size(12)
        app.show_help()
        self.assertIsNotNone(app.help_win)
        app.apply_theme('dark')                      # help window rebuilt
        app.help_win.close()
        key(app, 'F1'); key(app, 'F2'); key(app, 'F11'); key(app, 'Escape')
        self.assertFalse(app.fullscreen)
        app.apply_theme('light')
        app.navigate('settings')
        st = app.screen
        st.backup()
        st.clear_history()
        self.assertEqual(len(app.db.list_exams()), 0)
        self.assertTrue(list(app.paths.backups.glob('*before-clear-history*')))
        st.v_count.set('abc'); st._count()
        st.cb_mode.current(2)
        st.cb_mode._binds['<<ComboboxSelected>>'](None)
        self.assertEqual(app.settings.get('default_mode'), 'practice')

    def test_10_fullscreen_exam_and_resize(self):
        app = self.app
        app.settings.set('fullscreen_exams', True)
        ex = self.start('standard', '3')
        self.assertTrue(app.fullscreen)
        ex.on_resize(500)
        app.apply_theme('dark')
        app.apply_theme('light')
        ex.try_finish()
        self.assertFalse(app.fullscreen)              # left again after the exam
        app.settings.set('fullscreen_exams', False)
        app._after_resize()
        app.screen.on_resize(800)


if __name__ == '__main__':
    unittest.main()
