"""Statistics computed from the exam history (no fake data: everything comes from saved exams)."""
from datetime import date, timedelta


def _since(days):
    return (date.today() - timedelta(days=days - 1)).isoformat()


def _pack(r):
    answered = (r['correct'] or 0) + (r['wrong'] or 0)
    return dict(exams=r['exams'] or 0, questions=r['questions'] or 0, answered=answered,
                correct=r['correct'] or 0, wrong=r['wrong'] or 0, unanswered=r['unanswered'] or 0,
                accuracy=(r['correct'] / answered * 100) if answered else None,
                avg_score=r['avg_score'], best=r['best'], time=r['time'] or 0.0)


_AGG = ('SELECT COUNT(*) AS exams, SUM(n_questions) AS questions, SUM(correct) AS correct, SUM(wrong) AS wrong, '
        'SUM(unanswered) AS unanswered, AVG(score) AS avg_score, MAX(score) AS best, SUM(duration) AS time '
        'FROM exams')


def overview(db, pdf_id=None, days=None):
    """Aggregate numbers, optionally for one PDF and/or the last `days` days (today included)."""
    where, args = [], []
    if pdf_id:
        where.append('pdf_id=?')
        args.append(pdf_id)
    if days:
        where.append('finished_at>=?')
        args.append(_since(days))
    sql = _AGG + (' WHERE ' + ' AND '.join(where) if where else '')
    return _pack(db.one(sql, args))


def recent_exams(db, limit=20, pdf_id=None):
    """Oldest -> newest, for charts."""
    rows = db.list_exams(pdf_id=pdf_id, limit=limit)
    return list(reversed(rows))


def daily(db, days=30):
    """One entry per calendar day of the period (days without exams have zeros)."""
    rows = db.query('SELECT substr(finished_at,1,10) AS d, COUNT(*) AS exams, SUM(correct+wrong) AS answered, '
                    'SUM(correct) AS correct, AVG(score) AS avg_score FROM exams WHERE finished_at>=? GROUP BY d',
                    (_since(days),))
    by_day = {r['d']: r for r in rows}
    out = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        r = by_day.get(d)
        out.append(dict(date=d, exams=r['exams'] if r else 0, answered=(r['answered'] or 0) if r else 0,
                        correct=(r['correct'] or 0) if r else 0,
                        avg_score=r['avg_score'] if r else None))
    return out


def per_pdf(db):
    rows = db.query('SELECT e.pdf_id, COALESCE(p.name, e.pdf_name) AS name, p.removed AS removed, '
                    'COUNT(*) AS exams, SUM(e.n_questions) AS questions, SUM(e.correct) AS correct, '
                    'SUM(e.wrong) AS wrong, SUM(e.unanswered) AS unanswered, AVG(e.score) AS avg_score, '
                    'MAX(e.score) AS best, SUM(e.duration) AS time '
                    'FROM exams e LEFT JOIN pdfs p ON p.id=e.pdf_id GROUP BY e.pdf_id ORDER BY name COLLATE NOCASE')
    out = []
    for r in rows:
        d = _pack(r)
        d.update(pdf_id=r['pdf_id'], name=r['name'] + (' (removed)' if r['removed'] else ''))
        out.append(d)
    return out


def fmt_duration(sec):
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}h {m:02d}m'
    return f'{m}m {s:02d}s' if m else f'{s}s'


def fmt_clock(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


def fmt_pct(v, digits=1):
    return '–' if v is None else f'{v:.{digits}f}%'
