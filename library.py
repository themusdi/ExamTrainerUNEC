"""PDF library service: importing, change detection, safe re-linking of saved data, bank cache.

Heavy work (hashing / parsing) is in `prepare()` and is safe to run in a worker thread.  Everything
that touches the database happens in the main-thread methods (`register`, `complete_open`, `relink`).
"""
import os
from collections import OrderedDict
from dataclasses import dataclass, field

from database import now
from pdf_parser import PDFLoadError, CancelledError, file_sha256, load_questions, fingerprint
from question_bank import Bank


@dataclass
class OpenData:
    path: str
    sha: str
    size: int
    mtime: float
    questions: list = field(default_factory=list)


def question_fps(questions):
    """{number: fingerprint} - the first question wins when a number appears twice (as in Bank)."""
    out = {}
    for q in questions:
        out.setdefault(q['num'], fingerprint(q))
    return out


class Library:
    def __init__(self, db, cache_dir, max_banks=3):
        self.db = db
        self.cache_dir = cache_dir
        self.max_banks = max_banks
        self._banks = OrderedDict()

    # ------------------------------------------------------------ worker-thread part
    def prepare(self, path, known=None, progress=None, use_cache=True):
        """Hash the file (unless size+mtime match what we know) and parse it (or load the cached parse).

        known: sqlite row / dict with sha256, size, mtime of the library record.  progress(fraction, text).
        """
        try:
            st = os.stat(path)
        except OSError:
            raise PDFLoadError('The file was not found. It may have been moved, renamed or deleted.\n\n'
                               f'{path}\n\nUse "Locate file…" in the PDF Library to point to its new place.')
        sha = None
        if known and known['sha256'] and known['size'] == st.st_size and known['mtime'] == st.st_mtime:
            sha = known['sha256']
        if sha is None:
            if progress:
                progress(0.0, 'Checking the file…')
            try:
                sha = file_sha256(path, (lambda d, t: progress(0.1 * d / t, 'Checking the file…')) if progress else None)
            except OSError as e:
                raise PDFLoadError(f'The file cannot be read: {e.strerror or e}') from e

        def p(done, total):
            if progress:
                progress(0.1 + 0.9 * done / max(1, total), f'Reading the PDF…  page {done} / {total}')
        qs = load_questions(path, sha, self.cache_dir, p, use_cache=use_cache)
        return OpenData(path=str(path), sha=sha, size=st.st_size, mtime=st.st_mtime, questions=qs)

    # ------------------------------------------------------------ main-thread part
    def status(self, row):
        """'ok' | 'missing' | 'modified' (size / date differ from what was last read)."""
        try:
            st = os.stat(row['path'])
        except OSError:
            return 'missing'
        if row['size'] is not None and (st.st_size != row['size'] or st.st_mtime != row['mtime']):
            return 'modified'
        return 'ok'

    def register(self, data, name=None, category_id=None):
        """Create / update the library record for freshly prepared data.
        Returns (pdf_id, status, message); status: new | existing | updated | relinked | duplicate."""
        db = self.db
        name = (name or os.path.splitext(os.path.basename(data.path))[0]).strip() or 'PDF'
        by_path = db.pdf_by_path(data.path)
        if by_path:
            changed = by_path['sha256'] != data.sha
            was_removed = bool(by_path['removed'])
            db.add_pdf(data.path, by_path['name'], data.sha, data.size, data.mtime, len(question_fps(data.questions)),
                       by_path['category_id'])
            self.reconcile(by_path['id'], data)
            if was_removed:
                return by_path['id'], 'existing', f'"{by_path["name"]}" was restored to the library with its history.'
            if changed:
                return by_path['id'], 'updated', f'"{by_path["name"]}" had changed and was re-read.'
            return by_path['id'], 'existing', f'"{by_path["name"]}" is already in the library.'
        for other in db.pdfs_by_sha(data.sha):
            if other['removed'] or not os.path.exists(other['path']):
                # the same content under a new path: a moved file (or a removed entry) -> reuse the record
                try:
                    db.update_pdf(other['id'], path=data.path, removed=0, size=data.size, mtime=data.mtime)
                except Exception:
                    continue
                self.reconcile(other['id'], data)
                return other['id'], 'relinked', f'"{other["name"]}" was found at its new location.'
            return other['id'], 'duplicate', (f'This file has exactly the same content as "{other["name"]}" '
                                              'which is already in the library, so it was not added again.')
        pid = db.add_pdf(data.path, name, data.sha, data.size, data.mtime,
                         len(question_fps(data.questions)), category_id)
        return pid, 'new', f'"{name}" added - {len(question_fps(data.questions))} questions found.'

    def reconcile(self, pdf_id, data):
        return self.db.reconcile_questions(pdf_id, question_fps(data.questions))

    def complete_open(self, pdf_id, data):
        """Update the record after reading the PDF and build the Bank.
        Returns (bank, report) with report = dict(changed, moved, stale, restored)."""
        row = self.db.get_pdf(pdf_id)
        changed = bool(row['sha256']) and row['sha256'] != data.sha
        report = self.reconcile(pdf_id, data)
        report['changed'] = changed
        self.db.update_pdf(pdf_id, sha256=data.sha, size=data.size, mtime=data.mtime,
                           q_count=len(question_fps(data.questions)), last_opened=now())
        bank = Bank(row['path'], data.questions, pdf_id=pdf_id, name=row['name'])
        self.remember(bank)
        return bank, report

    def relink(self, pdf_id, new_path, data):
        """Point an existing record at another file (e.g. after moving it). Returns the reconcile report."""
        clash = self.db.pdf_by_path(new_path)
        if clash and clash['id'] != pdf_id:
            raise ValueError(f'That file is already in the library as "{clash["name"]}".')
        row = self.db.get_pdf(pdf_id)
        changed = bool(row['sha256']) and row['sha256'] != data.sha
        self.db.update_pdf(pdf_id, path=data.path, sha256=data.sha, size=data.size, mtime=data.mtime,
                           q_count=len(question_fps(data.questions)), removed=0)
        report = self.reconcile(pdf_id, data)
        report['changed'] = changed
        self._banks.pop(pdf_id, None)
        return report

    # ------------------------------------------------------------ bank cache
    def cached_bank(self, pdf_id):
        """The open Bank for this PDF if the file on disk is still the one we read."""
        bank = self._banks.get(pdf_id)
        if bank is None:
            return None
        row = self.db.get_pdf(pdf_id)
        if row is None or self.status(row) == 'modified' or row['path'] != bank.path:
            self.forget(pdf_id)
            return None
        self._banks.move_to_end(pdf_id)
        return bank

    def remember(self, bank):
        self._banks[bank.pdf_id] = bank
        self._banks.move_to_end(bank.pdf_id)
        while len(self._banks) > self.max_banks:
            _, old = self._banks.popitem(last=False)
            old.close()

    def forget(self, pdf_id):
        b = self._banks.pop(pdf_id, None)
        if b:
            b.close()

    def close_all(self):
        for b in self._banks.values():
            b.close()
        self._banks.clear()


def describe_report(report):
    """Human text for the result of a reconcile (or '' when nothing noteworthy happened)."""
    if not report:
        return ''
    parts = []
    if report.get('changed'):
        parts.append('This PDF has changed since you last used it, so it was read again.')
    if report.get('moved'):
        parts.append(f'{report["moved"]} question(s) got a new number - their notes, bookmarks and statistics '
                     'moved with them.')
    if report.get('restored'):
        parts.append(f'{report["restored"]} previously hidden question(s) were found again and restored.')
    if report.get('stale'):
        parts.append(f'{report["stale"]} question(s) with saved notes / statistics no longer exist in the file. '
                     'Their data was kept safely (hidden) and returns if the question reappears.')
    return '\n\n'.join(parts)
