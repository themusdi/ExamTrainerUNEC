# Exam Trainer 2.0

A desktop application (Python + Tkinter) that turns PDF files with multiple-choice questions into a
complete study platform: exams in six modes, a PDF library, revision of mistakes, bookmarks and notes,
history, statistics and exports.

## Install and run (Windows)

1. Install Python 3.9 or newer from python.org (tick **Add python.exe to PATH**).
2. Double-click **`run.bat`** - the first start creates a private environment and installs the packages.

Manual alternative:

    pip install -r requirements.txt
    python main.py

Requirements: `pdfplumber`, `pypdfium2`, `Pillow` (see `requirements.txt`). Everything else is the
Python standard library (Tkinter, SQLite).

## PDF format

    12. Question text ...
    • a wrong variant
    √ the correct variant
    • another wrong variant

Each question starts with its number; each variant starts with `•` (wrong) or `√` (correct). Pictures and
formulas inside questions or variants are supported. (This is the format of version 1 - the parser is unchanged.)

## Using the program

Press **F1** inside the program for the guide. In short:

| Page | What it does |
|---|---|
| Home | Resume an interrupted exam, quick numbers, recent PDFs |
| New exam | Choose PDF, mode and mode settings, question numbers (`7`, `5-61`, `1,5-61,69`) |
| Revision | Practise active mistakes / unanswered / marked / difficult questions |
| PDF Library | Add, rename, categorise, re-read, re-locate, export and remove PDFs |
| Bookmarks | Favourites, difficult questions and notes; start an exam from them |
| History | Review any finished exam, export history as CSV |
| Statistics | Totals, 7 / 30-day numbers, charts, per-PDF table, CSV export |
| Settings | Theme, font size, defaults, fullscreen exams, backups |

### Exam modes

* **Standard** - random questions, checked at the end.
* **Timed** - standard with a time limit for the whole exam; it finishes by itself when time is up.
* **Practice** - immediate right / wrong; the answer is then locked.
* **Sequential** - the first N questions of the pool in their original order.
* **Endless** - serves questions one after another without repeats until the pool is empty.
* **Survival** - immediate feedback; ends when the lives (default 1) are used up.

Every mode has its own configuration panel on the *New exam* page.

### Keyboard

| Key | Action |
|---|---|
| A-E / 1-5 | choose a variant (again = clear) |
| Right / Enter, Left | next / previous question |
| Home / End | first / last question |
| M | mark for review |
| S / X | favourite / difficult |
| N | note |
| O | overview grid |
| Ctrl+Enter | finish exam |
| F1 / F2 / F11 | guide / light-dark / fullscreen |
| Ctrl + / Ctrl - | font size |
| Esc | close dialog, leave fullscreen |

## Revision rules

* Wrong answer -> the question joins the **mistake list**, `times_wrong` +1.
* No answer -> the question joins the **unanswered list**.
* A correct answer in a **revision exam** (started from Revision, or "Retry wrong / unanswered") removes the
  question from the mistake list. The counters (`times_wrong`, `times_correct`) are never reset.
* A correct answer in a normal exam leaves the mistake list unchanged.
* Questions marked with M during an exam are remembered and pre-marked next time.

## Data and safety

Everything is stored in one SQLite file in `%APPDATA%\ExamTrainer` (Linux/macOS: `~/.local/share/ExamTrainer`).
Create an empty file `portable.flag` next to `main.py` to keep the data in `./data` instead, or set the
environment variable `EXAM_TRAINER_DATA`.

* **Migrations:** schema changes are numbered; a backup is written before each one.
* **Backups:** automatic once a day, plus *Settings -> Back up now* (the last 15 are kept in `backups/`).
* **Nothing is silently deleted:** removing a PDF from the library only hides it (file untouched, data kept and
  restored when you add it again). Clearing history asks twice and makes a backup first.
* **Changed PDFs:** questions are identified by a fingerprint of their content, not by their number. When a PDF
  changes, notes / bookmarks / statistics follow their questions to the new numbers; data of questions that no
  longer exist is kept hidden and restored if they come back.
* **Crash recovery:** the running exam is saved continuously and can be resumed from the Home page.
* **Version 1 settings** (`~/.exam_trainer.json`) are imported once; the old file is left alone.

## Architecture (Stage 1 analysis of the original and the new layout)

The original was one file with three layers: parsing (`collect_items`, `group_questions`, `join_lines`,
`parse_ranges`), data (`Bank` with lazy picture cropping, `Session`) and the Tk GUI. The parsing code is kept
**verbatim** in `pdf_parser.py` (between the VERBATIM markers); everything else was separated:

    main.py              entry point
    config.py            constants, data locations, default settings
    database.py          SQLite: settings, library, question state, history, session snapshot, migrations
    pdf_parser.py        original parser + fingerprints, hashing, parse cache, friendly errors
    question_bank.py     Bank: lazy rendering (original), previews, JSON text, closes PDF handles
    library.py           import / change detection / re-linking of saved data / bank cache
    exam_engine.py       modes, Session, scoring, crash-recovery snapshots
    exam_stats.py        statistics queries            (named exam_stats: "statistics" would shadow the stdlib module)
    revision.py          mistake / unanswered / marked / difficult lists
    export.py            PDF report (Pillow), CSV, JSON, clipboard text
    tasks.py             background threads with safe delivery to the Tk thread
    ui/                  app shell, theme, widgets, charts and one module per screen
    tests/               automated tests (core + GUI smoke tests with a fake Tk)

Performance: PDFs are hashed and parsed in a worker thread with a progress bar and *Cancel*; the parse result is
cached (gzip JSON keyed by file hash), so re-opening is instant. Pictures are cropped lazily per question;
the PDF handle is released when a bank leaves the 3-entry cache.

## Tests

    python -m unittest discover -s tests -v

* `test_core.py` - real PDFs (generated with reportlab, `tests/make_sample_pdf.py`): parsing, markers, pictures,
  cache, corrupt files, every mode, scoring, persistence across restart, revision rules, library (duplicates,
  moved / changed / renumbered PDFs), statistics, CSV / JSON / PDF export, a 1 500-question bank.
* `test_ui_smoke.py` - drives every screen (all modes, keys, notes, resume, results, history, statistics,
  settings, both themes, fonts, fullscreen, help, resizing) through a fake Tk toolkit, so it runs without a display.

## Build a Windows .exe

Double-click `build.bat`, or:

    pip install pyinstaller
    pyinstaller --noconsole --onefile --name ExamTrainer --collect-all pdfplumber --collect-all pypdfium2 --collect-submodules pdfminer main.py

The result is `dist\ExamTrainer.exe`. Data is still stored in `%APPDATA%\ExamTrainer`.

## Known limitations

* The GUI was verified with the fake-Tk smoke tests and the non-GUI code with real PDFs, but **not visually on a
  real Windows screen** - please look through each page once and report layout problems.
* The PDF report is drawn with Pillow: pictures and text are included, but glyphs missing from the system font
  (rare maths symbols) may show as boxes. The exam screen itself is unaffected.
* An exam uses the questions of one PDF; revision across several PDFs is listed, but practised one PDF at a time.
* The JSON bank export contains text only; pictures are counted, not embedded.
* If two questions have identical text and variants they share one fingerprint (and therefore one note / statistic).
* "Smooth transitions" are limited to hover highlights; Tk has no animation support worth the complexity.
