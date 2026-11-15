"""Exam logic without any GUI code: modes, sessions, scoring, snapshots for crash recovery."""
import json
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime

from pdf_parser import parse_ranges

MODES = {
    'standard':   dict(label='Standard',   icon='📝', desc='Random questions. Answers are checked when you finish.'),
    'timed':      dict(label='Timed',      icon='⏳', desc='Like Standard, but the whole exam has a time limit.'),
    'practice':   dict(label='Practice',   icon='🎯', desc='Right / wrong is shown immediately after each answer.'),
    'sequential': dict(label='Sequential', icon='📖', desc='Questions appear in their original order.'),
    'endless':    dict(label='Endless',    icon='♾', desc='Keeps serving new questions from the pool - no repeats until the pool is empty.'),
    'survival':   dict(label='Survival',   icon='❤', desc='Immediate feedback. The session ends after the first wrong answer.'),
}
MODE_ORDER = ['standard', 'timed', 'practice', 'sequential', 'endless', 'survival']
FEEDBACK_MODES = ('practice', 'survival')       # answer is checked at once and then locked
DYNAMIC_MODES = ('endless', 'survival')         # only the questions actually reached count


def mode_label(mode):
    return MODES.get(mode, {}).get('label', mode.title())


def build_pool(bank, range_text):
    """'1,5-61' -> (sorted question numbers that exist, list of tokens that were not understood)."""
    text = (range_text or '').strip()
    if not text:
        return list(bank.numbers), []
    return parse_ranges(text, set(bank.numbers))


@dataclass
class ExamConfig:
    pdf_id: int = None
    mode: str = 'standard'
    pool: list = field(default_factory=list)
    count: int = 30                    # 0 = everything in the pool
    shuffle_options: bool = False
    time_limit_min: float = None       # timed mode
    lives: int = 1                     # survival mode
    revision: bool = False             # a wrong->correct answer removes the question from the mistake list
    source: str = 'pool'               # pool | mistakes | skipped | marked | difficult | favorite | notes | retry
    source_label: str = ''

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


class Session:
    """One running (or reviewed) exam. ans[i] is the ORIGINAL option index that was chosen."""

    def __init__(self, bank, config, ids, order=None, ans=None, flags=None, remaining=None,
                 elapsed=0.0, started_at=None):
        self.bank = bank
        self.config = config
        self.mode = config.mode
        self.ids = list(ids)
        self.order = order if order is not None else [self._opt_order(n) for n in self.ids]
        self.ans = ans if ans is not None else [None] * len(self.ids)
        self.flags = set(flags or ())
        self.remaining = list(remaining or [])
        self.lives = max(1, int(config.lives or 1))
        self.visited_max = 0
        self.started_at = started_at or datetime.now().isoformat(timespec='seconds')
        self._base = float(elapsed)
        self._t = None
        self.finalized = False

    # ------------------------------------------------------------------ creation
    def _opt_order(self, num):
        idx = list(range(len(self.bank.q[num]['opts'])))
        if self.config.shuffle_options:
            random.shuffle(idx)
        return idx

    @classmethod
    def create(cls, bank, config, marked_numbers=(), rng=random):
        pool = [n for n in dict.fromkeys(config.pool) if n in bank.q]
        if not pool:
            raise ValueError('The question pool is empty.')
        count = config.count if config.count and config.count > 0 else len(pool)
        count = min(count, len(pool))
        mode, remaining = config.mode, []
        if mode == 'sequential':
            ids = sorted(pool)[:count]
        elif mode == 'endless':
            shuffled = pool[:]
            rng.shuffle(shuffled)
            remaining = shuffled[::-1]                 # pop() from the end = next question
            ids = [remaining.pop()]
        else:
            ids = rng.sample(pool, count)
        marked = set(marked_numbers)
        s = cls(bank, config, ids, remaining=remaining, flags=[i for i, n in enumerate(ids) if n in marked])
        s.resume()
        return s

    # ------------------------------------------------------------------ clock
    def resume(self):
        if self._t is None:
            self._t = time.monotonic()

    def pause(self):
        if self._t is not None:
            self._base += time.monotonic() - self._t
            self._t = None

    def elapsed(self):
        return self._base + ((time.monotonic() - self._t) if self._t is not None else 0.0)

    def time_limit(self):
        if self.mode == 'timed' and self.config.time_limit_min:
            return float(self.config.time_limit_min) * 60
        return None

    def time_left(self):
        lim = self.time_limit()
        return None if lim is None else max(0.0, lim - self.elapsed())

    def time_up(self):
        left = self.time_left()
        return left is not None and left <= 0

    # ------------------------------------------------------------------ answering
    @property
    def feedback(self):
        return self.mode in FEEDBACK_MODES

    def locked(self, i):
        return self.feedback and self.ans[i] is not None

    def answer(self, i, oi):
        """Choose option oi (original index) for question i. Clicking the chosen option again clears it
        (not in feedback modes). Returns True if something changed."""
        if self.locked(i) or self.finalized:
            return False
        self.ans[i] = None if (self.ans[i] == oi and not self.feedback) else oi
        return True

    def is_correct(self, i):
        a = self.ans[i]
        return a is not None and bool(self.bank.q[self.ids[i]]['opts'][a]['correct'])

    def score(self):
        return sum(self.is_correct(i) for i in range(len(self.ids)))

    def answered(self):
        return sum(a is not None for a in self.ans)

    def unanswered(self):
        return len(self.ids) - self.answered()

    def wrong(self):
        return self.answered() - self.score()

    def percent(self):
        return (self.score() / len(self.ids) * 100) if self.ids else 0.0

    def status(self, i):
        if self.ans[i] is None:
            return 'skipped'
        return 'correct' if self.is_correct(i) else 'wrong'

    def wrong_ids(self):
        """Question numbers answered wrongly or not at all."""
        return [self.ids[i] for i in range(len(self.ids)) if not self.is_correct(i)]

    @property
    def game_over(self):
        return self.mode == 'survival' and self.wrong() >= self.lives

    @property
    def pool_exhausted(self):
        return self.mode == 'endless' and not self.remaining

    def visit(self, i):
        self.visited_max = max(self.visited_max, i)

    def extend(self):
        """Endless mode: append the next unseen question. False if the pool is used up."""
        if self.mode != 'endless' or not self.remaining:
            return False
        n = self.remaining.pop()
        self.ids.append(n)
        self.order.append(self._opt_order(n))
        self.ans.append(None)
        return True

    # ------------------------------------------------------------------ finishing
    def finalize(self):
        """Freeze the session. Survival / endless count only the questions actually reached."""
        if self.finalized:
            return
        self.pause()
        if self.mode in DYNAMIC_MODES:
            keep = max(self.visited_max + 1, max((i + 1 for i, a in enumerate(self.ans) if a is not None), default=0))
            keep = min(keep, len(self.ids))
            del self.ids[keep:], self.order[keep:], self.ans[keep:]
            self.flags = {f for f in self.flags if f < keep}
        self.finalized = True

    def summary(self):
        n = len(self.ids)
        c, u = self.score(), self.unanswered()
        return dict(n=n, correct=c, unanswered=u, wrong=n - c - u, percent=self.percent(),
                    duration=self.elapsed())

    def results(self):
        """For the revision statistics: list of dict(num, fp, status, flagged)."""
        return [dict(num=n, fp=self.bank.fp(n), status=self.status(i), flagged=i in self.flags)
                for i, n in enumerate(self.ids)]

    def answer_records(self):
        return [dict(pos=i, qnum=n, fp=self.bank.fp(n), chosen=self.ans[i], correct=self.is_correct(i),
                     flagged=i in self.flags, opt_order=self.order[i]) for i, n in enumerate(self.ids)]

    def exam_record(self, pdf_name):
        s = self.summary()
        return dict(pdf_id=self.config.pdf_id, pdf_name=pdf_name, mode=self.mode,
                    kind='revision' if self.config.revision else 'exam', source=self.config.source,
                    started_at=self.started_at, finished_at=datetime.now().isoformat(timespec='seconds'),
                    n_questions=s['n'], correct=s['correct'], wrong=s['wrong'], unanswered=s['unanswered'],
                    score=round(s['percent'], 2), duration=round(s['duration'], 1),
                    config=json.dumps({k: v for k, v in self.config.to_dict().items() if k != 'pool'}))

    # ------------------------------------------------------------------ crash recovery
    def to_state(self):
        return dict(pdf_id=self.config.pdf_id, config=self.config.to_dict(), ids=self.ids, order=self.order,
                    ans=self.ans, flags=sorted(self.flags), remaining=self.remaining, elapsed=self.elapsed(),
                    started_at=self.started_at, cur=self.visited_max)

    @classmethod
    def from_state(cls, bank, state):
        """Rebuild an interrupted session; questions that no longer exist in the bank are dropped."""
        cfg = ExamConfig.from_dict(state.get('config'))
        keep = [i for i, n in enumerate(state['ids']) if n in bank.q
                and sorted(state['order'][i]) == list(range(len(bank.q[n]['opts'])))]
        if not keep:
            raise ValueError('None of the questions of the interrupted exam exist any more.')
        remap = {old: new for new, old in enumerate(keep)}
        s = cls(bank, cfg, [state['ids'][i] for i in keep], order=[state['order'][i] for i in keep],
                ans=[state['ans'][i] for i in keep],
                flags=[remap[f] for f in state.get('flags', []) if f in remap],
                remaining=[n for n in state.get('remaining', []) if n in bank.q],
                elapsed=state.get('elapsed', 0.0), started_at=state.get('started_at'))
        s.visited_max = min(state.get('cur', 0), len(s.ids) - 1)
        s.resume()
        return s

    @classmethod
    def from_record(cls, bank, exam_row, answer_rows):
        """Rebuild a finished exam from the history for review. Questions are located by fingerprint, so
        a renumbered PDF still works; questions that vanished are skipped (the count is returned)."""
        cfg = ExamConfig.from_dict(json.loads(exam_row['config'] or '{}'))
        cfg.mode = exam_row['mode']
        ids, order, ans, flags, missing = [], [], [], set(), 0
        for r in answer_rows:
            num = bank.num_for_fp(r['fp']) if r['fp'] else None
            if num is None and r['qnum'] in bank.q and not r['fp']:
                num = r['qnum']
            if num is None:
                missing += 1
                continue
            n_opts = len(bank.q[num]['opts'])
            try:
                o = json.loads(r['opt_order'] or 'null')
            except ValueError:
                o = None
            if not isinstance(o, list) or sorted(o) != list(range(n_opts)):
                o = list(range(n_opts))
            ch = r['chosen']
            if ch is not None and not (0 <= ch < n_opts):
                ch = None
            if r['flagged']:
                flags.add(len(ids))
            ids.append(num)
            order.append(o)
            ans.append(ch)
        s = cls(bank, cfg, ids, order=order, ans=ans, flags=flags, elapsed=exam_row['duration'],
                started_at=exam_row['started_at'])
        s.finalized = True
        s.missing = missing
        return s


def retry_config(session, shuffle=None):
    """Config for 'retry the wrong / unanswered ones' (counts as a revision session)."""
    ids = session.wrong_ids()
    mode = session.mode if session.mode in ('standard', 'timed', 'practice', 'sequential') else 'standard'
    cfg = ExamConfig(pdf_id=session.config.pdf_id, mode=mode, pool=ids, count=len(ids),
                     shuffle_options=session.config.shuffle_options if shuffle is None else shuffle,
                     time_limit_min=session.config.time_limit_min if mode == 'timed' else None,
                     revision=True, source='retry', source_label='Wrong / unanswered questions')
    return cfg
