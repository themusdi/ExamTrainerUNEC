"""Automated tests for everything that has no GUI. Run:  python -m unittest discover -s tests -v"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exam_stats
import export
import revision
from database import Database
from exam_engine import ExamConfig, Session, build_pool, retry_config
from library import Library, describe_report
from make_sample_pdf import make
from pdf_parser import PDFLoadError, parse_ranges


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = Database(self.tmp / 't.db', self.tmp / 'backups')
        self.lib = Library(self.db, self.tmp)
        self.pdf = self.tmp / 'exam.pdf'
        make(self.pdf, 40)

    def tearDown(self):
        self.lib.close_all()
        self.db.close()

    def open_bank(self, path=None):
        path = path or self.pdf
        data = self.lib.prepare(str(path))
        pid, status, _ = self.lib.register(data)
        bank, report = self.lib.complete_open(pid, data)
        return pid, bank, report, status


class TestParsing(Base):
    def test_extraction_and_markers(self):
        pid, bank, _, status = self.open_bank()
        self.assertEqual(status, 'new')
        self.assertEqual(len(bank.numbers), 40)
        for n in bank.numbers:
            q = bank.q[n]
            self.assertEqual(len(q['opts']), 4)
            self.assertEqual(sum(o['correct'] for o in q['opts']), 1)
            self.assertTrue(q['opts'][1]['correct'])           # sample PDF: 2nd variant is right

    def test_images_rendered(self):
        _, bank, _, _ = self.open_bank()
        stem, opts = bank.load(7)
        self.assertEqual([k for k, _ in stem], ['t', 'i'])
        self.assertGreater(stem[1][1].width, 50)

    def test_missing_file_gives_placeholder_not_crash(self):
        _, bank, _, _ = self.open_bank()
        bank.close()
        bank.path = str(self.tmp / 'gone.pdf')
        stem, _ = bank.load(14)
        self.assertTrue(any(k == 't' and 'not available' in v for k, v in stem))

    def test_parse_cache(self):
        self.lib.prepare(str(self.pdf))
        self.assertTrue(list(self.tmp.glob('*.json.gz')))

    def test_bad_files(self):
        bad = self.tmp / 'x.pdf'
        bad.write_text('hello')
        with self.assertRaises(PDFLoadError):
            self.lib.prepare(str(bad))
        with self.assertRaises(PDFLoadError):
            self.lib.prepare(str(self.tmp / 'nothere.pdf'))
        broken = self.tmp / 'broken.pdf'
        broken.write_bytes(b'%PDF-1.4\n garbage garbage')
        with self.assertRaises(PDFLoadError):
            self.lib.prepare(str(broken))

    def test_ranges(self):
        self.assertEqual(parse_ranges('1,5-7,99', set(range(1, 11)))[0], [1, 5, 6, 7])
        self.assertEqual(parse_ranges('50-60', set(range(1, 11)))[1], ['50-60'])


class TestEngine(Base):
    def cfg(self, bank, **kw):
        base = dict(pdf_id=bank.pdf_id, pool=list(bank.numbers), count=10)
        base.update(kw)
        return ExamConfig(**base)

    def test_modes(self):
        pid, bank, _, _ = self.open_bank()
        s = Session.create(bank, self.cfg(bank, mode='sequential', count=5))
        self.assertEqual(s.ids, [1, 2, 3, 4, 5])
        s = Session.create(bank, self.cfg(bank, mode='standard', count=12))
        self.assertEqual(len(set(s.ids)), 12)
        s = Session.create(bank, self.cfg(bank, mode='standard', shuffle_options=True, count=40))
        self.assertTrue(any(o != [0, 1, 2, 3] for o in s.order))
        # endless: no repeats until exhausted
        s = Session.create(bank, self.cfg(bank, mode='endless', pool=list(range(1, 6))))
        while s.extend():
            pass
        self.assertEqual(sorted(s.ids), [1, 2, 3, 4, 5])
        self.assertTrue(s.pool_exhausted)

    def test_scoring_and_toggle(self):
        _, bank, _, _ = self.open_bank()
        s = Session.create(bank, self.cfg(bank, mode='sequential', count=4))
        s.answer(0, 1); s.answer(1, 0); s.answer(2, 1); s.answer(2, 1)        # last click clears
        self.assertEqual((s.score(), s.wrong(), s.unanswered()), (1, 1, 2))
        self.assertEqual(s.wrong_ids(), [2, 3, 4])

    def test_practice_locks(self):
        _, bank, _, _ = self.open_bank()
        s = Session.create(bank, self.cfg(bank, mode='practice', count=3))
        self.assertTrue(s.answer(0, 0))
        self.assertFalse(s.answer(0, 1))

    def test_survival(self):
        _, bank, _, _ = self.open_bank()
        s = Session.create(bank, self.cfg(bank, mode='sequential', count=5))
        s.mode = 'survival'; s.config.mode = 'survival'
        s.answer(0, 1); s.visit(0)
        self.assertFalse(s.game_over)
        s.answer(1, 0); s.visit(1)
        self.assertTrue(s.game_over)
        s.finalize()
        self.assertEqual(len(s.ids), 2)
        self.assertEqual(s.summary()['wrong'], 1)

    def test_timed(self):
        _, bank, _, _ = self.open_bank()
        s = Session.create(bank, self.cfg(bank, mode='timed', time_limit_min=0.001))
        import time; time.sleep(0.1)
        self.assertTrue(s.time_up())
        self.assertEqual(s.time_left(), 0.0)

    def test_state_roundtrip(self):
        _, bank, _, _ = self.open_bank()
        s = Session.create(bank, self.cfg(bank, mode='standard', shuffle_options=True, count=6))
        s.answer(0, 2); s.flags.add(3)
        st = json.loads(json.dumps(s.to_state()))
        s2 = Session.from_state(bank, st)
        self.assertEqual((s2.ids, s2.order, s2.ans, s2.flags), (s.ids, s.order, s.ans, s.flags))


class TestPersistence(Base):
    def run_exam(self, bank, answers, revision=False, ids=None, mode='sequential'):
        cfg = ExamConfig(pdf_id=bank.pdf_id, mode=mode, pool=ids or list(range(1, 6)), count=len(ids or range(5)),
                         revision=revision)
        s = Session.create(bank, cfg)
        for i, a in enumerate(answers):
            if a is not None:
                s.answer(i, a)
        s.finalize()
        name = self.db.get_pdf(bank.pdf_id)['name']
        eid = self.db.save_exam(s.exam_record(name), s.answer_records())
        self.db.record_results(bank.pdf_id, revision, s.results())
        return s, eid

    def test_history_and_review(self):
        pid, bank, _, _ = self.open_bank()
        s, eid = self.run_exam(bank, [1, 0, None, 1, 1])
        row = self.db.get_exam(eid)
        self.assertEqual((row['correct'], row['wrong'], row['unanswered'], row['n_questions']), (3, 1, 1, 5))
        s2 = Session.from_record(bank, row, self.db.exam_answers(eid))
        self.assertEqual((s2.ids, s2.ans), (s.ids, s.ans))
        self.assertEqual(s2.score(), 3)

    def test_revision_lists(self):
        pid, bank, _, _ = self.open_bank()
        self.run_exam(bank, [1, 0, None, 1, 0])
        c = revision.counts(self.db, pid)
        self.assertEqual((c['mistakes'], c['skipped']), (2, 1))
        self.assertEqual(revision.pool(self.db, pid, ['mistakes']), [2, 5])
        # normal exam: correct answer does NOT clear a mistake
        self.run_exam(bank, [None, 1], ids=[2, 5])
        self.assertEqual(revision.counts(self.db, pid)['mistakes'], 2)
        # revision session: correct answer clears it, history stays
        self.run_exam(bank, [1, 0], revision=True, ids=[2, 5])
        self.assertEqual(revision.pool(self.db, pid, ['mistakes']), [5])
        q2 = self.db.get_q(pid, bank.fp(2))
        self.assertEqual((q2['times_wrong'], q2['times_correct'], q2['in_mistakes']), (1, 1, 0))
        q5 = self.db.get_q(pid, bank.fp(5))
        self.assertEqual(q5['times_wrong'], 2)
        cfg = revision.make_config(self.db, pid, ['mistakes', 'skipped'], bank)
        self.assertEqual(sorted(cfg.pool), [3, 5])
        self.assertTrue(cfg.revision)

    def test_bookmarks_notes_persist_across_restart(self):
        pid, bank, _, _ = self.open_bank()
        self.db.set_q_field(pid, bank.fp(4), 4, 'favorite', True)
        self.db.set_q_field(pid, bank.fp(4), 4, 'note', '  remember this  ')
        self.db.set_q_field(pid, bank.fp(9), 9, 'difficult', True)
        self.db.set_setting('theme', 'dark')
        self.db.close()
        db2 = Database(self.tmp / 't.db', self.tmp / 'backups')
        self.addCleanup(db2.close)
        q = db2.get_q(pid, bank.fp(4))
        self.assertEqual((q['favorite'], q['note']), (1, 'remember this'))
        self.assertEqual(len(db2.list_q(pid, 'q.difficult=1')), 1)
        self.assertEqual(db2.get_setting('theme'), 'dark')
        self.db = db2

    def test_marked_sync(self):
        pid, bank, _, _ = self.open_bank()
        cfg = ExamConfig(pdf_id=pid, mode='sequential', pool=[1, 2, 3], count=3)
        s = Session.create(bank, cfg)
        s.flags.add(1)
        s.finalize()
        self.db.record_results(pid, False, s.results())
        self.assertEqual([r['qnum'] for r in self.db.list_q(pid, 'q.marked=1')], [2])
        s = Session.create(bank, cfg, marked_numbers=[2])
        self.assertEqual(s.flags, {1})

    def test_migration_backup_and_no_dupes(self):
        pid, bank, _, _ = self.open_bank()
        self.db.set_q_field(pid, bank.fp(1), 1, 'favorite', True)
        self.db.set_q_field(pid, bank.fp(1), 1, 'favorite', True)
        self.assertEqual(len(self.db.query('SELECT 1 FROM qstate')), 1)
        self.assertEqual(len(self.db.query('SELECT 1 FROM pdfs')), 1)
        self.assertTrue(self.db.backup('t').exists())

    def test_session_recovery_state(self):
        self.assertIsNone(self.db.load_state())
        self.db.save_state({'a': 1})
        self.assertEqual(self.db.load_state(), {'a': 1})
        self.db.clear_state()
        self.assertIsNone(self.db.load_state())


class TestLibrary(Base):
    def test_duplicate_and_categories(self):
        pid, bank, _, _ = self.open_bank()
        copy = self.tmp / 'copy.pdf'
        copy.write_bytes(self.pdf.read_bytes())
        data = self.lib.prepare(str(copy))
        pid2, status, msg = self.lib.register(data)
        self.assertEqual((pid2, status), (pid, 'duplicate'))
        cid = self.db.add_category('Math')
        self.assertEqual(self.db.add_category('math'), cid)
        self.db.update_pdf(pid, category_id=cid, name='My exam')
        self.assertEqual(self.db.get_pdf(pid)['category'], 'Math')
        self.db.delete_category(cid)
        self.assertIsNone(self.db.get_pdf(pid)['category_id'])

    def test_remove_keeps_data_and_readd_restores(self):
        pid, bank, _, _ = self.open_bank()
        self.db.set_q_field(pid, bank.fp(3), 3, 'note', 'keep me')
        self.db.remove_pdf(pid)
        self.assertEqual(self.db.list_pdfs(), [])
        self.assertTrue(self.pdf.exists())                 # original file untouched
        data = self.lib.prepare(str(self.pdf))
        pid2, status, _ = self.lib.register(data)
        self.assertEqual(pid2, pid)
        self.assertEqual(self.db.get_q(pid, bank.fp(3))['note'], 'keep me')

    def test_moved_file_relinked(self):
        pid, bank, _, _ = self.open_bank()
        new = self.tmp / 'moved.pdf'
        os.replace(self.pdf, new)
        data = self.lib.prepare(str(new))
        pid2, status, _ = self.lib.register(data)
        self.assertEqual((pid2, status), (pid, 'relinked'))
        self.assertEqual(self.lib.status(self.db.get_pdf(pid)), 'ok')

    def test_changed_pdf_rematches_by_fingerprint(self):
        pid, bank, _, _ = self.open_bank()
        self.db.set_q_field(pid, bank.fp(5), 5, 'note', 'five')
        self.db.set_q_field(pid, bank.fp(6), 6, 'favorite', True)
        # new version: question 6 reworded; question 1 removed by shifting numbers is simulated by editing 6
        make(self.pdf, 40, edit={6: 'A completely different question text?'})
        self.assertEqual(self.lib.status(self.db.get_pdf(pid)), 'modified')
        data = self.lib.prepare(str(self.pdf), known=self.db.get_pdf(pid))
        bank2, report = self.lib.complete_open(pid, data)
        self.assertTrue(report['changed'])
        self.assertEqual(report['stale'], 1)               # the old question 6 has gone
        self.assertEqual(self.db.get_q(pid, bank2.fp(5))['note'], 'five')   # untouched question keeps data
        self.assertEqual(len(self.db.list_q(pid, 'q.favorite=1')), 0)       # hidden, not deleted
        self.assertEqual(self.db.query('SELECT COUNT(*) FROM qstate WHERE stale=1')[0][0], 1)
        self.assertIn('no longer exist', describe_report(report))
        # the old version comes back -> data restored
        make(self.pdf, 40)
        data = self.lib.prepare(str(self.pdf), known=self.db.get_pdf(pid))
        _, report = self.lib.complete_open(pid, data)
        self.assertEqual(report['restored'], 1)
        self.assertEqual(len(self.db.list_q(pid, 'q.favorite=1')), 1)

    def test_renumbered_questions_keep_state(self):
        pid, bank, _, _ = self.open_bank()
        self.db.set_q_field(pid, bank.fp(10), 10, 'note', 'ten')
        # new file: questions 1..40 keep text but a new first question is inserted -> numbers shift
        from pdf_parser import fingerprint
        qs = [dict(q) for q in bank.q.values()]
        for q in qs:
            q['num'] += 1
        from library import OpenData, question_fps
        rep = self.db.reconcile_questions(pid, question_fps(qs))
        self.assertEqual(rep['moved'], 1)
        self.assertEqual(self.db.list_q(pid, "q.note<>''")[0]['qnum'], 11)


class TestStatsAndExport(Base):
    def make_history(self):
        pid, bank, _, _ = self.open_bank()
        t = TestPersistence('run_exam')
        t.db = self.db
        t.run_exam(bank, [1, 1, 1, 0, None])
        t.run_exam(bank, [1, 1, 1, 1, 1])
        return pid, bank

    def test_statistics(self):
        pid, bank = self.make_history()
        o = exam_stats.overview(self.db)
        self.assertEqual((o['exams'], o['questions'], o['correct'], o['wrong'], o['unanswered']), (2, 10, 8, 1, 1))
        self.assertAlmostEqual(o['accuracy'], 8 / 9 * 100)
        self.assertAlmostEqual(o['avg_score'], 80.0)
        self.assertEqual(o['best'], 100.0)
        self.assertEqual(exam_stats.overview(self.db, days=7)['exams'], 2)
        self.assertEqual(exam_stats.overview(self.db, pdf_id=999)['exams'], 0)
        d = exam_stats.daily(self.db, 7)
        self.assertEqual(len(d), 7)
        self.assertEqual(d[-1]['exams'], 2)
        self.assertEqual(exam_stats.per_pdf(self.db)[0]['exams'], 2)

    def test_exports(self):
        pid, bank = self.make_history()
        rows = self.db.list_exams()
        p = self.tmp / 'h.csv'
        self.assertEqual(export.export_history_csv(str(p), rows), 2)
        self.assertIn('Score %', p.read_text(encoding='utf-8-sig'))
        p = self.tmp / 's.csv'
        export.export_stats_csv(str(p), exam_stats.overview(self.db), exam_stats.overview(self.db, days=7),
                                exam_stats.overview(self.db, days=30), exam_stats.per_pdf(self.db),
                                exam_stats.daily(self.db, 30))
        self.assertIn('Per PDF', p.read_text(encoding='utf-8-sig'))
        p = self.tmp / 'b.json'
        n = export.export_bank_json(str(p), bank, 'x', self.db.qstates(pid))
        data = json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual((n, data['question_count']), (40, 40))
        self.assertTrue(data['questions'][0]['options'][1]['correct'])
        # PDF report
        cfg = ExamConfig(pdf_id=pid, mode='sequential', pool=list(range(1, 15)), count=14)
        s = Session.create(bank, cfg)
        for i in range(14):
            s.answer(i, i % 3)
        s.finalize()
        out = self.tmp / 'r.pdf'
        pages = export.export_results_pdf(str(out), s, dict(pdf_name='Sample'), 'all', notes={3: 'my note'})
        self.assertGreaterEqual(pages, 2)
        self.assertTrue(out.read_bytes().startswith(b'%PDF'))
        pages_w = export.export_results_pdf(str(self.tmp / 'w.pdf'), s, dict(pdf_name='Sample'), 'wrong')
        self.assertGreaterEqual(pages, pages_w)
        txt = export.results_text(s, 'Sample')
        self.assertIn('Score:', txt)
        self.assertEqual(export.numbers_text([5, 2, 9]), '2,5,9')

    def test_large_bank_speed(self):
        import time
        big = self.tmp / 'big.pdf'
        make(big, 1500)
        t = time.time()
        pid, bank, _, _ = self.open_bank(big)
        self.assertEqual(len(bank.numbers), 1500)
        self.assertLess(time.time() - t, 60)
        t = time.time()
        Session.create(bank, ExamConfig(pdf_id=pid, pool=list(bank.numbers), count=100))
        self.assertLess(time.time() - t, 1)


if __name__ == '__main__':
    unittest.main()
