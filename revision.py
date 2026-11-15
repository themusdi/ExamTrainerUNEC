"""Smart revision: which questions to practise again (mistakes, unanswered, marked, difficult, favourites)."""
from exam_engine import ExamConfig

SOURCES = {
    'mistakes':  dict(label='Active mistakes', where='q.in_mistakes=1'),
    'skipped':   dict(label='Unanswered',      where='q.in_skipped=1'),
    'marked':    dict(label='Marked for review', where='q.marked=1'),
    'difficult': dict(label='Difficult',       where='q.difficult=1'),
    'favorite':  dict(label='Favourites',      where='q.favorite=1'),
    'notes':     dict(label='With notes',      where="q.note<>''"),
}


def counts(db, pdf_id=None):
    """{source: number of questions} (stale questions of changed PDFs are not counted)."""
    out = {}
    for key, info in SOURCES.items():
        out[key] = len(db.list_q(pdf_id, info['where']))
    return out


def counts_by_pdf(db):
    """{pdf_id: {source: n}} for every library PDF that has any flagged question."""
    res = {}
    for key, info in SOURCES.items():
        for r in db.query('SELECT q.pdf_id AS pid, COUNT(*) AS n FROM qstate q JOIN pdfs p ON p.id=q.pdf_id '
                          'WHERE q.stale=0 AND q.qnum IS NOT NULL AND p.removed=0 AND ' + info['where'] +
                          ' GROUP BY q.pdf_id'):
            res.setdefault(r['pid'], {k: 0 for k in SOURCES})[key] = r['n']
    return res


def questions(db, pdf_id, sources, most_missed_first=True):
    """Rows for the union of the chosen sources."""
    where = ' OR '.join(SOURCES[s]['where'] for s in sources if s in SOURCES) or '0'
    order = 'q.times_wrong DESC, q.qnum' if most_missed_first else 'q.qnum'
    return db.list_q(pdf_id, where, order=order)


def pool(db, pdf_id, sources, bank=None, most_missed_first=True):
    nums = [r['qnum'] for r in questions(db, pdf_id, sources, most_missed_first)]
    if bank is not None:
        nums = [n for n in nums if n in bank.q]
    return nums


def make_config(db, pdf_id, sources, bank=None, mode='standard', label=None, revision=True):
    nums = pool(db, pdf_id, sources, bank)
    src = sources[0] if len(sources) == 1 else 'revision'
    names = ', '.join(SOURCES[s]['label'] for s in sources)
    return ExamConfig(pdf_id=pdf_id, mode=mode, pool=nums, count=len(nums), revision=revision,
                      source=src, source_label=label or names)


def clear_mistake(db, pdf_id, fp, qnum):
    """Manually take a question off the active mistake / unanswered lists (history is kept)."""
    db.set_q_field(pdf_id, fp, qnum, 'in_mistakes', 0)
    db.set_q_field(pdf_id, fp, qnum, 'in_skipped', 0)
