"""SQLite persistence: settings, PDF library, per-question state (bookmarks, notes, revision
statistics), exam history and the interrupted-session snapshot.

Design rules
  * schema changes only through numbered migrations; a backup is written before each one
  * nothing is ever deleted implicitly (removing a PDF from the library is a soft delete;
    questions of a changed PDF that cannot be matched are kept as 'stale')
  * question state is keyed by a content fingerprint, so it survives re-numbering
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class DatabaseError(Exception):
    pass


def now():
    return datetime.now().isoformat(timespec='seconds')


def path_key(path):
    return os.path.normcase(os.path.abspath(str(path)))


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS pdfs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    path_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    sha256 TEXT, size INTEGER, mtime REAL,
    q_count INTEGER NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL,
    last_opened TEXT,
    removed INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS qstate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_id INTEGER NOT NULL REFERENCES pdfs(id),
    fp TEXT NOT NULL,
    qnum INTEGER,
    last_qnum INTEGER,
    favorite INTEGER NOT NULL DEFAULT 0,
    difficult INTEGER NOT NULL DEFAULT 0,
    marked INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    times_wrong INTEGER NOT NULL DEFAULT 0,
    times_correct INTEGER NOT NULL DEFAULT 0,
    times_skipped INTEGER NOT NULL DEFAULT 0,
    in_mistakes INTEGER NOT NULL DEFAULT 0,
    in_skipped INTEGER NOT NULL DEFAULT 0,
    last_result TEXT,
    last_seen TEXT,
    last_wrong TEXT,
    stale INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    UNIQUE (pdf_id, fp));
CREATE INDEX IF NOT EXISTS idx_qstate_num ON qstate(pdf_id, qnum);

CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pdf_id INTEGER,
    pdf_name TEXT NOT NULL,
    mode TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'exam',
    source TEXT,
    started_at TEXT,
    finished_at TEXT NOT NULL,
    n_questions INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    wrong INTEGER NOT NULL,
    unanswered INTEGER NOT NULL,
    score REAL NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    config TEXT);
CREATE INDEX IF NOT EXISTS idx_exams_pdf ON exams(pdf_id);
CREATE INDEX IF NOT EXISTS idx_exams_finished ON exams(finished_at);

CREATE TABLE IF NOT EXISTS exam_answers (
    exam_id INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
    pos INTEGER NOT NULL,
    qnum INTEGER NOT NULL,
    fp TEXT,
    chosen INTEGER,
    correct INTEGER NOT NULL DEFAULT 0,
    flagged INTEGER NOT NULL DEFAULT 0,
    opt_order TEXT,
    PRIMARY KEY (exam_id, pos));

CREATE TABLE IF NOT EXISTS session_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL);
"""


def _migrate_1(conn):
    conn.executescript(SCHEMA_V1)


MIGRATIONS = [(1, _migrate_1)]          # (target version, function) - append new ones, never edit old ones
LATEST = MIGRATIONS[-1][0]

QFLAGS = ('favorite', 'difficult', 'marked', 'in_mistakes', 'in_skipped')


class Database:
    def __init__(self, path, backup_dir):
        self.path = Path(path)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        try:
            self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute('PRAGMA foreign_keys=ON')
            self.conn.execute('PRAGMA journal_mode=WAL')
            self._migrate()
        except sqlite3.DatabaseError as e:
            raise DatabaseError(f'The database file could not be opened: {e}') from e

    # ------------------------------------------------------------------ infrastructure
    def _migrate(self):
        cur = self.conn.execute('PRAGMA user_version').fetchone()[0]
        if cur > LATEST:
            raise DatabaseError('This data was written by a newer version of Exam Trainer. '
                                'Please update the program.')
        for ver, fn in MIGRATIONS:
            if ver > cur:
                if cur > 0:
                    self.backup(f'before-migration-v{ver}')
                fn(self.conn)
                self.conn.execute(f'PRAGMA user_version={ver}')
                self.conn.commit()
                cur = ver

    def close(self):
        with self.lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass

    def execute(self, sql, params=()):
        with self.lock, self.conn:
            return self.conn.execute(sql, params)

    def query(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def backup(self, tag='manual', keep=15):
        """Consistent copy of the whole database into the backup folder. Returns the file path."""
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        dest = self.backup_dir / f'exam_trainer-{stamp}-{tag}.db'
        with self.lock:
            out = sqlite3.connect(str(dest))
            try:
                self.conn.backup(out)
            finally:
                out.close()
        files = sorted(self.backup_dir.glob('exam_trainer-*.db'), key=lambda p: p.stat().st_mtime)
        for old in files[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
        return dest

    def auto_backup(self):
        """At most one automatic backup per day, and only if there is something worth saving."""
        if not self.one('SELECT 1 FROM exams LIMIT 1') and not self.one('SELECT 1 FROM qstate LIMIT 1'):
            return None
        today = datetime.now().strftime('%Y%m%d')
        if any(self.backup_dir.glob(f'exam_trainer-{today}-*-auto.db')):
            return None
        try:
            return self.backup('auto')
        except (sqlite3.Error, OSError):
            return None

    # ------------------------------------------------------------------ settings
    def get_setting(self, key, default=None):
        row = self.one('SELECT value FROM settings WHERE key=?', (key,))
        if row is None:
            return default
        try:
            return json.loads(row['value'])
        except ValueError:
            return default

    def set_setting(self, key, value):
        self.execute('INSERT INTO settings(key,value) VALUES(?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, json.dumps(value)))

    def all_settings(self):
        out = {}
        for r in self.query('SELECT key, value FROM settings'):
            try:
                out[r['key']] = json.loads(r['value'])
            except ValueError:
                pass
        return out

    # ------------------------------------------------------------------ categories
    def list_categories(self):
        return self.query('SELECT c.id, c.name, '
                          '(SELECT COUNT(*) FROM pdfs p WHERE p.category_id=c.id AND p.removed=0) AS n '
                          'FROM categories c ORDER BY c.name COLLATE NOCASE')

    def add_category(self, name):
        name = (name or '').strip()
        if not name:
            raise ValueError('The category name cannot be empty.')
        if len(name) > 60:
            raise ValueError('The category name is too long (60 characters max).')
        with self.lock, self.conn:
            self.conn.execute('INSERT OR IGNORE INTO categories(name) VALUES(?)', (name,))
            return self.conn.execute('SELECT id FROM categories WHERE name=?', (name,)).fetchone()[0]

    def rename_category(self, cid, name):
        name = (name or '').strip()
        if not name:
            raise ValueError('The category name cannot be empty.')
        try:
            self.execute('UPDATE categories SET name=? WHERE id=?', (name, cid))
        except sqlite3.IntegrityError:
            raise ValueError('A category with this name already exists.')

    def delete_category(self, cid):
        """PDFs of the category are kept - they just become uncategorised."""
        self.execute('UPDATE pdfs SET category_id=NULL WHERE category_id=?', (cid,))
        self.execute('DELETE FROM categories WHERE id=?', (cid,))

    # ------------------------------------------------------------------ PDF library
    def add_pdf(self, path, name, sha256, size, mtime, q_count, category_id=None):
        """Insert a PDF, or update/revive the existing record for the same path. Returns its id."""
        key, ts = path_key(path), now()
        with self.lock, self.conn:
            row = self.conn.execute('SELECT id FROM pdfs WHERE path_key=?', (key,)).fetchone()
            if row:
                self.conn.execute('UPDATE pdfs SET path=?, sha256=?, size=?, mtime=?, q_count=?, removed=0 '
                                  'WHERE id=?', (os.path.abspath(str(path)), sha256, size, mtime, q_count, row['id']))
                return row['id']
            cur = self.conn.execute(
                'INSERT INTO pdfs(path,path_key,name,category_id,sha256,size,mtime,q_count,added_at) '
                'VALUES(?,?,?,?,?,?,?,?,?)',
                (os.path.abspath(str(path)), key, name, category_id, sha256, size, mtime, q_count, ts))
            return cur.lastrowid

    def get_pdf(self, pdf_id):
        return self.one('SELECT p.*, c.name AS category FROM pdfs p '
                        'LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=?', (pdf_id,))

    def pdf_by_path(self, path):
        return self.one('SELECT * FROM pdfs WHERE path_key=?', (path_key(path),))

    def pdfs_by_sha(self, sha):
        return self.query('SELECT * FROM pdfs WHERE sha256=?', (sha,))

    def list_pdfs(self, include_removed=False, category_id=None, search=None):
        sql = ('SELECT p.*, c.name AS category FROM pdfs p '
               'LEFT JOIN categories c ON c.id=p.category_id WHERE 1=1')
        args = []
        if not include_removed:
            sql += ' AND p.removed=0'
        if category_id == 0:
            sql += ' AND p.category_id IS NULL'
        elif category_id:
            sql += ' AND p.category_id=?'
            args.append(category_id)
        if search:
            sql += ' AND p.name LIKE ?'
            args.append(f'%{search}%')
        return self.query(sql + ' ORDER BY p.name COLLATE NOCASE', args)

    def recent_pdfs(self, limit=5):
        return self.query('SELECT p.*, c.name AS category FROM pdfs p '
                          'LEFT JOIN categories c ON c.id=p.category_id '
                          'WHERE p.removed=0 AND p.last_opened IS NOT NULL '
                          'ORDER BY p.last_opened DESC LIMIT ?', (limit,))

    _PDF_FIELDS = ('path', 'name', 'category_id', 'sha256', 'size', 'mtime', 'q_count', 'last_opened', 'removed')

    def update_pdf(self, pdf_id, **fields):
        bad = set(fields) - set(self._PDF_FIELDS)
        if bad:
            raise ValueError(f'Unknown PDF field(s): {bad}')
        if not fields:
            return
        if 'path' in fields:
            fields['path'] = os.path.abspath(str(fields['path']))
            fields['path_key'] = path_key(fields['path'])
        sets = ', '.join(f'{k}=?' for k in fields)
        self.execute(f'UPDATE pdfs SET {sets} WHERE id=?', (*fields.values(), pdf_id))

    def remove_pdf(self, pdf_id):
        """Soft delete: hides the PDF from the library but keeps all history, notes and statistics."""
        self.execute('UPDATE pdfs SET removed=1 WHERE id=?', (pdf_id,))

    # ------------------------------------------------------------------ question state
    def reconcile_questions(self, pdf_id, fps):
        """Align stored question state with the current bank.

        fps: {question number: fingerprint}.  Rows are matched by fingerprint, so a question that moved
        to another number keeps its notes / bookmarks / statistics.  Rows whose question no longer exists
        are flagged 'stale' (hidden, but kept - they come back if the question reappears).
        Returns dict(moved=, stale=, restored=).
        """
        fp_to_num = {}
        for n in sorted(fps):
            fp_to_num.setdefault(fps[n], n)
        moved = stale = restored = 0
        ts = now()
        with self.lock, self.conn:
            for r in self.conn.execute('SELECT id, fp, qnum, stale FROM qstate WHERE pdf_id=?', (pdf_id,)).fetchall():
                new = fp_to_num.get(r['fp'])
                if new is None:
                    if not r['stale']:
                        stale += 1
                        self.conn.execute('UPDATE qstate SET stale=1, last_qnum=qnum, qnum=NULL, updated_at=? '
                                          'WHERE id=?', (ts, r['id']))
                elif r['stale'] or r['qnum'] != new:
                    restored += 1 if r['stale'] else 0
                    moved += 0 if r['stale'] else 1
                    self.conn.execute('UPDATE qstate SET stale=0, qnum=?, updated_at=? WHERE id=?',
                                      (new, ts, r['id']))
        return dict(moved=moved, stale=stale, restored=restored)

    def qstates(self, pdf_id):
        """{question number: row} for all non-stale state rows of a PDF."""
        return {r['qnum']: r for r in self.query(
            'SELECT * FROM qstate WHERE pdf_id=? AND stale=0 AND qnum IS NOT NULL', (pdf_id,))}

    def get_q(self, pdf_id, fp):
        return self.one('SELECT * FROM qstate WHERE pdf_id=? AND fp=?', (pdf_id, fp))

    def set_q_field(self, pdf_id, fp, qnum, field, value):
        if field not in QFLAGS and field != 'note':
            raise ValueError(f'Bad question field: {field}')
        if field == 'note':
            value = (value or '').strip()[:5000]
        else:
            value = 1 if value else 0
        ts = now()
        with self.lock, self.conn:
            self.conn.execute('INSERT OR IGNORE INTO qstate(pdf_id,fp,qnum,updated_at) VALUES(?,?,?,?)',
                              (pdf_id, fp, qnum, ts))
            self.conn.execute(f'UPDATE qstate SET {field}=?, qnum=?, stale=0, updated_at=? '
                              'WHERE pdf_id=? AND fp=?', (value, qnum, ts, pdf_id, fp))

    def record_results(self, pdf_id, revision, results):
        """results: list of dict(num, fp, status in correct|wrong|skipped, flagged).

        correct -> times_correct+1, leaves the unanswered list; in a *revision* session it also leaves
                   the active mistake list (its history stays)
        wrong   -> times_wrong+1, joins the mistake list
        skipped -> times_skipped+1, joins the unanswered list
        """
        ts = now()
        with self.lock, self.conn:
            c = self.conn
            for r in results:
                c.execute('INSERT OR IGNORE INTO qstate(pdf_id,fp,qnum,updated_at) VALUES(?,?,?,?)',
                          (pdf_id, r['fp'], r['num'], ts))
                marked = 1 if r.get('flagged') else 0
                st = r['status']
                common = (r['num'], marked, ts, ts, pdf_id, r['fp'])
                if st == 'correct':
                    c.execute("UPDATE qstate SET times_correct=times_correct+1, last_result='correct', "
                              "in_skipped=0, in_mistakes=CASE WHEN ?=1 THEN 0 ELSE in_mistakes END, "
                              "qnum=?, marked=?, stale=0, last_seen=?, updated_at=? "
                              "WHERE pdf_id=? AND fp=?", (1 if revision else 0,) + common)
                elif st == 'wrong':
                    c.execute("UPDATE qstate SET times_wrong=times_wrong+1, last_result='wrong', "
                              "in_mistakes=1, in_skipped=0, last_wrong=?, "
                              "qnum=?, marked=?, stale=0, last_seen=?, updated_at=? "
                              "WHERE pdf_id=? AND fp=?", (ts,) + common)
                else:
                    c.execute("UPDATE qstate SET times_skipped=times_skipped+1, last_result='skipped', "
                              "in_skipped=1, qnum=?, marked=?, stale=0, last_seen=?, updated_at=? "
                              "WHERE pdf_id=? AND fp=?", common)

    def list_q(self, pdf_id=None, where='1=1', params=(), order='p.name COLLATE NOCASE, q.qnum'):
        sql = ('SELECT q.*, p.name AS pdf_name FROM qstate q JOIN pdfs p ON p.id=q.pdf_id '
               'WHERE q.stale=0 AND q.qnum IS NOT NULL AND p.removed=0 AND (' + where + ')')
        args = list(params)
        if pdf_id:
            sql += ' AND q.pdf_id=?'
            args.append(pdf_id)
        return self.query(sql + ' ORDER BY ' + order, args)

    # ------------------------------------------------------------------ exams / history
    def save_exam(self, exam, answers):
        """exam: dict with the columns of table 'exams'; answers: list of dict(pos,qnum,fp,chosen,correct,
        flagged,opt_order). Stored atomically. Returns the new exam id."""
        cols = ('pdf_id', 'pdf_name', 'mode', 'kind', 'source', 'started_at', 'finished_at', 'n_questions',
                'correct', 'wrong', 'unanswered', 'score', 'duration', 'config')
        with self.lock, self.conn:
            cur = self.conn.execute(
                f'INSERT INTO exams({",".join(cols)}) VALUES({",".join("?" * len(cols))})',
                [exam.get(c) for c in cols])
            eid = cur.lastrowid
            self.conn.executemany(
                'INSERT INTO exam_answers(exam_id,pos,qnum,fp,chosen,correct,flagged,opt_order) '
                'VALUES(?,?,?,?,?,?,?,?)',
                [(eid, a['pos'], a['qnum'], a.get('fp'), a.get('chosen'), 1 if a.get('correct') else 0,
                  1 if a.get('flagged') else 0, json.dumps(a.get('opt_order'))) for a in answers])
            return eid

    def list_exams(self, pdf_id=None, limit=None, since=None):
        sql, args = 'SELECT * FROM exams WHERE 1=1', []
        if pdf_id:
            sql += ' AND pdf_id=?'
            args.append(pdf_id)
        if since:
            sql += ' AND finished_at>=?'
            args.append(since)
        sql += ' ORDER BY finished_at DESC, id DESC'
        if limit:
            sql += ' LIMIT ?'
            args.append(limit)
        return self.query(sql, args)

    def get_exam(self, exam_id):
        return self.one('SELECT * FROM exams WHERE id=?', (exam_id,))

    def exam_answers(self, exam_id):
        return self.query('SELECT * FROM exam_answers WHERE exam_id=? ORDER BY pos', (exam_id,))

    def delete_exam(self, exam_id):
        self.execute('DELETE FROM exams WHERE id=?', (exam_id,))

    def clear_history(self):
        """Remove all exam records (a backup is written first). Notes, bookmarks and mistake lists stay."""
        self.backup('before-clear-history')
        with self.lock, self.conn:
            self.conn.execute('DELETE FROM exam_answers')
            self.conn.execute('DELETE FROM exams')

    # ------------------------------------------------------------------ interrupted session
    def save_state(self, data):
        self.execute('INSERT INTO session_state(id,data,updated_at) VALUES(1,?,?) '
                     'ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at',
                     (json.dumps(data), now()))

    def load_state(self):
        row = self.one('SELECT data FROM session_state WHERE id=1')
        if not row:
            return None
        try:
            return json.loads(row['data'])
        except ValueError:
            return None

    def clear_state(self):
        self.execute('DELETE FROM session_state')
