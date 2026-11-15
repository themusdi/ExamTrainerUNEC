"""Application-wide constants and per-user data locations (no machine-specific paths)."""
import os
import sys
from pathlib import Path

APP_NAME = 'Exam Trainer'
APP_VERSION = '2.0.0'
PARSER_VERSION = 1            # bump when PDF parsing changes -> invalidates the parse cache

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
LEGACY_CONFIG = Path.home() / '.exam_trainer.json'      # settings file of Exam Trainer 1.x


def data_dir():
    """Where the database, caches and backups live.

    1. $EXAM_TRAINER_DATA, if set
    2. ./data next to the program, if a file called 'portable.flag' sits next to it
    3. %APPDATA%/ExamTrainer on Windows, ~/.local/share/ExamTrainer elsewhere
    """
    env = os.environ.get('EXAM_TRAINER_DATA')
    if env:
        p = Path(env)
    elif (ROOT / 'portable.flag').exists():
        p = ROOT / 'data'
    elif sys.platform == 'win32':
        p = Path(os.environ.get('APPDATA') or Path.home()) / 'ExamTrainer'
    else:
        p = Path.home() / '.local' / 'share' / 'ExamTrainer'
    p.mkdir(parents=True, exist_ok=True)
    return p


class Paths:
    def __init__(self, base=None):
        self.base = Path(base) if base else data_dir()
        self.db = self.base / 'exam_trainer.db'
        self.cache = self.base / 'cache'
        self.backups = self.base / 'backups'
        for d in (self.cache, self.backups):
            d.mkdir(parents=True, exist_ok=True)


DEFAULT_SETTINGS = {
    'theme': 'light',
    'font_size': 12,
    'fullscreen_exams': False,
    'confirm_finish': True,
    'default_mode': 'standard',
    'default_count': 30,
    'default_shuffle': False,
    'autosave_sessions': True,
    'seen_help': False,
    'last_pdf_id': None,
    'last_range': '',
    'legacy_imported': False,
}
FONT_SIZE_RANGE = (9, 20)
